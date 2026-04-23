import asyncio
from pathlib import Path

from runtime.builtins.tools import builtin_tools
from runtime.contracts import RuntimePrivateContext
from runtime.hosts.base import NullHostAdapter
from runtime.jobs import (
    JobExecutorBinding,
    JobExecutorContext,
    JobRecoveryResult,
    JobScopeFilter,
    JobStartResult,
    JobStatus,
    JobStopResult,
    JobSubmitRequest,
)
from runtime.registries import AgentRegistry, SkillRegistry, ToolRegistry
from runtime.runtime_kernel import RuntimeConfig, assemble_runtime
from runtime.tasking import TaskStatus
from runtime.tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler


class _ImmediateExecutor:
    def __init__(self, name: str) -> None:
        self.name = name

    async def submit(
        self,
        request: JobSubmitRequest,
        *,
        context: JobExecutorContext,
    ) -> JobStartResult:
        _ = context
        return JobStartResult(
            status=JobStatus.COMPLETED,
            metadata={"executor_name": self.name},
            result={"handled_by": self.name, "executor_kind": request.executor_kind},
        )

    async def stop(self, record, *, context: JobExecutorContext) -> JobStopResult:
        _ = record, context
        return JobStopResult(status=JobStatus.STOPPED)

    async def recover(self, record, *, context: JobExecutorContext) -> JobRecoveryResult | None:
        _ = record, context
        return None


class _FailingExecutor:
    async def submit(
        self,
        request: JobSubmitRequest,
        *,
        context: JobExecutorContext,
    ) -> JobStartResult:
        _ = request, context
        raise RuntimeError("boom")

    async def stop(self, record, *, context: JobExecutorContext) -> JobStopResult:
        _ = record, context
        return JobStopResult(status=JobStatus.STOPPED)

    async def recover(self, record, *, context: JobExecutorContext) -> JobRecoveryResult | None:
        _ = record, context
        return None


def _job_tool_context(runtime, tmp_path: Path, *, session_id: str, team_id: str | None = None) -> ToolContext:
    tool_registry = ToolRegistry()
    for definition in builtin_tools():
        tool_registry.register(definition)
    async def allow_permissions(*args, **kwargs):
        from runtime.definitions import PermissionBehavior, PermissionDecision

        _ = args, kwargs
        return PermissionDecision(PermissionBehavior.ALLOW)

    runtime.services.configure_compat(permission_handler=allow_permissions)
    return ToolContext(
        session_id=session_id,
        turn_id="turn-job",
        agent_name="planner",
        cwd=tmp_path,
        tool_registry=tool_registry,
        agent_registry=AgentRegistry(),
        skill_registry=SkillRegistry(),
        runtime_services=runtime.services,
        private_context=RuntimePrivateContext(
            extensions={"team_id": team_id} if team_id is not None else {}
        ),
    )


