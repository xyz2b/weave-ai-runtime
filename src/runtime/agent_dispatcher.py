from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .agent_execution import AgentExecutionSpec, AgentRunStatus, SpawnMode
from .contracts import MessageRole, RuntimeMessage
from .definitions import AgentDefinition
from .execution_policy import policy_state_from_metadata
from .jobs import (
    JobControlCapabilities,
    JobExecutor,
    JobExecutorContext,
    JobRecoveryResult,
    JobSidecarRef,
    JobStartResult,
    JobStatus,
    JobStopResult,
    JobSubmitRequest,
)
from .runtime_services import RuntimeServices
from uuid import uuid4

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
        self._background_tasks: dict[str, asyncio.Task[AgentRunResult]] = {}
        self._notifications: list[RuntimeMessage] = []
        self._job_executor = AgentJobExecutor(dispatcher=self)

    @property
    def notifications(self) -> tuple[RuntimeMessage, ...]:
        return tuple(self._notifications)

    @property
    def job_executor(self) -> JobExecutor:
        return self._job_executor

    async def wait_for_background(self, task_id: str) -> AgentRunResult:
        task = self._background_tasks[task_id]
        try:
            return await task
        except asyncio.CancelledError:
            record = self._runtime_services.job_service.get_sync(task_id)
            if record is None:
                raise
            from .agent_runtime import AgentRunResult

            return AgentRunResult(
                agent_name=_coerce_optional_string(record.metadata.get("agent")) or record.summary,
                status=AgentRunStatus.STOPPED.value,
                task_id=task_id,
                background=True,
                run_id=_coerce_optional_string(record.metadata.get("run_id")),
                parent_run_id=record.parent_run_id,
                turn_id=_coerce_optional_string(record.metadata.get("turn_id")) or record.parent_turn_id,
                query_source=_coerce_optional_string(record.metadata.get("query_source")),
            )
        finally:
            if self._background_tasks.get(task_id) is task:
                self._background_tasks.pop(task_id, None)

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
            requested_effort=invocation.requested_effort
            if invocation.requested_effort is not None
            else invocation.metadata.get("requested_effort"),
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

        job = await self._runtime_services.job_service.submit(
            JobSubmitRequest(
                executor_kind="agent",
                summary=f"agent:{agent.name}",
                input={
                    "agent": agent,
                    "invocation": invocation,
                    "execution_spec": execution_spec,
                },
                description=invocation.prompt,
                session_id=execution_spec.session_id,
                team_id=_coerce_optional_string(execution_spec.metadata.get("team_id")),
                submitted_by=_coerce_optional_string(execution_spec.metadata.get("submitted_by")),
                projection_kind="background_agent",
                parent_run_id=execution_spec.parent_run_id,
                parent_turn_id=execution_spec.parent_turn_id,
                metadata=_background_job_metadata(
                    execution_spec,
                    agent_name=agent.name,
                ),
                capabilities=JobControlCapabilities(stoppable=True),
                sidecar_refs=_agent_sidecar_refs(execution_spec, agent_name=agent.name),
            )
        )
        running_record = await self._execution_service.run_store.get(execution_spec.run_id)
        initial_status = (
            _coerce_optional_string((job.result or {}).get("agent_status"))
            or (JobStatus.RUNNING.value if job.status is JobStatus.RUNNING else job.status.value)
        )
        return AgentRunResult(
            agent_name=agent.name,
            status=initial_status,
            task_id=job.job_id,
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


def _background_job_metadata(
    execution_spec: AgentExecutionSpec,
    *,
    agent_name: str | None = None,
    agent_status: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "run_id": execution_spec.run_id,
        "session_id": execution_spec.session_id,
        "query_source": execution_spec.query_source,
        "kind": "background_agent",
    }
    if agent_name is not None:
        metadata["agent"] = agent_name
    if agent_status is not None:
        metadata["agent_status"] = agent_status
        metadata["turn_id"] = execution_spec.turn_id
    team_id = _coerce_optional_string(execution_spec.metadata.get("team_id"))
    if team_id is not None:
        metadata["team_id"] = team_id
    return metadata


def _job_status_for_agent_result(status: str) -> JobStatus:
    if status == AgentRunStatus.COMPLETED.value:
        return JobStatus.COMPLETED
    if status == AgentRunStatus.MAX_TURNS.value:
        return JobStatus.STOPPED
    if status == AgentRunStatus.STOPPED.value:
        return JobStatus.STOPPED
    return JobStatus.FAILED


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
        AgentRunStatus.STOPPED.value: "was stopped",
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


def _agent_sidecar_refs(
    execution_spec: AgentExecutionSpec,
    *,
    agent_name: str | None,
) -> tuple[JobSidecarRef, ...]:
    metadata: dict[str, Any] = {}
    if agent_name is not None:
        metadata["agent"] = agent_name
    return (JobSidecarRef(kind="agent_run", ref=execution_spec.run_id, metadata=metadata),)


class AgentJobExecutor:
    def __init__(self, *, dispatcher: AgentDispatcher) -> None:
        self._dispatcher = dispatcher

    async def submit(
        self,
        request: JobSubmitRequest,
        *,
        context: JobExecutorContext,
    ) -> JobStartResult:
        from .agent_runtime import AgentRunResult

        invocation = request.input.get("invocation")
        agent = request.input.get("agent")
        execution_spec = request.input.get("execution_spec")
        if invocation is None or agent is None or execution_spec is None:
            raise ValueError("Agent job submission requires invocation, agent, and execution_spec")
        job_id = request.requested_job_id or uuid4().hex
        running_record = await self._dispatcher._execution_service.write_running_record(
            invocation,
            execution_spec,
        )

        async def runner() -> AgentRunResult:
            try:
                result = await self._dispatcher._execution_service.run(invocation, execution_spec)
                context.services.job_service.apply_recovery_result(
                    job_id,
                    JobRecoveryResult(
                        status=_job_status_for_agent_result(result.status),
                        metadata=_background_job_metadata(
                            execution_spec,
                            agent_status=result.status,
                        ),
                        sidecar_refs=_agent_sidecar_refs(execution_spec, agent_name=agent.name),
                        result={
                            "agent_status": result.status,
                            "run_id": result.run_id,
                            "turn_id": result.turn_id,
                        },
                        error=_background_error_for_result(result),
                    ),
                )
                notification = _background_notification(
                    agent_name=agent.name,
                    status=result.status,
                    task_id=job_id,
                    error=_background_error_for_result(result),
                )
                result.notification = notification
                self._dispatcher._notifications.append(notification)
                await self._dispatcher._runtime_services.host.emit_notification(notification)
                return result
            except asyncio.CancelledError:
                stopped_record = await self._dispatcher._execution_service.write_terminal_record(
                    invocation,
                    execution_spec,
                    status=AgentRunStatus.STOPPED,
                    terminal_metadata={"stopped": True},
                )
                context.services.job_service.apply_recovery_result(
                    job_id,
                    JobRecoveryResult(
                        status=JobStatus.STOPPED,
                        metadata=_background_job_metadata(
                            execution_spec,
                            agent_status=AgentRunStatus.STOPPED.value,
                        ),
                        sidecar_refs=_agent_sidecar_refs(execution_spec, agent_name=agent.name),
                        result={
                            "agent_status": AgentRunStatus.STOPPED.value,
                            "run_id": execution_spec.run_id,
                            "turn_id": execution_spec.turn_id,
                        },
                    ),
                )
                notification = _background_notification(
                    agent_name=agent.name,
                    status=AgentRunStatus.STOPPED.value,
                    task_id=job_id,
                )
                self._dispatcher._notifications.append(notification)
                await self._dispatcher._runtime_services.host.emit_notification(notification)
                return AgentRunResult(
                    agent_name=agent.name,
                    status=AgentRunStatus.STOPPED.value,
                    messages=[],
                    background=True,
                    isolation_mode=None,
                    notification=notification,
                    run_id=execution_spec.run_id,
                    parent_run_id=execution_spec.parent_run_id,
                    turn_id=execution_spec.turn_id,
                    query_source=execution_spec.query_source,
                    execution_spec=execution_spec,
                    run_record=stopped_record,
                    task_id=job_id,
                )
            except Exception as exc:  # pragma: no cover - defensive boundary
                context.services.job_service.apply_recovery_result(
                    job_id,
                    JobRecoveryResult(
                        status=JobStatus.FAILED,
                        metadata=_background_job_metadata(
                            execution_spec,
                            agent_status=AgentRunStatus.FAILED.value,
                        ),
                        sidecar_refs=_agent_sidecar_refs(execution_spec, agent_name=agent.name),
                        error=str(exc),
                    ),
                )
                notification = _background_notification(
                    agent_name=agent.name,
                    status=AgentRunStatus.FAILED.value,
                    task_id=job_id,
                    error=str(exc),
                )
                self._dispatcher._notifications.append(notification)
                await self._dispatcher._runtime_services.host.emit_notification(notification)
                raise

        task = asyncio.create_task(runner())
        self._dispatcher._background_tasks[job_id] = task
        return JobStartResult(
            status=JobStatus.RUNNING,
            capabilities=JobControlCapabilities(stoppable=True),
            metadata=_background_job_metadata(
                execution_spec,
                agent_status=AgentRunStatus.RUNNING.value,
            ),
            sidecar_refs=_agent_sidecar_refs(execution_spec, agent_name=agent.name),
            result={
                "agent_status": AgentRunStatus.RUNNING.value,
                "run_id": running_record.run_id,
                "turn_id": running_record.turn_id,
            },
        )

    async def stop(
        self,
        record: Any,
        *,
        context: JobExecutorContext,
    ) -> JobStopResult:
        task = self._dispatcher._background_tasks.get(record.job_id)
        run_id = _coerce_optional_string(record.metadata.get("run_id"))
        turn_id = _coerce_optional_string(record.metadata.get("turn_id"))
        if task is None:
            return JobStopResult(
                status=JobStatus.STOPPED,
                stop_requested=True,
                metadata=dict(record.metadata),
                sidecar_refs=tuple(record.sidecar_refs),
                result={
                    "agent_status": AgentRunStatus.STOPPED.value,
                    "run_id": run_id,
                    "turn_id": turn_id,
                },
                error="Background agent handle was unavailable during stop",
            )
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return JobStopResult(
            status=JobStatus.STOPPED,
            stop_requested=True,
            metadata=dict(record.metadata),
            sidecar_refs=tuple(record.sidecar_refs),
            result={
                "agent_status": AgentRunStatus.STOPPED.value,
                "run_id": run_id,
                "turn_id": turn_id,
            },
        )

    async def recover(
        self,
        record: Any,
        *,
        context: JobExecutorContext,
    ) -> JobRecoveryResult | None:
        task = self._dispatcher._background_tasks.get(record.job_id)
        if task is not None and not task.done():
            return JobRecoveryResult(
                status=JobStatus.RUNNING,
                capabilities=JobControlCapabilities(stoppable=True),
                metadata=dict(record.metadata),
                sidecar_refs=tuple(record.sidecar_refs),
            )
        metadata = dict(record.metadata)
        metadata["agent_status"] = AgentRunStatus.STOPPED.value
        metadata["recovery"] = "lost_handle"
        return JobRecoveryResult(
            status=JobStatus.STOPPED,
            capabilities=record.capabilities or JobControlCapabilities(stoppable=True),
            metadata=metadata,
            sidecar_refs=tuple(record.sidecar_refs),
            error="Background agent job was interrupted before recovery",
        )
