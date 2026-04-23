from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable

from .contracts import utc_now
from .jobs import DefaultJobService, JobScopeFilter, JobStatus, task_status_to_job_status


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
    def __init__(self, *, job_service: DefaultJobService | None = None) -> None:
        self._job_service = job_service or DefaultJobService()
        self._stop_handlers: dict[str, Callable[[ManagedTask], Any]] = {}

    @property
    def job_service(self) -> DefaultJobService:
        return self._job_service

    def create(
        self,
        task_id: str,
        title: str,
        *,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ManagedTask:
        record = self._job_service.create_or_update_compat(
            task_id,
            title,
            description=description,
            metadata=metadata or {},
        )
        return _managed_task_from_job(record)

    def get(self, task_id: str) -> ManagedTask | None:
        record = self._job_service.get_sync(task_id)
        if record is None:
            return None
        return _managed_task_from_job(record)

    def update(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        result: Any = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ManagedTask:
        patch: dict[str, Any] = {"metadata": metadata}
        if status is not None:
            patch["status"] = task_status_to_job_status(status)
        if result is not None:
            patch["result"] = result
        if error is not None:
            patch["error"] = error
        record = self._job_service.update_compat(task_id, **patch)
        return _managed_task_from_job(record)

    def list(self) -> tuple[ManagedTask, ...]:
        return tuple(_managed_task_from_job(record) for record in self._job_service.list_sync())

    def list_visible(
        self,
        *,
        session_id: str | None = None,
        team_id: str | None = None,
    ) -> tuple[ManagedTask, ...]:
        return tuple(
            _managed_task_from_job(record)
            for record in self._job_service.list_sync(
                scope=JobScopeFilter(session_id=session_id, team_id=team_id)
            )
        )

    def register_stop_handler(self, task_id: str, handler: Callable[[ManagedTask], Any]) -> None:
        self._stop_handlers[task_id] = handler
        self._job_service.register_compat_stop_handler(
            task_id,
            lambda _record: handler(self.get(task_id) or _managed_task_from_job(_record)),
        )

    def unregister_stop_handler(self, task_id: str) -> None:
        self._stop_handlers.pop(task_id, None)
        self._job_service.unregister_compat_stop_handler(task_id)

    def stop_handler(self, task_id: str) -> Callable[[ManagedTask], Any] | None:
        return self._stop_handlers.get(task_id)

    def stop(self, task_id: str) -> ManagedTask:
        record = self._job_service.update_compat(
            task_id,
            status=JobStatus.STOPPED,
            stop_requested=True,
        )
        return _managed_task_from_job(record)

    async def stop_job(self, task_id: str) -> ManagedTask:
        record = await self._job_service.stop(task_id)
        return _managed_task_from_job(record)


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


def _managed_task_from_job(record: Any) -> ManagedTask:
    return ManagedTask(
        task_id=record.job_id,
        title=record.summary,
        status=TaskStatus(record.status.value),
        description=record.description,
        created_at=record.created_at,
        updated_at=record.updated_at,
        result=record.result,
        error=record.error,
        metadata=dict(record.metadata),
        stop_requested=record.stop_requested,
    )
