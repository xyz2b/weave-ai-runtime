import asyncio
from pathlib import Path

from runtime.builtins.tools import builtin_tools
from runtime.contracts import RuntimePrivateContext
from runtime.definitions import AgentDefinition, PermissionBehavior, PermissionDecision
from runtime.execution_policy import ExecutionPolicy, ExecutionPolicyState
from runtime.hosts.base import NullHostAdapter
from runtime.permissions import PermissionContext
from runtime.registries import SkillRegistry, ToolRegistry
from runtime.runtime_kernel.config import RuntimeConfig
from runtime.runtime_kernel.kernel import assemble_runtime
from runtime.runtime_services import RuntimeServices
from runtime.task_discipline import TaskDisciplineSidecar
from runtime.task_lists import DefaultTaskListService, FileTaskListStore
from runtime.tasking import TaskManager, TaskStatus
from runtime.tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler


def _build_tool_runtime(
    tmp_path: Path,
    *,
    runtime_services: RuntimeServices | None = None,
) -> tuple[ToolScheduler, ToolContext]:
    tool_registry = ToolRegistry()
    for definition in builtin_tools():
        tool_registry.register(definition)

    async def permission_handler(*args, **kwargs) -> PermissionDecision:
        _ = args, kwargs
        return PermissionDecision(PermissionBehavior.ALLOW)

    context = ToolContext(
        session_id="session",
        turn_id="turn",
        agent_name="planner",
        cwd=tmp_path,
        tool_registry=tool_registry,
        skill_registry=SkillRegistry(),
        task_manager=TaskManager(),
        runtime_services=runtime_services,
        permission_handler=permission_handler,
    )
    return ToolScheduler(tool_registry), context


def test_task_list_service_persists_and_resolves_scope(tmp_path: Path) -> None:
    store_root = tmp_path / ".runtime" / "task_lists"
    service = DefaultTaskListService(store=FileTaskListStore(store_root))

    session_list_id = asyncio.run(service.resolve_list_id(session_id="session-a"))
    team_list_id = asyncio.run(
        service.resolve_list_id(
            session_id="session-b",
            private_context=RuntimePrivateContext(extensions={"team_id": "team-alpha"}),
        )
    )

    asyncio.run(service.create(session_list_id, subject="Write docs"))
    asyncio.run(service.create(team_list_id, subject="Coordinate deploy"))

    reopened = DefaultTaskListService(store=FileTaskListStore(store_root))
    session_tasks = asyncio.run(reopened.list(session_list_id))
    team_tasks = asyncio.run(reopened.list(team_list_id))

    assert session_list_id == "session:session-a"
    assert team_list_id == "team:team-alpha"
    assert session_tasks[0].subject == "Write docs"
    assert team_tasks[0].subject == "Coordinate deploy"


def test_task_tools_surface_structured_errors_and_strict_validation(tmp_path: Path) -> None:
    task_lists = DefaultTaskListService(store=FileTaskListStore(tmp_path / ".runtime" / "task_lists"))
    task_discipline = TaskDisciplineSidecar(task_lists=task_lists)
    runtime_services = RuntimeServices(
        task_lists=task_lists,
        task_discipline=task_discipline,
        metadata={"task_discipline": {"strict_single_in_progress": True}},
    )
    scheduler, context = _build_tool_runtime(tmp_path, runtime_services=runtime_services)

    create_results = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "task_create", {"subject": "First task"}),
                ToolCall("2", "task_create", {"subject": "Second task"}),
            ],
            context,
        )
    )
    first_task_id = create_results[0].output["task"]["task_id"]
    second_task_id = create_results[1].output["task"]["task_id"]

    update_first = asyncio.run(
        scheduler.run(
            [ToolCall("3", "task_update", {"task_id": first_task_id, "status": "in_progress"})],
            context,
        )
    )[0]
    update_second = asyncio.run(
        scheduler.run(
            [ToolCall("4", "task_update", {"task_id": second_task_id, "status": "in_progress"})],
            context,
        )
    )[0]
    empty_patch = asyncio.run(
        scheduler.run([ToolCall("5", "task_update", {"task_id": first_task_id})], context)
    )[0]
    missing_task = asyncio.run(
        scheduler.run([ToolCall("6", "task_get", {"task_id": "missing-task"})], context)
    )[0]

    assert update_first.status == ToolCallStatus.SUCCESS
    assert update_second.status == ToolCallStatus.ERROR
    assert update_second.metadata["category"] == "multiple_in_progress"
    assert update_second.output["error"]["code"] == "multiple_in_progress"
    assert empty_patch.status == ToolCallStatus.ERROR
    assert empty_patch.metadata["category"] == "invalid_request"
    assert missing_task.status == ToolCallStatus.ERROR
    assert missing_task.metadata["category"] == "not_found"


def test_job_stop_does_not_mutate_task_lists_and_task_update_does_not_mutate_jobs(tmp_path: Path) -> None:
    scheduler, context = _build_tool_runtime(tmp_path)
    context.task_manager.create(
        "job-1",
        title="background-review",
        metadata={"session_id": context.session_id, "kind": "background_agent"},
    )
    context.task_manager.update("job-1", status=TaskStatus.RUNNING)

    created = asyncio.run(
        scheduler.run([ToolCall("1", "task_create", {"subject": "Review output"})], context)
    )[0]
    task_id = created.output["task"]["task_id"]

    updated = asyncio.run(
        scheduler.run([ToolCall("2", "task_update", {"task_id": task_id, "status": "completed"})], context)
    )[0]
    assert updated.status == ToolCallStatus.SUCCESS
    assert context.task_manager.get("job-1").status == TaskStatus.RUNNING

    stopped = asyncio.run(
        scheduler.run([ToolCall("3", "job_stop", {"job_id": "job-1"})], context)
    )[0]
    listed = asyncio.run(
        scheduler.run([ToolCall("4", "task_list", {})], context)
    )[0]

    assert stopped.status == ToolCallStatus.SUCCESS
    assert stopped.output["job"]["status"] == "stopped"
    assert listed.output["tasks"][0]["status"] == "completed"


