from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

from ..agent_execution import SpawnMode
from ..agent_runtime import AgentInvocation, AgentRunResult, AgentRuntime
from ..builtins import load_builtin_pack
from ..contracts import RuntimeMessage, serialize_content_blocks
from ..definitions import (
    AgentDefinition,
    InvocationCapabilityView,
    InvocationDiagnostics,
    IsolationMode,
    PermissionMode,
    ResolvedInvocationCatalog,
    SkillDefinition,
    ToolDefinition,
)
from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..errors import RegistryConflictError
from ..hosts.base import BoundHostRuntime, HostAdapter, NullHostAdapter
from ..invocation_catalog import SkillInvocationProvider
from ..memory import MemoryManagerService
from ..registries import AgentRegistry, DefinitionDiscovery, InvocationRegistry, SkillRegistry, ToolRegistry
from ..runtime_services import DefaultTranscriptService, RuntimeServices
from ..session_runtime import InMemoryTranscriptStore, InboundEvent, InboundEventType, SessionController
from ..skill_runtime import SkillExecutionResult, SkillExecutor
from ..tasking import TaskManager
from ..tool_runtime import ToolContext
from ..turn_engine.composer import ContextAssembler
from ..turn_engine.engine import TurnEngine, TurnStreamEvent
from ..turn_engine.models import ModelRequest, TranscriptStore
from .config import RuntimeConfig
from ..execution_policy import policy_state_from_metadata


@dataclass(slots=True)
class RuntimeKernel:
    config: RuntimeConfig
    tool_registry: ToolRegistry
    agent_registry: AgentRegistry
    skill_registry: SkillRegistry
    invocation_registry: InvocationRegistry
    diagnostics: tuple[Diagnostic, ...] = ()
    model_client: Any = None
    transcript_store: Any = None
    services: RuntimeServices | None = None
    hosts: dict[str, HostAdapter] = field(default_factory=dict)


class _UnconfiguredModelClient:
    def _error(self) -> RuntimeError:
        return RuntimeError("RuntimeConfig.model_client is required for runnable turn execution")

    async def complete(self, request: ModelRequest):  # pragma: no cover - defensive boundary
        _ = request
        raise self._error()

    async def stream(self, request: ModelRequest):
        _ = request
        raise self._error()
        if False:  # pragma: no cover - marks this as an async generator
            yield None


