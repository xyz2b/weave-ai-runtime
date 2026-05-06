from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol

from ..contracts import utc_now
from ..definitions import IsolationMode, PermissionMode
from ..tasking import TaskStatus
from ..team_config import TeammateOrchestrationConfig

SCHEMA_VERSION = 1


def utc_isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


class TeammateLifecycleState(StrEnum):
    STARTING = "starting"
    IDLE = "idle"
    ACTIVE = "active"
    WAITING_PERMISSION = "waiting_permission"
    STOPPING = "stopping"
    STOPPED = "stopped"


class MailboxTerminalState(StrEnum):
    DONE = "done"
    FAILED = "failed"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class MailboxSender:
    type: str
    id: str

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | None) -> "MailboxSender":
        payload = dict(value or {})
        return cls(
            type=str(payload.get("type") or "leader"),
            id=str(payload.get("id") or "main"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "id": self.id}


@dataclass(frozen=True, slots=True)
class MailboxEnvelope:
    message_id: str
    team_id: str
    teammate_id: str
    kind: str
    sender: MailboxSender
    created_at: datetime = field(default_factory=utc_now)
    attempt: int = 1
    correlation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    payload_ref: str | None = None
    claim_id: str | None = None
    claimed_at: datetime | None = None
    claim_lease_ms: int | None = None
    last_heartbeat_at: datetime | None = None
    claimer_identity: str | None = None
    current_run_id: str | None = None
    retry_max_attempts: int | None = None
    retry_reason: str | None = None
    next_retry_after: datetime | None = None
    terminal_state: MailboxTerminalState | None = None
    terminal_reason: str | None = None
    completed_at: datetime | None = None
    schema_version: int = SCHEMA_VERSION

    def with_claim(
        self,
        *,
        claim_id: str,
        claimer_identity: str,
        claim_lease_ms: int,
        claimed_at: datetime | None = None,
    ) -> "MailboxEnvelope":
        timestamp = claimed_at or utc_now()
        return replace(
            self,
            claim_id=claim_id,
            claimed_at=timestamp,
            claim_lease_ms=claim_lease_ms,
            last_heartbeat_at=timestamp,
            claimer_identity=claimer_identity,
            terminal_state=None,
            terminal_reason=None,
            completed_at=None,
        )

    def with_heartbeat(self, timestamp: datetime | None = None) -> "MailboxEnvelope":
        return replace(self, last_heartbeat_at=timestamp or utc_now())

    def with_run_linkage(self, run_id: str) -> "MailboxEnvelope":
        return replace(self, current_run_id=run_id)

    def with_terminal(
        self,
        state: MailboxTerminalState,
        *,
        reason: str | None = None,
        completed_at: datetime | None = None,
    ) -> "MailboxEnvelope":
        return replace(
            self,
            terminal_state=state,
            terminal_reason=reason,
            completed_at=completed_at or utc_now(),
        )

    def for_retry(
        self,
        *,
        reason: str,
        next_retry_after: datetime | None = None,
    ) -> "MailboxEnvelope":
        return replace(
            self,
            attempt=self.attempt + 1,
            claim_id=None,
            claimed_at=None,
            claim_lease_ms=self.claim_lease_ms,
            last_heartbeat_at=None,
            claimer_identity=None,
            current_run_id=None,
            retry_reason=reason,
            next_retry_after=next_retry_after,
            terminal_state=None,
            terminal_reason=None,
            completed_at=None,
        )

    @property
    def claimed(self) -> bool:
        return self.claim_id is not None

    @property
    def claim_basename(self) -> str:
        if self.claim_id is None:
            raise ValueError("Envelope is not claimed")
        return f"{self.message_id}--{self.claim_id}.json"

    def retry_ready(self, now: datetime | None = None) -> bool:
        if self.next_retry_after is None:
            return True
        return self.next_retry_after <= (now or utc_now())

    def lease_expired(self, now: datetime | None = None) -> bool:
        if self.claimed_at is None or self.claim_lease_ms is None:
            return False
        reference = self.last_heartbeat_at or self.claimed_at
        return reference + timedelta(milliseconds=self.claim_lease_ms) <= (now or utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "message_id": self.message_id,
            "team_id": self.team_id,
            "teammate_id": self.teammate_id,
            "kind": self.kind,
            "sender": self.sender.to_dict(),
            "created_at": utc_isoformat(self.created_at),
            "attempt": self.attempt,
            "correlation_id": self.correlation_id,
            "payload": dict(self.payload),
            "payload_ref": self.payload_ref,
            "claim_id": self.claim_id,
            "claimed_at": utc_isoformat(self.claimed_at) if self.claimed_at is not None else None,
            "claim_lease_ms": self.claim_lease_ms,
            "last_heartbeat_at": (
                utc_isoformat(self.last_heartbeat_at)
                if self.last_heartbeat_at is not None
                else None
            ),
            "claimer_identity": self.claimer_identity,
            "current_run_id": self.current_run_id,
            "retry_max_attempts": self.retry_max_attempts,
            "retry_reason": self.retry_reason,
            "next_retry_after": (
                utc_isoformat(self.next_retry_after)
                if self.next_retry_after is not None
                else None
            ),
            "terminal_state": self.terminal_state.value if self.terminal_state is not None else None,
            "terminal_reason": self.terminal_reason,
            "completed_at": utc_isoformat(self.completed_at) if self.completed_at is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MailboxEnvelope":
        payload = dict(value)
        terminal_state = payload.get("terminal_state")
        return cls(
            schema_version=int(payload.get("schema_version") or SCHEMA_VERSION),
            message_id=str(payload.get("message_id") or ""),
            team_id=str(payload.get("team_id") or ""),
            teammate_id=str(payload.get("teammate_id") or ""),
            kind=str(payload.get("kind") or "work_item"),
            sender=MailboxSender.from_value(payload.get("sender")),
            created_at=parse_utc_timestamp(payload.get("created_at")) or utc_now(),
            attempt=int(payload.get("attempt") or 1),
            correlation_id=_coerce_optional_string(payload.get("correlation_id")),
            payload=_coerce_mapping(payload.get("payload")),
            payload_ref=_coerce_optional_string(payload.get("payload_ref")),
            claim_id=_coerce_optional_string(payload.get("claim_id")),
            claimed_at=parse_utc_timestamp(payload.get("claimed_at")),
            claim_lease_ms=_coerce_optional_int(payload.get("claim_lease_ms")),
            last_heartbeat_at=parse_utc_timestamp(payload.get("last_heartbeat_at")),
            claimer_identity=_coerce_optional_string(payload.get("claimer_identity")),
            current_run_id=_coerce_optional_string(payload.get("current_run_id")),
            retry_max_attempts=_coerce_optional_int(payload.get("retry_max_attempts")),
            retry_reason=_coerce_optional_string(payload.get("retry_reason")),
            next_retry_after=parse_utc_timestamp(payload.get("next_retry_after")),
            terminal_state=MailboxTerminalState(terminal_state) if terminal_state else None,
            terminal_reason=_coerce_optional_string(payload.get("terminal_reason")),
            completed_at=parse_utc_timestamp(payload.get("completed_at")),
        )


@dataclass(frozen=True, slots=True)
class TeammateStateSnapshot:
    team_id: str
    teammate_id: str
    state: TeammateLifecycleState
    updated_at: datetime = field(default_factory=utc_now)
    current_message_id: str | None = None
    current_run_id: str | None = None
    current_claim_id: str | None = None
    waiting_permission_id: str | None = None
    shutdown_workflow_id: str | None = None
    agent_name: str | None = None
    session_id: str | None = None
    working_directory: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    @property
    def current_work_attached(self) -> bool:
        return any(
            value is not None
            for value in (
                self.current_message_id,
                self.current_run_id,
                self.current_claim_id,
                self.waiting_permission_id,
            )
        )

    def with_registration(
        self,
        *,
        agent_name: str,
        session_id: str,
        working_directory: Path,
        metadata: Mapping[str, Any] | None = None,
    ) -> "TeammateStateSnapshot":
        return replace(
            self,
            agent_name=agent_name,
            session_id=session_id,
            working_directory=str(working_directory),
            metadata=dict(metadata or {}),
            updated_at=utc_now(),
        )

    def activate(
        self,
        *,
        message_id: str,
        run_id: str,
        claim_id: str,
    ) -> "TeammateStateSnapshot":
        return replace(
            self,
            state=TeammateLifecycleState.ACTIVE,
            current_message_id=message_id,
            current_run_id=run_id,
            current_claim_id=claim_id,
            waiting_permission_id=None,
            updated_at=utc_now(),
        )

    def waiting_permission(self, permission_id: str) -> "TeammateStateSnapshot":
        next_state = (
            self.state
            if self.state in {TeammateLifecycleState.STOPPING, TeammateLifecycleState.STOPPED}
            else TeammateLifecycleState.WAITING_PERMISSION
        )
        return replace(
            self,
            state=next_state,
            waiting_permission_id=permission_id,
            updated_at=utc_now(),
        )

    def resume_active(self) -> "TeammateStateSnapshot":
        next_state = (
            TeammateLifecycleState.STOPPING
            if self.shutdown_workflow_id is not None
            else TeammateLifecycleState.ACTIVE
        )
        return replace(
            self,
            state=next_state,
            waiting_permission_id=None,
            updated_at=utc_now(),
        )

    def stopping(self, workflow_id: str) -> "TeammateStateSnapshot":
        return replace(
            self,
            state=TeammateLifecycleState.STOPPING,
            shutdown_workflow_id=workflow_id,
            updated_at=utc_now(),
        )

    def stopped(self) -> "TeammateStateSnapshot":
        return replace(
            self,
            state=TeammateLifecycleState.STOPPED,
            current_message_id=None,
            current_run_id=None,
            current_claim_id=None,
            waiting_permission_id=None,
            updated_at=utc_now(),
        )

    def idle(self) -> "TeammateStateSnapshot":
        return replace(
            self,
            state=TeammateLifecycleState.IDLE,
            current_message_id=None,
            current_run_id=None,
            current_claim_id=None,
            waiting_permission_id=None,
            shutdown_workflow_id=None,
            updated_at=utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "team_id": self.team_id,
            "teammate_id": self.teammate_id,
            "state": self.state.value,
            "current_message_id": self.current_message_id,
            "current_run_id": self.current_run_id,
            "current_claim_id": self.current_claim_id,
            "waiting_permission_id": self.waiting_permission_id,
            "shutdown_workflow_id": self.shutdown_workflow_id,
            "updated_at": utc_isoformat(self.updated_at),
        }
        if self.agent_name is not None:
            payload["agent_name"] = self.agent_name
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if self.working_directory is not None:
            payload["working_directory"] = self.working_directory
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeammateStateSnapshot":
        payload = dict(value)
        metadata = payload.get("metadata")
        return cls(
            schema_version=int(payload.get("schema_version") or SCHEMA_VERSION),
            team_id=str(payload.get("team_id") or ""),
            teammate_id=str(payload.get("teammate_id") or ""),
            state=TeammateLifecycleState(str(payload.get("state") or TeammateLifecycleState.STARTING.value)),
            current_message_id=_coerce_optional_string(payload.get("current_message_id")),
            current_run_id=_coerce_optional_string(payload.get("current_run_id")),
            current_claim_id=_coerce_optional_string(payload.get("current_claim_id")),
            waiting_permission_id=_coerce_optional_string(payload.get("waiting_permission_id")),
            shutdown_workflow_id=_coerce_optional_string(payload.get("shutdown_workflow_id")),
            updated_at=parse_utc_timestamp(payload.get("updated_at")) or utc_now(),
            agent_name=_coerce_optional_string(payload.get("agent_name")),
            session_id=_coerce_optional_string(payload.get("session_id")),
            working_directory=_coerce_optional_string(payload.get("working_directory")),
            metadata=_coerce_mapping(metadata),
        )


@dataclass(frozen=True, slots=True)
class TeammateRegistration:
    team_id: str
    teammate_id: str
    agent_name: str
    session_id: str
    working_directory: Path
    claim_lease_ms: int
    retry_max_attempts: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.team_id, self.teammate_id)


@dataclass(frozen=True, slots=True)
class TeammateExecutionRequest:
    team_id: str
    teammate_id: str
    message_id: str
    claim_id: str
    agent_name: str
    prompt: str
    session_id: str
    cwd: Path
    requested_model_route: str | None = None
    requested_model: str | None = None
    requested_effort: Any = None
    requested_permission_mode: PermissionMode | None = None
    requested_isolation: IsolationMode | None = None
    max_turns: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TeammateProjection:
    team_id: str
    teammate_id: str
    lifecycle_state: TeammateLifecycleState
    task_id: str | None = None
    task_status: TaskStatus | None = None
    current_run_id: str | None = None
    current_message_id: str | None = None
    waiting_permission_id: str | None = None
    shutdown_workflow_id: str | None = None
    progress_status: str | None = None
    latest_notification: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TeammateRecoveryResult:
    team_id: str
    teammate_id: str
    message_id: str | None
    action: str
    reason: str | None = None


class SharedExecutionCore(Protocol):
    def prepare_execution(self, invocation: Any) -> tuple[Any, Any]: ...

    async def dispatch_prepared(
        self,
        invocation: Any,
        *,
        agent: Any,
        execution_spec: Any,
    ) -> Any: ...


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): inner for key, inner in value.items()}
    return {}


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "MailboxEnvelope",
    "MailboxSender",
    "MailboxTerminalState",
    "SCHEMA_VERSION",
    "SharedExecutionCore",
    "TeammateExecutionRequest",
    "TeammateLifecycleState",
    "TeammateOrchestrationConfig",
    "TeammateProjection",
    "TeammateRecoveryResult",
    "TeammateRegistration",
    "TeammateStateSnapshot",
    "parse_utc_timestamp",
    "utc_isoformat",
]
