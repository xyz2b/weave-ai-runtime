from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from .contracts import MessageRole, RuntimeMessage
from .definitions import AgentDefinition, IsolationMode, PermissionBehavior, PermissionDecision, SkillDefinition, ToolDefinition
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
from .runtime_services import DefaultTaskService, RuntimeServices
from .tasking import TaskManager, TaskStatus
from .tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler
from .turn_engine.engine import TurnEngine


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    agent_name: str
    prompt: str
    session_id: str
    cwd: Path
    background: bool = False
    parent_tool_pool: tuple[ToolDefinition, ...] = ()
    parent_skill_pool: tuple[SkillDefinition, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentRunResult:
    agent_name: str
    status: str
    messages: list[RuntimeMessage] = field(default_factory=list)
    task_id: str | None = None
    background: bool = False
    isolation_mode: IsolationMode | None = None
    notification: RuntimeMessage | None = None


class AgentRuntime:
    def __init__(
        self,
        *,
        turn_engine: TurnEngine,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        skill_registry: SkillRegistry,
        task_manager: TaskManager | None = None,
        runtime_services: RuntimeServices | None = None,
    ) -> None:
        self._turn_engine = turn_engine
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._runtime_services = runtime_services or RuntimeServices(
            tasks=DefaultTaskService(task_manager or TaskManager())
        )
        if task_manager is not None and self._runtime_services.task_manager is not task_manager:
            self._runtime_services.tasks = DefaultTaskService(task_manager)
        self._task_manager = self._runtime_services.task_manager
        self._skill_executor: Any = None
        self._background_tasks: dict[str, asyncio.Task[AgentRunResult]] = {}
        self._notifications: list[RuntimeMessage] = []

    @property
    def notifications(self) -> tuple[RuntimeMessage, ...]:
        return tuple(self._notifications)

    @property
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    def bind_skill_executor(self, skill_executor: Any) -> None:
        self._skill_executor = skill_executor

    async def invoke(self, invocation: AgentInvocation) -> AgentRunResult:
        agent = self._resolve_agent(invocation.agent_name)
        resolved_policy = self._resolve_execution_policy(invocation, agent)
        denial = await self._authorize_agent(invocation, agent, resolved_policy)
        if denial is not None:
            return denial
        if agent.name == "main-router":
            routed = await self._try_compat_route(invocation)
            if routed is not None:
                return routed

        if invocation.background or agent.background:
            return self._start_background(invocation, agent, resolved_policy)
        return await self._run_agent(invocation, agent, resolved_policy)

    async def wait_for_background(self, task_id: str) -> AgentRunResult:
        return await self._background_tasks[task_id]

    async def _try_compat_route(self, invocation: AgentInvocation) -> AgentRunResult | None:
        # These string-prefixed routes remain as a compatibility/debug surface.
        # The assembled turn engine is the primary execution path.
        stripped = invocation.prompt.strip()
        if stripped.startswith("/tool "):
            _, remainder = stripped.split(" ", 1)
            tool_name, raw_payload = remainder.split(" ", 1)
            payload = json.loads(raw_payload)
            scheduler = ToolScheduler(self._tool_registry)
            compat_message = RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.USER,
                content=invocation.prompt,
            )
            tool_pool = tuple(invocation.parent_tool_pool) or self._tool_registry.definitions()
            skill_pool = tuple(invocation.parent_skill_pool) or self._skill_registry.resolve_active()
            context = self._turn_engine.create_tool_context(
                session_id=invocation.session_id,
                turn_id=uuid4().hex,
                agent_name="main-router",
                cwd=invocation.cwd,
                messages=(compat_message,),
                tool_pool=tool_pool,
                skill_pool=skill_pool,
                metadata={**invocation.metadata, "compat_route": True},
            )
            result = await scheduler.run(
                [ToolCall(call_id=uuid4().hex, tool_name=tool_name, tool_input=payload)],
                context,
            )
            content = json.dumps(result[0].output, ensure_ascii=True) if result[0].status == ToolCallStatus.SUCCESS else result[0].error
            return AgentRunResult(
                agent_name="main-router",
                status="completed",
                messages=[
                    RuntimeMessage(
                        message_id=uuid4().hex,
                        role=MessageRole.TOOL,
                        content=content,
                    )
                ],
            )
        if stripped.startswith("/skill "):
            _, remainder = stripped.split(" ", 1)
            skill_name, *arguments = remainder.split()
            executor = self._skill_executor
            if executor is None:
                from .skill_runtime import SkillExecutor

                executor = SkillExecutor(skill_registry=self._skill_registry, agent_runtime=self)
            skill_result = await executor.execute(
                skill_name,
                arguments=arguments,
                session_id=invocation.session_id,
                cwd=invocation.cwd,
                parent_tool_pool=invocation.parent_tool_pool,
                parent_skill_pool=invocation.parent_skill_pool,
                permission_context=invocation.metadata.get("permission_context"),
                turn_id=invocation.metadata.get("turn_id"),
                policy_state=policy_state_from_metadata(invocation.metadata),
            )
            return AgentRunResult(
                agent_name="main-router",
                status="completed",
                messages=skill_result.injected_messages
                or (skill_result.agent_result.messages if skill_result.agent_result else []),
            )
        if stripped.startswith("/agent "):
            _, remainder = stripped.split(" ", 1)
            agent_name, prompt = remainder.split(" ", 1)
            return await self.invoke(
                AgentInvocation(
                    agent_name=agent_name,
                    prompt=prompt,
                    session_id=invocation.session_id,
                    cwd=invocation.cwd,
                    parent_tool_pool=invocation.parent_tool_pool,
                    parent_skill_pool=invocation.parent_skill_pool,
                    metadata={**invocation.metadata, "compat_route": True},
                )
            )
        return None

    def _start_background(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
        policy: ExecutionPolicy,
    ) -> AgentRunResult:
        task_id = uuid4().hex
        self._task_manager.create(task_id, title=f"agent:{agent.name}", metadata={"agent": agent.name})

        async def runner() -> AgentRunResult:
            self._task_manager.update(task_id, status=TaskStatus.RUNNING)
            try:
                result = await self._run_agent(invocation, agent, policy)
                self._task_manager.update(task_id, status=TaskStatus.COMPLETED)
                notification = RuntimeMessage(
                    message_id=uuid4().hex,
                    role=MessageRole.NOTIFICATION,
                    content=f"Background agent '{agent.name}' completed",
                    metadata={"task_id": task_id},
                )
                result.notification = notification
                self._notifications.append(notification)
                await self._runtime_services.host.emit_notification(notification)
                return result
            except Exception as exc:  # pragma: no cover - defensive boundary
                self._task_manager.update(task_id, status=TaskStatus.FAILED, error=str(exc))
                raise

        task = asyncio.create_task(runner())
        self._background_tasks[task_id] = task
        return AgentRunResult(
            agent_name=agent.name,
            status="running",
            task_id=task_id,
            background=True,
            isolation_mode=policy.isolation_mode,
        )

    async def _run_agent(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
        policy: ExecutionPolicy,
    ) -> AgentRunResult:
        turn_id = uuid4().hex
        isolation_lease = await self._prepare_isolation(invocation, agent, policy)
        effective_tools = policy.tool_pool
        effective_skills = policy.skill_pool
        effective_agent = replace(
            agent,
            tools=tuple(tool.name for tool in effective_tools),
            skills=tuple(skill.name for skill in effective_skills),
            permission_mode=policy.permission_context.mode,
            memory=policy.memory_scope,
            isolation=policy.isolation_mode,
        )
        memory_service = self._runtime_services.memory
        owner = self._register_invocation_hooks(invocation, turn_id=turn_id)
        try:
            if memory_service is not None and hasattr(memory_service, "start_session"):
                await _maybe_await(
                    memory_service.start_session(
                        session_id=invocation.session_id,
                        agent=effective_agent,
                        cwd=isolation_lease.working_directory,
                        set_default=False,
                    )
                )
            prompt_message = RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.USER,
                content=invocation.prompt,
            )
            child_policy_state = ExecutionPolicyState(policy)
            runtime_context = {
                **dict(invocation.metadata),
                "agent_name": agent.name,
                "background": invocation.background,
                "turn_id": turn_id,
                "permission_context": policy.permission_context,
                EXECUTION_POLICY_STATE_KEY: child_policy_state,
                "isolation": serialize_isolation_lease(isolation_lease),
            }
            turn_result = await self._turn_engine.run_turn(
                session_id=invocation.session_id,
                turn_id=turn_id,
                agent=effective_agent,
                cwd=str(isolation_lease.working_directory),
                messages=[prompt_message],
                base_system_prompt=invocation.metadata.get("system_prompt", ""),
                runtime_context=runtime_context,
            )
            result = AgentRunResult(
                agent_name=agent.name,
                status="completed" if turn_result.completed else "max_turns",
                messages=turn_result.messages,
                background=invocation.background or agent.background,
                isolation_mode=policy.isolation_mode,
            )
            await self._dispatch_subagent_stop(invocation.session_id, agent.name, result.status)
            return result
        finally:
            if owner is not None and self._runtime_services.hook_bus is not None:
                self._runtime_services.hook_bus.release_owner(invocation.session_id, owner)
            await self._runtime_services.isolation.cleanup(isolation_lease)

    def _resolve_agent(self, name: str) -> AgentDefinition:
        agent = self._agent_registry.get(name)
        if agent is None:
            raise KeyError(name)
        return agent

    def _resolve_execution_policy(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
    ) -> ExecutionPolicy:
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
            agent,
            parent_policy=parent_policy,
            base_tool_pool=base_tool_pool,
            base_skill_pool=base_skill_pool,
            permission_context=permission_context,
        )

    async def _prepare_isolation(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
        policy: ExecutionPolicy,
    ) -> IsolationLease:
        return await self._runtime_services.isolation.prepare(
            session_id=invocation.session_id,
            agent_name=agent.name,
            mode=policy.isolation_mode,
            cwd=invocation.cwd,
            metadata={
                "background": invocation.background or agent.background,
                "policy": serialize_runtime_metadata({EXECUTION_POLICY_STATE_KEY: ExecutionPolicyState(policy)})[
                    "policy"
                ],
            },
        )

    async def _authorize_agent(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
        policy: ExecutionPolicy,
    ) -> AgentRunResult | None:
        if agent.name == "main-router" and not invocation.background:
            return None
        initial = PermissionDecision(
            PermissionBehavior.ASK
            if (
                invocation.background or policy.isolation_mode != IsolationMode.NONE
            )
            and _supports_permission_requests(self._runtime_services.host)
            else PermissionBehavior.ALLOW
        )
        request = PermissionRequest(
            session_id=invocation.session_id,
            turn_id=None,
            target=PermissionTarget.AGENT,
            name=agent.name,
            payload={"prompt": invocation.prompt, "background": invocation.background},
            context=policy.permission_context,
            message=f"Agent '{agent.name}' requires permission",
        )
        runtime_context = _PermissionRuntimeContext(
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
        return AgentRunResult(
            agent_name=agent.name,
            status="denied",
            messages=[
                RuntimeMessage(
                    message_id=uuid4().hex,
                    role=MessageRole.NOTIFICATION,
                    content=outcome.message or f"Agent '{agent.name}' was denied",
                    metadata={"permission_denied": True},
                )
            ],
            background=invocation.background or agent.background,
            isolation_mode=policy.isolation_mode,
        )

    def _register_invocation_hooks(
        self,
        invocation: AgentInvocation,
        *,
        turn_id: str,
    ) -> str | None:
        hooks = invocation.metadata.get("skill_hooks")
        if not isinstance(hooks, dict) or self._runtime_services.hook_bus is None:
            return None
        owner = str(invocation.metadata.get("skill_hook_owner") or f"skill:delegated:{uuid4().hex}")
        self._runtime_services.hook_bus.register_handlers(
            session_id=invocation.session_id,
            owner=owner,
            hooks=hooks,
            turn_id=turn_id,
        )
        return owner

    async def _dispatch_subagent_stop(self, session_id: str, agent_name: str, status: str) -> None:
        if self._runtime_services.hook_bus is None:
            return
        await self._runtime_services.hook_bus.dispatch(
            session_id,
            SubagentStopPayload(
                session_id=session_id,
                agent_name=agent_name,
                status=status,
            ),
        )


@dataclass(frozen=True, slots=True)
class _PermissionRuntimeContext:
    runtime_services: RuntimeServices
    permission_context: PermissionContext | None = None


def _supports_permission_requests(host: Any) -> bool:
    if isinstance(host, CallbackHostAdapter):
        return host.permission_handler is not None
    if type(host) is NullHostAdapter:
        return False
    return True


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
