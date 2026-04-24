from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from .contracts import RuntimePrivateContext, private_context_from_legacy_runtime_context, utc_now

TASK_LIST_ID_EXTENSION_KEY = "task_list_id"
TASK_LIST_RESOLVED_ID_EXTENSION_KEY = "resolved_task_list_id"
TASK_DISCIPLINE_EXTENSION_KEY = "task_discipline"
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class TaskListStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TaskReadinessState(StrEnum):
    AVAILABLE = "available"
    BLOCKED = "blocked"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class TaskListEntry:
    task_id: str
    subject: str
    description: str | None = None
    active_form: str | None = None
    status: TaskListStatus = TaskListStatus.PENDING
    owner: str | None = None
    blocks: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    is_archived: bool = False
    archived_at: datetime | None = None
    archived_by: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", tuple(str(item) for item in self.blocks))
        object.__setattr__(self, "blocked_by", tuple(str(item) for item in self.blocked_by))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "is_archived", bool(self.is_archived))
        archived_at = self.archived_at if isinstance(self.archived_at, datetime) else None
        object.__setattr__(self, "archived_at", archived_at)
        archived_by = _coerce_optional_string(self.archived_by)
        object.__setattr__(self, "archived_by", archived_by)
        if not self.is_archived:
            object.__setattr__(self, "archived_at", None)
            object.__setattr__(self, "archived_by", None)

    def serialize(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "subject": self.subject,
            "description": self.description,
            "active_form": self.active_form,
            "status": self.status.value,
            "owner": self.owner,
            "blocks": list(self.blocks),
            "blocked_by": list(self.blocked_by),
            "metadata": _json_safe_mapping(self.metadata),
            "is_archived": self.is_archived,
            "archived_at": self.archived_at.isoformat() if self.archived_at is not None else None,
            "archived_by": self.archived_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TaskListEntry":
        archived_at = _coerce_datetime(payload.get("archived_at"))
        archived_by = _coerce_optional_string(payload.get("archived_by"))
        is_archived = _coerce_bool(
            payload.get("is_archived"),
            default=archived_at is not None or archived_by is not None,
        )
        return cls(
            task_id=str(payload.get("task_id") or uuid4().hex),
            subject=str(payload.get("subject") or ""),
            description=_coerce_optional_string(payload.get("description")),
            active_form=_coerce_optional_string(payload.get("active_form")),
            status=_coerce_task_status(payload.get("status")) or TaskListStatus.PENDING,
            owner=_coerce_optional_string(payload.get("owner")),
            blocks=_coerce_string_sequence(payload.get("blocks")),
            blocked_by=_coerce_string_sequence(payload.get("blocked_by")),
            metadata=_coerce_mapping(payload.get("metadata")),
            is_archived=is_archived,
            archived_at=archived_at if is_archived else None,
            archived_by=archived_by if is_archived else None,
            created_at=_coerce_datetime(payload.get("created_at")) or utc_now(),
            updated_at=_coerce_datetime(payload.get("updated_at")) or utc_now(),
        )


@dataclass(frozen=True, slots=True)
class TaskListSnapshot:
    list_id: str
    tasks: tuple[TaskListEntry, ...] = ()
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.tasks, key=lambda task: (task.created_at, task.task_id)))
        object.__setattr__(self, "tasks", ordered)

    def serialize(self) -> dict[str, Any]:
        return {
            "list_id": self.list_id,
            "updated_at": self.updated_at.isoformat(),
            "tasks": [task.serialize() for task in self.tasks],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TaskListSnapshot":
        return cls(
            list_id=str(payload.get("list_id") or ""),
            updated_at=_coerce_datetime(payload.get("updated_at")) or utc_now(),
            tasks=tuple(
                TaskListEntry.from_payload(item)
                for item in payload.get("tasks", ())
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True, slots=True)
class TaskOrchestrationEntry:
    task: TaskListEntry
    readiness_state: TaskReadinessState
    unresolved_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "unresolved_blockers", tuple(str(item) for item in self.unresolved_blockers))

    def serialize(self) -> dict[str, Any]:
        payload = self.task.serialize()
        payload["readiness_state"] = self.readiness_state.value
        payload["unresolved_blockers"] = list(self.unresolved_blockers)
        return payload


@dataclass(frozen=True, slots=True)
class TaskOrchestrationSnapshot:
    list_id: str
    tasks: tuple[TaskOrchestrationEntry, ...] = ()
    available_task_ids: tuple[str, ...] = ()
    blocked_task_ids: tuple[str, ...] = ()
    claimed_task_ids: tuple[str, ...] = ()
    in_progress_task_ids: tuple[str, ...] = ()
    completed_task_ids: tuple[str, ...] = ()
    unresolved_blocker_ids: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.tasks, key=lambda item: (item.task.created_at, item.task.task_id)))
        object.__setattr__(self, "tasks", ordered)
        object.__setattr__(self, "available_task_ids", tuple(str(item) for item in self.available_task_ids))
        object.__setattr__(self, "blocked_task_ids", tuple(str(item) for item in self.blocked_task_ids))
        object.__setattr__(self, "claimed_task_ids", tuple(str(item) for item in self.claimed_task_ids))
        object.__setattr__(self, "in_progress_task_ids", tuple(str(item) for item in self.in_progress_task_ids))
        object.__setattr__(self, "completed_task_ids", tuple(str(item) for item in self.completed_task_ids))
        object.__setattr__(
            self,
            "unresolved_blocker_ids",
            tuple(str(item) for item in self.unresolved_blocker_ids),
        )

    def serialize(self) -> dict[str, Any]:
        return {
            "list_id": self.list_id,
            "updated_at": self.updated_at.isoformat(),
            "tasks": [task.serialize() for task in self.tasks],
            "available_task_ids": list(self.available_task_ids),
            "blocked_task_ids": list(self.blocked_task_ids),
            "claimed_task_ids": list(self.claimed_task_ids),
            "in_progress_task_ids": list(self.in_progress_task_ids),
            "completed_task_ids": list(self.completed_task_ids),
            "unresolved_blocker_ids": list(self.unresolved_blocker_ids),
        }


