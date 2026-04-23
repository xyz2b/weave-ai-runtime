from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable

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
        self._stop_handlers: dict[str, Callable[[ManagedTask], Any]] = {}

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

    def list_visible(
        self,
        *,
        session_id: str | None = None,
        team_id: str | None = None,
    ) -> tuple[ManagedTask, ...]:
        return tuple(
            sorted(
                (
                    task
                    for task in self._tasks.values()
                    if _task_matches_scope(task, session_id=session_id, team_id=team_id)
                ),
                key=lambda task: task.created_at,
            )
        )

    def register_stop_handler(self, task_id: str, handler: Callable[[ManagedTask], Any]) -> None:
        self._stop_handlers[task_id] = handler

    def unregister_stop_handler(self, task_id: str) -> None:
        self._stop_handlers.pop(task_id, None)

    def stop_handler(self, task_id: str) -> Callable[[ManagedTask], Any] | None:
        return self._stop_handlers.get(task_id)

    def stop(self, task_id: str) -> ManagedTask:
        task = self._tasks[task_id]
        task.stop_requested = True
        task.status = TaskStatus.STOPPED
        task.updated_at = utc_now()
        return task

    async def stop_job(self, task_id: str) -> ManagedTask:
        task = self._tasks[task_id]
        task.stop_requested = True
        task.updated_at = utc_now()
        handler = self._stop_handlers.get(task_id)
        if handler is None:
            task.status = TaskStatus.STOPPED
            task.updated_at = utc_now()
            return task
        result = handler(task)
        if inspect.isawaitable(result):
            await result
        task = self._tasks[task_id]
        if task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.STOPPED
            task.updated_at = utc_now()
        return task


def _task_matches_scope(
    task: ManagedTask,
    *,
    session_id: str | None,
    team_id: str | None,
) -> bool:
    if session_id is None and team_id is None:
        return True
    if session_id is not None and str(task.metadata.get("session_id") or "") == session_id:
        return True
    if team_id is not None and str(task.metadata.get("team_id") or "") == team_id:
        return True
    return False
