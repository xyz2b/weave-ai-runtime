import asyncio
from pathlib import Path

import pytest

from runtime.builtins.tools import builtin_tools
from runtime.contracts import MessageRole, RuntimeMessage, RuntimePrivateContext
from runtime.definitions import AgentDefinition, PermissionBehavior, PermissionDecision
from runtime.execution_policy import ExecutionPolicy, ExecutionPolicyState
from runtime.hosts.base import NullHostAdapter
from runtime.memory.manager import LongTermMemory
from runtime.permissions import PermissionContext
from runtime.registries import SkillRegistry, ToolRegistry
from runtime.runtime_kernel.config import RuntimeConfig
from runtime.runtime_kernel.kernel import assemble_runtime
from runtime.runtime_services import RuntimeServices
from runtime.task_discipline import TaskDisciplineSidecar
from runtime.task_lists import (
    TASK_LIST_RESOLVED_ID_EXTENSION_KEY,
    DefaultTaskListService,
    FileTaskListStore,
    TaskListBlockedError,
    TaskListDependencyCycleError,
    TaskListOwnerBusyError,
    TaskReadinessState,
)
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


def test_task_list_service_derives_orchestration_views() -> None:
    service = DefaultTaskListService()

    async def scenario():
        list_id = "session:orchestration-view"
        available = await service.create(list_id, subject="Available task")
        blocker = await service.create(list_id, subject="Blocker task")
        blocked = await service.create(list_id, subject="Blocked task", blocked_by=(blocker.task_id,))
        claimed = await service.create(list_id, subject="Claimed task", owner="planner")
        started = await service.create(list_id, subject="Started task")
        await service.update(list_id, started.task_id, patch={"status": "in_progress"})
        completed = await service.create(list_id, subject="Completed task")
        await service.update(list_id, completed.task_id, patch={"status": "completed"})
        view = await service.get_orchestration_snapshot(list_id)
        return available, blocker, blocked, claimed, started, completed, view

    available, blocker, blocked, claimed, started, completed, view = asyncio.run(scenario())
    states = {task.task.task_id: task for task in view.tasks}

    assert states[available.task_id].readiness_state == TaskReadinessState.AVAILABLE
    assert states[blocker.task_id].readiness_state == TaskReadinessState.AVAILABLE
    assert states[blocked.task_id].readiness_state == TaskReadinessState.BLOCKED
    assert states[blocked.task_id].unresolved_blockers == (blocker.task_id,)
    assert states[claimed.task_id].readiness_state == TaskReadinessState.CLAIMED
    assert states[started.task_id].readiness_state == TaskReadinessState.IN_PROGRESS
    assert states[completed.task_id].readiness_state == TaskReadinessState.COMPLETED
    assert blocker.task_id in view.available_task_ids
    assert blocked.task_id in view.blocked_task_ids
    assert claimed.task_id in view.claimed_task_ids
    assert started.task_id in view.in_progress_task_ids
    assert completed.task_id in view.completed_task_ids
    assert view.unresolved_blocker_ids == (blocker.task_id,)


def test_task_list_service_enforces_blockers_owner_busy_and_release() -> None:
    service = DefaultTaskListService()

    async def scenario():
        list_id = "session:claim-rules"
        blocker = await service.create(list_id, subject="Blocker task")
        blocked = await service.create(list_id, subject="Blocked task", blocked_by=(blocker.task_id,))
        first = await service.create(list_id, subject="First task")
        second = await service.create(list_id, subject="Second task")

        with pytest.raises(TaskListBlockedError):
            await service.claim(list_id, blocked.task_id, "planner")

        claimed = await service.claim(
            list_id,
            first.task_id,
            "planner",
            enforce_owner_busy=True,
        )
        with pytest.raises(TaskListOwnerBusyError):
            await service.claim(
                list_id,
                second.task_id,
                "planner",
                enforce_owner_busy=True,
            )
        released = await service.release(list_id, first.task_id)
        claimed_second = await service.claim(
            list_id,
            second.task_id,
            "planner",
            enforce_owner_busy=True,
        )
        return claimed, released, claimed_second

    claimed, released, claimed_second = asyncio.run(scenario())

    assert claimed.owner == "planner"
    assert claimed.status.value == "in_progress"
    assert released.owner is None
    assert released.status.value == "pending"
    assert claimed_second.owner == "planner"
    assert claimed_second.status.value == "in_progress"