@dataclass(slots=True)
class RuntimeAssembly:
    kernel: RuntimeKernel
    services: RuntimeServices
    turn_engine: TurnEngine
    agent_runtime: AgentRuntime
    skill_executor: SkillExecutor
    transcript_store: TranscriptStore
    task_manager: TaskManager
    system_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def bind_host(self, host: HostAdapter) -> BoundHostRuntime:
        self.services.bind_host(host)
        return BoundHostRuntime(
            kernel=self.kernel,
            host=host,
            runtime=self,
            services=self.services,
        )

    def resolve_invocations(
        self,
        *,
        session_id: str,
        cwd: str | Path | None = None,
        messages: tuple[RuntimeMessage, ...] | list[RuntimeMessage] = (),
        runtime_context: dict[str, object] | None = None,
        turn_id: str | None = None,
    ) -> ResolvedInvocationCatalog:
        resolved_cwd = Path(cwd) if cwd is not None else self.kernel.config.working_directory
        return self.turn_engine.resolve_invocation_catalog(
            session_id=session_id,
            turn_id=turn_id,
            cwd=resolved_cwd,
            messages=tuple(messages),
            runtime_context=runtime_context,
        )

    def resolve_session_invocations(
        self,
        session: SessionController,
        *,
        runtime_context: dict[str, object] | None = None,
    ) -> ResolvedInvocationCatalog:
        session_runtime_context = dict(session.state.metadata)
        if runtime_context:
            session_runtime_context.update(runtime_context)
        return self.resolve_invocations(
            session_id=session.state.session_id,
            turn_id=session.state.active_turn_id,
            cwd=session.cwd,
            messages=session.messages,
            runtime_context=session_runtime_context,
        )

    def visible_invocations(
        self,
        session: SessionController,
        *,
        user_invocable: bool | None = None,
        model_invocable: bool | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> tuple[InvocationCapabilityView, ...]:
        catalog = self.resolve_session_invocations(session, runtime_context=runtime_context)
        return catalog.visible_capabilities(
            user_invocable=user_invocable,
            model_invocable=model_invocable,
        )

    def invocation_diagnostics(
        self,
        session: SessionController,
        *,
        runtime_context: dict[str, object] | None = None,
    ) -> tuple[InvocationDiagnostics, ...]:
        catalog = self.resolve_session_invocations(session, runtime_context=runtime_context)
        return catalog.diagnostics

    def create_session(
        self,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
    ) -> SessionController:
        selected_agent = self._resolve_agent(agent_name or self.kernel.config.default_agent)
        session_cwd = Path(cwd) if cwd is not None else self.kernel.config.working_directory
        return SessionController(
            session_id=session_id or uuid4().hex,
            agent=selected_agent,
            turn_engine=self.turn_engine,
            transcript_store=self.transcript_store,
            cwd=str(session_cwd),
            system_prompt=self.system_prompt if system_prompt is None else system_prompt,
            runtime_services=self.services,
        )

    async def run_prompt(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> tuple[RuntimeMessage, ...]:
        session = self.create_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
        )
        await session.resume()
        await session.start()
        session.enqueue_event(
            InboundEvent(
                InboundEventType.USER_PROMPT,
                prompt,
                metadata=metadata or {},
            )
        )
        return await session.run_until_idle()

    async def stream_prompt(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AsyncIterator[TurnStreamEvent]:
        session = self.create_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
        )
        await session.resume()
        await session.start()
        session.enqueue_event(
            InboundEvent(
                InboundEventType.USER_PROMPT,
                prompt,
                metadata=metadata or {},
            )
        )
        async for event in session.stream_until_idle():
            yield event

    async def run_agent_tool(
        self,
        agent_name: str,
        prompt: str,
        context: ToolContext,
        *,
        background: bool = False,
        spawn_mode: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        model_route: str | None = None,
        reason: str | None = None,
        permission_mode: str | None = None,
        isolation: str | None = None,
        max_turns: int | None = None,
    ) -> dict[str, Any]:
        metadata = dict(context.metadata)
        if reason is not None:
            metadata["delegation_reason"] = reason
        normalized_model_route = _coerce_optional_string(model_route)
        if (
            normalized_model_route is not None
            and normalized_model_route not in self.kernel.config.model_routes
        ):
            raise ValueError(f"Unknown model route: {normalized_model_route}")
        result = await self.agent_runtime.invoke(
            AgentInvocation(
                agent_name=agent_name,
                prompt=prompt,
                session_id=context.session_id,
                cwd=_resolve_invocation_cwd(context.cwd, cwd),
                background=background,
                query_source="agent_tool",
                spawn_mode=_coerce_spawn_mode(spawn_mode),
                parent_run_id=_coerce_optional_string(context.metadata.get("run_id")),
                parent_turn_id=context.turn_id,
                requested_model_route=normalized_model_route,
                requested_model=_coerce_optional_string(model),
                requested_permission_mode=_coerce_permission_mode(permission_mode),
                requested_isolation=_coerce_isolation_mode(isolation),
                max_turns=max_turns,
                parent_tool_pool=context.tool_pool,
                parent_skill_pool=context.skill_pool,
                metadata=metadata,
            )
        )
        return _serialize_agent_run_result(result)

    async def run_skill_tool(
        self,
        skill_name: str,
        arguments: list[str] | tuple[str, ...],
        context: ToolContext,
    ) -> dict[str, Any]:
        result = await self.skill_executor.execute(
            skill_name,
            arguments=tuple(arguments),
            session_id=context.session_id,
            cwd=context.cwd,
            parent_tool_pool=context.tool_pool,
            parent_skill_pool=context.skill_pool,
            permission_context=context.permission_context,
            turn_id=context.turn_id,
            parent_run_id=_coerce_optional_string(context.metadata.get("run_id")),
            policy_state=policy_state_from_metadata(context.metadata),
        )
        return _serialize_skill_execution_result(result)

    def _resolve_agent(self, agent_name: str) -> AgentDefinition:
        agent = self.kernel.agent_registry.get(agent_name)
        if agent is None:
            raise KeyError(agent_name)
        return agent


def build_runtime_kernel(config: RuntimeConfig) -> RuntimeKernel:
    tool_registry = ToolRegistry()
    agent_registry = AgentRegistry()
    skill_registry = SkillRegistry()
    invocation_registry = InvocationRegistry()
    diagnostics: list[Diagnostic] = []

    builtin_pack = load_builtin_pack()
    _register_builtin_tools(tool_registry, config, builtin_pack.tools, diagnostics)
    _register_builtin_agents(agent_registry, config, builtin_pack.agents, diagnostics)
    _register_builtin_skills(skill_registry, config, builtin_pack.skills, diagnostics)

    discovery = DefinitionDiscovery(config.discovery_sources)
    discovered = discovery.discover()
    diagnostics.extend(discovered.diagnostics)
    _register_all(tool_registry, discovered.tools, diagnostics)
    _register_all(agent_registry, discovered.agents, diagnostics)
    _register_all(skill_registry, discovered.skills, diagnostics)
    invocation_registry.register_provider(SkillInvocationProvider(skill_registry))
    for provider in config.extra_invocation_providers:
        invocation_registry.register_provider(provider)

    kernel = RuntimeKernel(
        config=config,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        invocation_registry=invocation_registry,
        diagnostics=tuple(diagnostics),
        model_client=_default_model_client(config),
        transcript_store=config.transcript_store,
    )
    kernel.services = _build_runtime_services(kernel)
    kernel.transcript_store = kernel.services.transcript_store
    for binding in config.host_bindings:
        kernel.hosts[binding.name] = binding.factory(binding.name, binding.config, kernel)
    return kernel


def assemble_runtime(config: RuntimeConfig) -> RuntimeAssembly:
    kernel = build_runtime_kernel(config)
    return _assemble_runtime_stack(kernel)


def assemble_host_runtime(
    config: RuntimeConfig,
    host_name: str | None = None,
) -> BoundHostRuntime:
    runtime = assemble_runtime(config)
    kernel = runtime.kernel
    if host_name is None:
        host = next(iter(kernel.hosts.values()), NullHostAdapter())
    else:
        host = kernel.hosts.get(host_name)
        if host is None:
            raise KeyError(host_name)
    return runtime.bind_host(host)


def _assemble_runtime_stack(kernel: RuntimeKernel) -> RuntimeAssembly:
    services = kernel.services or _build_runtime_services(kernel)
    kernel.services = services
    transcript_store = services.transcript_store
    kernel.transcript_store = transcript_store
    task_manager = services.task_manager
    turn_engine = TurnEngine(
        model_client=kernel.model_client or _UnconfiguredModelClient(),
        tool_registry=kernel.tool_registry,
        agent_registry=kernel.agent_registry,
        skill_registry=kernel.skill_registry,
        invocation_registry=kernel.invocation_registry,
        runtime_services=services,
    )
    agent_runtime = AgentRuntime(
        turn_engine=turn_engine,
        agent_registry=kernel.agent_registry,
        tool_registry=kernel.tool_registry,
        skill_registry=kernel.skill_registry,
        runtime_services=services,
        run_store=kernel.config.child_run_store,
        model_routes=kernel.config.model_routes,
        default_model_route=kernel.config.default_model_route,
    )
    skill_executor = SkillExecutor(
        skill_registry=kernel.skill_registry,
        agent_runtime=agent_runtime,
        runtime_services=services,
    )
    agent_runtime.bind_skill_executor(skill_executor)
    runtime = RuntimeAssembly(
        kernel=kernel,
        services=services,
        turn_engine=turn_engine,
        agent_runtime=agent_runtime,
        skill_executor=skill_executor,
        transcript_store=transcript_store,
        task_manager=task_manager,
        system_prompt=kernel.config.system_prompt,
        metadata=dict(kernel.config.metadata),
    )
    services.bind_execution(
        agent_runner=runtime.run_agent_tool,
        skill_runner=runtime.run_skill_tool,
    )
    services.configure_compat(
        permission_handler=kernel.config.permission_handler,
        ask_user_handler=kernel.config.ask_user_handler,
        notification_provider=lambda: agent_runtime.notifications,
        tool_refresh_callback=kernel.config.tool_refresh_callback,
    )
    return runtime


def _build_runtime_services(kernel: RuntimeKernel) -> RuntimeServices:
    transcript_store = kernel.transcript_store or InMemoryTranscriptStore()
    services = RuntimeServices(
        transcript=DefaultTranscriptService(transcript_store),
        memory=MemoryManagerService(project_root=kernel.config.working_directory),
        context_assembler=ContextAssembler(),
        metadata=dict(kernel.config.metadata),
    )
    services.configure_compat(
        permission_handler=kernel.config.permission_handler,
        ask_user_handler=kernel.config.ask_user_handler,
        tool_refresh_callback=kernel.config.tool_refresh_callback,
    )
    return services


def _serialize_agent_run_result(result: AgentRunResult) -> dict[str, Any]:
    run_record = result.run_record
    payload: dict[str, Any] = {
        "agent": result.agent_name,
        "status": result.status,
        "background": result.background,
        "run_id": result.run_id,
        "parent_run_id": result.parent_run_id,
        "turn_id": result.turn_id,
        "query_source": result.query_source,
        "messages": [_serialize_message(message) for message in result.messages],
        "task_id": result.task_id,
        "requested_model": (
            result.execution_spec.requested_model if result.execution_spec is not None else None
        ),
        "requested_model_route": (
            result.execution_spec.requested_model_route if result.execution_spec is not None else None
        ),
        "resolved_model_route": run_record.resolved_model_route if run_record is not None else None,
        "isolation_mode": result.isolation_mode.value if result.isolation_mode is not None else None,
        "terminal_metadata": dict(run_record.terminal_metadata) if run_record is not None else {},
        "notification": _serialize_message(result.notification) if result.notification is not None else None,
    }
    return payload


def _serialize_skill_execution_result(result: SkillExecutionResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "skill": result.skill_name,
        "mode": result.mode.value,
        "injected_messages": [_serialize_message(message) for message in result.injected_messages],
    }
    if result.agent_result is not None:
        payload["agent_result"] = _serialize_agent_run_result(result.agent_result)
    return payload


def _serialize_message(message: RuntimeMessage) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "role": message.role.value,
        "content": serialize_content_blocks(message.content),
        "metadata": dict(message.metadata),
    }


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    stringified = str(value).strip()
    return stringified or None


