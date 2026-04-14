from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from .contracts import utc_now


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(slots=True)
class ManagedTask:
    task_id: str
    title: str
    status: TaskStatus = TaskStatus.PENDING
    description: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    stop_requested: bool = False


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, ManagedTask] = {}

    def create(
        self,
        task_id: str,
        title: str,
        *,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ManagedTask:
        task = ManagedTask(
            task_id=task_id,
            title=title,
            description=description,
            metadata=metadata or {},
        )
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> ManagedTask | None:
        return self._tasks.get(task_id)

    def update(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        result: Any = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ManagedTask:
        task = self._tasks[task_id]
        if status is not None:
            task.status = status
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        if metadata:
            task.metadata.update(metadata)
        task.updated_at = utc_now()
        return task

    def list(self) -> tuple[ManagedTask, ...]:
        return tuple(sorted(self._tasks.values(), key=lambda task: task.created_at))

    def stop(self, task_id: str) -> ManagedTask:
        task = self._tasks[task_id]
        task.stop_requested = True
        task.status = TaskStatus.STOPPED
        task.updated_at = utc_now()
        return task

