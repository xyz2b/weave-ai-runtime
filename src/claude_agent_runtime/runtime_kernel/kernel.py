from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

from ..agent_runtime import AgentInvocation, AgentRunResult, AgentRuntime
from ..builtins import load_builtin_pack
from ..contracts import RuntimeMessage, serialize_content_blocks
from ..definitions import AgentDefinition, SkillDefinition, ToolDefinition
from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..errors import RegistryConflictError
from ..hosts.base import BoundHostRuntime, HostAdapter, NullHostAdapter
from ..memory import MemoryManagerService
from ..registries import AgentRegistry, DefinitionDiscovery, SkillRegistry, ToolRegistry
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
    ) -> dict[str, Any]:
        result = await self.agent_runtime.invoke(
            AgentInvocation(
                agent_name=agent_name,
                prompt=prompt,
                session_id=context.session_id,
                cwd=context.cwd,
                background=background,
                parent_tool_pool=context.tool_pool,
                parent_skill_pool=context.skill_pool,
                metadata=dict(context.metadata),
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

    kernel = RuntimeKernel(
        config=config,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        diagnostics=tuple(diagnostics),
        model_client=config.model_client,
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
        runtime_services=services,
    )
    agent_runtime = AgentRuntime(
        turn_engine=turn_engine,
        agent_registry=kernel.agent_registry,
        tool_registry=kernel.tool_registry,
        skill_registry=kernel.skill_registry,
        runtime_services=services,
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
    payload: dict[str, Any] = {
        "agent": result.agent_name,
        "status": result.status,
        "background": result.background,
        "messages": [_serialize_message(message) for message in result.messages],
    }
    if result.task_id is not None:
        payload["task_id"] = result.task_id
    if result.isolation_mode is not None:
        payload["isolation_mode"] = result.isolation_mode.value
    if result.notification is not None:
        payload["notification"] = _serialize_message(result.notification)
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