def test_task_list_service_rejects_dependency_cycles_and_cleans_dangling_edges() -> None:
    service = DefaultTaskListService()

    async def scenario():
        list_id = "session:dependency-rules"
        first = await service.create(list_id, subject="First")
        second = await service.create(list_id, subject="Second")
        third = await service.create(list_id, subject="Third")
        await service.add_dependency(list_id, first.task_id, second.task_id)
        await service.add_dependency(list_id, second.task_id, third.task_id)
        with pytest.raises(TaskListDependencyCycleError):
            await service.add_dependency(list_id, third.task_id, first.task_id)
        await service.remove_dependency(list_id, first.task_id, second.task_id)
        await service.add_dependency(list_id, first.task_id, second.task_id)
        await service.delete(list_id, second.task_id)
        first_after = await service.get(list_id, first.task_id)
        third_after = await service.get(list_id, third.task_id)
        return first_after, third_after

    first_after, third_after = asyncio.run(scenario())

    assert first_after is not None
    assert third_after is not None
    assert first_after.blocks == ()
    assert third_after.blocked_by == ()


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
    invalid_owner_update = asyncio.run(
        scheduler.run([ToolCall("7", "task_update", {"task_id": first_task_id, "owner": "planner"})], context)
    )[0]

    assert update_first.status == ToolCallStatus.SUCCESS
    assert update_second.status == ToolCallStatus.ERROR
    assert update_second.metadata["category"] == "multiple_in_progress"
    assert update_second.output["error"]["code"] == "multiple_in_progress"
    assert empty_patch.status == ToolCallStatus.ERROR
    assert empty_patch.metadata["category"] == "invalid_request"
    assert missing_task.status == ToolCallStatus.ERROR
    assert missing_task.metadata["category"] == "not_found"
    assert invalid_owner_update.status == ToolCallStatus.ERROR
    assert invalid_owner_update.metadata["category"] == "invalid_request"
    assert "task_claim" in invalid_owner_update.output["error"]["message"]


