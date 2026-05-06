import asyncio
from pathlib import Path

import pytest

from weavert.builtins.tools import builtin_tools
from weavert.contracts import ExecutionResult, ExecutionStatus, MessageRole, RuntimeMessage, RuntimePrivateContext
from weavert.definitions import AgentDefinition, PermissionBehavior, PermissionDecision
from weavert.execution_policy import ExecutionPolicy, ExecutionPolicyState
from weavert.hosts.base import NullHostAdapter
from weavert_memory.manager import LongTermMemory
from weavert.permissions import PermissionContext
from weavert.registries import SkillRegistry, ToolRegistry
from weavert.runtime_kernel.config import RuntimeConfig
from weavert.runtime_kernel.kernel import assemble_runtime
from weavert.runtime_services import RuntimeServices
from weavert.task_discipline import TaskDisciplineSidecar
from weavert.task_lists import (
    TASK_LIST_RESOLVED_ID_EXTENSION_KEY,
    DefaultTaskListService,
    FileTaskListStore,
    TaskListBlockedError,
    TaskListDependencyCycleError,
    TaskListError,
    TaskListInvalidRequestError,
    TaskListOwnerBusyError,
    TaskReadinessState,
)
from weavert.tasking import TaskManager, TaskStatus
from weavert.tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler, validate_input_schema


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
    store_root = tmp_path / ".weavert" / "task_lists"
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


def test_task_list_service_same_owner_reclaim_respects_blockers_and_completed_guard() -> None:
    service = DefaultTaskListService()

    async def scenario():
        list_id = "session:claim-guardrails"
        blocker = await service.create(list_id, subject="Blocker task")
        blocked = await service.create(
            list_id,
            subject="Blocked task",
            owner="planner",
            blocked_by=(blocker.task_id,),
        )
        with pytest.raises(TaskListBlockedError):
            await service.claim(list_id, blocked.task_id, "planner")

        completed = await service.create(list_id, subject="Completed task", owner="planner")
        await service.update(list_id, completed.task_id, patch={"status": "completed"})
        with pytest.raises(TaskListInvalidRequestError):
            await service.claim(list_id, completed.task_id, "planner")

        blocked_after = await service.get(list_id, blocked.task_id)
        completed_after = await service.get(list_id, completed.task_id)
        return blocked, blocked_after, completed_after

    blocked, blocked_after, completed_after = asyncio.run(scenario())

    assert blocked_after is not None
    assert blocked_after.task_id == blocked.task_id
    assert blocked_after.owner == "planner"
    assert blocked_after.status.value == "pending"
    assert completed_after is not None
    assert completed_after.owner == "planner"
    assert completed_after.status.value == "completed"


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
        await service.update(list_id, second.task_id, patch={"status": "completed"})
        await service.archive(list_id, second.task_id, archived_by="planner")
        await service.delete(list_id, second.task_id)
        first_after = await service.get(list_id, first.task_id)
        third_after = await service.get(list_id, third.task_id)
        return first_after, third_after

    first_after, third_after = asyncio.run(scenario())

    assert first_after is not None
    assert third_after is not None
    assert first_after.blocks == ()
    assert third_after.blocked_by == ()