def test_job_payload_is_canonical_across_tool_and_host_surfaces(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    bound = runtime.bind_host(NullHostAdapter())
    runtime.task_manager.create(
        "job-1",
        title="background-check",
        description="inspect a shared record",
        metadata={
            "session_id": "session-canonical",
            "team_id": "team-alpha",
            "submitted_by": "planner",
            "kind": "background_agent",
            "projection_kind": "background_agent",
            "run_id": "run-1",
            "turn_id": "turn-1",
        },
    )
    runtime.task_manager.update("job-1", status=TaskStatus.RUNNING)

    async def scenario() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        context = _job_tool_context(
            runtime,
            tmp_path,
            session_id="session-canonical",
            team_id="team-alpha",
        )
        scheduler = ToolScheduler(context.tool_registry)
        fetched = (
            await scheduler.run([ToolCall("1", "job_get", {"job_id": "job-1"})], context)
        )[0].output["job"]
        listed = (
            await scheduler.run([ToolCall("2", "job_list", {})], context)
        )[0].output["jobs"][0]
        hosted = await bound.get_job("job-1", session_id="session-canonical")
        return fetched, listed, hosted

    fetched, listed, hosted = asyncio.run(scenario())

    assert fetched == listed == hosted
    assert fetched["job_id"] == "job-1"
    assert fetched["executor_kind"] == "agent"
    assert fetched["control"] == {"stoppable": False, "stop_requested": False}
    assert fetched["visibility"] == {
        "session_id": "session-canonical",
        "team_id": "team-alpha",
        "submitted_by": "planner",
        "projection_kind": "background_agent",
    }
    assert fetched["linkage"] == {"parent_run_id": "run-1", "parent_turn_id": "turn-1"}
    assert fetched["sidecars"] == [
        {"kind": "agent_run", "ref": "run-1", "metadata": {"agent": None}}
    ]
    assert fetched["timestamps"]["created_at"]
    assert fetched["timestamps"]["updated_at"]


def test_bound_host_watch_and_stop_use_shared_job_service(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    bound = runtime.bind_host(NullHostAdapter())
    observed: list[list[dict[str, object]]] = []

    async def scenario() -> dict[str, object]:
        unsubscribe = await bound.watch_jobs(
            session_id="session-watch",
            callback=lambda snapshot: observed.append(snapshot),
        )
        runtime.task_manager.create(
            "job-1",
            title="background-watch",
            metadata={"session_id": "session-watch", "kind": "background_agent", "run_id": "run-watch"},
        )
        runtime.task_manager.register_stop_handler(
            "job-1",
            lambda task: runtime.task_manager.update(task.task_id, status=TaskStatus.STOPPED),
        )
        await asyncio.sleep(0)
        runtime.task_manager.update("job-1", status=TaskStatus.RUNNING)
        await asyncio.sleep(0)
        stopped = await bound.stop_job("job-1", session_id="session-watch")
        await asyncio.sleep(0)
        unsubscribe()
        return stopped

    stopped = asyncio.run(scenario())

    assert observed[0] == []
    assert any(snapshot and snapshot[0]["status"] == "running" for snapshot in observed[1:])
    assert observed[-1][0]["status"] == "stopped"
    assert stopped["status"] == "stopped"
    assert stopped["control"]["stop_requested"] is True


def test_job_watchers_receive_cross_thread_terminal_updates(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    observed: list[list[tuple[str, str]]] = []

    async def scenario() -> None:
        unsubscribe = await runtime.job_service.watch(
            scope=JobScopeFilter(session_id="session-cross-thread"),
            callback=lambda snapshot: observed.append(
                [(record.job_id, record.status.value) for record in snapshot]
            ),
        )
        runtime.task_manager.create(
            "job-threaded",
            title="threaded projection",
            metadata={"session_id": "session-cross-thread", "kind": "background_memory_consolidation"},
        )
        runtime.task_manager.update("job-threaded", status=TaskStatus.RUNNING)
        await asyncio.sleep(0)
        await asyncio.to_thread(
            runtime.task_manager.update,
            "job-threaded",
            status=TaskStatus.COMPLETED,
        )
        await asyncio.sleep(0)
        unsubscribe()

    asyncio.run(scenario())

    assert observed[0] == []
    assert any(snapshot and snapshot[0][1] == "running" for snapshot in observed[1:])
    assert any(snapshot and snapshot[0][1] == "completed" for snapshot in observed[1:])


def test_job_stop_surface_returns_structured_shared_errors(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    context = _job_tool_context(runtime, tmp_path, session_id="session-errors")
    scheduler = ToolScheduler(context.tool_registry)

    runtime.task_manager.create(
        "job-running-locked",
        title="locked job",
        metadata={"session_id": "session-errors", "kind": "background_agent", "stoppable": False},
    )
    runtime.task_manager.update("job-running-locked", status=TaskStatus.RUNNING)
    runtime.task_manager.create(
        "job-finished",
        title="finished job",
        metadata={"session_id": "session-errors", "kind": "background_agent"},
    )
    runtime.task_manager.update("job-finished", status=TaskStatus.COMPLETED)

    locked, finished = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "job_stop", {"job_id": "job-running-locked"}),
                ToolCall("2", "job_stop", {"job_id": "job-finished"}),
            ],
            context,
        )
    )

    assert locked.status == ToolCallStatus.ERROR
    assert locked.output["error"]["code"] == "not_stoppable"
    assert finished.status == ToolCallStatus.ERROR
    assert finished.output["error"]["code"] == "not_running"