def test_task_orchestration_tools_surface_readiness_and_dependency_controls(tmp_path: Path) -> None:
    scheduler, context = _build_tool_runtime(tmp_path)

    created = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "task_create", {"subject": "Blocker"}),
                ToolCall("2", "task_create", {"subject": "Blocked"}),
            ],
            context,
        )
    )
    blocker_task_id = created[0].output["task"]["task_id"]
    blocked_task_id = created[1].output["task"]["task_id"]

    blocked = asyncio.run(
        scheduler.run(
            [ToolCall("3", "task_block", {"blocker_task_id": blocker_task_id, "blocked_task_id": blocked_task_id})],
            context,
        )
    )[0]
    listed = asyncio.run(
        scheduler.run([ToolCall("4", "task_list", {})], context)
    )[0]
    assigned = asyncio.run(
        scheduler.run([ToolCall("5", "task_assign_next", {"owner": "planner"})], context)
    )[0]
    blocked_claim = asyncio.run(
        scheduler.run([ToolCall("6", "task_claim", {"task_id": blocked_task_id, "owner": "reviewer"})], context)
    )[0]
    released = asyncio.run(
        scheduler.run([ToolCall("7", "task_release", {"task_id": blocker_task_id})], context)
    )[0]
    unblocked = asyncio.run(
        scheduler.run(
            [ToolCall("8", "task_unblock", {"blocker_task_id": blocker_task_id, "blocked_task_id": blocked_task_id})],
            context,
        )
    )[0]
    claimed = asyncio.run(
        scheduler.run([ToolCall("9", "task_claim", {"task_id": blocked_task_id, "owner": "reviewer"})], context)
    )[0]

    assert blocked.status == ToolCallStatus.SUCCESS
    assert blocked.output["blocker_task"]["blocks"] == [blocked_task_id]
    assert blocked.output["blocked_task"]["blocked_by"] == [blocker_task_id]
    assert listed.output["available_task_ids"] == [blocker_task_id]
    assert listed.output["blocked_task_ids"] == [blocked_task_id]
    assert listed.output["tasks"][1]["readiness_state"] == "blocked"
    assert listed.output["tasks"][1]["unresolved_blockers"] == [blocker_task_id]
    assert assigned.status == ToolCallStatus.SUCCESS
    assert assigned.output["task"]["task_id"] == blocker_task_id
    assert assigned.output["task"]["status"] == "in_progress"
    assert blocked_claim.status == ToolCallStatus.ERROR
    assert blocked_claim.output["error"]["code"] == "blocked"
    assert released.output["task"]["status"] == "pending"
    assert unblocked.status == ToolCallStatus.SUCCESS
    assert unblocked.output["blocker_task"]["blocks"] == []
    assert unblocked.output["blocked_task"]["blocked_by"] == []
    assert claimed.status == ToolCallStatus.SUCCESS
    assert claimed.output["task"]["task_id"] == blocked_task_id
    assert claimed.output["task"]["owner"] == "reviewer"


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
    observed: list[dict[str, object]] = []

    async def scenario():
        unsubscribe = await bound.watch_task_list(
            session_id="session-watch",
            callback=lambda snapshot: observed.append(snapshot),
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

    assert [len(snapshot["tasks"]) for snapshot in observed] == [0, 1]
    assert task_list_snapshot["list_id"] == task_list_id
    assert task_list_snapshot["tasks"][0]["subject"] == "Ship release"
    assert task_list_snapshot["tasks"][0]["readiness_state"] == "available"
    assert task_list_snapshot["available_task_ids"] == [task_list_snapshot["tasks"][0]["task_id"]]
    assert task_list_snapshot["blocked_task_ids"] == []
    assert jobs[0]["job_id"] == "job-1"
    assert job["status"] == "running"


def test_task_list_watch_rolls_back_failed_initial_callback() -> None:
    task_lists = DefaultTaskListService()

    async def scenario() -> None:
        async def broken(_: object) -> None:
            raise RuntimeError("boom")

        try:
            await task_lists.watch("session:failed-watch", broken)
        except RuntimeError as exc:
            assert str(exc) == "boom"
        else:  # pragma: no cover - defensive guard
            raise AssertionError("watch() should surface the initial callback failure")

        assert task_lists._watchers == {}
        await task_lists.create("session:failed-watch", subject="Ship release")
        assert task_lists._watchers == {}

    asyncio.run(scenario())


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


def test_sidecar_resolved_task_list_does_not_pin_session_fallback_over_team_scope() -> None:
    task_lists = DefaultTaskListService()
    sidecar = TaskDisciplineSidecar(task_lists=task_lists)
    task_tools = tuple(definition for definition in builtin_tools() if definition.name.startswith("task_"))
    policy_state = ExecutionPolicyState(
        ExecutionPolicy(
            tool_pool=task_tools,
            skill_pool=(),
            permission_context=PermissionContext(session_id="session-fallback"),
        )
    )

    async def scenario() -> None:
        initial_private = RuntimePrivateContext(policy_state=policy_state)
        first = await sidecar.collect(
            session_id="session-fallback",
            turn_id="turn-1",
            agent=AgentDefinition(name="planner", description="planner", prompt="plan"),
            cwd=".",
            messages=(),
            private_context=initial_private,
            runtime_context={},
        )
        inherited_private = RuntimePrivateContext(
            policy_state=policy_state,
            extensions={
                **first.private_updates,
                "team_id": "team-alpha",
            },
        )
        resolved = await task_lists.resolve_list_id(
            session_id="session-fallback",
            private_context=inherited_private,
        )

        assert first.private_updates[TASK_LIST_RESOLVED_ID_EXTENSION_KEY] == "session:session-fallback"
        assert resolved == "team:team-alpha"

    asyncio.run(scenario())


def test_team_scoped_background_jobs_are_visible_to_job_queries(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    bound = runtime.bind_host(NullHostAdapter())

    async def scenario() -> None:
        context = ToolContext(
            session_id="session-team",
            turn_id="turn-team",
            agent_name="coordinator",
            cwd=tmp_path,
            private_context=RuntimePrivateContext(extensions={"team_id": "team-alpha"}),
            metadata={"run_id": "parent-run"},
            runtime_services=runtime.services,
        )
        delegated = await runtime.run_agent_tool(
            "general-purpose",
            "inspect team state",
            context,
            background=True,
        )
        job_id = delegated["task_id"]
        job = runtime.task_manager.get(job_id)
        assert job is not None
        assert job.metadata["team_id"] == "team-alpha"

        jobs = await bound.list_jobs(team_id="team-alpha")
        assert jobs[0]["job_id"] == job_id

        current = runtime.task_manager.get(job_id)
        if current is not None and current.status == TaskStatus.RUNNING:
            await runtime.task_manager.stop_job(job_id)
        await runtime.agent_runtime.wait_for_background(job_id)

    asyncio.run(scenario())


def test_memory_background_jobs_include_team_scope_metadata(tmp_path: Path) -> None:
    memory = LongTermMemory(project_root=tmp_path, user_root=tmp_path / ".user")
    task_manager = TaskManager()

    async def scenario() -> None:
        task_id = memory.schedule_background_extraction(
            session_id="session-memory",
            agent=AgentDefinition(name="planner", description="planner", prompt="plan"),
            cwd=tmp_path,
            messages=(
                RuntimeMessage(
                    message_id="msg-1",
                    role=MessageRole.USER,
                    content="Remember the deployment checklist.",
                ),
            ),
            task_manager=task_manager,
            team_id="team-alpha",
        )
        assert task_id is not None
        task = task_manager.get(str(task_id))
        assert task is not None
        assert task.metadata["team_id"] == "team-alpha"
        await memory.wait_for_background_extraction(str(task_id))

    asyncio.run(scenario())


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

    assert first.private_updates[TASK_LIST_RESOLVED_ID_EXTENSION_KEY] == "team:team-alpha"
    assert first.prompt_fragments == ()
    assert second.prompt_fragments
    assert "Coordinate rollout" in second.prompt_fragments[0]
    assert third.prompt_fragments == ()