def test_task_list_service_enforces_retirement_lifecycle_and_archive_visibility() -> None:
    service = DefaultTaskListService()

    async def scenario():
        list_id = "session:retirement-rules"
        blocker = await service.create(list_id, subject="Archived blocker")
        dependent = await service.create(list_id, subject="Dependent task", blocked_by=(blocker.task_id,))
        active = await service.create(list_id, subject="Active task")

        with pytest.raises(TaskListError) as archive_requires_completed:
            await service.archive(list_id, blocker.task_id, archived_by="planner")

        await service.update(list_id, blocker.task_id, patch={"status": "completed"})
        archived = await service.archive(list_id, blocker.task_id, archived_by="planner")
        exact = await service.get_orchestration_task(list_id, blocker.task_id, include_archived=True)
        default_view = await service.get_orchestration_snapshot(list_id)
        archived_view = await service.get_orchestration_snapshot(list_id, include_archived=True)

        with pytest.raises(TaskListError) as repeated_archive:
            await service.archive(list_id, blocker.task_id, archived_by="planner")
        with pytest.raises(TaskListError) as archived_update:
            await service.update(list_id, blocker.task_id, patch={"subject": "Renamed"})
        with pytest.raises(TaskListError) as archived_claim:
            await service.claim(list_id, blocker.task_id, "planner")
        with pytest.raises(TaskListError) as archived_dependency:
            await service.add_dependency(list_id, blocker.task_id, active.task_id)
        with pytest.raises(TaskListError) as not_archived:
            await service.unarchive(list_id, active.task_id)
        with pytest.raises(TaskListError) as delete_requires_archived:
            await service.delete(list_id, active.task_id)

        restored = await service.unarchive(list_id, blocker.task_id)
        rearchived = await service.archive(list_id, blocker.task_id, archived_by="planner")
        deleted = await service.delete(list_id, blocker.task_id)
        after_delete = await service.get_orchestration_snapshot(list_id, include_archived=True)
        return {
            "blocker": blocker,
            "dependent": dependent,
            "archived": archived,
            "exact": exact,
            "default_view": default_view,
            "archived_view": archived_view,
            "archive_requires_completed": archive_requires_completed.value,
            "repeated_archive": repeated_archive.value,
            "archived_update": archived_update.value,
            "archived_claim": archived_claim.value,
            "archived_dependency": archived_dependency.value,
            "not_archived": not_archived.value,
            "delete_requires_archived": delete_requires_archived.value,
            "restored": restored,
            "rearchived": rearchived,
            "deleted": deleted,
            "after_delete": after_delete,
        }

    result = asyncio.run(scenario())

    blocker = result["blocker"]
    dependent = result["dependent"]
    default_tasks = {task.task.task_id: task for task in result["default_view"].tasks}
    archived_tasks = {task.task.task_id: task for task in result["archived_view"].tasks}
    dependent_default = default_tasks[dependent.task_id]
    dependent_archived = archived_tasks[dependent.task_id]
    after_delete_tasks = {task.task.task_id: task for task in result["after_delete"].tasks}

    assert result["archive_requires_completed"].code == "archive_requires_completed"
    assert result["archived"].is_archived is True
    assert result["archived"].archived_by == "planner"
    assert result["exact"] is not None
    assert result["exact"].task.is_archived is True
    assert dependent.task_id in result["default_view"].available_task_ids
    assert blocker.task_id not in default_tasks
    assert blocker.task_id in archived_tasks
    assert dependent_default.task.blocked_by == ()
    assert dependent_default.readiness_state == TaskReadinessState.AVAILABLE
    assert dependent_archived.task.blocked_by == (blocker.task_id,)
    assert blocker.task_id not in result["archived_view"].completed_task_ids
    assert result["repeated_archive"].code == "already_archived"
    assert result["archived_update"].code == "archived_task_immutable"
    assert result["archived_claim"].code == "archived_task_immutable"
    assert result["archived_dependency"].code == "archived_task_immutable"
    assert result["not_archived"].code == "not_archived"
    assert result["delete_requires_archived"].code == "delete_requires_archived"
    assert result["restored"].is_archived is False
    assert result["rearchived"].is_archived is True
    assert result["deleted"].task_id == blocker.task_id
    assert after_delete_tasks[dependent.task_id].task.blocked_by == ()


def test_file_task_list_store_uses_atomic_replace_and_ignores_interrupted_temp_files(tmp_path: Path) -> None:
    store = FileTaskListStore(tmp_path / ".weavert" / "task_lists")
    service = DefaultTaskListService(store=store)

    async def scenario():
        list_id = "session:atomic-store"
        await service.create(list_id, subject="First task")
        path = store._path_for(list_id)
        interrupted = path.with_name(f".{path.name}.interrupted.tmp")
        interrupted.write_text("{broken", encoding="utf-8")
        before = await store.load(list_id)
        await service.create(list_id, subject="Second task")
        after = await store.load(list_id)
        snapshots = await store.list_snapshots()
        return path, interrupted, before, after, snapshots

    path, interrupted, before, after, snapshots = asyncio.run(scenario())

    assert path.exists()
    assert interrupted.exists()
    assert before is not None
    assert after is not None
    assert [task.subject for task in before.tasks] == ["First task"]
    assert [task.subject for task in after.tasks] == ["First task", "Second task"]
    assert len(snapshots) == 1


