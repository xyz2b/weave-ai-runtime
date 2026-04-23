from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from .contracts import RuntimePrivateContext, private_context_from_legacy_runtime_context, utc_now

TASK_LIST_ID_EXTENSION_KEY = "task_list_id"
TASK_DISCIPLINE_EXTENSION_KEY = "task_discipline"
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class TaskListStatus(StrEnum):
    PENDING = "pending"
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
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", tuple(str(item) for item in self.blocks))
        object.__setattr__(self, "blocked_by", tuple(str(item) for item in self.blocked_by))
        object.__setattr__(self, "metadata", dict(self.metadata))

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
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TaskListEntry":
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
        path.write_text(
            json.dumps(snapshot.serialize(), ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
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
            task = TaskListEntry(
                task_id=uuid4().hex,
                subject=normalized_subject,
                description=_coerce_optional_string(description),
                active_form=_coerce_optional_string(active_form),
                owner=_coerce_optional_string(owner),
                blocks=_coerce_string_sequence(blocks),
                blocked_by=_coerce_string_sequence(blocked_by),
                metadata=_coerce_mapping(metadata),
            )
            updated = replace(
                snapshot,
                tasks=tuple(snapshot.tasks) + (task,),
                updated_at=utc_now(),
            )
            await self.store.save(updated)
        await self._notify_watchers(updated)
        return task

    async def get(self, list_id: str, task_id: str) -> TaskListEntry | None:
        snapshot = await self.get_snapshot(list_id)
        for task in snapshot.tasks:
            if task.task_id == task_id:
                return task
        return None

    async def list(self, list_id: str) -> tuple[TaskListEntry, ...]:
        return (await self.get_snapshot(list_id)).tasks

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
            index = next((offset for offset, task in enumerate(tasks) if task.task_id == task_id), None)
            if index is None:
                raise TaskListNotFoundError(list_id=list_id, task_id=task_id)
            existing = tasks[index]
            updated = self._apply_patch(existing, patch)
            if strict_single_in_progress and updated.status is TaskListStatus.IN_PROGRESS:
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
            tasks[index] = updated
            next_snapshot = replace(
                snapshot,
                tasks=tuple(tasks),
                updated_at=utc_now(),
            )
            await self.store.save(next_snapshot)
        await self._notify_watchers(next_snapshot)
        return updated

    async def delete(self, list_id: str, task_id: str) -> None:
        async with self._lock_for(list_id):
            snapshot = await self.get_snapshot(list_id)
            remaining = tuple(task for task in snapshot.tasks if task.task_id != task_id)
            if len(remaining) == len(snapshot.tasks):
                raise TaskListNotFoundError(list_id=list_id, task_id=task_id)
            next_snapshot = replace(snapshot, tasks=remaining, updated_at=utc_now())
            await self.store.save(next_snapshot)
        await self._notify_watchers(next_snapshot)

    async def claim(self, list_id: str, task_id: str, owner: str | None) -> TaskListEntry:
        return await self.update(
            list_id,
            task_id,
            patch={"owner": _coerce_optional_string(owner)},
        )

    async def watch(
        self,
        list_id: str,
        callback: TaskListWatcher,
    ) -> Callable[[], None]:
        watcher_id = uuid4().hex
        self._watchers.setdefault(list_id, {})[watcher_id] = callback
        await _maybe_await(callback(await self.get_snapshot(list_id)))

        def unsubscribe() -> None:
            watchers = self._watchers.get(list_id)
            if watchers is None:
                return
            watchers.pop(watcher_id, None)
            if not watchers:
                self._watchers.pop(list_id, None)

        return unsubscribe

    async def _notify_watchers(self, snapshot: TaskListSnapshot) -> None:
        watchers = tuple(self._watchers.get(snapshot.list_id, {}).values())
        for callback in watchers:
            try:
                await _maybe_await(callback(snapshot))
            except Exception:
                continue

    def _lock_for(self, list_id: str) -> asyncio.Lock:
        lock = self._locks.get(list_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[list_id] = lock
        return lock

    def _apply_patch(self, task: TaskListEntry, patch: Mapping[str, Any]) -> TaskListEntry:
        allowed = {
            "status",
            "subject",
            "description",
            "active_form",
            "owner",
            "blocks",
            "blocked_by",
            "metadata",
        }
        unsupported = sorted(str(key) for key in patch if key not in allowed)
        if unsupported:
            raise TaskListInvalidRequestError(
                f"task_update does not support fields: {', '.join(unsupported)}",
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
            owner=_coerce_optional_string(patch.get("owner")) if "owner" in patch else task.owner,
            blocks=_coerce_string_sequence(patch.get("blocks")) if "blocks" in patch else task.blocks,
            blocked_by=(
                _coerce_string_sequence(patch.get("blocked_by"))
                if "blocked_by" in patch
                else task.blocked_by
            ),
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
    return f"session:{session_id}"


def task_list_entry_to_dict(entry: TaskListEntry) -> dict[str, Any]:
    return entry.serialize()


def task_list_snapshot_to_dict(snapshot: TaskListSnapshot) -> dict[str, Any]:
    return snapshot.serialize()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


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
        return (_coerce_optional_string(value) or "",)
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
    "TaskDisciplinePolicy",
    "TaskListEntry",
    "TaskListError",
    "TaskListInvalidRequestError",
    "TaskListMultipleInProgressError",
    "TaskListNotFoundError",
    "TaskListSnapshot",
    "TaskListStatus",
    "coerce_private_context",
    "resolve_task_list_id",
    "task_list_entry_to_dict",
    "task_list_snapshot_to_dict",
]