def test_bound_host_runtime_exposes_task_list_watch_and_job_queries(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    bound = runtime.bind_host(NullHostAdapter())
    observed: list[int] = []

    async def scenario():
        unsubscribe = await bound.watch_task_list(
            session_id="session-watch",
            callback=lambda snapshot: observed.append(len(snapshot["tasks"])),
        )
        task_list_id = await bound.resolve_task_list_id(session_id="session-watch")
        await runtime.services.task_list_service.create(task_list_id, subject="Ship release")
        runtime.task_manager.create(
            "job-1",
            title="background-release",
            metadata={"session_id": "session-watch", "kind": "background_agent"},
        )
        runtime.task_manager.update("job-1", status=TaskStatus.RUNNING)
        task_list_snapshot = await bound.get_task_list(session_id="session-watch")
        jobs = await bound.list_jobs(session_id="session-watch")
        job = await bound.get_job("job-1", session_id="session-watch")
        unsubscribe()
        return task_list_id, task_list_snapshot, jobs, job

    task_list_id, task_list_snapshot, jobs, job = asyncio.run(scenario())

    assert observed == [0, 1]
    assert task_list_snapshot["list_id"] == task_list_id
    assert task_list_snapshot["tasks"][0]["subject"] == "Ship release"
    assert jobs[0]["job_id"] == "job-1"
    assert job["status"] == "running"


def test_custom_agent_task_access_and_child_execution_inherit_task_list_scope(tmp_path: Path) -> None:
    scheduler, context = _build_tool_runtime(tmp_path)
    custom_private_context = RuntimePrivateContext(extensions={"task_list_id": "team:team-alpha"})
    custom_context = ToolContext(
        session_id=context.session_id,
        turn_id=context.turn_id,
        agent_name="custom-planner",
        cwd=context.cwd,
        tool_registry=context.tool_registry,
        skill_registry=context.skill_registry,
        task_manager=context.task_manager,
        permission_handler=context.permission_handler,
        private_context=custom_private_context,
        tool_pool=tuple(definition for definition in builtin_tools() if definition.name.startswith("task_")),
    )

    created = asyncio.run(
        scheduler.run([ToolCall("1", "task_create", {"subject": "Shared plan item"})], custom_context)
    )[0]
    listed = asyncio.run(
        scheduler.run([ToolCall("2", "task_list", {})], custom_context)
    )[0]

    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    captured: dict[str, object] = {}

    async def fake_invoke(invocation):
        from runtime.agent_runtime import AgentRunResult

        captured["task_list_id"] = invocation.metadata.get("task_list_id")
        return AgentRunResult(agent_name=invocation.agent_name, status="completed")

    runtime.agent_runtime.invoke = fake_invoke
    delegated = asyncio.run(
        runtime.run_agent_tool(
            "custom-worker",
            "do delegated work",
            ToolContext(
                session_id="session-delegate",
                turn_id="turn-delegate",
                agent_name="coordinator",
                cwd=tmp_path,
                private_context=custom_private_context,
                runtime_services=runtime.services,
            ),
        )
    )

    assert created.status == ToolCallStatus.SUCCESS
    assert created.output["task_list_id"] == "team:team-alpha"
    assert listed.output["task_list_id"] == "team:team-alpha"
    assert listed.output["tasks"][0]["subject"] == "Shared plan item"
    assert delegated["status"] == "completed"
    assert captured["task_list_id"] == "team:team-alpha"


def test_task_discipline_sidecar_emits_hidden_reminders_for_stale_lists() -> None:
    task_lists = DefaultTaskListService()
    sidecar = TaskDisciplineSidecar(task_lists=task_lists)
    task_tools = tuple(definition for definition in builtin_tools() if definition.name.startswith("task_"))
    policy_state = ExecutionPolicyState(
        ExecutionPolicy(
            tool_pool=task_tools,
            skill_pool=(),
            permission_context=PermissionContext(session_id="session-reminder"),
        )
    )
    private_context = RuntimePrivateContext(
        policy_state=policy_state,
        extensions={"team_id": "team-alpha"},
    )
    task_list_id = asyncio.run(
        task_lists.resolve_list_id(session_id="session-reminder", private_context=private_context)
    )
    asyncio.run(task_lists.create(task_list_id, subject="Coordinate rollout"))

    async def collect(turn_id: str):
        return await sidecar.collect(
            session_id="session-reminder",
            turn_id=turn_id,
            agent=AgentDefinition(name="planner", description="planner", prompt="plan"),
            cwd=".",
            messages=(),
            private_context=private_context,
            runtime_context={"task_discipline": {"reminder_turn_threshold": 2}},
        )

    first = asyncio.run(collect("turn-1"))
    second = asyncio.run(collect("turn-2"))
    sidecar.record_task_touch(session_id="session-reminder", task_list_id=task_list_id)
    third = asyncio.run(collect("turn-3"))

    assert first.private_updates["task_list_id"] == "team:team-alpha"
    assert first.prompt_fragments == ()
    assert second.prompt_fragments
    assert "Coordinate rollout" in second.prompt_fragments[0]
    assert third.prompt_fragments == ()