def _resolve_invocation_cwd(base_cwd: Path, requested_cwd: str | None) -> Path:
    if requested_cwd is None:
        return base_cwd
    resolved = Path(requested_cwd)
    if not resolved.is_absolute():
        resolved = (base_cwd / resolved).resolve()
    return resolved


def _coerce_spawn_mode(value: str | None) -> SpawnMode | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    return SpawnMode(normalized)


def _coerce_permission_mode(value: str | None) -> PermissionMode | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    return PermissionMode(normalized)


def _coerce_isolation_mode(value: str | None) -> IsolationMode | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    return IsolationMode(normalized)


def _default_model_client(config: RuntimeConfig) -> Any:
    if config.model_client is not None:
        return config.model_client
    if config.default_model_route is not None:
        binding = config.model_routes.get(config.default_model_route)
        if binding is not None:
            return binding.client
    return None


def _register_builtin_tools(
    registry: ToolRegistry,
    config: RuntimeConfig,
    definitions: tuple[ToolDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        if not config.builtins.tool_enabled(definition.name):
            continue
        replacement = config.builtins.tool_replacements.get(definition.name, definition)
        diagnostics.extend(registry.register(replacement).diagnostics)
    for extra in config.builtins.extra_tools:
        diagnostics.extend(registry.register(extra).diagnostics)


def _register_builtin_agents(
    registry: AgentRegistry,
    config: RuntimeConfig,
    definitions: tuple[AgentDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        if not config.builtins.agent_enabled(definition.name):
            continue
        replacement = config.builtins.agent_replacements.get(definition.name, definition)
        diagnostics.extend(registry.register(replacement).diagnostics)
    for extra in config.builtins.extra_agents:
        diagnostics.extend(registry.register(extra).diagnostics)


def _register_builtin_skills(
    registry: SkillRegistry,
    config: RuntimeConfig,
    definitions: tuple[SkillDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        if not config.builtins.skill_enabled(definition.name):
            continue
        replacement = config.builtins.skill_replacements.get(definition.name, definition)
        diagnostics.extend(registry.register(replacement).diagnostics)
    for extra in config.builtins.extra_skills:
        diagnostics.extend(registry.register(extra).diagnostics)


def _register_all(
    registry: ToolRegistry | AgentRegistry | SkillRegistry,
    definitions: tuple[ToolDefinition, ...]
    | tuple[AgentDefinition, ...]
    | tuple[SkillDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        try:
            diagnostics.extend(registry.register(definition).diagnostics)
        except RegistryConflictError as exc:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code=exc.code.value,
                    message=str(exc),
                    definition_type=getattr(registry, "definition_type", "definition"),
                    source=definition.origin.source.value,
                    location=definition.origin.label,
                    details=exc.details,
                )
            )