@dataclass(frozen=True, slots=True)
class TaskDisciplinePolicy:
    enabled: bool = True
    reminder_turn_threshold: int = 3
    strict_single_in_progress: bool = False
    reminder_task_limit: int = 8

    @classmethod
    def resolve(
        cls,
        *,
        private_context: RuntimePrivateContext | Mapping[str, Any] | None = None,
        runtime_metadata: Mapping[str, Any] | None = None,
    ) -> "TaskDisciplinePolicy":
        resolved_private = coerce_private_context(private_context)
        payload: dict[str, Any] = {}
        if isinstance(runtime_metadata, Mapping):
            base = runtime_metadata.get(TASK_DISCIPLINE_EXTENSION_KEY)
            if isinstance(base, Mapping):
                payload.update({str(key): value for key, value in base.items()})
        if isinstance(resolved_private.extensions.get(TASK_DISCIPLINE_EXTENSION_KEY), Mapping):
            payload.update(
                {
                    str(key): value
                    for key, value in resolved_private.extensions[TASK_DISCIPLINE_EXTENSION_KEY].items()
                }
            )
        return cls(
            enabled=_coerce_bool(payload.get("enabled"), default=True),
            reminder_turn_threshold=max(1, _coerce_int(payload.get("reminder_turn_threshold"), default=3)),
            strict_single_in_progress=_coerce_bool(
                payload.get("strict_single_in_progress"),
                default=False,
            ),
            reminder_task_limit=max(1, _coerce_int(payload.get("reminder_task_limit"), default=8)),
        )


class TaskListError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class TaskListNotFoundError(TaskListError):
    def __init__(self, *, list_id: str, task_id: str) -> None:
        super().__init__(
            "not_found",
            f"Task '{task_id}' was not found in task list '{list_id}'",
            details={"task_list_id": list_id, "task_id": task_id},
        )