def test_runtime_config_registers_direct_and_factory_job_executors(tmp_path: Path) -> None:
    direct = _ImmediateExecutor("direct")
    factory_calls: list[tuple[str, str]] = []

    def build_factory(executor_kind, binding, kernel, services):
        _ = binding, services
        factory_calls.append((executor_kind, kernel.config.runtime_id))
        return _ImmediateExecutor("factory")

    runtime = assemble_runtime(
        RuntimeConfig(
            runtime_id="job-executor-test",
            working_directory=tmp_path,
            discovery_sources=RuntimeConfig.for_project(tmp_path).discovery_sources,
            job_executors={
                "direct-demo": JobExecutorBinding(executor=direct),
                "factory-demo": JobExecutorBinding(factory=build_factory),
            },
        )
    )

    async def scenario():
        direct_job = await runtime.job_service.submit(
            JobSubmitRequest(
                executor_kind="direct-demo",
                summary="run direct",
                session_id="session-direct",
            )
        )
        factory_job = await runtime.job_service.submit(
            JobSubmitRequest(
                executor_kind="factory-demo",
                summary="run factory",
                session_id="session-factory",
            )
        )
        return direct_job, factory_job

    direct_job, factory_job = asyncio.run(scenario())

    assert runtime.job_service.executor_registry.get("direct-demo") is direct
    assert runtime.job_service.executor_registry.get("factory-demo") is not None
    assert factory_calls == [("factory-demo", "job-executor-test")]
    assert direct_job.result == {"handled_by": "direct", "executor_kind": "direct-demo"}
    assert factory_job.result == {"handled_by": "factory", "executor_kind": "factory-demo"}


def test_submit_failure_marks_job_failed_in_store(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            discovery_sources=RuntimeConfig.for_project(tmp_path).discovery_sources,
            job_executors={"failing-demo": JobExecutorBinding(executor=_FailingExecutor())},
        )
    )

    async def scenario():
        try:
            await runtime.job_service.submit(
                JobSubmitRequest(
                    executor_kind="failing-demo",
                    summary="run broken",
                    session_id="session-failing",
                    requested_job_id="job-failing",
                )
            )
        except RuntimeError as exc:
            assert str(exc) == "boom"
        return await runtime.job_service.get("job-failing", scope=JobScopeFilter(session_id="session-failing"))

    record = asyncio.run(scenario())

    assert record is not None
    assert record.status is JobStatus.FAILED
    assert record.error == "boom"
    assert record.metadata["submit_failed"] is True


def test_task_manager_is_a_compatibility_projection_over_job_service(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    runtime.task_manager.create(
        "job-compat",
        title="compat job",
        metadata={"session_id": "session-compat", "kind": "background_agent", "run_id": "run-compat"},
    )
    runtime.task_manager.update("job-compat", status=TaskStatus.RUNNING)

    async def scenario():
        record = await runtime.job_service.get("job-compat")
        assert record is not None
        runtime.job_service.apply_recovery_result(
            "job-compat",
            JobRecoveryResult(
                status=JobStatus.COMPLETED,
                result={"source": "job_service"},
            ),
        )
        return await runtime.job_service.get("job-compat")

    record = asyncio.run(scenario())
    projected = runtime.task_manager.get("job-compat")

    assert record is not None
    assert record.status is JobStatus.COMPLETED
    assert projected is not None
    assert projected.status is TaskStatus.COMPLETED
    assert projected.result == {"source": "job_service"}


def test_runtime_config_can_override_builtin_agent_executor(tmp_path: Path) -> None:
    override = _ImmediateExecutor("override-agent")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            discovery_sources=RuntimeConfig.for_project(tmp_path).discovery_sources,
            job_executors={"agent": JobExecutorBinding(executor=override)},
        )
    )

    async def scenario() -> tuple[dict[str, object], dict[str, object] | None]:
        result = await runtime.run_agent_tool(
            "general-purpose",
            "complete immediately",
            ToolContext(
                session_id="session-override",
                turn_id="turn-override",
                agent_name="planner",
                cwd=tmp_path,
                runtime_services=runtime.services,
            ),
            background=True,
        )
        job = await runtime.get_job(result["task_id"], session_id="session-override")
        return result, job

    result, job = asyncio.run(scenario())

    assert runtime.job_service.executor_registry.get("agent") is override
    assert result["status"] == "completed"
    assert job is not None
    assert job["result"] == {"handled_by": "override-agent", "executor_kind": "agent"}