def test_task_update_schema_rejects_orchestration_fields() -> None:
    task_update_schema = next(definition.input_schema for definition in builtin_tools() if definition.name == "task_update")

    assert validate_input_schema(task_update_schema, {"task_id": "task-1", "status": "completed"}) == {
        "task_id": "task-1",
        "status": "completed",
    }

    with pytest.raises(ValueError, match="additional properties are not allowed"):
        validate_input_schema(task_update_schema, {"task_id": "task-1", "owner": "planner"})

    with pytest.raises(ValueError, match="additional properties are not allowed"):
        validate_input_schema(task_update_schema, {"task_id": "task-1", "blocked_by": ["task-0"]})


def test_task_tools_surface_structured_errors_and_strict_validation(tmp_path: Path) -> None:
    task_lists = DefaultTaskListService(store=FileTaskListStore(tmp_path / ".weavert" / "task_lists"))
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


def test_task_retirement_tools_surface_lifecycle_and_archived_visibility(tmp_path: Path) -> None:
    scheduler, context = _build_tool_runtime(tmp_path)

    created = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "task_create", {"subject": "Completed blocker"}),
                ToolCall("2", "task_create", {"subject": "Dependent task"}),
                ToolCall("3", "task_create", {"subject": "Pending task"}),
            ],
            context,
        )
    )
    blocker_task_id = created[0].output["task"]["task_id"]
    dependent_task_id = created[1].output["task"]["task_id"]
    pending_task_id = created[2].output["task"]["task_id"]

    asyncio.run(
        scheduler.run(
            [ToolCall("4", "task_block", {"blocker_task_id": blocker_task_id, "blocked_task_id": dependent_task_id})],
            context,
        )
    )

    archive_requires_completed = asyncio.run(
        scheduler.run([ToolCall("5", "task_archive", {"task_id": blocker_task_id})], context)
    )[0]
    asyncio.run(
        scheduler.run([ToolCall("6", "task_update", {"task_id": blocker_task_id, "status": "completed"})], context)
    )
    archived = asyncio.run(
        scheduler.run([ToolCall("7", "task_archive", {"task_id": blocker_task_id})], context)
    )[0]
    repeated_archive = asyncio.run(
        scheduler.run([ToolCall("8", "task_archive", {"task_id": blocker_task_id})], context)
    )[0]
    exact = asyncio.run(
        scheduler.run([ToolCall("9", "task_get", {"task_id": blocker_task_id})], context)
    )[0]
    default_list = asyncio.run(
        scheduler.run([ToolCall("10", "task_list", {})], context)
    )[0]
    archived_list = asyncio.run(
        scheduler.run([ToolCall("11", "task_list", {"include_archived": True})], context)
    )[0]
    archived_claim = asyncio.run(
        scheduler.run([ToolCall("12", "task_claim", {"task_id": blocker_task_id, "owner": "planner"})], context)
    )[0]
    not_archived_unarchive = asyncio.run(
        scheduler.run([ToolCall("13", "task_unarchive", {"task_id": pending_task_id})], context)
    )[0]
    delete_requires_archived = asyncio.run(
        scheduler.run([ToolCall("14", "task_delete", {"task_id": dependent_task_id})], context)
    )[0]
    unarchived = asyncio.run(
        scheduler.run([ToolCall("15", "task_unarchive", {"task_id": blocker_task_id})], context)
    )[0]
    rearchived = asyncio.run(
        scheduler.run([ToolCall("16", "task_archive", {"task_id": blocker_task_id})], context)
    )[0]
    deleted = asyncio.run(
        scheduler.run([ToolCall("17", "task_delete", {"task_id": blocker_task_id})], context)
    )[0]
    after_delete = asyncio.run(
        scheduler.run([ToolCall("18", "task_list", {"include_archived": True})], context)
    )[0]

    dependent_default = next(task for task in default_list.output["tasks"] if task["task_id"] == dependent_task_id)
    dependent_archived = next(task for task in archived_list.output["tasks"] if task["task_id"] == dependent_task_id)

    assert archive_requires_completed.status == ToolCallStatus.ERROR
    assert archive_requires_completed.output["error"]["code"] == "archive_requires_completed"
    assert archived.status == ToolCallStatus.SUCCESS
    assert archived.output["task"]["is_archived"] is True
    assert archived.output["task"]["archived_by"] == "planner"
    assert repeated_archive.status == ToolCallStatus.ERROR
    assert repeated_archive.output["error"]["code"] == "already_archived"
    assert exact.output["task"]["is_archived"] is True
    assert blocker_task_id not in [task["task_id"] for task in default_list.output["tasks"]]
    assert dependent_default["blocked_by"] == []
    assert dependent_default["readiness_state"] == "available"
    assert blocker_task_id in [task["task_id"] for task in archived_list.output["tasks"]]
    assert dependent_archived["blocked_by"] == [blocker_task_id]
    assert blocker_task_id not in archived_list.output["completed_task_ids"]
    assert archived_claim.status == ToolCallStatus.ERROR
    assert archived_claim.output["error"]["code"] == "archived_task_immutable"
    assert not_archived_unarchive.output["error"]["code"] == "not_archived"
    assert delete_requires_archived.output["error"]["code"] == "delete_requires_archived"
    assert unarchived.output["task"]["is_archived"] is False
    assert rearchived.output["task"]["is_archived"] is True
    assert deleted.status == ToolCallStatus.SUCCESS
    assert deleted.output["task"]["task_id"] == blocker_task_id
    assert next(task for task in after_delete.output["tasks"] if task["task_id"] == dependent_task_id)["blocked_by"] == []


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


