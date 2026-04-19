from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Mapping, Sequence
from uuid import uuid4

from .agent_execution import (
    AgentExecutionSpec,
    AgentRunRecord,
    AgentRunStatus,
    ChildRunStore,
)
from .control_plane import RuntimeControlPlaneContext
from .contracts import MessageRole, RuntimeMessage
from .definitions import AgentDefinition, IsolationMode, PermissionBehavior, PermissionDecision
from .execution_policy import (
    EXECUTION_POLICY_STATE_KEY,
    ExecutionPolicy,
    ExecutionPolicyState,
    policy_state_from_metadata,
    resolve_agent_execution_policy,
    serialize_runtime_metadata,
)
from .hooks import SubagentStopPayload
from .hosts.base import CallbackHostAdapter, NullHostAdapter
from .isolation import IsolationLease, serialize_isolation_lease
from .permissions import PermissionContext, PermissionRequest, PermissionTarget
from .registries import AgentRegistry, SkillRegistry, ToolRegistry
from .runtime_kernel.config import ModelRouteBinding
from .runtime_services import RuntimeServices
from .turn_engine.engine import TurnEngine
from .turn_engine.models import ModelInvocationMode, NormalizedModelCapabilities

if TYPE_CHECKING:
    from .agent_runtime import AgentInvocation, AgentRunResult


