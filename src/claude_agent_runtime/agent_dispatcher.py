from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .agent_execution import AgentExecutionSpec, AgentRunStatus, SpawnMode
from .contracts import MessageRole, RuntimeMessage
from .definitions import AgentDefinition
from .execution_policy import policy_state_from_metadata
from .runtime_services import RuntimeServices
from .tasking import TaskStatus

if TYPE_CHECKING:
    from .agent_execution_service import AgentExecutionService
    from .agent_runtime import AgentInvocation, AgentRunResult


class AgentDispatcher:
    def __init__(
        self,
        *,
        execution_service: AgentExecutionService,
        runtime_services: RuntimeServices,
    ) -> None:
        self._execution_service = execution_service
        self._runtime_services = runtime_services
        self._task_manager = runtime_services.task_manager
        self._background_tasks: dict[str, asyncio.Task[AgentRunResult]] = {}
        self._notifications: list[RuntimeMessage] = []

    @property
    def notifications(self) -> tuple[RuntimeMessage, ...]:
        return tuple(self._notifications)

    async def wait_for_background(self, task_id: str) -> AgentRunResult:
        return await self._background_tasks[task_id]

    def resolve_agent(self, name: str) -> AgentDefinition:
        return self._execution_service.resolve_agent(name)

    def build_execution_spec(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
    ) -> AgentExecutionSpec:
        explicit_query_source = (
            invocation.query_source
            or _coerce_optional_string(invocation.metadata.get("query_source"))
        )
        spawn_mode = self._resolve_spawn_mode(invocation, agent, query_source=explicit_query_source)
        query_source = explicit_query_source or self._default_query_source(
            invocation,
            agent,
            spawn_mode=spawn_mode,
        )
        return AgentExecutionSpec(
            run_id=uuid4().hex,
            parent_run_id=invocation.parent_run_id or _coerce_optional_string(invocation.metadata.get("run_id")),
            session_id=invocation.session_id,
            parent_turn_id=invocation.parent_turn_id
            or _coerce_optional_string(invocation.metadata.get("turn_id")),
            turn_id=uuid4().hex,
            agent_name=agent.name,
            spawn_mode=spawn_mode,
            query_source=query_source,
            prompt_messages=(
                RuntimeMessage(
                    message_id=uuid4().hex,
                    role=MessageRole.USER,
                    content=invocation.prompt,
                ),
            ),
            cwd=invocation.cwd,
            base_system_prompt=_coerce_optional_string(invocation.metadata.get("system_prompt")) or "",
            parent_policy_state=policy_state_from_metadata(invocation.metadata),
            requested_model_route=invocation.requested_model_route
            or _coerce_optional_string(invocation.metadata.get("requested_model_route")),
            requested_model=invocation.requested_model
            or _coerce_optional_string(invocation.metadata.get("requested_model")),
            requested_permission_mode=invocation.requested_permission_mode,
            requested_isolation=invocation.requested_isolation,
            max_turns=invocation.max_turns,
            background=spawn_mode is SpawnMode.BACKGROUND,
            metadata=dict(invocation.metadata),
        )

    async def dispatch(
        self,
        invocation: AgentInvocation,
        *,
        agent: AgentDefinition | None = None,
        execution_spec: AgentExecutionSpec | None = None,
    ) -> AgentRunResult:
        from .agent_runtime import AgentRunResult

        resolved_agent = agent or self.resolve_agent(invocation.agent_name)
        resolved_spec = execution_spec or self.build_execution_spec(invocation, resolved_agent)
        if resolved_spec.spawn_mode is SpawnMode.BACKGROUND:
            return await self._start_background(invocation, resolved_agent, resolved_spec)
        return await self._execution_service.run(invocation, resolved_spec)

    async def _start_background(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
        execution_spec: AgentExecutionSpec,
    ) -> AgentRunResult:
        from .agent_runtime import AgentRunResult

        task_id = uuid4().hex
        self._task_manager.create(
            task_id,
            title=f"agent:{agent.name}",
            metadata={"agent": agent.name, "run_id": execution_spec.run_id},
        )
        running_record = await self._execution_service.write_running_record(invocation, execution_spec)

        async def runner() -> AgentRunResult:
            self._task_manager.update(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={
                    "agent_status": AgentRunStatus.RUNNING.value,
                    "run_id": execution_spec.run_id,
                    "turn_id": execution_spec.turn_id,
                },
            )
            try:
                result = await self._execution_service.run(invocation, execution_spec)
                self._task_manager.update(
                    task_id,
                    status=_task_status_for_agent_result(result.status),
                    result={
                        "agent_status": result.status,
                        "run_id": result.run_id,
                        "turn_id": result.turn_id,
                    },
                    error=_background_error_for_result(result),
                    metadata={
                        "agent_status": result.status,
                        "run_id": result.run_id,
                        "turn_id": result.turn_id,
                    },
                )
                notification = _background_notification(
                    agent_name=agent.name,
                    status=result.status,
                    task_id=task_id,
                    error=_background_error_for_result(result),
                )
                result.notification = notification
                self._notifications.append(notification)
                await self._runtime_services.host.emit_notification(notification)
                return result
            except Exception as exc:  # pragma: no cover - defensive boundary
                self._task_manager.update(
                    task_id,
                    status=TaskStatus.FAILED,
                    error=str(exc),
                    metadata={
                        "agent_status": AgentRunStatus.FAILED.value,
                        "run_id": execution_spec.run_id,
                        "turn_id": execution_spec.turn_id,
                    },
                )
                notification = _background_notification(
                    agent_name=agent.name,
                    status=AgentRunStatus.FAILED.value,
                    task_id=task_id,
                    error=str(exc),
                )
                self._notifications.append(notification)
                await self._runtime_services.host.emit_notification(notification)
                raise

        task = asyncio.create_task(runner())
        self._background_tasks[task_id] = task
        return AgentRunResult(
            agent_name=agent.name,
            status="running",
            task_id=task_id,
            background=True,
            run_id=execution_spec.run_id,
            parent_run_id=execution_spec.parent_run_id,
            turn_id=execution_spec.turn_id,
            query_source=execution_spec.query_source,
            execution_spec=execution_spec,
            run_record=running_record,
        )

    def _resolve_spawn_mode(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
        *,
        query_source: str | None,
    ) -> SpawnMode:
        if invocation.spawn_mode is not None:
            return invocation.spawn_mode
        if invocation.background or agent.background:
            return SpawnMode.BACKGROUND
        if query_source == "skill_fork" or "skill_hook_owner" in invocation.metadata:
            return SpawnMode.FORK
        return SpawnMode.SYNC

    def _default_query_source(
        self,
        invocation: AgentInvocation,
        agent: AgentDefinition,
        *,
        spawn_mode: SpawnMode,
    ) -> str:
        if spawn_mode is SpawnMode.BACKGROUND:
            return "background_agent"
        if spawn_mode is SpawnMode.FORK or "skill_hook_owner" in invocation.metadata:
            return "skill_fork"
        if invocation.metadata.get("compat_route"):
            return "compat_agent_route"
        return "agent_invocation"


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    stringified = str(value).strip()
    return stringified or None