def test_task_claim_tool_rejects_same_owner_blocked_and_completed_tasks(tmp_path: Path) -> None:
    scheduler, context = _build_tool_runtime(tmp_path)

    created = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "task_create", {"subject": "Blocker"}),
                ToolCall(
                    "2",
                    "task_create",
                    {"subject": "Blocked", "owner": "planner"},
                ),
                ToolCall(
                    "3",
                    "task_create",
                    {"subject": "Completed", "owner": "planner"},
                ),
            ],
            context,
        )
    )
    blocker_task_id = created[0].output["task"]["task_id"]
    blocked_task_id = created[1].output["task"]["task_id"]
    completed_task_id = created[2].output["task"]["task_id"]

    asyncio.run(
        scheduler.run(
            [
                ToolCall(
                    "4",
                    "task_block",
                    {"blocker_task_id": blocker_task_id, "blocked_task_id": blocked_task_id},
                ),
                ToolCall("5", "task_update", {"task_id": completed_task_id, "status": "completed"}),
            ],
            context,
        )
    )

    blocked_claim = asyncio.run(
        scheduler.run([ToolCall("6", "task_claim", {"task_id": blocked_task_id, "owner": "planner"})], context)
    )[0]
    completed_claim = asyncio.run(
        scheduler.run([ToolCall("7", "task_claim", {"task_id": completed_task_id, "owner": "planner"})], context)
    )[0]
    listed = asyncio.run(
        scheduler.run([ToolCall("8", "task_list", {})], context)
    )[0]

    blocked_snapshot = next(task for task in listed.output["tasks"] if task["task_id"] == blocked_task_id)
    completed_snapshot = next(task for task in listed.output["tasks"] if task["task_id"] == completed_task_id)

    assert blocked_claim.status == ToolCallStatus.ERROR
    assert blocked_claim.output["error"]["code"] == "blocked"
    assert completed_claim.status == ToolCallStatus.ERROR
    assert completed_claim.output["error"]["code"] == "invalid_request"
    assert blocked_snapshot["owner"] == "planner"
    assert blocked_snapshot["status"] == "pending"
    assert blocked_snapshot["unresolved_blockers"] == [blocker_task_id]
    assert completed_snapshot["owner"] == "planner"
    assert completed_snapshot["status"] == "completed"