class AgentExecutionService:
    def __init__(
        self,
        *,
        turn_engine: TurnEngine,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        skill_registry: SkillRegistry,
        runtime_services: RuntimeServices,
        run_store: ChildRunStore,
        model_routes: Mapping[str, ModelRouteBinding] | None = None,
        default_model_route: str | None = None,
    ) -> None:
        self._turn_engine = turn_engine
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._runtime_services = runtime_services
        self._run_store = run_store
        self._model_routes = dict(model_routes or {})
        self._default_model_route = default_model_route

    @property
    def run_store(self) -> ChildRunStore:
        return self._run_store

    @property
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

    def resolve_agent(self, name: str) -> AgentDefinition:
        agent = self._agent_registry.get(name)
        if agent is None:
            raise KeyError(name)
        return agent

    def resolve_execution_policy(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
        *,
        execution_spec: AgentExecutionSpec | None = None,
    ) -> ExecutionPolicy:
        policy_agent = self._apply_execution_overrides(agent, execution_spec)
        parent_state = policy_state_from_metadata(invocation.metadata)
        parent_policy = parent_state.effective if parent_state is not None else None
        base_tool_pool = (
            tuple(invocation.parent_tool_pool)
            if invocation.parent_tool_pool
            else (
                parent_policy.tool_pool
                if parent_policy is not None
                else self._tool_registry.definitions()
            )
        )
        base_skill_pool = (
            tuple(invocation.parent_skill_pool)
            if invocation.parent_skill_pool
            else (
                parent_policy.skill_pool
                if parent_policy is not None
                else self._skill_registry.resolve_active()
            )
        )
        permission_context = invocation.metadata.get("permission_context")
        if not isinstance(permission_context, PermissionContext):
            permission_context = (
                parent_policy.permission_context
                if parent_policy is not None
                else PermissionContext(session_id=invocation.session_id)
            )
        return resolve_agent_execution_policy(
            policy_agent,
            parent_policy=parent_policy,
            base_tool_pool=base_tool_pool,
            base_skill_pool=base_skill_pool,
            permission_context=permission_context,
        )

    async def run(
        self,
        invocation: AgentInvocation,
        execution_spec: AgentExecutionSpec,
    ) -> AgentRunResult:
        from .agent_runtime import AgentRunResult

        agent = self.resolve_agent(execution_spec.agent_name)
        resolved_route_name, route_binding = self._resolve_model_route(agent, execution_spec)
        resolved_model = (
            execution_spec.requested_model
            or agent.model
            or (route_binding.default_model if route_binding is not None else None)
        )
        resolved_capabilities = (
            route_binding.capabilities if route_binding is not None else execution_spec.resolved_capabilities
        )
        execution_spec = replace(
            execution_spec,
            resolved_model_route=resolved_route_name,
            provider_name=route_binding.provider_name if route_binding is not None else None,
            resolved_capabilities=resolved_capabilities,
            invocation_mode=_select_invocation_mode(resolved_capabilities),
        )
        requested_agent = self._apply_execution_overrides(agent, execution_spec)
        policy = self.resolve_execution_policy(
            invocation,
            agent,
            execution_spec=execution_spec,
        )

        request_metadata = self._policy_request_metadata(execution_spec, policy)
        isolation_lease: IsolationLease | None = None
        owner = self._register_invocation_hooks(execution_spec)
        try:
            denial = await self._authorize_agent(execution_spec, invocation, agent, policy)
            if denial is not None:
                await self._dispatch_subagent_stop(
                    execution_spec.session_id,
                    execution_spec.turn_id,
                    agent.name,
                    denial.status,
                )
                return denial

            effective_tools = policy.tool_pool
            effective_skills = policy.skill_pool
            effective_agent = replace(
                requested_agent,
                tools=tuple(tool.name for tool in effective_tools),
                skills=tuple(skill.name for skill in effective_skills),
                model=resolved_model,
                permission_mode=policy.permission_context.mode,
                memory=policy.memory_scope,
                isolation=policy.isolation_mode,
            )
            memory_service = self._runtime_services.memory
            isolation_lease = await self._prepare_isolation(execution_spec, agent, policy)
            if memory_service is not None and hasattr(memory_service, "start_session"):
                await _maybe_await(
                    memory_service.start_session(
                        session_id=execution_spec.session_id,
                        agent=effective_agent,
                        cwd=isolation_lease.working_directory,
                        set_default=False,
                    )
                )
            child_policy_state = ExecutionPolicyState(policy)
            runtime_context = self._build_runtime_context(
                execution_spec,
                agent_name=agent.name,
                policy_state=child_policy_state,
                isolation_lease=isolation_lease,
            )
            request_metadata = serialize_runtime_metadata(runtime_context)
            turn_result = await self._turn_engine.run_turn(
                session_id=execution_spec.session_id,
                turn_id=execution_spec.turn_id,
                agent=effective_agent,
                cwd=str(isolation_lease.working_directory),
                messages=list(execution_spec.prompt_messages),
                base_system_prompt=execution_spec.base_system_prompt,
                runtime_context=runtime_context,
                model_client_override=route_binding.client if route_binding is not None else None,
            )
            run_status = _agent_run_status_from_turn_result(turn_result)
            run_record = self._build_run_record(
                execution_spec,
                agent_name=agent.name,
                status=run_status,
                request_metadata=request_metadata,
                terminal_metadata=_terminal_metadata_from_turn_result(turn_result),
                messages=tuple(turn_result.messages),
            )
            await self._run_store.upsert(run_record)
            await self._turn_engine.emit_child_run(run_record)
            result = AgentRunResult(
                agent_name=agent.name,
                status=run_status.value,
                messages=turn_result.messages,
                background=execution_spec.background,
                isolation_mode=policy.isolation_mode,
                run_id=execution_spec.run_id,
                parent_run_id=execution_spec.parent_run_id,
                turn_id=execution_spec.turn_id,
                query_source=execution_spec.query_source,
                execution_spec=execution_spec,
                run_record=run_record,
            )
            await self._dispatch_subagent_stop(
                execution_spec.session_id,
                execution_spec.turn_id,
                agent.name,
                result.status,
            )
            return result
        except Exception as exc:
            failed_record = self._build_run_record(
                execution_spec,
                agent_name=agent.name,
                status=AgentRunStatus.FAILED,
                request_metadata=request_metadata,
                terminal_metadata={"error": str(exc)},
            )
            await self._run_store.upsert(failed_record)
            await self._turn_engine.emit_child_run(failed_record)
            await self._dispatch_subagent_stop(
                execution_spec.session_id,
                execution_spec.turn_id,
                agent.name,
                AgentRunStatus.FAILED.value,
            )
            raise
        finally:
            if owner is not None and self._runtime_services.hook_bus is not None:
                self._runtime_services.hook_bus.release_owner(execution_spec.session_id, owner)
            if isolation_lease is not None:
                await self._runtime_services.isolation.cleanup(isolation_lease)

    async def write_running_record(
        self,
        invocation: AgentInvocation,
        execution_spec: AgentExecutionSpec,
    ) -> AgentRunRecord:
        agent = self.resolve_agent(execution_spec.agent_name)
        policy = self.resolve_execution_policy(
            invocation,
            agent,
            execution_spec=execution_spec,
        )
        running_record = self._build_run_record(
            execution_spec,
            agent_name=agent.name,
            status=AgentRunStatus.RUNNING,
            request_metadata=self._policy_request_metadata(execution_spec, policy),
        )
        await self._run_store.upsert(running_record)
        await self._turn_engine.emit_child_run(running_record)
        return running_record

    async def _prepare_isolation(
        self,
        execution_spec: AgentExecutionSpec,
        agent: AgentDefinition,
        policy: ExecutionPolicy,
    ) -> IsolationLease:
        return await self._runtime_services.isolation.prepare(
            session_id=execution_spec.session_id,
            agent_name=agent.name,
            mode=policy.isolation_mode,
            cwd=execution_spec.cwd,
            metadata={
                "background": execution_spec.background,
                "run_id": execution_spec.run_id,
                "parent_run_id": execution_spec.parent_run_id,
                "turn_id": execution_spec.turn_id,
                "parent_turn_id": execution_spec.parent_turn_id,
                "spawn_mode": execution_spec.spawn_mode.value,
                "query_source": execution_spec.query_source,
                "policy": serialize_runtime_metadata({EXECUTION_POLICY_STATE_KEY: ExecutionPolicyState(policy)})[
                    "policy"
                ],
            },
        )

    async def _authorize_agent(
        self,
        execution_spec: AgentExecutionSpec,
        invocation: AgentInvocation,
        agent: AgentDefinition,
        policy: ExecutionPolicy,
    ) -> AgentRunResult | None:
        from .agent_runtime import AgentRunResult

        if agent.name == "main-router" and not execution_spec.background:
            return None
        initial = PermissionDecision(
            PermissionBehavior.ASK
            if (
                execution_spec.background or policy.isolation_mode != IsolationMode.NONE
            )
            and _supports_permission_requests(self._runtime_services.host)
            else PermissionBehavior.ALLOW
        )
        request = PermissionRequest(
            session_id=execution_spec.session_id,
            turn_id=None,
            target=PermissionTarget.AGENT,
            name=agent.name,
            payload={"prompt": invocation.prompt, "background": execution_spec.background},
            context=policy.permission_context,
            message=f"Agent '{agent.name}' requires permission",
        )
        runtime_context = RuntimeControlPlaneContext(
            runtime_services=self._runtime_services,
            permission_context=policy.permission_context,
        )
        outcome = await self._runtime_services.permissions.evaluate(  # type: ignore[attr-defined]
            request,
            initial_decision=initial,
            runtime_context=runtime_context,
        )
        if outcome.behavior == PermissionBehavior.ALLOW:
            return None
        denied_message = RuntimeMessage(
            message_id=uuid4().hex,
            role=MessageRole.NOTIFICATION,
            content=outcome.message or f"Agent '{agent.name}' was denied",
            metadata={"permission_denied": True},
        )
        denied_record = self._build_run_record(
            execution_spec,
            agent_name=agent.name,
            status=AgentRunStatus.DENIED,
            request_metadata=self._policy_request_metadata(execution_spec, policy),
            terminal_metadata={
                "error": outcome.message or f"Agent '{agent.name}' was denied",
                "permission_denied": True,
            },
            messages=(denied_message,),
        )
        await self._run_store.upsert(denied_record)
        await self._turn_engine.emit_child_run(denied_record)
        return AgentRunResult(
            agent_name=agent.name,
            status=AgentRunStatus.DENIED.value,
            messages=[denied_message],
            background=execution_spec.background,
            isolation_mode=policy.isolation_mode,
            run_id=execution_spec.run_id,
            parent_run_id=execution_spec.parent_run_id,
            turn_id=execution_spec.turn_id,
            query_source=execution_spec.query_source,
            execution_spec=execution_spec,
            run_record=denied_record,
        )

    def _register_invocation_hooks(self, execution_spec: AgentExecutionSpec) -> str | None:
        hooks = execution_spec.metadata.get("skill_hooks")
        if not isinstance(hooks, dict) or self._runtime_services.hook_bus is None:
            return None
        owner = str(execution_spec.metadata.get("skill_hook_owner") or f"skill:delegated:{uuid4().hex}")
        self._runtime_services.hook_bus.register_handlers(
            session_id=execution_spec.session_id,
            owner=owner,
            hooks=hooks,
            turn_id=execution_spec.turn_id,
        )
        return owner

    def _build_runtime_context(
        self,
        execution_spec: AgentExecutionSpec,
        *,
        agent_name: str,
        policy_state: ExecutionPolicyState,
        isolation_lease: IsolationLease,
    ) -> dict[str, Any]:
        return {
            **dict(execution_spec.metadata),
            "agent_name": agent_name,
            "background": execution_spec.background,
            "run_id": execution_spec.run_id,
            "parent_run_id": execution_spec.parent_run_id,
            "session_id": execution_spec.session_id,
            "turn_id": execution_spec.turn_id,
            "parent_turn_id": execution_spec.parent_turn_id,
            "spawn_mode": execution_spec.spawn_mode,
            "query_source": execution_spec.query_source,
            "requested_model_route": execution_spec.requested_model_route,
            "requested_model": execution_spec.requested_model,
            "resolved_model_route": execution_spec.resolved_model_route,
            "provider_name": execution_spec.provider_name,
            "resolved_capabilities": _serialize_capabilities(execution_spec.resolved_capabilities),
            "invocation_mode": execution_spec.invocation_mode,
            "requested_permission_mode": execution_spec.requested_permission_mode,
            "requested_isolation": execution_spec.requested_isolation,
            "max_turns": execution_spec.max_turns,
            "permission_context": policy_state.effective.permission_context,
            EXECUTION_POLICY_STATE_KEY: policy_state,
            "isolation": serialize_isolation_lease(isolation_lease),
        }

    def _policy_request_metadata(
        self,
        execution_spec: AgentExecutionSpec,
        policy: ExecutionPolicy,
    ) -> dict[str, Any]:
        return serialize_runtime_metadata(
            {
                **dict(execution_spec.metadata),
                "agent_name": execution_spec.agent_name,
                "background": execution_spec.background,
                "run_id": execution_spec.run_id,
                "parent_run_id": execution_spec.parent_run_id,
                "session_id": execution_spec.session_id,
                "turn_id": execution_spec.turn_id,
                "parent_turn_id": execution_spec.parent_turn_id,
                "spawn_mode": execution_spec.spawn_mode,
                "query_source": execution_spec.query_source,
                "requested_model_route": execution_spec.requested_model_route,
                "requested_model": execution_spec.requested_model,
                "resolved_model_route": execution_spec.resolved_model_route,
                "provider_name": execution_spec.provider_name,
                "resolved_capabilities": _serialize_capabilities(execution_spec.resolved_capabilities),
                "invocation_mode": execution_spec.invocation_mode,
                "requested_permission_mode": (
                    execution_spec.requested_permission_mode.value
                    if execution_spec.requested_permission_mode is not None
                    else None
                ),
                "requested_isolation": (
                    execution_spec.requested_isolation.value
                    if execution_spec.requested_isolation is not None
                    else None
                ),
                "max_turns": execution_spec.max_turns,
                "permission_context": policy.permission_context,
                EXECUTION_POLICY_STATE_KEY: ExecutionPolicyState(policy),
            }
        )

    def _apply_execution_overrides(
        self,
        agent: AgentDefinition,
        execution_spec: AgentExecutionSpec | None,
    ) -> AgentDefinition:
        if execution_spec is None:
            return agent
        max_turns = _resolve_max_turns(agent.max_turns, execution_spec.max_turns)
        return replace(
            agent,
            permission_mode=execution_spec.requested_permission_mode or agent.permission_mode,
            isolation=execution_spec.requested_isolation or agent.isolation,
            max_turns=max_turns,
        )

    def _build_run_record(
        self,
        execution_spec: AgentExecutionSpec,
        *,
        agent_name: str,
        status: AgentRunStatus,
        request_metadata: dict[str, Any],
        terminal_metadata: dict[str, Any] | None = None,
        messages: Sequence[RuntimeMessage] = (),
    ) -> AgentRunRecord:
        return AgentRunRecord(
            run_id=execution_spec.run_id,
            parent_run_id=execution_spec.parent_run_id,
            session_id=execution_spec.session_id,
            parent_turn_id=execution_spec.parent_turn_id,
            turn_id=execution_spec.turn_id,
            agent_name=agent_name,
            spawn_mode=execution_spec.spawn_mode,
            status=status,
            query_source=execution_spec.query_source,
            requested_model_route=execution_spec.requested_model_route,
            requested_model=execution_spec.requested_model,
            resolved_model_route=execution_spec.resolved_model_route,
            provider_name=execution_spec.provider_name,
            resolved_capabilities=_serialize_capabilities(execution_spec.resolved_capabilities),
            invocation_mode=(
                execution_spec.invocation_mode.value
                if execution_spec.invocation_mode is not None
                else None
            ),
            request_metadata=dict(request_metadata),
            terminal_metadata=dict(terminal_metadata or {}),
            messages=tuple(messages),
        )

    def _resolve_model_route(
        self,
        agent: AgentDefinition,
        execution_spec: AgentExecutionSpec,
    ) -> tuple[str | None, ModelRouteBinding | None]:
        inherited_route = (
            _coerce_optional_string(execution_spec.metadata.get("resolved_model_route"))
            or _coerce_optional_string(execution_spec.metadata.get("requested_model_route"))
        )
        resolved_route = (
            execution_spec.requested_model_route
            or agent.model_route
            or inherited_route
            or self._default_model_route
        )
        if resolved_route is None:
            return None, None
        binding = self._model_routes.get(resolved_route)
        if binding is None:
            raise ValueError(f"Unknown model route: {resolved_route}")
        return resolved_route, binding

    async def _dispatch_subagent_stop(
        self,
        session_id: str,
        turn_id: str | None,
        agent_name: str,
        status: str,
    ) -> None:
        if self._runtime_services.hook_bus is None:
            return
        await self._runtime_services.hook_bus.dispatch(
            session_id,
            SubagentStopPayload(
                session_id=session_id,
                agent_name=agent_name,
                status=status,
                turn_id=turn_id,
            ),
        )