def _task_status_for_agent_result(status: str) -> TaskStatus:
    if status == AgentRunStatus.COMPLETED.value:
        return TaskStatus.COMPLETED
    if status == AgentRunStatus.MAX_TURNS.value:
        return TaskStatus.STOPPED
    return TaskStatus.FAILED


def _background_error_for_result(result: AgentRunResult) -> str | None:
    run_record = result.run_record
    if run_record is not None:
        error = run_record.terminal_metadata.get("error")
        if error is not None:
            return str(error)
    for message in result.messages:
        if message.metadata.get("permission_denied"):
            return message.text
    return None


def _background_notification(
    *,
    agent_name: str,
    status: str,
    task_id: str,
    error: str | None = None,
) -> RuntimeMessage:
    status_text = {
        AgentRunStatus.COMPLETED.value: "completed",
        AgentRunStatus.MAX_TURNS.value: "stopped after reaching the max turn limit",
        AgentRunStatus.DENIED.value: "was denied",
        AgentRunStatus.FAILED.value: "failed",
    }.get(status, f"ended with status '{status}'")
    content = f"Background agent '{agent_name}' {status_text}"
    if error:
        content = f"{content}: {error}"
    return RuntimeMessage(
        message_id=uuid4().hex,
        role=MessageRole.NOTIFICATION,
        content=content,
        metadata={"task_id": task_id, "status": status},
    )