class TaskListInvalidRequestError(TaskListError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("invalid_request", message, details=details)


class TaskListLifecycleError(TaskListError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        list_id: str,
        task_id: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {"task_list_id": list_id, "task_id": task_id}
        if details is not None:
            payload.update(details)
        super().__init__(code, message, details=payload)


class TaskListMultipleInProgressError(TaskListError):
    def __init__(self, *, list_id: str, task_id: str, existing_task_id: str) -> None:
        super().__init__(
            "multiple_in_progress",
            (
                f"Task list '{list_id}' already has an in_progress task "
                f"('{existing_task_id}') and strict single in_progress enforcement is enabled"
            ),
            details={
                "task_list_id": list_id,
                "task_id": task_id,
                "existing_task_id": existing_task_id,
            },
        )


class TaskListBlockedError(TaskListError):
    def __init__(self, *, list_id: str, task_id: str, unresolved_blockers: Sequence[str]) -> None:
        blockers = tuple(str(item) for item in unresolved_blockers)
        super().__init__(
            "blocked",
            f"Task '{task_id}' is blocked by unresolved tasks: {', '.join(blockers)}",
            details={
                "task_list_id": list_id,
                "task_id": task_id,
                "unresolved_blockers": list(blockers),
            },
        )


class TaskListAlreadyClaimedError(TaskListError):
    def __init__(self, *, list_id: str, task_id: str, owner: str | None) -> None:
        super().__init__(
            "already_claimed",
            f"Task '{task_id}' in task list '{list_id}' is already claimed"
            + (f" by '{owner}'" if owner else ""),
            details={
                "task_list_id": list_id,
                "task_id": task_id,
                "owner": owner,
            },
        )


class TaskListOwnerBusyError(TaskListError):
    def __init__(self, *, list_id: str, task_id: str, owner: str, existing_task_id: str) -> None:
        super().__init__(
            "owner_busy",
            (
                f"Owner '{owner}' already holds unresolved task '{existing_task_id}' "
                f"in task list '{list_id}'"
            ),
            details={
                "task_list_id": list_id,
                "task_id": task_id,
                "owner": owner,
                "existing_task_id": existing_task_id,
            },
        )


class TaskListDependencyCycleError(TaskListError):
    def __init__(self, *, list_id: str, blocker_task_id: str, blocked_task_id: str) -> None:
        super().__init__(
            "dependency_cycle",
            (
                f"Adding dependency '{blocker_task_id}' -> '{blocked_task_id}' "
                f"would create a cycle in task list '{list_id}'"
            ),
            details={
                "task_list_id": list_id,
                "blocker_task_id": blocker_task_id,
                "blocked_task_id": blocked_task_id,
            },
        )


class TaskListStore(Protocol):
    async def load(self, list_id: str) -> TaskListSnapshot | None: ...

    async def save(self, snapshot: TaskListSnapshot) -> TaskListSnapshot: ...

    async def list_snapshots(self) -> tuple[TaskListSnapshot, ...]: ...


@dataclass(slots=True)
class InMemoryTaskListStore:
    _snapshots: dict[str, TaskListSnapshot] = field(default_factory=dict)

    async def load(self, list_id: str) -> TaskListSnapshot | None:
        return self._snapshots.get(list_id)

    async def save(self, snapshot: TaskListSnapshot) -> TaskListSnapshot:
        self._snapshots[snapshot.list_id] = snapshot
        return snapshot

    async def list_snapshots(self) -> tuple[TaskListSnapshot, ...]:
        return tuple(self._snapshots[list_id] for list_id in sorted(self._snapshots))


@dataclass(slots=True)
class FileTaskListStore:
    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def load(self, list_id: str) -> TaskListSnapshot | None:
        path = self._path_for(list_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            return None
        snapshot = TaskListSnapshot.from_payload(payload)
        if snapshot.list_id != list_id:
            return None
        return snapshot

    async def save(self, snapshot: TaskListSnapshot) -> TaskListSnapshot:
        path = self._path_for(snapshot.list_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        payload = json.dumps(snapshot.serialize(), ensure_ascii=True, indent=2, sort_keys=True)
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
        return snapshot

    async def list_snapshots(self) -> tuple[TaskListSnapshot, ...]:
        snapshots: list[TaskListSnapshot] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            snapshots.append(TaskListSnapshot.from_payload(payload))
        return tuple(sorted(snapshots, key=lambda snapshot: snapshot.list_id))

    def _path_for(self, list_id: str) -> Path:
        safe_prefix = _SAFE_FILENAME_RE.sub("_", list_id).strip("._") or "task_list"
        digest = hashlib.sha1(list_id.encode("utf-8")).hexdigest()[:12]
        return self.root / f"{safe_prefix}--{digest}.json"


TaskListWatcher = Callable[[TaskListSnapshot], Any]


@dataclass(slots=True)
class DefaultTaskListService:
    store: TaskListStore = field(default_factory=InMemoryTaskListStore)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict, init=False)
    _watchers: dict[str, dict[str, TaskListWatcher]] = field(default_factory=dict, init=False)

    async def resolve_list_id(
        self,
        *,
        session_id: str,
        private_context: RuntimePrivateContext | Mapping[str, Any] | None = None,
    ) -> str:
        return resolve_task_list_id(
            session_id=session_id,
            private_context=private_context,
        )

    async def list_snapshots(self) -> tuple[TaskListSnapshot, ...]:
        return await self.store.list_snapshots()

    async def get_snapshot(self, list_id: str) -> TaskListSnapshot:
        snapshot = await self.store.load(list_id)
        if snapshot is None:
            return TaskListSnapshot(list_id=list_id)
        return snapshot

    async def get_orchestration_snapshot(
        self,
        list_id: str,
        *,
        include_archived: bool = False,
    ) -> TaskOrchestrationSnapshot:
        snapshot = await self.get_snapshot(list_id)
        return _derive_orchestration_snapshot(snapshot, include_archived=include_archived)

    async def get_orchestration_task(
        self,
        list_id: str,
        task_id: str,
        *,
        include_archived: bool = True,
    ) -> TaskOrchestrationEntry | None:
        snapshot = await self.get_orchestration_snapshot(list_id, include_archived=include_archived)
        for task in snapshot.tasks:
            if task.task.task_id == task_id:
                return task
        return None

    async def create(
        self,
        list_id: str,
        *,
        subject: str,
        description: str | None = None,
        active_form: str | None = None,
        owner: str | None = None,
        blocks: Sequence[str] = (),
        blocked_by: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> TaskListEntry:
        normalized_subject = str(subject).strip()
        if not normalized_subject:
            raise TaskListInvalidRequestError("task_create requires a non-empty subject")
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            mutation_time = utc_now()
            task = TaskListEntry(
                task_id=uuid4().hex,
                subject=normalized_subject,
                description=_coerce_optional_string(description),
                active_form=_coerce_optional_string(active_form),
                owner=_coerce_optional_string(owner),
                metadata=_coerce_mapping(metadata),
                created_at=mutation_time,
                updated_at=mutation_time,
            )
            tasks = list(snapshot.tasks) + [task]
            if blocks or blocked_by:
                tasks, _ = _apply_dependency_overrides(
                    tasks,
                    list_id=list_id,
                    task_id=task.task_id,
                    blocks=blocks,
                    blocked_by=blocked_by,
                    mutation_time=mutation_time,
                )
                task = next(item for item in tasks if item.task_id == task.task_id)
            next_snapshot = replace(
                snapshot,
                tasks=tuple(tasks),
                updated_at=mutation_time,
            )
            await self.store.save(next_snapshot)
        await self._notify_watchers(next_snapshot)
        return task

    async def get(self, list_id: str, task_id: str) -> TaskListEntry | None:
        snapshot = await self.get_snapshot(list_id)
        for task in snapshot.tasks:
            if task.task_id == task_id:
                return task
        return None

    async def list(
        self,
        list_id: str,
        *,
        include_archived: bool = False,
    ) -> tuple[TaskListEntry, ...]:
        snapshot = await self.get_snapshot(list_id)
        visible = _visible_tasks(snapshot.tasks, include_archived=include_archived)
        archived_task_ids = _archived_task_ids(snapshot.tasks)
        return tuple(
            _project_task_entry(
                task,
                archived_task_ids=archived_task_ids,
                include_archived=include_archived,
            )
            for task in visible
        )

    async def update(
        self,
        list_id: str,
        task_id: str,
        *,
        patch: Mapping[str, Any],
        strict_single_in_progress: bool = False,
    ) -> TaskListEntry:
        if not patch:
            raise TaskListInvalidRequestError(
                "task_update requires at least one supported mutable field",
                details={"task_list_id": list_id, "task_id": task_id},
            )
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            tasks = list(snapshot.tasks)
            index = _find_task_index(tasks, list_id=list_id, task_id=task_id)
            existing = tasks[index]
            _assert_task_mutable(existing, list_id=list_id)
            updated = self._apply_patch(existing, patch)
            if strict_single_in_progress and updated.status is TaskListStatus.IN_PROGRESS:
                _validate_single_in_progress(tasks, list_id=list_id, task_id=task_id)
            tasks[index] = updated
            next_snapshot = replace(
                snapshot,
                tasks=tuple(tasks),
                updated_at=updated.updated_at,
            )
            await self.store.save(next_snapshot)
        await self._notify_watchers(next_snapshot)
        return updated

    async def archive(
        self,
        list_id: str,
        task_id: str,
        *,
        archived_by: str | None = None,
    ) -> TaskListEntry:
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            tasks = list(snapshot.tasks)
            index = _find_task_index(tasks, list_id=list_id, task_id=task_id)
            existing = tasks[index]
            if existing.is_archived:
                raise TaskListLifecycleError(
                    "already_archived",
                    f"Task '{task_id}' in task list '{list_id}' is already archived",
                    list_id=list_id,
                    task_id=task_id,
                )
            if existing.status is not TaskListStatus.COMPLETED:
                raise TaskListLifecycleError(
                    "archive_requires_completed",
                    f"Task '{task_id}' in task list '{list_id}' must be completed before archiving",
                    list_id=list_id,
                    task_id=task_id,
                    details={"status": existing.status.value},
                )
            mutation_time = utc_now()
            archived = replace(
                existing,
                is_archived=True,
                archived_at=mutation_time,
                archived_by=_coerce_optional_string(archived_by),
                updated_at=mutation_time,
            )
            tasks[index] = archived
            next_snapshot = replace(
                snapshot,
                tasks=tuple(tasks),
                updated_at=mutation_time,
            )
            await self.store.save(next_snapshot)
        await self._notify_watchers(next_snapshot)
        return archived

    async def unarchive(self, list_id: str, task_id: str) -> TaskListEntry:
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            tasks = list(snapshot.tasks)
            index = _find_task_index(tasks, list_id=list_id, task_id=task_id)
            existing = tasks[index]
            if not existing.is_archived:
                raise TaskListLifecycleError(
                    "not_archived",
                    f"Task '{task_id}' in task list '{list_id}' is not archived",
                    list_id=list_id,
                    task_id=task_id,
                )
            mutation_time = utc_now()
            updated = replace(
                existing,
                is_archived=False,
                archived_at=None,
                archived_by=None,
                updated_at=mutation_time,
            )
            tasks[index] = updated
            next_snapshot = replace(
                snapshot,
                tasks=tuple(tasks),
                updated_at=mutation_time,
            )
            await self.store.save(next_snapshot)
        await self._notify_watchers(next_snapshot)
        return updated

    async def delete(self, list_id: str, task_id: str) -> TaskListEntry:
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            index = _find_task_index(snapshot.tasks, list_id=list_id, task_id=task_id)
            deleted = snapshot.tasks[index]
            if not deleted.is_archived:
                raise TaskListLifecycleError(
                    "delete_requires_archived",
                    f"Task '{task_id}' in task list '{list_id}' must be archived before deletion",
                    list_id=list_id,
                    task_id=task_id,
                )
            remaining = [task for task in snapshot.tasks if task.task_id != task_id]
            if len(remaining) == len(snapshot.tasks):
                raise TaskListNotFoundError(list_id=list_id, task_id=task_id)
            mutation_time = utc_now()
            edges, _ = _normalized_dependency_graph(remaining)
            normalized_remaining, _ = _tasks_from_graph(remaining, edges, mutation_time)
            next_snapshot = replace(
                snapshot,
                tasks=tuple(normalized_remaining),
                updated_at=mutation_time,
            )
            await self.store.save(next_snapshot)
        await self._notify_watchers(next_snapshot)
        return deleted

    async def claim(
        self,
        list_id: str,
        task_id: str,
        owner: str | None,
        *,
        set_in_progress: bool = True,
        enforce_owner_busy: bool = False,
        strict_single_in_progress: bool = False,
    ) -> TaskListEntry:
        next_snapshot: TaskListSnapshot | None = None
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            tasks = list(snapshot.tasks)
            _assert_task_mutable(tasks[_find_task_index(tasks, list_id=list_id, task_id=task_id)], list_id=list_id)
            updated, changed = _claim_task(
                tasks,
                list_id=list_id,
                task_id=task_id,
                owner=owner,
                set_in_progress=set_in_progress,
                enforce_owner_busy=enforce_owner_busy,
                strict_single_in_progress=strict_single_in_progress,
            )
            if changed:
                next_snapshot = replace(
                    snapshot,
                    tasks=tuple(tasks),
                    updated_at=updated.updated_at,
                )
                await self.store.save(next_snapshot)
        if next_snapshot is not None:
            await self._notify_watchers(next_snapshot)
        return updated

    async def release(self, list_id: str, task_id: str) -> TaskListEntry:
        next_snapshot: TaskListSnapshot | None = None
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            tasks = list(snapshot.tasks)
            _assert_task_mutable(tasks[_find_task_index(tasks, list_id=list_id, task_id=task_id)], list_id=list_id)
            updated, changed = _release_task(
                tasks,
                list_id=list_id,
                task_id=task_id,
            )
            if changed:
                next_snapshot = replace(
                    snapshot,
                    tasks=tuple(tasks),
                    updated_at=updated.updated_at,
                )
                await self.store.save(next_snapshot)
        if next_snapshot is not None:
            await self._notify_watchers(next_snapshot)
        return updated

    async def assign_next(
        self,
        list_id: str,
        owner: str | None,
        *,
        set_in_progress: bool = True,
        enforce_owner_busy: bool = False,
        strict_single_in_progress: bool = False,
    ) -> TaskListEntry | None:
        normalized_owner = _coerce_optional_string(owner)
        if normalized_owner is None:
            raise TaskListInvalidRequestError(
                "task_assign_next requires a non-empty owner",
                details={"task_list_id": list_id},
            )
        next_snapshot: TaskListSnapshot | None = None
        assigned: TaskListEntry | None = None
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            tasks = list(snapshot.tasks)
            view = _derive_orchestration_snapshot(snapshot)
            next_task_id = next(
                (
                    task.task.task_id
                    for task in view.tasks
                    if task.readiness_state is TaskReadinessState.AVAILABLE
                ),
                None,
            )
            if next_task_id is None:
                return None
            assigned, changed = _claim_task(
                tasks,
                list_id=list_id,
                task_id=next_task_id,
                owner=normalized_owner,
                set_in_progress=set_in_progress,
                enforce_owner_busy=enforce_owner_busy,
                strict_single_in_progress=strict_single_in_progress,
            )
            if changed:
                next_snapshot = replace(
                    snapshot,
                    tasks=tuple(tasks),
                    updated_at=assigned.updated_at,
                )
                await self.store.save(next_snapshot)
        if next_snapshot is not None:
            await self._notify_watchers(next_snapshot)
        return assigned

    async def add_dependency(
        self,
        list_id: str,
        blocker_task_id: str,
        blocked_task_id: str,
    ) -> tuple[TaskListEntry, TaskListEntry]:
        next_snapshot: TaskListSnapshot | None = None
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            tasks = list(snapshot.tasks)
            mutation_time = utc_now()
            tasks, changed = _mutate_dependency_graph(
                tasks,
                list_id=list_id,
                blocker_task_id=blocker_task_id,
                blocked_task_id=blocked_task_id,
                remove=False,
                mutation_time=mutation_time,
            )
            blocker_task = next(task for task in tasks if task.task_id == blocker_task_id)
            blocked_task = next(task for task in tasks if task.task_id == blocked_task_id)
            if changed:
                next_snapshot = replace(
                    snapshot,
                    tasks=tuple(tasks),
                    updated_at=mutation_time,
                )
                await self.store.save(next_snapshot)
        if next_snapshot is not None:
            await self._notify_watchers(next_snapshot)
        return blocker_task, blocked_task

    async def remove_dependency(
        self,
        list_id: str,
        blocker_task_id: str,
        blocked_task_id: str,
    ) -> tuple[TaskListEntry, TaskListEntry]:
        next_snapshot: TaskListSnapshot | None = None
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            tasks = list(snapshot.tasks)
            mutation_time = utc_now()
            tasks, changed = _mutate_dependency_graph(
                tasks,
                list_id=list_id,
                blocker_task_id=blocker_task_id,
                blocked_task_id=blocked_task_id,
                remove=True,
                mutation_time=mutation_time,
            )
            blocker_task = next(task for task in tasks if task.task_id == blocker_task_id)
            blocked_task = next(task for task in tasks if task.task_id == blocked_task_id)
            if changed:
                next_snapshot = replace(
                    snapshot,
                    tasks=tuple(tasks),
                    updated_at=mutation_time,
                )
                await self.store.save(next_snapshot)
        if next_snapshot is not None:
            await self._notify_watchers(next_snapshot)
        return blocker_task, blocked_task

    async def watch(
        self,
        list_id: str,
        callback: TaskListWatcher,
    ) -> Callable[[], None]:
        watcher_id = uuid4().hex
        self._watchers.setdefault(list_id, {})[watcher_id] = callback
        try:
            await _maybe_await(callback(await self.get_snapshot(list_id)))
        except Exception:
            self._remove_watcher(list_id, watcher_id)
            raise

        def unsubscribe() -> None:
            self._remove_watcher(list_id, watcher_id)

        return unsubscribe

    async def _notify_watchers(self, snapshot: TaskListSnapshot) -> None:
        watchers = tuple(self._watchers.get(snapshot.list_id, {}).items())
        for watcher_id, callback in watchers:
            try:
                await _maybe_await(callback(snapshot))
            except Exception:
                self._remove_watcher(snapshot.list_id, watcher_id)
                continue

    def _lock_for(self, list_id: str) -> asyncio.Lock:
        lock = self._locks.get(list_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[list_id] = lock
        return lock

    def _remove_watcher(self, list_id: str, watcher_id: str) -> None:
        watchers = self._watchers.get(list_id)
        if watchers is None:
            return
        watchers.pop(watcher_id, None)
        if not watchers:
            self._watchers.pop(list_id, None)

    def _apply_patch(self, task: TaskListEntry, patch: Mapping[str, Any]) -> TaskListEntry:
        allowed = {
            "status",
            "subject",
            "description",
            "active_form",
            "metadata",
        }
        unsupported = sorted(str(key) for key in patch if key not in allowed)
        if unsupported:
            raise TaskListInvalidRequestError(
                _task_update_unsupported_message(unsupported),
                details={"unsupported_fields": unsupported, "task_id": task.task_id},
            )

        if not any(key in patch for key in allowed):
            raise TaskListInvalidRequestError(
                "task_update requires at least one supported mutable field",
                details={"task_id": task.task_id},
            )

        updated_metadata = dict(task.metadata)
        if "metadata" in patch:
            updated_metadata.update(_coerce_mapping(patch.get("metadata")))

        subject = task.subject
        if "subject" in patch:
            normalized_subject = _coerce_optional_string(patch.get("subject"))
            if normalized_subject is None:
                raise TaskListInvalidRequestError(
                    "task_update requires subject to be a non-empty string when provided",
                    details={"task_id": task.task_id},
                )
            subject = normalized_subject

        return replace(
            task,
            subject=subject,
            description=(
                _coerce_optional_string(patch.get("description"))
                if "description" in patch
                else task.description
            ),
            active_form=(
                _coerce_optional_string(patch.get("active_form"))
                if "active_form" in patch
                else task.active_form
            ),
            status=_coerce_task_status(patch.get("status")) if "status" in patch else task.status,
            metadata=updated_metadata,
            updated_at=utc_now(),
        )


def coerce_private_context(
    value: RuntimePrivateContext | Mapping[str, Any] | None,
) -> RuntimePrivateContext:
    if isinstance(value, RuntimePrivateContext):
        return value
    if isinstance(value, Mapping):
        return private_context_from_legacy_runtime_context(value)
    return RuntimePrivateContext()


def resolve_task_list_id(
    *,
    session_id: str,
    private_context: RuntimePrivateContext | Mapping[str, Any] | None = None,
) -> str:
    resolved_private = coerce_private_context(private_context)
    extensions = resolved_private.extensions
    explicit = _coerce_optional_string(extensions.get(TASK_LIST_ID_EXTENSION_KEY))
    if explicit is not None:
        return explicit
    orchestration_id = _coerce_optional_string(
        extensions.get("orchestration_id") or extensions.get("orchestration_scope_id")
    )
    if orchestration_id is not None:
        return f"orchestration:{orchestration_id}"
    team_id = _coerce_optional_string(extensions.get("team_id"))
    if team_id is not None:
        return f"team:{team_id}"
    inherited = _coerce_optional_string(extensions.get(TASK_LIST_RESOLVED_ID_EXTENSION_KEY))
    if inherited is not None:
        return inherited
    return f"session:{session_id}"


def task_list_entry_to_dict(entry: TaskListEntry | TaskOrchestrationEntry) -> dict[str, Any]:
    return entry.serialize()


def task_orchestration_entry_to_dict(entry: TaskOrchestrationEntry) -> dict[str, Any]:
    return entry.serialize()


def task_list_snapshot_to_dict(
    snapshot: TaskListSnapshot | TaskOrchestrationSnapshot,
    *,
    orchestration: TaskOrchestrationSnapshot | None = None,
) -> dict[str, Any]:
    if orchestration is not None:
        return orchestration.serialize()
    return snapshot.serialize()


def task_orchestration_snapshot_to_dict(snapshot: TaskOrchestrationSnapshot) -> dict[str, Any]:
    return snapshot.serialize()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _find_task_index(tasks: Sequence[TaskListEntry], *, list_id: str, task_id: str) -> int:
    for index, task in enumerate(tasks):
        if task.task_id == task_id:
            return index
    raise TaskListNotFoundError(list_id=list_id, task_id=task_id)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _archived_task_ids(tasks: Sequence[TaskListEntry]) -> frozenset[str]:
    return frozenset(task.task_id for task in tasks if task.is_archived)


def _visible_tasks(
    tasks: Sequence[TaskListEntry],
    *,
    include_archived: bool,
) -> tuple[TaskListEntry, ...]:
    if include_archived:
        return tuple(tasks)
    return tuple(task for task in tasks if not task.is_archived)


def _project_task_entry(
    task: TaskListEntry,
    *,
    archived_task_ids: frozenset[str],
    include_archived: bool,
) -> TaskListEntry:
    if include_archived or not archived_task_ids:
        return task
    projected_blocks = tuple(task_id for task_id in task.blocks if task_id not in archived_task_ids)
    projected_blocked_by = tuple(task_id for task_id in task.blocked_by if task_id not in archived_task_ids)
    if projected_blocks == task.blocks and projected_blocked_by == task.blocked_by:
        return task
    return replace(task, blocks=projected_blocks, blocked_by=projected_blocked_by)


def _assert_task_mutable(task: TaskListEntry, *, list_id: str) -> None:
    if task.is_archived:
        raise TaskListLifecycleError(
            "archived_task_immutable",
            f"Task '{task.task_id}' in task list '{list_id}' is archived and cannot be modified",
            list_id=list_id,
            task_id=task.task_id,
        )


def _claim_task(
    tasks: list[TaskListEntry],
    *,
    list_id: str,
    task_id: str,
    owner: str | None,
    set_in_progress: bool,
    enforce_owner_busy: bool,
    strict_single_in_progress: bool,
) -> tuple[TaskListEntry, bool]:
    normalized_owner = _coerce_optional_string(owner)
    if normalized_owner is None:
        raise TaskListInvalidRequestError(
            "task_claim requires a non-empty owner",
            details={"task_list_id": list_id, "task_id": task_id},
        )
    index = _find_task_index(tasks, list_id=list_id, task_id=task_id)
    existing = tasks[index]
    _assert_task_mutable(existing, list_id=list_id)
    if existing.status is TaskListStatus.COMPLETED:
        raise TaskListInvalidRequestError(
            "task_claim does not support completed tasks",
            details={"task_list_id": list_id, "task_id": task_id},
        )

    desired_status = existing.status
    if set_in_progress:
        desired_status = TaskListStatus.IN_PROGRESS

    unresolved_blockers = _unresolved_blockers(tasks, task_id)

    if existing.owner == normalized_owner:
        if desired_status is existing.status:
            return existing, False
        if unresolved_blockers:
            raise TaskListBlockedError(
                list_id=list_id,
                task_id=task_id,
                unresolved_blockers=unresolved_blockers,
            )
        if strict_single_in_progress and desired_status is TaskListStatus.IN_PROGRESS:
            _validate_single_in_progress(tasks, list_id=list_id, task_id=task_id)
        updated = replace(existing, status=desired_status, updated_at=utc_now())
        tasks[index] = updated
        return updated, True

    if existing.owner is not None:
        raise TaskListAlreadyClaimedError(
            list_id=list_id,
            task_id=task_id,
            owner=existing.owner,
        )

    if unresolved_blockers:
        raise TaskListBlockedError(
            list_id=list_id,
            task_id=task_id,
            unresolved_blockers=unresolved_blockers,
        )

    if enforce_owner_busy:
        _assert_owner_available(
            tasks,
            list_id=list_id,
            task_id=task_id,
            owner=normalized_owner,
        )

    if strict_single_in_progress and desired_status is TaskListStatus.IN_PROGRESS:
        _validate_single_in_progress(tasks, list_id=list_id, task_id=task_id)

    updated = replace(
        existing,
        owner=normalized_owner,
        status=desired_status,
        updated_at=utc_now(),
    )
    tasks[index] = updated
    return updated, True


def _release_task(
    tasks: list[TaskListEntry],
    *,
    list_id: str,
    task_id: str,
) -> tuple[TaskListEntry, bool]:
    index = _find_task_index(tasks, list_id=list_id, task_id=task_id)
    existing = tasks[index]
    _assert_task_mutable(existing, list_id=list_id)
    desired_status = existing.status if existing.status is TaskListStatus.COMPLETED else TaskListStatus.PENDING
    if existing.owner is None and existing.status is desired_status:
        return existing, False
    updated = replace(
        existing,
        owner=None,
        status=desired_status,
        updated_at=utc_now(),
    )
    tasks[index] = updated
    return updated, True


def _validate_single_in_progress(
    tasks: Sequence[TaskListEntry],
    *,
    list_id: str,
    task_id: str,
) -> None:
    current = next(
        (
            task.task_id
            for task in tasks
            if task.task_id != task_id and task.status is TaskListStatus.IN_PROGRESS
        ),
        None,
    )
    if current is not None:
        raise TaskListMultipleInProgressError(
            list_id=list_id,
            task_id=task_id,
            existing_task_id=current,
        )


def _assert_owner_available(
    tasks: Sequence[TaskListEntry],
    *,
    list_id: str,
    task_id: str,
    owner: str,
) -> None:
    current = next(
        (
            task.task_id
            for task in tasks
            if task.task_id != task_id
            and task.owner == owner
            and task.status is not TaskListStatus.COMPLETED
        ),
        None,
    )
    if current is not None:
        raise TaskListOwnerBusyError(
            list_id=list_id,
            task_id=task_id,
            owner=owner,
            existing_task_id=current,
        )


def _mutate_dependency_graph(
    tasks: list[TaskListEntry],
    *,
    list_id: str,
    blocker_task_id: str,
    blocked_task_id: str,
    remove: bool,
    mutation_time: datetime,
) -> tuple[list[TaskListEntry], bool]:
    blocker_index = _find_task_index(tasks, list_id=list_id, task_id=blocker_task_id)
    blocked_index = _find_task_index(tasks, list_id=list_id, task_id=blocked_task_id)
    _assert_task_mutable(tasks[blocker_index], list_id=list_id)
    _assert_task_mutable(tasks[blocked_index], list_id=list_id)
    if not remove and blocker_task_id == blocked_task_id:
        raise TaskListDependencyCycleError(
            list_id=list_id,
            blocker_task_id=blocker_task_id,
            blocked_task_id=blocked_task_id,
        )
    edges, _ = _normalized_dependency_graph(tasks)
    if remove:
        if blocked_task_id in edges[blocker_task_id]:
            edges[blocker_task_id].remove(blocked_task_id)
        return _tasks_from_graph(tasks, edges, mutation_time)
    if blocked_task_id not in edges[blocker_task_id]:
        if _path_exists(edges, start=blocked_task_id, target=blocker_task_id):
            raise TaskListDependencyCycleError(
                list_id=list_id,
                blocker_task_id=blocker_task_id,
                blocked_task_id=blocked_task_id,
            )
        edges[blocker_task_id].add(blocked_task_id)
    return _tasks_from_graph(tasks, edges, mutation_time)


def _apply_dependency_overrides(
    tasks: list[TaskListEntry],
    *,
    list_id: str,
    task_id: str,
    blocks: Sequence[str],
    blocked_by: Sequence[str],
    mutation_time: datetime,
) -> tuple[list[TaskListEntry], bool]:
    task_index = _find_task_index(tasks, list_id=list_id, task_id=task_id)
    _assert_task_mutable(tasks[task_index], list_id=list_id)
    task_ids = {task.task_id for task in tasks}
    edges, _ = _normalized_dependency_graph(tasks)
    task_map = {task.task_id: task for task in tasks}

    for blocked_task_id in _coerce_string_sequence(blocks):
        if blocked_task_id not in task_ids:
            raise TaskListNotFoundError(list_id=list_id, task_id=blocked_task_id)
        _assert_task_mutable(task_map[blocked_task_id], list_id=list_id)
        if task_id == blocked_task_id or _path_exists(edges, start=blocked_task_id, target=task_id):
            raise TaskListDependencyCycleError(
                list_id=list_id,
                blocker_task_id=task_id,
                blocked_task_id=blocked_task_id,
            )
        edges[task_id].add(blocked_task_id)

    for blocker_task_id in _coerce_string_sequence(blocked_by):
        if blocker_task_id not in task_ids:
            raise TaskListNotFoundError(list_id=list_id, task_id=blocker_task_id)
        _assert_task_mutable(task_map[blocker_task_id], list_id=list_id)
        if blocker_task_id == task_id or _path_exists(edges, start=task_id, target=blocker_task_id):
            raise TaskListDependencyCycleError(
                list_id=list_id,
                blocker_task_id=blocker_task_id,
                blocked_task_id=task_id,
            )
        edges[blocker_task_id].add(task_id)

    return _tasks_from_graph(tasks, edges, mutation_time)


def _derive_orchestration_snapshot(
    snapshot: TaskListSnapshot,
    *,
    include_archived: bool = False,
) -> TaskOrchestrationSnapshot:
    order = {task.task_id: index for index, task in enumerate(snapshot.tasks)}
    archived_task_ids = _archived_task_ids(snapshot.tasks)
    available_task_ids: list[str] = []
    blocked_task_ids: list[str] = []
    claimed_task_ids: list[str] = []
    in_progress_task_ids: list[str] = []
    completed_task_ids: list[str] = []
    unresolved_blocker_ids: set[str] = set()
    tasks: list[TaskOrchestrationEntry] = []
    task_map = {task.task_id: task for task in snapshot.tasks}

    for task in _visible_tasks(snapshot.tasks, include_archived=include_archived):
        projected_task = _project_task_entry(
            task,
            archived_task_ids=archived_task_ids,
            include_archived=include_archived,
        )
        blockers = tuple(
            blocker_id
            for blocker_id in sorted(
                projected_task.blocked_by,
                key=lambda item: (order.get(item, len(order)), item),
            )
            if (
                (blocker := task_map.get(blocker_id)) is not None
                and not blocker.is_archived
                and blocker.status is not TaskListStatus.COMPLETED
            )
        )
        state = _readiness_state(projected_task, blockers)
        tasks.append(
            TaskOrchestrationEntry(
                task=projected_task,
                readiness_state=state,
                unresolved_blockers=blockers,
            )
        )
        if projected_task.is_archived:
            continue
        if state is TaskReadinessState.AVAILABLE:
            available_task_ids.append(task.task_id)
        elif state is TaskReadinessState.BLOCKED:
            blocked_task_ids.append(task.task_id)
        elif state is TaskReadinessState.CLAIMED:
            claimed_task_ids.append(task.task_id)
        elif state is TaskReadinessState.IN_PROGRESS:
            in_progress_task_ids.append(task.task_id)
        elif state is TaskReadinessState.COMPLETED:
            completed_task_ids.append(task.task_id)
        unresolved_blocker_ids.update(blockers)

    ordered_unresolved = tuple(
        blocker_id
        for blocker_id, _ in sorted(
            ((item, order.get(item, len(order))) for item in unresolved_blocker_ids),
            key=lambda item: (item[1], item[0]),
        )
    )
    return TaskOrchestrationSnapshot(
        list_id=snapshot.list_id,
        tasks=tuple(tasks),
        available_task_ids=tuple(available_task_ids),
        blocked_task_ids=tuple(blocked_task_ids),
        claimed_task_ids=tuple(claimed_task_ids),
        in_progress_task_ids=tuple(in_progress_task_ids),
        completed_task_ids=tuple(completed_task_ids),
        unresolved_blocker_ids=ordered_unresolved,
        updated_at=snapshot.updated_at,
    )


def _readiness_state(
    task: TaskListEntry,
    unresolved_blockers: Sequence[str],
) -> TaskReadinessState:
    if task.status is TaskListStatus.COMPLETED:
        return TaskReadinessState.COMPLETED
    if task.status is TaskListStatus.IN_PROGRESS:
        return TaskReadinessState.IN_PROGRESS
    if task.owner is not None:
        return TaskReadinessState.CLAIMED
    if unresolved_blockers:
        return TaskReadinessState.BLOCKED
    return TaskReadinessState.AVAILABLE


def _unresolved_blockers(tasks: Sequence[TaskListEntry], task_id: str) -> tuple[str, ...]:
    order = {task.task_id: index for index, task in enumerate(tasks)}
    task_map = {task.task_id: task for task in tasks}
    _, blocked_by = _normalized_dependency_graph(tasks)
    return tuple(
        blocker_id
        for blocker_id in sorted(
            blocked_by.get(task_id, set()),
            key=lambda item: (order.get(item, len(order)), item),
        )
        if task_map[blocker_id].status is not TaskListStatus.COMPLETED
    )


def _normalized_dependency_graph(
    tasks: Sequence[TaskListEntry],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    task_ids = {task.task_id for task in tasks}
    edges = {task.task_id: set() for task in tasks}
    for task in tasks:
        for blocked_task_id in task.blocks:
            if blocked_task_id in task_ids and blocked_task_id != task.task_id:
                edges[task.task_id].add(blocked_task_id)
        for blocker_task_id in task.blocked_by:
            if blocker_task_id in task_ids and blocker_task_id != task.task_id:
                edges[blocker_task_id].add(task.task_id)
    reverse = {task_id: set() for task_id in task_ids}
    for blocker_task_id, blocked_task_ids in edges.items():
        for blocked_task_id in blocked_task_ids:
            reverse[blocked_task_id].add(blocker_task_id)
    return edges, reverse


def _tasks_from_graph(
    tasks: Sequence[TaskListEntry],
    edges: Mapping[str, set[str]],
    mutation_time: datetime,
) -> tuple[list[TaskListEntry], bool]:
    order = {task.task_id: index for index, task in enumerate(tasks)}
    reverse: dict[str, set[str]] = {task.task_id: set() for task in tasks}
    for blocker_task_id, blocked_task_ids in edges.items():
        for blocked_task_id in blocked_task_ids:
            if blocked_task_id in reverse:
                reverse[blocked_task_id].add(blocker_task_id)
    updated_tasks: list[TaskListEntry] = []
    changed = False
    for task in tasks:
        new_blocks = tuple(
            sorted(
                edges.get(task.task_id, set()),
                key=lambda item: (order.get(item, len(order)), item),
            )
        )
        new_blocked_by = tuple(
            sorted(
                reverse.get(task.task_id, set()),
                key=lambda item: (order.get(item, len(order)), item),
            )
        )
        if new_blocks != task.blocks or new_blocked_by != task.blocked_by:
            updated_tasks.append(
                replace(
                    task,
                    blocks=new_blocks,
                    blocked_by=new_blocked_by,
                    updated_at=mutation_time,
                )
            )
            changed = True
            continue
        updated_tasks.append(task)
    return updated_tasks, changed


def _path_exists(
    edges: Mapping[str, set[str]],
    *,
    start: str,
    target: str,
) -> bool:
    if start == target:
        return True
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for candidate in edges.get(current, set()):
            if candidate == target:
                return True
            stack.append(candidate)
    return False


def _task_update_unsupported_message(unsupported: Sequence[str]) -> str:
    fields = ", ".join(unsupported)
    guidance: list[str] = []
    if any(field == "owner" for field in unsupported):
        guidance.append("Use task_claim or task_release for ownership changes.")
    if any(field in {"blocks", "blocked_by"} for field in unsupported):
        guidance.append("Use task_block or task_unblock for dependency changes.")
    if guidance:
        return f"task_update does not support fields: {fields}. {' '.join(guidance)}"
    return f"task_update does not support fields: {fields}"


def _coerce_optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): inner for key, inner in value.items()}


def _coerce_string_sequence(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = _coerce_optional_string(value)
        return (normalized,) if normalized is not None else ()
    if not isinstance(value, Sequence):
        return ()
    normalized = [
        candidate
        for item in value
        if (candidate := _coerce_optional_string(item)) is not None
    ]
    return tuple(normalized)


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _coerce_task_status(value: object) -> TaskListStatus | None:
    if value is None:
        return None
    if isinstance(value, TaskListStatus):
        return value
    return TaskListStatus(str(value))


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: object, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe(inner) for key, inner in value.items()}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


__all__ = [
    "DefaultTaskListService",
    "FileTaskListStore",
    "InMemoryTaskListStore",
    "TASK_DISCIPLINE_EXTENSION_KEY",
    "TASK_LIST_ID_EXTENSION_KEY",
    "TASK_LIST_RESOLVED_ID_EXTENSION_KEY",
    "TaskDisciplinePolicy",
    "TaskListAlreadyClaimedError",
    "TaskListBlockedError",
    "TaskListDependencyCycleError",
    "TaskListEntry",
    "TaskListError",
    "TaskListInvalidRequestError",
    "TaskListMultipleInProgressError",
    "TaskListNotFoundError",
    "TaskListOwnerBusyError",
    "TaskListSnapshot",
    "TaskListStatus",
    "TaskOrchestrationEntry",
    "TaskOrchestrationSnapshot",
    "TaskReadinessState",
    "coerce_private_context",
    "resolve_task_list_id",
    "task_list_entry_to_dict",
    "task_list_snapshot_to_dict",
    "task_orchestration_entry_to_dict",
    "task_orchestration_snapshot_to_dict",
]