def _supports_permission_requests(host: Any) -> bool:
    if isinstance(host, CallbackHostAdapter):
        return host.permission_handler is not None
    if type(host) is NullHostAdapter:
        return False
    return True


def _terminal_metadata_from_turn_result(turn_result: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if turn_result.stop_reason is not None:
        metadata["stop_reason"] = turn_result.stop_reason
    if turn_result.request_id is not None:
        metadata["request_id"] = turn_result.request_id
    if turn_result.ttft_ms is not None:
        metadata["ttft_ms"] = turn_result.ttft_ms
    if turn_result.abort_reason is not None:
        metadata["abort_reason"] = turn_result.abort_reason
    if turn_result.error is not None:
        metadata["error"] = turn_result.error
    if turn_result.usage:
        metadata["usage"] = dict(turn_result.usage)
    terminal = getattr(turn_result, "terminal", None)
    if terminal is not None:
        provider_stop_reason = getattr(terminal, "provider_stop_reason", None)
        if provider_stop_reason is not None and provider_stop_reason != turn_result.stop_reason:
            metadata["provider_stop_reason"] = provider_stop_reason
    return metadata


def _agent_run_status_from_turn_result(turn_result: Any) -> AgentRunStatus:
    stop_reason = getattr(turn_result, "stop_reason", None)
    if stop_reason in {"end_turn", "message_stop"}:
        return AgentRunStatus.COMPLETED
    if stop_reason == "max_turns":
        return AgentRunStatus.MAX_TURNS
    return AgentRunStatus.FAILED


def _resolve_max_turns(agent_limit: int | None, requested_limit: int | None) -> int | None:
    if agent_limit is None:
        return requested_limit
    if requested_limit is None:
        return agent_limit
    return min(agent_limit, requested_limit)


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _select_invocation_mode(
    capabilities: NormalizedModelCapabilities | None,
) -> ModelInvocationMode:
    if capabilities is not None and not capabilities.supports_streaming:
        return ModelInvocationMode.BUFFERED_COMPLETION
    return ModelInvocationMode.STREAM


def _serialize_capabilities(
    capabilities: NormalizedModelCapabilities | None,
) -> dict[str, Any] | None:
    if capabilities is None:
        return None
    return {
        "structured_tool_calls": capabilities.structured_tool_calls,
        "streaming_tool_call_deltas": capabilities.streaming_tool_call_deltas,
        "tool_call_finalize_boundary": capabilities.tool_call_finalize_boundary,
        "parseable_tool_calls_after_message": capabilities.parseable_tool_calls_after_message,
        "multiple_tool_calls_per_message": capabilities.multiple_tool_calls_per_message,
        "abort_signal_passthrough": capabilities.abort_signal_passthrough,
        "supports_streaming": capabilities.supports_streaming,
    }


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