def test_job_stop_does_not_mutate_task_lists_and_task_update_does_not_mutate_jobs(tmp_path: Path) -> None:
    scheduler, context = _build_tool_runtime(tmp_path)
    context.task_manager.create(
        "job-1",
        title="background-review",
        metadata={"session_id": context.session_id, "kind": "background_agent"},
    )
    context.task_manager.register_stop_handler(
        "job-1",
        lambda task: context.task_manager.update(task.task_id, status=TaskStatus.STOPPED),
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


def test_bound_host_runtime_exposes_task_mutations_and_archived_visibility(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    bound = runtime.bind_host(NullHostAdapter())
    observed_default: list[dict[str, object]] = []
    observed_archived: list[dict[str, object]] = []

    async def scenario():
        unsubscribe_default = await bound.watch_task_list(
            session_id="session-host-mutations",
            callback=lambda snapshot: observed_default.append(snapshot),
        )
        unsubscribe_archived = await bound.watch_task_list(
            session_id="session-host-mutations",
            include_archived=True,
            callback=lambda snapshot: observed_archived.append(snapshot),
        )

        first = await bound.create_task(session_id="session-host-mutations", subject="First task")
        second = await bound.create_task(session_id="session-host-mutations", subject="Second task")
        blocked = await bound.block_task(
            session_id="session-host-mutations",
            blocker_task_id=first["task"]["task_id"],
            blocked_task_id=second["task"]["task_id"],
        )
        assigned = await bound.assign_next_task(session_id="session-host-mutations", owner="planner")
        blocked_claim = await bound.claim_task(
            second["task"]["task_id"],
            session_id="session-host-mutations",
            owner="reviewer",
        )
        released = await bound.release_task(first["task"]["task_id"], session_id="session-host-mutations")
        unblocked = await bound.unblock_task(
            session_id="session-host-mutations",
            blocker_task_id=first["task"]["task_id"],
            blocked_task_id=second["task"]["task_id"],
        )
        claimed_second = await bound.claim_task(
            second["task"]["task_id"],
            session_id="session-host-mutations",
            owner="reviewer",
        )

        archived_blocker = await bound.create_task(session_id="session-host-mutations", subject="Archived blocker")
        dependent = await bound.create_task(
            session_id="session-host-mutations",
            subject="Dependent on archived task",
            blocked_by=[archived_blocker["task"]["task_id"]],
        )
        await bound.update_task(
            archived_blocker["task"]["task_id"],
            session_id="session-host-mutations",
            status="completed",
        )
        archived = await bound.archive_task(
            archived_blocker["task"]["task_id"],
            session_id="session-host-mutations",
            archived_by="host-user",
        )
        exact = await bound.get_task(
            archived_blocker["task"]["task_id"],
            session_id="session-host-mutations",
        )
        default_list = await bound.get_task_list(session_id="session-host-mutations")
        archived_list = await bound.get_task_list(
            session_id="session-host-mutations",
            include_archived=True,
        )
        listed = await bound.list_task_lists(
            session_id="session-host-mutations",
            include_archived=True,
        )
        unarchived = await bound.unarchive_task(
            archived_blocker["task"]["task_id"],
            session_id="session-host-mutations",
        )
        rearchived = await bound.archive_task(
            archived_blocker["task"]["task_id"],
            session_id="session-host-mutations",
            archived_by="host-user",
        )
        deleted = await bound.delete_task(
            archived_blocker["task"]["task_id"],
            session_id="session-host-mutations",
        )
        after_delete = await bound.get_task_list(
            session_id="session-host-mutations",
            include_archived=True,
        )

        unsubscribe_default()
        unsubscribe_archived()
        return {
            "first": first,
            "second": second,
            "blocked": blocked,
            "assigned": assigned,
            "blocked_claim": blocked_claim,
            "released": released,
            "unblocked": unblocked,
            "claimed_second": claimed_second,
            "archived_blocker": archived_blocker,
            "dependent": dependent,
            "archived": archived,
            "exact": exact,
            "default_list": default_list,
            "archived_list": archived_list,
            "listed": listed,
            "unarchived": unarchived,
            "rearchived": rearchived,
            "deleted": deleted,
            "after_delete": after_delete,
        }

    result = asyncio.run(scenario())

    first_task_id = result["first"]["task"]["task_id"]
    second_task_id = result["second"]["task"]["task_id"]
    archived_task_id = result["archived_blocker"]["task"]["task_id"]
    dependent_task_id = result["dependent"]["task"]["task_id"]
    dependent_default = next(task for task in result["default_list"]["tasks"] if task["task_id"] == dependent_task_id)
    dependent_archived = next(task for task in result["archived_list"]["tasks"] if task["task_id"] == dependent_task_id)

    assert result["blocked"]["blocked_task"]["blocked_by"] == [first_task_id]
    assert result["assigned"]["task"]["task_id"] == first_task_id
    assert isinstance(result["blocked_claim"], ExecutionResult)
    assert result["blocked_claim"].status == ExecutionStatus.FAILED
    assert result["blocked_claim"].metadata["category"] == "blocked"
    assert result["released"]["task"]["status"] == "pending"
    assert result["unblocked"]["blocked_task"]["blocked_by"] == []
    assert result["claimed_second"]["task"]["task_id"] == second_task_id
    assert result["claimed_second"]["task"]["owner"] == "reviewer"
    assert result["archived"]["task"]["is_archived"] is True
    assert result["archived"]["task"]["archived_by"] == "host-user"
    assert result["exact"]["task"]["is_archived"] is True
    assert archived_task_id not in [task["task_id"] for task in result["default_list"]["tasks"]]
    assert dependent_default["blocked_by"] == []
    assert dependent_default["readiness_state"] == "available"
    assert archived_task_id in [task["task_id"] for task in result["archived_list"]["tasks"]]
    assert dependent_archived["blocked_by"] == [archived_task_id]
    assert archived_task_id not in result["archived_list"]["completed_task_ids"]
    assert result["listed"][0]["list_id"] == "session:session-host-mutations"
    assert result["unarchived"]["task"]["is_archived"] is False
    assert result["rearchived"]["task"]["is_archived"] is True
    assert result["deleted"]["task"]["task_id"] == archived_task_id
    assert next(task for task in result["after_delete"]["tasks"] if task["task_id"] == dependent_task_id)["blocked_by"] == []
    assert not any(
        any(task["task_id"] == archived_task_id and task["is_archived"] for task in snapshot["tasks"])
        for snapshot in observed_default
    )
    assert any(
        any(task["task_id"] == archived_task_id and task["is_archived"] for task in snapshot["tasks"])
        for snapshot in observed_archived
    )


def test_bound_host_runtime_respects_strict_single_in_progress_policy(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    bound = runtime.bind_host(NullHostAdapter())
    policy = {"task_discipline": {"strict_single_in_progress": True}}

    async def scenario():
        first = await bound.create_task(session_id="session-host-strict", subject="First task")
        second = await bound.create_task(session_id="session-host-strict", subject="Second task")
        third = await bound.create_task(session_id="session-host-strict", subject="Third task")

        updated_first = await bound.update_task(
            first["task"]["task_id"],
            session_id="session-host-strict",
            status="in_progress",
            runtime_context=policy,
        )
        updated_second = await bound.update_task(
            second["task"]["task_id"],
            session_id="session-host-strict",
            status="in_progress",
            runtime_context=policy,
        )
        claimed_third = await bound.claim_task(
            third["task"]["task_id"],
            session_id="session-host-strict",
            owner="planner",
            runtime_context=policy,
        )
        assigned_next = await bound.assign_next_task(
            session_id="session-host-strict",
            owner="planner",
            runtime_context=policy,
        )
        return updated_first, updated_second, claimed_third, assigned_next

    updated_first, updated_second, claimed_third, assigned_next = asyncio.run(scenario())

    assert updated_first["task"]["status"] == "in_progress"
    for result in (updated_second, claimed_third, assigned_next):
        assert isinstance(result, ExecutionResult)
        assert result.status == ExecutionStatus.FAILED
        assert result.metadata["category"] == "multiple_in_progress"


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


def test_bound_host_work_surface_matches_flat_task_and_job_helpers(tmp_path: Path) -> None:
    runtime = assemble_runtime(RuntimeConfig.for_project(tmp_path))
    bound = runtime.bind_host(NullHostAdapter())
    runtime.task_manager.create(
        "job-surface",
        title="background-surface",
        metadata={"session_id": "session-surface", "kind": "background_agent"},
    )
    runtime.task_manager.update("job-surface", status=TaskStatus.RUNNING)

    async def scenario():
        grouped_task = await bound.work.create_task(
            session_id="session-surface",
            subject="Grouped task",
        )
        flat_task = await bound.create_task(
            session_id="session-surface",
            subject="Flat task",
        )
        grouped_list = await bound.work.get_task_list(session_id="session-surface")
        flat_list = await bound.get_task_list(session_id="session-surface")
        grouped_jobs = await bound.work.list_jobs(session_id="session-surface")
        flat_jobs = await bound.list_jobs(session_id="session-surface")
        grouped_job = await bound.work.get_job("job-surface", session_id="session-surface")
        flat_job = await bound.get_job("job-surface", session_id="session-surface")
        return grouped_task, flat_task, grouped_list, flat_list, grouped_jobs, flat_jobs, grouped_job, flat_job

    grouped_task, flat_task, grouped_list, flat_list, grouped_jobs, flat_jobs, grouped_job, flat_job = asyncio.run(
        scenario()
    )

    assert grouped_task["task"]["subject"] == "Grouped task"
    assert flat_task["task"]["subject"] == "Flat task"
    assert grouped_list == flat_list
    assert grouped_jobs == flat_jobs
    assert grouped_job == flat_job
    assert [task["subject"] for task in grouped_list["tasks"]] == ["Grouped task", "Flat task"]
    assert grouped_jobs[0]["job_id"] == "job-surface"


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
        from weavert.agent_runtime import AgentRunResult

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
