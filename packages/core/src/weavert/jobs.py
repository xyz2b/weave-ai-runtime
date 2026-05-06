from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from .contracts import utc_now

if TYPE_CHECKING:
    from .runtime_kernel.kernel import RuntimeKernel
    from .runtime_services import RuntimeServices

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MISSING = object()


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"

    @property
    def terminal(self) -> bool:
        return self in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.STOPPED}


@dataclass(frozen=True, slots=True)
class JobControlCapabilities:
    stoppable: bool = False

    def serialize(self) -> dict[str, Any]:
        return {"stoppable": self.stoppable}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "JobControlCapabilities | None":
        if not isinstance(payload, Mapping):
            return None
        return cls(stoppable=_coerce_bool(payload.get("stoppable"), default=False))


@dataclass(frozen=True, slots=True)
class JobSidecarRef:
    kind: str
    ref: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", str(self.kind))
        object.__setattr__(self, "ref", str(self.ref))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def serialize(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref": self.ref,
            "metadata": _json_safe_mapping(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "JobSidecarRef":
        return cls(
            kind=str(payload.get("kind") or ""),
            ref=str(payload.get("ref") or ""),
            metadata=_coerce_mapping(payload.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class JobScopeFilter:
    session_id: str | None = None
    team_id: str | None = None
    submitted_by: str | None = None
    projection_kind: str | None = None

    def matches(self, record: "JobRecord") -> bool:
        visibility_match = True
        if self.session_id is not None or self.team_id is not None:
            visibility_match = False
            if self.session_id is not None and record.session_id == self.session_id:
                visibility_match = True
            if self.team_id is not None and record.team_id == self.team_id:
                visibility_match = True
        if not visibility_match:
            return False
        if self.submitted_by is not None and record.submitted_by != self.submitted_by:
            return False
        if self.projection_kind is not None and record.projection_kind != self.projection_kind:
            return False
        return True


@dataclass(frozen=True, slots=True)
class JobSubmitRequest:
    executor_kind: str
    summary: str
    input: dict[str, Any] = field(default_factory=dict)
    description: str | None = None
    session_id: str | None = None
    team_id: str | None = None
    submitted_by: str | None = None
    projection_kind: str | None = None
    parent_run_id: str | None = None
    parent_turn_id: str | None = None
    requested_job_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    capabilities: JobControlCapabilities | None = None
    sidecar_refs: tuple[JobSidecarRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "executor_kind", str(self.executor_kind))
        object.__setattr__(self, "summary", str(self.summary))
        object.__setattr__(self, "input", dict(self.input))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "sidecar_refs", tuple(self.sidecar_refs))


@dataclass(frozen=True, slots=True)
class JobExecutorContext:
    runtime_id: str
    services: "RuntimeServices"
    kernel: "RuntimeKernel | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class JobStartResult:
    status: JobStatus
    capabilities: JobControlCapabilities | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sidecar_refs: tuple[JobSidecarRef, ...] = ()
    result: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", JobStatus(self.status))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "sidecar_refs", tuple(self.sidecar_refs))


@dataclass(frozen=True, slots=True)
class JobStopResult:
    status: JobStatus
    stop_requested: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    sidecar_refs: tuple[JobSidecarRef, ...] = ()
    result: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", JobStatus(self.status))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "sidecar_refs", tuple(self.sidecar_refs))


@dataclass(frozen=True, slots=True)
class JobRecoveryResult:
    status: JobStatus
    capabilities: JobControlCapabilities | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sidecar_refs: tuple[JobSidecarRef, ...] = ()
    result: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", JobStatus(self.status))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "sidecar_refs", tuple(self.sidecar_refs))


@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: str
    executor_kind: str
    summary: str
    description: str | None = None
    status: JobStatus = JobStatus.PENDING
    capabilities: JobControlCapabilities | None = None
    stop_requested: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    session_id: str | None = None
    team_id: str | None = None
    submitted_by: str | None = None
    projection_kind: str | None = None
    parent_run_id: str | None = None
    parent_turn_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sidecar_refs: tuple[JobSidecarRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", str(self.job_id))
        object.__setattr__(self, "executor_kind", str(self.executor_kind))
        object.__setattr__(self, "summary", str(self.summary))
        object.__setattr__(self, "status", JobStatus(self.status))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "sidecar_refs", tuple(self.sidecar_refs))

    @property
    def terminal(self) -> bool:
        return self.status.terminal

    def serialize(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "executor_kind": self.executor_kind,
            "summary": self.summary,
            "description": self.description,
            "status": self.status.value,
            "capabilities": self.capabilities.serialize() if self.capabilities is not None else None,
            "stop_requested": self.stop_requested,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at is not None else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at is not None else None,
            "session_id": self.session_id,
            "team_id": self.team_id,
            "submitted_by": self.submitted_by,
            "projection_kind": self.projection_kind,
            "parent_run_id": self.parent_run_id,
            "parent_turn_id": self.parent_turn_id,
            "result": _json_safe_value(self.result),
            "error": self.error,
            "metadata": _json_safe_mapping(self.metadata),
            "sidecar_refs": [sidecar.serialize() for sidecar in self.sidecar_refs],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "JobRecord":
        return cls(
            job_id=str(payload.get("job_id") or uuid4().hex),
            executor_kind=str(payload.get("executor_kind") or "legacy"),
            summary=str(payload.get("summary") or ""),
            description=_coerce_optional_string(payload.get("description")),
            status=_coerce_job_status(payload.get("status")) or JobStatus.PENDING,
            capabilities=JobControlCapabilities.from_payload(payload.get("capabilities")),
            stop_requested=_coerce_bool(payload.get("stop_requested"), default=False),
            created_at=_coerce_datetime(payload.get("created_at")) or utc_now(),
            updated_at=_coerce_datetime(payload.get("updated_at")) or utc_now(),
            started_at=_coerce_datetime(payload.get("started_at")),
            ended_at=_coerce_datetime(payload.get("ended_at")),
            session_id=_coerce_optional_string(payload.get("session_id")),
            team_id=_coerce_optional_string(payload.get("team_id")),
            submitted_by=_coerce_optional_string(payload.get("submitted_by")),
            projection_kind=_coerce_optional_string(payload.get("projection_kind")),
            parent_run_id=_coerce_optional_string(payload.get("parent_run_id")),
            parent_turn_id=_coerce_optional_string(payload.get("parent_turn_id")),
            result=_coerce_optional_mapping(payload.get("result")),
            error=_coerce_optional_string(payload.get("error")),
            metadata=_coerce_mapping(payload.get("metadata")),
            sidecar_refs=tuple(
                JobSidecarRef.from_payload(item)
                for item in payload.get("sidecar_refs", ())
                if isinstance(item, Mapping)
            ),
        )


class JobStore(Protocol):
    def create(self, record: JobRecord) -> JobRecord: ...

    def upsert(self, record: JobRecord) -> JobRecord: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def list(self) -> tuple[JobRecord, ...]: ...


@dataclass(slots=True)
class InMemoryJobStore:
    _records: dict[str, JobRecord] = field(default_factory=dict)

    def create(self, record: JobRecord) -> JobRecord:
        if record.job_id in self._records:
            raise ValueError(f"Job '{record.job_id}' already exists")
        self._records[record.job_id] = record
        return record

    def upsert(self, record: JobRecord) -> JobRecord:
        self._records[record.job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        return self._records.get(job_id)

    def list(self) -> tuple[JobRecord, ...]:
        return tuple(sorted(self._records.values(), key=lambda record: (record.created_at, record.job_id)))


@dataclass(slots=True)
class FileJobStore:
    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, record: JobRecord) -> JobRecord:
        existing = self.get(record.job_id)
        if existing is not None:
            raise ValueError(f"Job '{record.job_id}' already exists")
        return self.upsert(record)

    def upsert(self, record: JobRecord) -> JobRecord:
        path = self._path_for(record.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record.serialize(), ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return record

    def get(self, job_id: str) -> JobRecord | None:
        path = self._path_for(job_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        record = JobRecord.from_payload(payload)
        if record.job_id != job_id:
            return None
        return record

    def list(self) -> tuple[JobRecord, ...]:
        records: list[JobRecord] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            records.append(JobRecord.from_payload(payload))
        return tuple(sorted(records, key=lambda record: (record.created_at, record.job_id)))

    def _path_for(self, job_id: str) -> Path:
        safe_prefix = _SAFE_FILENAME_RE.sub("_", job_id).strip("._") or "job"
        digest = hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:12]
        return self.root / f"{safe_prefix}--{digest}.json"


class JobExecutor(Protocol):
    async def submit(
        self,
        request: JobSubmitRequest,
        *,
        context: JobExecutorContext,
    ) -> JobStartResult: ...

    async def stop(
        self,
        record: JobRecord,
        *,
        context: JobExecutorContext,
    ) -> JobStopResult: ...

    async def recover(
        self,
        record: JobRecord,
        *,
        context: JobExecutorContext,
    ) -> JobRecoveryResult | None: ...


class JobExecutorFactory(Protocol):
    def __call__(
        self,
        executor_kind: str,
        binding: "JobExecutorBinding",
        kernel: "RuntimeKernel",
        services: "RuntimeServices",
    ) -> JobExecutor: ...


@dataclass(frozen=True, slots=True)
class JobExecutorBinding:
    executor: JobExecutor | None = None
    factory: JobExecutorFactory | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", dict(self.config))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if (self.executor is None) == (self.factory is None):
            raise ValueError("JobExecutorBinding requires exactly one of executor or factory")


@dataclass(slots=True)
class JobExecutorRegistry:
    _executors: dict[str, JobExecutor] = field(default_factory=dict)
    _builtins: set[str] = field(default_factory=set)

    def register(
        self,
        executor_kind: str,
        executor: JobExecutor,
        *,
        builtin: bool = False,
        override: bool = True,
    ) -> JobExecutor | None:
        normalized = _require_non_empty(executor_kind, "executor_kind")
        previous = self._executors.get(normalized)
        if previous is not None and not override:
            raise ValueError(f"Job executor '{normalized}' is already registered")
        self._executors[normalized] = executor
        if builtin:
            self._builtins.add(normalized)
        return previous

    def get(self, executor_kind: str) -> JobExecutor | None:
        return self._executors.get(str(executor_kind))

    def unregister(self, executor_kind: str) -> JobExecutor | None:
        normalized = str(executor_kind)
        self._builtins.discard(normalized)
        return self._executors.pop(normalized, None)

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._executors))

    def is_builtin(self, executor_kind: str) -> bool:
        return str(executor_kind) in self._builtins


class JobControlError(RuntimeError):
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


class JobExecutorResolutionError(JobControlError):
    def __init__(self, *, executor_kind: str) -> None:
        super().__init__(
            "executor_not_found",
            f"Job executor '{executor_kind}' is not registered",
            details={"executor_kind": executor_kind},
        )


class JobLifecycleError(JobControlError):
    def __init__(
        self,
        *,
        job_id: str,
        current_status: JobStatus,
        next_status: JobStatus,
        phase: str,
    ) -> None:
        super().__init__(
            "invalid_transition",
            (
                f"Job '{job_id}' cannot transition from '{current_status.value}' "
                f"to '{next_status.value}' during {phase}"
            ),
            details={
                "job_id": job_id,
                "current_status": current_status.value,
                "next_status": next_status.value,
                "phase": phase,
            },
        )


class JobStopNotFoundError(JobControlError):
    def __init__(self, *, job_id: str) -> None:
        super().__init__(
            "not_found",
            f"Job '{job_id}' was not found",
            details={"job_id": job_id},
        )


class JobNotRunningError(JobControlError):
    def __init__(self, *, job_id: str, status: JobStatus) -> None:
        super().__init__(
            "not_running",
            f"Job '{job_id}' is not currently running",
            details={"job_id": job_id, "status": status.value},
        )


class JobNotStoppableError(JobControlError):
    def __init__(self, *, job_id: str) -> None:
        super().__init__(
            "not_stoppable",
            f"Job '{job_id}' is not stoppable",
            details={"job_id": job_id},
        )


JobWatcher = Callable[[tuple[JobRecord, ...]], Any]
CompatStopHandler = Callable[[JobRecord], Any]


@dataclass(slots=True)
class DefaultJobService:
    store: JobStore = field(default_factory=InMemoryJobStore)
    executor_registry: JobExecutorRegistry = field(default_factory=JobExecutorRegistry)
    runtime_id: str = "default"
    services: "RuntimeServices | None" = None
    kernel: "RuntimeKernel | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _watchers: dict[str, tuple[JobScopeFilter | None, JobWatcher, asyncio.AbstractEventLoop]] = field(
        default_factory=dict,
        init=False,
    )
    _compat_stop_handlers: dict[str, CompatStopHandler] = field(default_factory=dict, init=False)
    _lock: RLock = field(default_factory=RLock, init=False)

    def bind_runtime(
        self,
        *,
        runtime_id: str,
        services: "RuntimeServices",
        kernel: "RuntimeKernel | None" = None,
    ) -> None:
        self.runtime_id = str(runtime_id)
        self.services = services
        self.kernel = kernel

    def executor_context(
        self,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> JobExecutorContext:
        if self.services is None:
            raise RuntimeError("Job service is not bound to runtime services")
        return JobExecutorContext(
            runtime_id=self.runtime_id,
            services=self.services,
            kernel=self.kernel,
            metadata=dict(self.metadata) | dict(metadata or {}),
        )

    def get_sync(
        self,
        job_id: str,
        *,
        scope: JobScopeFilter | None = None,
    ) -> JobRecord | None:
        with self._lock:
            record = self.store.get(str(job_id))
        if record is None:
            return None
        if scope is not None and not scope.matches(record):
            return None
        return record

    def list_sync(
        self,
        *,
        scope: JobScopeFilter | None = None,
    ) -> tuple[JobRecord, ...]:
        with self._lock:
            records = self.store.list()
        if scope is None:
            return records
        return tuple(record for record in records if scope.matches(record))

    def upsert_record(
        self,
        record: JobRecord,
        *,
        notify: bool = True,
    ) -> JobRecord:
        with self._lock:
            saved = self.store.upsert(record)
        if notify:
            self._schedule_watch_notifications()
        return saved

    def create_or_update_compat(
        self,
        job_id: str,
        summary: str,
        *,
        description: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> JobRecord:
        existing = self.get_sync(job_id)
        mutation_time = utc_now()
        normalized_metadata = dict(metadata or {})
        capabilities = JobControlCapabilities(stoppable=self.compat_stop_handler(job_id) is not None)
        base = JobRecord(
            job_id=job_id,
            executor_kind=_compat_executor_kind(normalized_metadata),
            summary=summary,
            description=description,
            capabilities=capabilities,
            created_at=existing.created_at if existing is not None else mutation_time,
            updated_at=mutation_time,
            started_at=existing.started_at if existing is not None else None,
            ended_at=existing.ended_at if existing is not None else None,
            session_id=_coerce_optional_string(normalized_metadata.get("session_id")),
            team_id=_coerce_optional_string(normalized_metadata.get("team_id")),
            submitted_by=_coerce_optional_string(
                normalized_metadata.get("submitted_by") or normalized_metadata.get("agent")
            ),
            projection_kind=_coerce_optional_string(
                normalized_metadata.get("projection_kind") or normalized_metadata.get("kind")
            ),
            parent_run_id=_coerce_optional_string(normalized_metadata.get("run_id")),
            parent_turn_id=_coerce_optional_string(normalized_metadata.get("turn_id")),
            result=existing.result if existing is not None else None,
            error=existing.error if existing is not None else None,
            metadata=normalized_metadata,
            sidecar_refs=_compat_sidecar_refs(existing, normalized_metadata),
        )
        return self.upsert_record(base)

    def update_compat(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        description: str | object = _MISSING,
        result: Mapping[str, Any] | None | object = _MISSING,
        error: str | None | object = _MISSING,
        metadata: Mapping[str, Any] | None = None,
        stop_requested: bool | object = _MISSING,
    ) -> JobRecord:
        current = self.get_sync(job_id)
        if current is None:
            raise KeyError(job_id)
        next_status = current.status if status is None else validate_job_transition(
            current.status,
            JobStatus(status),
            phase="compat",
            job_id=current.job_id,
        )
        mutation_time = utc_now()
        merged_metadata = dict(current.metadata)
        if metadata:
            merged_metadata.update(metadata)
        started_at = current.started_at
        ended_at = current.ended_at
        if next_status in {JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.STOPPED}:
            started_at = started_at or mutation_time
        if next_status.terminal:
            ended_at = mutation_time
        updated = replace(
            current,
            executor_kind=_compat_executor_kind(merged_metadata, current=current),
            summary=current.summary,
            description=current.description if description is _MISSING else _coerce_optional_string(description),
            status=next_status,
            capabilities=JobControlCapabilities(stoppable=self.compat_stop_handler(job_id) is not None),
            stop_requested=current.stop_requested if stop_requested is _MISSING else bool(stop_requested),
            updated_at=mutation_time,
            started_at=started_at,
            ended_at=ended_at,
            session_id=_coerce_optional_string(merged_metadata.get("session_id")) or current.session_id,
            team_id=_coerce_optional_string(merged_metadata.get("team_id")) or current.team_id,
            submitted_by=(
                _coerce_optional_string(merged_metadata.get("submitted_by") or merged_metadata.get("agent"))
                or current.submitted_by
            ),
            projection_kind=(
                _coerce_optional_string(merged_metadata.get("projection_kind") or merged_metadata.get("kind"))
                or current.projection_kind
            ),
            parent_run_id=_coerce_optional_string(merged_metadata.get("run_id")) or current.parent_run_id,
            parent_turn_id=_coerce_optional_string(merged_metadata.get("turn_id")) or current.parent_turn_id,
            result=current.result if result is _MISSING else _coerce_optional_mapping(result),
            error=current.error if error is _MISSING else _coerce_optional_string(error),
            metadata=merged_metadata,
            sidecar_refs=_compat_sidecar_refs(current, merged_metadata),
        )
        return self.upsert_record(updated)

    def register_compat_stop_handler(self, job_id: str, handler: CompatStopHandler) -> None:
        self._compat_stop_handlers[str(job_id)] = handler
        record = self.get_sync(str(job_id))
        if record is not None and not _is_stoppable(record):
            self.upsert_record(replace(record, capabilities=JobControlCapabilities(stoppable=True)))

    def unregister_compat_stop_handler(self, job_id: str) -> None:
        self._compat_stop_handlers.pop(str(job_id), None)

    def compat_stop_handler(self, job_id: str) -> CompatStopHandler | None:
        return self._compat_stop_handlers.get(str(job_id))

    async def submit(
        self,
        request: JobSubmitRequest,
        *,
        context: JobExecutorContext | None = None,
    ) -> JobRecord:
        executor = self.executor_registry.get(request.executor_kind)
        if executor is None:
            raise JobExecutorResolutionError(executor_kind=request.executor_kind)
        executor_context = context or self.executor_context()
        mutation_time = utc_now()
        job_id = request.requested_job_id or uuid4().hex
        pending = JobRecord(
            job_id=job_id,
            executor_kind=request.executor_kind,
            summary=request.summary,
            description=request.description,
            status=JobStatus.PENDING,
            capabilities=request.capabilities,
            created_at=mutation_time,
            updated_at=mutation_time,
            session_id=request.session_id,
            team_id=request.team_id,
            submitted_by=request.submitted_by,
            projection_kind=request.projection_kind,
            parent_run_id=request.parent_run_id,
            parent_turn_id=request.parent_turn_id,
            metadata=request.metadata,
            sidecar_refs=request.sidecar_refs,
        )
        self.upsert_record(pending, notify=False)
        try:
            start_result = await executor.submit(
                replace(request, requested_job_id=job_id),
                context=executor_context,
            )
        except Exception as exc:
            self.apply_start_result(
                job_id,
                JobStartResult(
                    status=JobStatus.FAILED,
                    capabilities=pending.capabilities,
                    metadata={"submit_failed": True},
                    error=str(exc),
                ),
            )
            raise
        return self.apply_start_result(job_id, start_result)

    async def get(
        self,
        job_id: str,
        *,
        scope: JobScopeFilter | None = None,
    ) -> JobRecord | None:
        return self.get_sync(job_id, scope=scope)

    async def list(
        self,
        *,
        scope: JobScopeFilter | None = None,
    ) -> tuple[JobRecord, ...]:
        return self.list_sync(scope=scope)

    async def watch(
        self,
        *,
        callback: JobWatcher,
        scope: JobScopeFilter | None = None,
    ) -> Callable[[], None]:
        watcher_id = uuid4().hex
        loop = asyncio.get_running_loop()
        with self._lock:
            self._watchers[watcher_id] = (scope, callback, loop)
        try:
            maybe_result = callback(self.list_sync(scope=scope))
            if inspect.isawaitable(maybe_result):
                await maybe_result
        except Exception:
            with self._lock:
                self._watchers.pop(watcher_id, None)
            raise

        def unsubscribe() -> None:
            with self._lock:
                self._watchers.pop(watcher_id, None)

        return unsubscribe

    async def stop(
        self,
        job_id: str,
        *,
        scope: JobScopeFilter | None = None,
    ) -> JobRecord:
        record = self.get_sync(job_id, scope=scope)
        if record is None:
            raise JobStopNotFoundError(job_id=job_id)
        if record.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
            raise JobNotRunningError(job_id=job_id, status=record.status)
        if not _is_stoppable(record):
            raise JobNotStoppableError(job_id=job_id)

        executor = self.executor_registry.get(record.executor_kind)
        compat_handler = self._compat_stop_handlers.get(job_id)
        if executor is None and compat_handler is None:
            if _is_stoppable(record):
                record = self.upsert_record(
                    replace(record, capabilities=JobControlCapabilities(stoppable=False))
                )
            raise JobNotStoppableError(job_id=job_id)
        if executor is not None:
            stop_result = await executor.stop(record, context=self.executor_context())
            return self.apply_stop_result(job_id, stop_result)

        accepted = self.apply_stop_result(
            job_id,
            JobStopResult(
                status=record.status if record.status is JobStatus.RUNNING else JobStatus.STOPPED,
                stop_requested=True,
            ),
        )
        if compat_handler is not None:
            maybe_result = compat_handler(accepted)
            if inspect.isawaitable(maybe_result):
                await maybe_result
            refreshed = self.get_sync(job_id)
            if refreshed is not None and refreshed.status is JobStatus.RUNNING:
                return self.apply_stop_result(job_id, JobStopResult(status=JobStatus.STOPPED))
            return refreshed or accepted
        if accepted.status is JobStatus.RUNNING:
            return self.apply_stop_result(job_id, JobStopResult(status=JobStatus.STOPPED))
        return accepted

    async def recover_inflight(self) -> tuple[JobRecord, ...]:
        recovered: list[JobRecord] = []
        for record in self.list_sync():
            if record.status is not JobStatus.RUNNING:
                continue
            executor = self.executor_registry.get(record.executor_kind)
            if executor is None:
                continue
            result = await executor.recover(record, context=self.executor_context(metadata={"recovery": True}))
            if result is None:
                continue
            recovered.append(self.apply_recovery_result(record.job_id, result))
        return tuple(recovered)

    def apply_start_result(self, job_id: str, result: JobStartResult) -> JobRecord:
        current = self.get_sync(job_id)
        if current is None:
            raise KeyError(job_id)
        next_status = validate_job_transition(
            current.status,
            result.status,
            phase="start",
            job_id=job_id,
        )
        updated = _apply_result_patch(
            current,
            status=next_status,
            capabilities=result.capabilities,
            metadata_patch=result.metadata,
            sidecar_refs=result.sidecar_refs or current.sidecar_refs,
            result_payload=result.result,
            error=result.error,
            stop_requested=current.stop_requested,
        )
        return self.upsert_record(updated)

    def apply_stop_result(self, job_id: str, result: JobStopResult) -> JobRecord:
        current = self.get_sync(job_id)
        if current is None:
            raise KeyError(job_id)
        next_status = validate_job_transition(
            current.status,
            result.status,
            phase="stop",
            job_id=job_id,
        )
        updated = _apply_result_patch(
            current,
            status=next_status,
            metadata_patch=result.metadata,
            sidecar_refs=result.sidecar_refs or current.sidecar_refs,
            result_payload=result.result,
            error=result.error,
            stop_requested=result.stop_requested,
        )
        return self.upsert_record(updated)

    def apply_recovery_result(self, job_id: str, result: JobRecoveryResult) -> JobRecord:
        current = self.get_sync(job_id)
        if current is None:
            raise KeyError(job_id)
        next_status = validate_job_transition(
            current.status,
            result.status,
            phase="recovery",
            job_id=job_id,
        )
        updated = _apply_result_patch(
            current,
            status=next_status,
            capabilities=result.capabilities,
            metadata_patch=result.metadata,
            sidecar_refs=result.sidecar_refs or current.sidecar_refs,
            result_payload=result.result,
            error=result.error,
            stop_requested=current.stop_requested,
        )
        return self.upsert_record(updated)

    def _schedule_watch_notifications(self) -> None:
        with self._lock:
            watchers = tuple(self._watchers.items())
            records = self.store.list()
        for watcher_id, (scope, _callback, loop) in watchers:
            if loop.is_closed():
                with self._lock:
                    self._watchers.pop(watcher_id, None)
                continue
            snapshot = records if scope is None else tuple(record for record in records if scope.matches(record))
            try:
                loop.call_soon_threadsafe(self._dispatch_watcher_notification, watcher_id, snapshot)
            except RuntimeError:
                with self._lock:
                    self._watchers.pop(watcher_id, None)

    def _dispatch_watcher_notification(
        self,
        watcher_id: str,
        snapshot: tuple[JobRecord, ...],
    ) -> None:
        with self._lock:
            registration = self._watchers.get(watcher_id)
        if registration is None:
            return
        _scope, callback, _loop = registration
        try:
            maybe_result = callback(snapshot)
            if inspect.isawaitable(maybe_result):
                asyncio.create_task(self._await_watcher_callback(watcher_id, maybe_result))
        except Exception:
            with self._lock:
                self._watchers.pop(watcher_id, None)

    async def _await_watcher_callback(self, watcher_id: str, pending: Any) -> None:
        try:
            await pending
        except Exception:
            with self._lock:
                self._watchers.pop(watcher_id, None)


def validate_job_transition(
    current_status: JobStatus,
    next_status: JobStatus,
    *,
    phase: str,
    job_id: str,
) -> JobStatus:
    current = JobStatus(current_status)
    proposed = JobStatus(next_status)
    if current == proposed:
        return proposed
    if current.terminal:
        raise JobLifecycleError(
            job_id=job_id,
            current_status=current,
            next_status=proposed,
            phase=phase,
        )
    allowed = {
        "start": {
            JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED},
        },
        "stop": {
            JobStatus.PENDING: {JobStatus.STOPPED},
            JobStatus.RUNNING: {JobStatus.RUNNING, JobStatus.STOPPED},
        },
        "recovery": {
            JobStatus.RUNNING: {
                JobStatus.RUNNING,
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.STOPPED,
            },
        },
        "compat": {
            JobStatus.PENDING: {
                JobStatus.PENDING,
                JobStatus.RUNNING,
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.STOPPED,
            },
            JobStatus.RUNNING: {
                JobStatus.RUNNING,
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.STOPPED,
            },
        },
    }
    permitted = allowed.get(phase, {}).get(current, set())
    if proposed not in permitted:
        raise JobLifecycleError(
            job_id=job_id,
            current_status=current,
            next_status=proposed,
            phase=phase,
        )
    return proposed


def task_status_to_job_status(status: Any) -> JobStatus:
    normalized = getattr(status, "value", status)
    return JobStatus(str(normalized))


def job_record_to_payload(record: JobRecord) -> dict[str, Any]:
    return {
        "job_id": record.job_id,
        "executor_kind": record.executor_kind,
        "summary": record.summary,
        "description": record.description,
        "status": record.status.value,
        "control": {
            "stoppable": _is_stoppable(record),
            "stop_requested": record.stop_requested,
        },
        "timestamps": {
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "started_at": record.started_at.isoformat() if record.started_at is not None else None,
            "ended_at": record.ended_at.isoformat() if record.ended_at is not None else None,
        },
        "visibility": {
            "session_id": record.session_id,
            "team_id": record.team_id,
            "submitted_by": record.submitted_by,
            "projection_kind": record.projection_kind,
        },
        "linkage": {
            "parent_run_id": record.parent_run_id,
            "parent_turn_id": record.parent_turn_id,
        },
        "result": _json_safe_value(record.result),
        "error": record.error,
        "metadata": _json_safe_mapping(record.metadata),
        "sidecars": [sidecar.serialize() for sidecar in record.sidecar_refs],
    }


def _apply_result_patch(
    record: JobRecord,
    *,
    status: JobStatus,
    capabilities: JobControlCapabilities | None | object = _MISSING,
    metadata_patch: Mapping[str, Any] | None = None,
    sidecar_refs: Sequence[JobSidecarRef] | object = _MISSING,
    result_payload: Mapping[str, Any] | None | object = _MISSING,
    error: str | None | object = _MISSING,
    stop_requested: bool | object = _MISSING,
) -> JobRecord:
    mutation_time = utc_now()
    started_at = record.started_at
    ended_at = record.ended_at
    if status in {JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.STOPPED}:
        started_at = started_at or mutation_time
    if status.terminal:
        ended_at = mutation_time
    merged_metadata = dict(record.metadata)
    if metadata_patch:
        merged_metadata.update(metadata_patch)
    return replace(
        record,
        status=status,
        capabilities=record.capabilities if capabilities is _MISSING else capabilities,
        stop_requested=record.stop_requested if stop_requested is _MISSING else bool(stop_requested),
        updated_at=mutation_time,
        started_at=started_at,
        ended_at=ended_at,
        result=record.result if result_payload is _MISSING else _coerce_optional_mapping(result_payload),
        error=record.error if error is _MISSING else _coerce_optional_string(error),
        metadata=merged_metadata,
        sidecar_refs=record.sidecar_refs if sidecar_refs is _MISSING else tuple(sidecar_refs),
    )


def _compat_executor_kind(
    metadata: Mapping[str, Any],
    *,
    current: JobRecord | None = None,
) -> str:
    explicit = _coerce_optional_string(metadata.get("executor_kind"))
    if explicit is not None:
        return explicit
    kind = _coerce_optional_string(metadata.get("kind"))
    if kind == "background_agent":
        return "agent"
    if kind in {"background_memory_extraction", "background_memory_consolidation"}:
        return "memory"
    if kind == "teammate_projection":
        return "teammate_projection"
    return current.executor_kind if current is not None else "legacy"


def _compat_sidecar_refs(
    current: JobRecord | None,
    metadata: Mapping[str, Any],
) -> tuple[JobSidecarRef, ...]:
    explicit = metadata.get("sidecars")
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        refs = tuple(
            JobSidecarRef.from_payload(item)
            for item in explicit
            if isinstance(item, Mapping)
        )
        if refs:
            return refs
    existing = tuple(current.sidecar_refs) if current is not None else ()
    kind = _coerce_optional_string(metadata.get("kind"))
    run_id = _coerce_optional_string(metadata.get("run_id"))
    team_id = _coerce_optional_string(metadata.get("team_id"))
    teammate_id = _coerce_optional_string(metadata.get("teammate_id"))
    message_id = _coerce_optional_string(metadata.get("message_id"))
    if kind == "background_agent" and run_id is not None:
        return (
            JobSidecarRef(
                kind="agent_run",
                ref=run_id,
                metadata={"agent": _coerce_optional_string(metadata.get("agent"))},
            ),
        )
    if kind == "teammate_projection" and team_id and teammate_id and message_id:
        return (
            JobSidecarRef(
                kind="teammate_projection",
                ref=f"{team_id}/{teammate_id}/{message_id}",
                metadata={"claim_id": _coerce_optional_string(metadata.get("claim_id"))},
            ),
        )
    return existing


def _is_stoppable(record: JobRecord) -> bool:
    return bool(record.capabilities.stoppable) if record.capabilities is not None else False


def _json_safe_mapping(mapping: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(mapping, Mapping):
        return {}
    return {str(key): _json_safe_value(value) for key, value in mapping.items()}


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe_value(item) for item in value]
    return str(value)


def _coerce_optional_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    return None


def _coerce_mapping(value: Any) -> dict[str, Any]:
    return _coerce_optional_mapping(value) or {}


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_job_status(value: Any) -> JobStatus | None:
    normalized = _coerce_optional_string(getattr(value, "value", value))
    if normalized is None:
        return None
    return JobStatus(normalized)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _require_non_empty(value: Any, label: str) -> str:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        raise ValueError(f"{label} must be a non-empty string")
    return normalized


__all__ = [
    "CompatStopHandler",
    "DefaultJobService",
    "FileJobStore",
    "InMemoryJobStore",
    "JobControlCapabilities",
    "JobControlError",
    "JobExecutor",
    "JobExecutorBinding",
    "JobExecutorContext",
    "JobExecutorFactory",
    "JobExecutorRegistry",
    "JobExecutorResolutionError",
    "JobLifecycleError",
    "JobNotRunningError",
    "JobNotStoppableError",
    "JobRecord",
    "JobRecoveryResult",
    "JobScopeFilter",
    "JobSidecarRef",
    "JobStartResult",
    "JobStatus",
    "JobStopNotFoundError",
    "JobStopResult",
    "JobStore",
    "JobSubmitRequest",
    "JobWatcher",
    "job_record_to_payload",
    "task_status_to_job_status",
    "validate_job_transition",
]
