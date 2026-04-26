from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol
from uuid import uuid4

from .contracts import utc_now
from .definitions import PermissionBehavior
from .permissions import PermissionOutcome
from .team_control_plane import TeamEvent, TeamRole

if TYPE_CHECKING:
    from .runtime_services import RuntimeServices
    from .team_control_plane import RuntimeTeamControlPlane, TeamActor, TeamRecord
    from .team_message_bus import RuntimeTeamMessageBus

SCHEMA_VERSION = 1


class TeamWorkflowKind(StrEnum):
    PERMISSION = "permission"
    SHUTDOWN = "shutdown"


class TeamWorkflowStatus(StrEnum):
    PENDING = "pending"
    WAITING_HOST = "waiting_host"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    FORCED_CLOSED = "forced_closed"


TERMINAL_WORKFLOW_STATUSES = frozenset(
    {
        TeamWorkflowStatus.COMPLETED,
        TeamWorkflowStatus.REJECTED,
        TeamWorkflowStatus.TIMED_OUT,
        TeamWorkflowStatus.FORCED_CLOSED,
    }
)


class TeamWorkflowActorKind(StrEnum):
    LEADER = "leader"
    TEAMMATE = "teammate"
    HOST = "host"
    RUNTIME = "runtime"


class TeamWorkflowProtocolKind(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"


class TeamWorkflowError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details)


@dataclass(frozen=True, slots=True)
class TeamWorkflowTransition:
    transition_id: str
    action: str
    actor_kind: TeamWorkflowActorKind
    actor_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "action": self.action,
            "actor_kind": self.actor_kind.value,
            "actor_id": self.actor_id,
            "payload": _coerce_mapping(self.payload),
            "occurred_at": _utc_isoformat(self.occurred_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamWorkflowTransition":
        payload = dict(value)
        return cls(
            transition_id=str(payload.get("transition_id") or uuid4().hex),
            action=str(payload.get("action") or ""),
            actor_kind=TeamWorkflowActorKind(
                str(payload.get("actor_kind") or TeamWorkflowActorKind.RUNTIME.value)
            ),
            actor_id=_coerce_optional_string(payload.get("actor_id")),
            payload=_coerce_mapping(payload.get("payload")),
            occurred_at=_parse_utc_timestamp(payload.get("occurred_at")) or utc_now(),
        )


@dataclass(frozen=True, slots=True)
class TeamWorkflowRecord:
    workflow_id: str
    team_id: str
    workflow_kind: TeamWorkflowKind
    requester_member_id: str
    requester_name: str | None = None
    responder_member_id: str | None = None
    responder_name: str | None = None
    leader_session_id: str | None = None
    status: TeamWorkflowStatus = TeamWorkflowStatus.PENDING
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] | None = None
    transition_history: tuple[TeamWorkflowTransition, ...] = ()
    message_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    deadline_at: datetime | None = None
    terminal_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "transition_history", tuple(self.transition_history))
        object.__setattr__(self, "message_ids", tuple(self.message_ids))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "request_payload", dict(self.request_payload))
        if self.response_payload is not None:
            object.__setattr__(self, "response_payload", dict(self.response_payload))

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_WORKFLOW_STATUSES

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return allowed_workflow_actions(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "team_id": self.team_id,
            "workflow_kind": self.workflow_kind.value,
            "requester_member_id": self.requester_member_id,
            "requester_name": self.requester_name,
            "responder_member_id": self.responder_member_id,
            "responder_name": self.responder_name,
            "leader_session_id": self.leader_session_id,
            "status": self.status.value,
            "request_payload": _coerce_mapping(self.request_payload),
            "response_payload": None if self.response_payload is None else _coerce_mapping(self.response_payload),
            "transition_history": [transition.to_dict() for transition in self.transition_history],
            "message_ids": list(self.message_ids),
            "created_at": _utc_isoformat(self.created_at),
            "updated_at": _utc_isoformat(self.updated_at),
            "deadline_at": _utc_isoformat(self.deadline_at) if self.deadline_at is not None else None,
            "terminal_at": _utc_isoformat(self.terminal_at) if self.terminal_at is not None else None,
            "metadata": _coerce_mapping(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamWorkflowRecord":
        payload = dict(value)
        history = payload.get("transition_history")
        message_ids = payload.get("message_ids")
        return cls(
            schema_version=int(payload.get("schema_version") or SCHEMA_VERSION),
            workflow_id=str(payload.get("workflow_id") or ""),
            team_id=str(payload.get("team_id") or ""),
            workflow_kind=TeamWorkflowKind(
                str(payload.get("workflow_kind") or TeamWorkflowKind.PERMISSION.value)
            ),
            requester_member_id=str(payload.get("requester_member_id") or ""),
            requester_name=_coerce_optional_string(payload.get("requester_name")),
            responder_member_id=_coerce_optional_string(payload.get("responder_member_id")),
            responder_name=_coerce_optional_string(payload.get("responder_name")),
            leader_session_id=_coerce_optional_string(payload.get("leader_session_id")),
            status=TeamWorkflowStatus(str(payload.get("status") or TeamWorkflowStatus.PENDING.value)),
            request_payload=_coerce_mapping(payload.get("request_payload")),
            response_payload=(
                _coerce_mapping(payload.get("response_payload"))
                if isinstance(payload.get("response_payload"), Mapping)
                else None
            ),
            transition_history=tuple(
                TeamWorkflowTransition.from_dict(item)
                for item in history
                if isinstance(item, Mapping)
            )
            if isinstance(history, list)
            else (),
            message_ids=tuple(str(item) for item in message_ids if isinstance(item, str))
            if isinstance(message_ids, list)
            else (),
            created_at=_parse_utc_timestamp(payload.get("created_at")) or utc_now(),
            updated_at=_parse_utc_timestamp(payload.get("updated_at")) or utc_now(),
            deadline_at=_parse_utc_timestamp(payload.get("deadline_at")),
            terminal_at=_parse_utc_timestamp(payload.get("terminal_at")),
            metadata=_coerce_mapping(payload.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class TeamWorkflowRequestProtocol:
    workflow_id: str
    workflow_kind: TeamWorkflowKind
    requester_member_id: str
    requester_name: str | None = None
    responder_member_id: str | None = None
    responder_name: str | None = None
    allowed_actions: tuple[str, ...] = ()
    summary: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_actions", tuple(self.allowed_actions))
        object.__setattr__(self, "payload", dict(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_kind": TeamWorkflowProtocolKind.REQUEST.value,
            "workflow_id": self.workflow_id,
            "workflow_kind": self.workflow_kind.value,
            "requester_member_id": self.requester_member_id,
            "requester_name": self.requester_name,
            "responder_member_id": self.responder_member_id,
            "responder_name": self.responder_name,
            "allowed_actions": list(self.allowed_actions),
            "summary": self.summary,
            "payload": _coerce_mapping(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamWorkflowRequestProtocol":
        payload = dict(value)
        return cls(
            workflow_id=str(payload.get("workflow_id") or ""),
            workflow_kind=TeamWorkflowKind(
                str(payload.get("workflow_kind") or TeamWorkflowKind.PERMISSION.value)
            ),
            requester_member_id=str(payload.get("requester_member_id") or ""),
            requester_name=_coerce_optional_string(payload.get("requester_name")),
            responder_member_id=_coerce_optional_string(payload.get("responder_member_id")),
            responder_name=_coerce_optional_string(payload.get("responder_name")),
            allowed_actions=tuple(
                str(item).strip() for item in payload.get("allowed_actions", ()) if str(item).strip()
            ),
            summary=_coerce_optional_string(payload.get("summary")),
            payload=_coerce_mapping(payload.get("payload")),
        )


@dataclass(frozen=True, slots=True)
class TeamWorkflowResponseProtocol:
    workflow_id: str
    workflow_kind: TeamWorkflowKind
    status: TeamWorkflowStatus
    response_action: str
    actor_kind: TeamWorkflowActorKind
    actor_id: str | None = None
    allowed_actions: tuple[str, ...] = ()
    summary: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_actions", tuple(self.allowed_actions))
        object.__setattr__(self, "payload", dict(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_kind": TeamWorkflowProtocolKind.RESPONSE.value,
            "workflow_id": self.workflow_id,
            "workflow_kind": self.workflow_kind.value,
            "status": self.status.value,
            "response_action": self.response_action,
            "actor_kind": self.actor_kind.value,
            "actor_id": self.actor_id,
            "allowed_actions": list(self.allowed_actions),
            "summary": self.summary,
            "payload": _coerce_mapping(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamWorkflowResponseProtocol":
        payload = dict(value)
        return cls(
            workflow_id=str(payload.get("workflow_id") or ""),
            workflow_kind=TeamWorkflowKind(
                str(payload.get("workflow_kind") or TeamWorkflowKind.PERMISSION.value)
            ),
            status=TeamWorkflowStatus(str(payload.get("status") or TeamWorkflowStatus.PENDING.value)),
            response_action=str(payload.get("response_action") or ""),
            actor_kind=TeamWorkflowActorKind(
                str(payload.get("actor_kind") or TeamWorkflowActorKind.RUNTIME.value)
            ),
            actor_id=_coerce_optional_string(payload.get("actor_id")),
            allowed_actions=tuple(
                str(item).strip() for item in payload.get("allowed_actions", ()) if str(item).strip()
            ),
            summary=_coerce_optional_string(payload.get("summary")),
            payload=_coerce_mapping(payload.get("payload")),
        )


def allowed_workflow_actions(record: TeamWorkflowRecord) -> tuple[str, ...]:
    if record.terminal:
        return ()
    if record.workflow_kind is TeamWorkflowKind.PERMISSION:
        if record.status is TeamWorkflowStatus.PENDING:
            return ("approve", "reject")
        return ()
    if record.status is TeamWorkflowStatus.PENDING:
        return ("acknowledge", "complete")
    if record.status is TeamWorkflowStatus.ACKNOWLEDGED:
        return ("complete",)
    return ()


def build_workflow_request_protocol(record: TeamWorkflowRecord) -> TeamWorkflowRequestProtocol:
    return TeamWorkflowRequestProtocol(
        workflow_id=record.workflow_id,
        workflow_kind=record.workflow_kind,
        requester_member_id=record.requester_member_id,
        requester_name=record.requester_name,
        responder_member_id=record.responder_member_id,
        responder_name=record.responder_name,
        allowed_actions=record.allowed_actions,
        summary=workflow_request_summary(record),
        payload=record.request_payload,
    )


def build_workflow_response_protocol(
    record: TeamWorkflowRecord,
    *,
    action: str,
    actor_kind: TeamWorkflowActorKind,
    actor_id: str | None,
    payload: Mapping[str, Any] | None = None,
) -> TeamWorkflowResponseProtocol:
    return TeamWorkflowResponseProtocol(
        workflow_id=record.workflow_id,
        workflow_kind=record.workflow_kind,
        status=record.status,
        response_action=action,
        actor_kind=actor_kind,
        actor_id=actor_id,
        allowed_actions=record.allowed_actions,
        summary=workflow_response_summary(record, action=action),
        payload=_coerce_mapping(payload),
    )


def parse_workflow_request_protocol(value: Mapping[str, Any] | None) -> TeamWorkflowRequestProtocol | None:
    if not isinstance(value, Mapping):
        return None
    if str(value.get("protocol_kind") or TeamWorkflowProtocolKind.REQUEST.value) != TeamWorkflowProtocolKind.REQUEST.value:
        return None
    return TeamWorkflowRequestProtocol.from_dict(value)


def parse_workflow_response_protocol(value: Mapping[str, Any] | None) -> TeamWorkflowResponseProtocol | None:
    if not isinstance(value, Mapping):
        return None
    if str(value.get("protocol_kind") or "") != TeamWorkflowProtocolKind.RESPONSE.value:
        return None
    return TeamWorkflowResponseProtocol.from_dict(value)


def workflow_request_summary(record: TeamWorkflowRecord) -> str:
    requester_name = record.requester_name or record.requester_member_id
    if record.workflow_kind is TeamWorkflowKind.PERMISSION:
        permission_name = str(record.request_payload.get("permission_name") or "a privileged action")
        permission_message = _coerce_optional_string(record.request_payload.get("permission_message"))
        if permission_message:
            return (
                f"Permission workflow '{record.workflow_id}': teammate '{requester_name}' "
                f"requests permission for {permission_name}: {permission_message}"
            )
        return (
            f"Permission workflow '{record.workflow_id}': teammate '{requester_name}' "
            f"requests permission for {permission_name}"
        )
    target_name = (
        _coerce_optional_string(record.request_payload.get("member_name"))
        or _coerce_optional_string(record.request_payload.get("member_id"))
        or (record.responder_name or record.responder_member_id)
        or requester_name
    )
    reason = _coerce_optional_string(record.request_payload.get("reason")) or "graceful shutdown requested"
    return f"Shutdown workflow '{record.workflow_id}': stop teammate '{target_name}' because {reason}"


def workflow_response_summary(record: TeamWorkflowRecord, *, action: str) -> str:
    if record.workflow_kind is TeamWorkflowKind.PERMISSION:
        if record.status is TeamWorkflowStatus.WAITING_HOST:
            return f"Permission workflow '{record.workflow_id}' approved and waiting for host resolution"
        if record.status is TeamWorkflowStatus.COMPLETED:
            return f"Permission workflow '{record.workflow_id}' completed"
        if record.status is TeamWorkflowStatus.REJECTED:
            return f"Permission workflow '{record.workflow_id}' rejected"
        if record.status is TeamWorkflowStatus.TIMED_OUT:
            return f"Permission workflow '{record.workflow_id}' timed out"
        return f"Permission workflow '{record.workflow_id}' updated with '{action}'"
    if record.status is TeamWorkflowStatus.ACKNOWLEDGED:
        return f"Shutdown workflow '{record.workflow_id}' acknowledged"
    if record.status is TeamWorkflowStatus.COMPLETED:
        return f"Shutdown workflow '{record.workflow_id}' completed"
    if record.status is TeamWorkflowStatus.FORCED_CLOSED:
        return f"Shutdown workflow '{record.workflow_id}' forced closed"
    if record.status is TeamWorkflowStatus.TIMED_OUT:
        return f"Shutdown workflow '{record.workflow_id}' timed out"
    return f"Shutdown workflow '{record.workflow_id}' updated with '{action}'"


def workflow_priority(kind: TeamWorkflowKind) -> int:
    if kind is TeamWorkflowKind.SHUTDOWN:
        return 100
    return 80


def workflow_record_to_payload(record: TeamWorkflowRecord) -> dict[str, Any]:
    return {
        "workflow_id": record.workflow_id,
        "team_id": record.team_id,
        "workflow_kind": record.workflow_kind.value,
        "requester_member_id": record.requester_member_id,
        "requester_name": record.requester_name,
        "responder_member_id": record.responder_member_id,
        "responder_name": record.responder_name,
        "leader_session_id": record.leader_session_id,
        "status": record.status.value,
        "allowed_actions": list(record.allowed_actions),
        "request_payload": dict(record.request_payload),
        "response_payload": None if record.response_payload is None else dict(record.response_payload),
        "message_ids": list(record.message_ids),
        "created_at": _utc_isoformat(record.created_at),
        "updated_at": _utc_isoformat(record.updated_at),
        "deadline_at": _utc_isoformat(record.deadline_at) if record.deadline_at is not None else None,
        "terminal_at": _utc_isoformat(record.terminal_at) if record.terminal_at is not None else None,
        "terminal": record.terminal,
        "metadata": dict(record.metadata),
    }


class TeamWorkflowStore(Protocol):
    def create(self, record: TeamWorkflowRecord) -> TeamWorkflowRecord: ...

    def save(self, record: TeamWorkflowRecord) -> TeamWorkflowRecord: ...

    def load(self, workflow_id: str) -> TeamWorkflowRecord | None: ...

    def list_all(self) -> tuple[TeamWorkflowRecord, ...]: ...

    def list_pending(self) -> tuple[TeamWorkflowRecord, ...]: ...

    def list_terminal(self) -> tuple[TeamWorkflowRecord, ...]: ...

    def list_for_team(
        self,
        team_id: str,
        *,
        pending_only: bool | None = None,
    ) -> tuple[TeamWorkflowRecord, ...]: ...

    def list_for_responder(
        self,
        responder_member_id: str,
        *,
        pending_only: bool | None = None,
    ) -> tuple[TeamWorkflowRecord, ...]: ...

    def delete(self, workflow_id: str) -> None: ...


class InMemoryTeamWorkflowStore:
    def __init__(self) -> None:
        self._records: dict[str, TeamWorkflowRecord] = {}
        self._team_ids: dict[str, set[str]] = {}
        self._responder_ids: dict[str, set[str]] = {}
        self._pending_ids: set[str] = set()
        self._terminal_ids: set[str] = set()

    def create(self, record: TeamWorkflowRecord) -> TeamWorkflowRecord:
        if record.workflow_id in self._records:
            raise FileExistsError(record.workflow_id)
        self._records[record.workflow_id] = record
        self._update_indices(record, previous=None)
        return record

    def save(self, record: TeamWorkflowRecord) -> TeamWorkflowRecord:
        previous = self._records.get(record.workflow_id)
        self._records[record.workflow_id] = record
        self._update_indices(record, previous=previous)
        return record

    def load(self, workflow_id: str) -> TeamWorkflowRecord | None:
        return self._records.get(str(workflow_id))

    def list_all(self) -> tuple[TeamWorkflowRecord, ...]:
        return self._sort_records(self._records.values())

    def list_pending(self) -> tuple[TeamWorkflowRecord, ...]:
        return self._records_from_ids(self._pending_ids)

    def list_terminal(self) -> tuple[TeamWorkflowRecord, ...]:
        return self._records_from_ids(self._terminal_ids)

    def list_for_team(
        self,
        team_id: str,
        *,
        pending_only: bool | None = None,
    ) -> tuple[TeamWorkflowRecord, ...]:
        return self._filter_pending(
            self._records_from_ids(self._team_ids.get(str(team_id), set())),
            pending_only=pending_only,
        )

    def list_for_responder(
        self,
        responder_member_id: str,
        *,
        pending_only: bool | None = None,
    ) -> tuple[TeamWorkflowRecord, ...]:
        return self._filter_pending(
            self._records_from_ids(self._responder_ids.get(str(responder_member_id), set())),
            pending_only=pending_only,
        )

    def delete(self, workflow_id: str) -> None:
        previous = self._records.pop(str(workflow_id), None)
        if previous is None:
            return
        self._update_indices(None, previous=previous)

    def _records_from_ids(self, ids: set[str]) -> tuple[TeamWorkflowRecord, ...]:
        return self._sort_records(
            record
            for workflow_id in sorted(ids)
            if (record := self._records.get(workflow_id)) is not None
        )

    def _sort_records(self, records) -> tuple[TeamWorkflowRecord, ...]:
        return tuple(sorted(records, key=lambda item: (item.created_at, item.workflow_id)))

    def _filter_pending(
        self,
        records: tuple[TeamWorkflowRecord, ...],
        *,
        pending_only: bool | None,
    ) -> tuple[TeamWorkflowRecord, ...]:
        if pending_only is None:
            return records
        if pending_only:
            return tuple(record for record in records if not record.terminal)
        return tuple(record for record in records if record.terminal)

    def _update_indices(
        self,
        record: TeamWorkflowRecord | None,
        *,
        previous: TeamWorkflowRecord | None,
    ) -> None:
        if previous is not None:
            self._remove_team_index(previous.team_id, previous.workflow_id)
            if previous.responder_member_id:
                self._remove_responder_index(previous.responder_member_id, previous.workflow_id)
            self._pending_ids.discard(previous.workflow_id)
            self._terminal_ids.discard(previous.workflow_id)
        if record is None:
            return
        self._team_ids.setdefault(record.team_id, set()).add(record.workflow_id)
        if record.responder_member_id:
            self._responder_ids.setdefault(record.responder_member_id, set()).add(record.workflow_id)
        if record.terminal:
            self._terminal_ids.add(record.workflow_id)
        else:
            self._pending_ids.add(record.workflow_id)

    def _remove_team_index(self, team_id: str, workflow_id: str) -> None:
        ids = self._team_ids.get(team_id)
        if ids is None:
            return
        ids.discard(workflow_id)
        if not ids:
            self._team_ids.pop(team_id, None)

    def _remove_responder_index(self, responder_member_id: str, workflow_id: str) -> None:
        ids = self._responder_ids.get(responder_member_id)
        if ids is None:
            return
        ids.discard(workflow_id)
        if not ids:
            self._responder_ids.pop(responder_member_id, None)


class FileBackedTeamWorkflowStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def create(self, record: TeamWorkflowRecord) -> TeamWorkflowRecord:
        path = self._workflow_path(record.workflow_id)
        if path.exists():
            raise FileExistsError(path)
        _atomic_write_json(path, record.to_dict())
        self._update_indices(record, previous=None)
        return record

    def save(self, record: TeamWorkflowRecord) -> TeamWorkflowRecord:
        previous = self.load(record.workflow_id)
        _atomic_write_json(self._workflow_path(record.workflow_id), record.to_dict(), replace_existing=True)
        self._update_indices(record, previous=previous)
        return record

    def load(self, workflow_id: str) -> TeamWorkflowRecord | None:
        path = self._workflow_path(workflow_id)
        if not path.exists():
            return None
        return TeamWorkflowRecord.from_dict(_read_json(path))

    def list_all(self) -> tuple[TeamWorkflowRecord, ...]:
        workflows_root = self._root / "workflows"
        if not workflows_root.exists():
            return ()
        records = [
            TeamWorkflowRecord.from_dict(_read_json(path))
            for path in sorted(workflows_root.glob("*.json"))
        ]
        records.sort(key=lambda item: (item.created_at, item.workflow_id))
        return tuple(records)

    def list_pending(self) -> tuple[TeamWorkflowRecord, ...]:
        return self._records_from_ids(self._load_index(self._pending_index_path()))

    def list_terminal(self) -> tuple[TeamWorkflowRecord, ...]:
        return self._records_from_ids(self._load_index(self._terminal_index_path()))

    def list_for_team(
        self,
        team_id: str,
        *,
        pending_only: bool | None = None,
    ) -> tuple[TeamWorkflowRecord, ...]:
        ids = self._load_index(self._team_index_path(team_id))
        return self._filter_pending(self._records_from_ids(ids), pending_only=pending_only)

    def list_for_responder(
        self,
        responder_member_id: str,
        *,
        pending_only: bool | None = None,
    ) -> tuple[TeamWorkflowRecord, ...]:
        ids = self._load_index(self._responder_index_path(responder_member_id))
        return self._filter_pending(self._records_from_ids(ids), pending_only=pending_only)

    def delete(self, workflow_id: str) -> None:
        record = self.load(workflow_id)
        if record is None:
            return
        path = self._workflow_path(workflow_id)
        path.unlink(missing_ok=True)
        self._update_indices(None, previous=record)

    def _records_from_ids(self, ids: set[str]) -> tuple[TeamWorkflowRecord, ...]:
        records: list[TeamWorkflowRecord] = []
        for workflow_id in sorted(ids):
            record = self.load(workflow_id)
            if record is not None:
                records.append(record)
        records.sort(key=lambda item: (item.created_at, item.workflow_id))
        return tuple(records)

    def _filter_pending(
        self,
        records: tuple[TeamWorkflowRecord, ...],
        *,
        pending_only: bool | None,
    ) -> tuple[TeamWorkflowRecord, ...]:
        if pending_only is None:
            return records
        if pending_only:
            return tuple(record for record in records if not record.terminal)
        return tuple(record for record in records if record.terminal)

    def _update_indices(
        self,
        record: TeamWorkflowRecord | None,
        *,
        previous: TeamWorkflowRecord | None,
    ) -> None:
        if previous is not None:
            self._write_index(
                self._team_index_path(previous.team_id),
                self._load_index(self._team_index_path(previous.team_id)) - {previous.workflow_id},
            )
            if previous.responder_member_id:
                responder_path = self._responder_index_path(previous.responder_member_id)
                self._write_index(responder_path, self._load_index(responder_path) - {previous.workflow_id})
            pending_path = self._pending_index_path()
            terminal_path = self._terminal_index_path()
            if previous.terminal:
                self._write_index(terminal_path, self._load_index(terminal_path) - {previous.workflow_id})
            else:
                self._write_index(pending_path, self._load_index(pending_path) - {previous.workflow_id})
        if record is None:
            return
        self._write_index(
            self._team_index_path(record.team_id),
            self._load_index(self._team_index_path(record.team_id)) | {record.workflow_id},
        )
        if record.responder_member_id:
            responder_path = self._responder_index_path(record.responder_member_id)
            self._write_index(responder_path, self._load_index(responder_path) | {record.workflow_id})
        if record.terminal:
            self._write_index(
                self._terminal_index_path(),
                self._load_index(self._terminal_index_path()) | {record.workflow_id},
            )
        else:
            self._write_index(
                self._pending_index_path(),
                self._load_index(self._pending_index_path()) | {record.workflow_id},
            )

    def _workflow_path(self, workflow_id: str) -> Path:
        return self._root / "workflows" / f"{workflow_id}.json"

    def _team_index_path(self, team_id: str) -> Path:
        return self._root / "indexes" / "teams" / f"{team_id}.json"

    def _responder_index_path(self, responder_member_id: str) -> Path:
        return self._root / "indexes" / "responders" / f"{responder_member_id}.json"

    def _pending_index_path(self) -> Path:
        return self._root / "indexes" / "pending.json"

    def _terminal_index_path(self) -> Path:
        return self._root / "indexes" / "terminal.json"

    def _load_index(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        payload = _read_json(path)
        ids = payload.get("workflow_ids")
        if not isinstance(ids, list):
            return set()
        return {str(item).strip() for item in ids if str(item).strip()}

    def _write_index(self, path: Path, ids: set[str]) -> None:
        _atomic_write_json(path, {"workflow_ids": sorted(ids)}, replace_existing=True)


class RuntimeTeamWorkflowService:
    def __init__(
        self,
        *,
        store: TeamWorkflowStore,
        control_plane: RuntimeTeamControlPlane,
        runtime_services: RuntimeServices,
        permission_timeout: timedelta = timedelta(minutes=5),
        shutdown_timeout: timedelta = timedelta(seconds=30),
    ) -> None:
        self._store = store
        self._control_plane = control_plane
        self._runtime_services = runtime_services
        self._permission_timeout = permission_timeout
        self._shutdown_timeout = shutdown_timeout
        self._message_bus: RuntimeTeamMessageBus | None = None
        self._workflow_locks: dict[str, asyncio.Lock] = {}
        self._deadline_tasks: dict[str, asyncio.Task[None]] = {}
        self._terminal_waiters: dict[str, list[asyncio.Future[TeamWorkflowRecord]]] = {}

    @property
    def store(self) -> TeamWorkflowStore:
        return self._store

    def bind_message_bus(self, message_bus: RuntimeTeamMessageBus) -> None:
        self._message_bus = message_bus

    async def recover_pending(self) -> tuple[TeamWorkflowRecord, ...]:
        recovered: list[TeamWorkflowRecord] = []
        for record in self._store.list_pending():
            current, expired = self._refresh_record_deadline(record)
            recovered.append(current)
            if expired:
                await self._emit_workflow_event(
                    "team.workflow.timed_out"
                    if current.status is TeamWorkflowStatus.TIMED_OUT
                    else "team.workflow.forced_closed",
                    current,
                    payload={"deadline_expired": True},
                )
                await self._emit_workflow_response(
                    current,
                    action="deadline_expired",
                    actor_kind=TeamWorkflowActorKind.RUNTIME,
                    actor_id="deadline",
                    payload=current.response_payload,
                )
                self._resolve_waiters(current)
                continue
            self._schedule_deadline(current)
        return tuple(recovered)

    def get(self, workflow_id: str) -> TeamWorkflowRecord | None:
        record = self._store.load(workflow_id)
        if record is None:
            return None
        refreshed, _ = self._refresh_record_deadline(record)
        self._schedule_deadline(refreshed)
        return refreshed

    def is_pending(self, workflow_id: str) -> bool:
        record = self.get(workflow_id)
        return bool(record is not None and not record.terminal)

    async def wait_for_permission_resolution(self, workflow_id: str) -> TeamWorkflowRecord:
        while True:
            record = self._require_record(workflow_id)
            if record.workflow_kind is not TeamWorkflowKind.PERMISSION:
                raise TeamWorkflowError(
                    "invalid_workflow_kind",
                    f"Workflow '{workflow_id}' is not a permission workflow",
                    workflow_id=workflow_id,
                )
            if record.status is not TeamWorkflowStatus.PENDING:
                return record
            if record.deadline_at is not None and record.deadline_at <= utc_now():
                return record
            await asyncio.sleep(0.01)

    def list_workflows(
        self,
        *,
        team_id: str | None = None,
        responder_member_id: str | None = None,
        pending_only: bool | None = None,
    ) -> tuple[TeamWorkflowRecord, ...]:
        if team_id is not None:
            return self._tracked_records(
                self._store.list_for_team(team_id, pending_only=pending_only),
                pending_only=pending_only,
            )
        if responder_member_id is not None:
            return self._tracked_records(
                self._store.list_for_responder(responder_member_id, pending_only=pending_only),
                pending_only=pending_only,
            )
        if pending_only is True:
            return self._tracked_records(self._store.list_pending(), pending_only=True)
        if pending_only is False:
            return self._tracked_records(self._store.list_terminal(), pending_only=False)
        return self._tracked_records(self._store.list_all(), pending_only=None)

    async def create_permission_workflow(
        self,
        *,
        team: TeamRecord,
        requester_member_id: str,
        requester_name: str,
        responder_member_id: str,
        responder_name: str,
        request_payload: Mapping[str, Any],
        timeout: timedelta | None = None,
    ) -> TeamWorkflowRecord:
        record = TeamWorkflowRecord(
            workflow_id=uuid4().hex,
            team_id=team.team_id,
            workflow_kind=TeamWorkflowKind.PERMISSION,
            requester_member_id=requester_member_id,
            requester_name=requester_name,
            responder_member_id=responder_member_id,
            responder_name=responder_name,
            leader_session_id=team.leader_session_id,
            status=TeamWorkflowStatus.PENDING,
            request_payload=_coerce_mapping(request_payload),
            deadline_at=utc_now() + (timeout or self._permission_timeout),
            metadata={"response_channel": "leader"},
        )
        self._store.create(record)
        self._schedule_deadline(record)
        await self._emit_workflow_event("team.workflow.created", record, payload={"phase": "request"})
        record = await self._emit_workflow_request(record)
        return record

    async def create_shutdown_workflow(
        self,
        *,
        team: TeamRecord,
        requester_member_id: str,
        requester_name: str,
        responder_member_id: str,
        responder_name: str,
        request_payload: Mapping[str, Any],
        timeout: timedelta | None = None,
    ) -> TeamWorkflowRecord:
        record = TeamWorkflowRecord(
            workflow_id=uuid4().hex,
            team_id=team.team_id,
            workflow_kind=TeamWorkflowKind.SHUTDOWN,
            requester_member_id=requester_member_id,
            requester_name=requester_name,
            responder_member_id=responder_member_id,
            responder_name=responder_name,
            leader_session_id=team.leader_session_id,
            status=TeamWorkflowStatus.PENDING,
            request_payload=_coerce_mapping(request_payload),
            deadline_at=utc_now() + (timeout or self._shutdown_timeout),
            metadata={"response_channel": "runtime"},
        )
        self._store.create(record)
        self._schedule_deadline(record)
        await self._emit_workflow_event("team.workflow.created", record, payload={"phase": "request"})
        record = await self._emit_workflow_request(record)
        if team.leader_member_id != record.responder_member_id:
            record = await self._emit_workflow_request(
                record,
                recipient_member_id=team.leader_member_id,
            )
        return record

    async def wait_for_terminal(self, workflow_id: str) -> TeamWorkflowRecord:
        record = self._store.load(workflow_id)
        if record is None:
            raise TeamWorkflowError("not_found", f"Workflow '{workflow_id}' was not found", workflow_id=workflow_id)
        if record.terminal:
            return record
        future: asyncio.Future[TeamWorkflowRecord] = asyncio.get_running_loop().create_future()
        self._terminal_waiters.setdefault(workflow_id, []).append(future)
        try:
            resolved = await future
            if resolved is not None:
                return resolved
            refreshed = self._store.load(workflow_id)
            if refreshed is None:
                raise TeamWorkflowError("not_found", f"Workflow '{workflow_id}' was not found", workflow_id=workflow_id)
            return refreshed
        finally:
            waiters = self._terminal_waiters.get(workflow_id)
            if waiters is not None:
                self._terminal_waiters[workflow_id] = [item for item in waiters if item is not future]
                if not self._terminal_waiters[workflow_id]:
                    self._terminal_waiters.pop(workflow_id, None)

    async def respond_model(
        self,
        *,
        session_id: str,
        extensions: Mapping[str, Any],
        workflow_id: str,
        action: str,
        payload: Mapping[str, Any] | None = None,
    ) -> TeamWorkflowRecord:
        actor = self._control_plane.resolve_actor(session_id=session_id, extensions=extensions)
        if actor.team is None or actor.member is None:
            raise TeamWorkflowError(
                "invalid_team_state",
                "The caller does not have an active runtime team for this workflow",
                session_id=session_id,
            )
        return await self._respond(
            workflow_id=workflow_id,
            action=action,
            actor_kind=_actor_kind(actor),
            actor_id=actor.member.member_id,
            actor=actor,
            payload=payload,
        )

    async def respond_host(
        self,
        *,
        workflow_id: str,
        action: str,
        host_name: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> TeamWorkflowRecord:
        return await self._respond(
            workflow_id=workflow_id,
            action=action,
            actor_kind=TeamWorkflowActorKind.HOST,
            actor_id=host_name or getattr(self._runtime_services.host, "name", None),
            actor=None,
            payload=payload,
        )

    async def record_permission_host_outcome(
        self,
        workflow_id: str,
        outcome: PermissionOutcome,
    ) -> TeamWorkflowRecord:
        async with self._workflow_lock(workflow_id):
            record = self._require_record(workflow_id)
            if record.workflow_kind is not TeamWorkflowKind.PERMISSION:
                raise TeamWorkflowError(
                    "invalid_workflow_kind",
                    f"Workflow '{workflow_id}' is not a permission workflow",
                    workflow_id=workflow_id,
                )
            if record.terminal:
                return record
            if record.status is not TeamWorkflowStatus.WAITING_HOST:
                raise TeamWorkflowError(
                    "invalid_workflow_state",
                    "Permission host results require a leader-approved workflow",
                    workflow_id=workflow_id,
                    status=record.status.value,
                )
            action = "host_allow" if outcome.behavior is PermissionBehavior.ALLOW else "host_deny"
            terminal_status = (
                TeamWorkflowStatus.COMPLETED
                if outcome.behavior is PermissionBehavior.ALLOW
                else TeamWorkflowStatus.REJECTED
            )
            updated = self._mutate_record(
                record,
                status=terminal_status,
                action=action,
                actor_kind=TeamWorkflowActorKind.HOST,
                actor_id=getattr(self._runtime_services.host, "name", None),
                payload={
                    "behavior": outcome.behavior.value,
                    "message": outcome.message,
                    "source": outcome.source,
                    "details": dict(outcome.details),
                },
                response_payload={
                    **(record.response_payload or {}),
                    "host_behavior": outcome.behavior.value,
                    "host_message": outcome.message,
                    "host_source": outcome.source,
                    "host_details": dict(outcome.details),
                },
                terminal=terminal_status,
            )
            self._store.save(updated)
            self._cancel_deadline(updated.workflow_id)
            await self._emit_workflow_event(
                "team.workflow.completed"
                if updated.status is TeamWorkflowStatus.COMPLETED
                else "team.workflow.rejected",
                updated,
                payload={"action": action},
            )
            await self._emit_workflow_response(updated, action=action, actor_kind=TeamWorkflowActorKind.HOST, actor_id=getattr(self._runtime_services.host, "name", None), payload=updated.response_payload)
            self._resolve_waiters(updated)
            return updated

    async def acknowledge_shutdown(
        self,
        workflow_id: str,
        *,
        actor_kind: TeamWorkflowActorKind = TeamWorkflowActorKind.RUNTIME,
        actor_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> TeamWorkflowRecord:
        return await self._internal_respond(
            workflow_id=workflow_id,
            action="acknowledge",
            actor_kind=actor_kind,
            actor_id=actor_id,
            payload=payload,
        )

    async def complete_shutdown(
        self,
        workflow_id: str,
        *,
        actor_kind: TeamWorkflowActorKind = TeamWorkflowActorKind.RUNTIME,
        actor_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> TeamWorkflowRecord:
        return await self._internal_respond(
            workflow_id=workflow_id,
            action="complete",
            actor_kind=actor_kind,
            actor_id=actor_id,
            payload=payload,
        )

    async def force_close_shutdown(
        self,
        workflow_id: str,
        *,
        reason: str = "deadline_expired",
        actor_id: str | None = None,
    ) -> TeamWorkflowRecord:
        async with self._workflow_lock(workflow_id):
            record = self._require_record(workflow_id)
            if record.workflow_kind is not TeamWorkflowKind.SHUTDOWN:
                raise TeamWorkflowError(
                    "invalid_workflow_kind",
                    f"Workflow '{workflow_id}' is not a shutdown workflow",
                    workflow_id=workflow_id,
                )
            if record.terminal:
                return record
            updated = self._mutate_record(
                record,
                status=TeamWorkflowStatus.FORCED_CLOSED,
                action="force_close",
                actor_kind=TeamWorkflowActorKind.RUNTIME,
                actor_id=actor_id,
                payload={"reason": reason},
                response_payload={"forced_close_reason": reason},
                terminal=TeamWorkflowStatus.FORCED_CLOSED,
            )
            self._store.save(updated)
            self._cancel_deadline(updated.workflow_id)
            await self._emit_workflow_event(
                "team.workflow.forced_closed",
                updated,
                payload={"reason": reason},
            )
            await self._emit_workflow_response(
                updated,
                action="force_close",
                actor_kind=TeamWorkflowActorKind.RUNTIME,
                actor_id=actor_id,
                payload=updated.response_payload,
            )
            self._resolve_waiters(updated)
            return updated

    async def _internal_respond(
        self,
        *,
        workflow_id: str,
        action: str,
        actor_kind: TeamWorkflowActorKind,
        actor_id: str | None,
        payload: Mapping[str, Any] | None,
    ) -> TeamWorkflowRecord:
        return await self._respond(
            workflow_id=workflow_id,
            action=action,
            actor_kind=actor_kind,
            actor_id=actor_id,
            actor=None,
            payload=payload,
            bypass_authority=True,
        )

    async def _respond(
        self,
        *,
        workflow_id: str,
        action: str,
        actor_kind: TeamWorkflowActorKind,
        actor_id: str | None,
        actor: TeamActor | None,
        payload: Mapping[str, Any] | None,
        bypass_authority: bool = False,
    ) -> TeamWorkflowRecord:
        normalized_action = str(action).strip().lower()
        async with self._workflow_lock(workflow_id):
            record = self._require_record(workflow_id)
            if record.terminal:
                raise TeamWorkflowError(
                    "terminal_workflow",
                    f"Workflow '{workflow_id}' is already terminal",
                    workflow_id=workflow_id,
                    status=record.status.value,
                )
            if normalized_action not in record.allowed_actions:
                raise TeamWorkflowError(
                    "invalid_action",
                    f"Action '{normalized_action}' is not allowed for workflow '{workflow_id}'",
                    workflow_id=workflow_id,
                    allowed_actions=list(record.allowed_actions),
                    status=record.status.value,
                )
            if not bypass_authority:
                self._validate_authority(record, action=normalized_action, actor=actor, actor_kind=actor_kind)

            updated = self._apply_action(
                record,
                action=normalized_action,
                actor_kind=actor_kind,
                actor_id=actor_id,
                payload=payload,
            )
            self._store.save(updated)
            self._schedule_deadline(updated)
            event_type = self._event_type_for_transition(updated)
            await self._emit_workflow_event(event_type, updated, payload={"action": normalized_action})
            await self._emit_workflow_response(
                updated,
                action=normalized_action,
                actor_kind=actor_kind,
                actor_id=actor_id,
                payload=payload,
            )
            if updated.terminal:
                self._cancel_deadline(updated.workflow_id)
                self._resolve_waiters(updated)
            return updated

    def _apply_action(
        self,
        record: TeamWorkflowRecord,
        *,
        action: str,
        actor_kind: TeamWorkflowActorKind,
        actor_id: str | None,
        payload: Mapping[str, Any] | None,
    ) -> TeamWorkflowRecord:
        response_payload = dict(record.response_payload or {})
        terminal_status: TeamWorkflowStatus | None = None
        status = record.status

        if record.workflow_kind is TeamWorkflowKind.PERMISSION:
            if action == "approve":
                status = TeamWorkflowStatus.WAITING_HOST
                response_payload.update({"leader_decision": "approve", **_coerce_mapping(payload)})
            elif action == "reject":
                status = TeamWorkflowStatus.REJECTED
                terminal_status = status
                response_payload.update({"leader_decision": "reject", **_coerce_mapping(payload)})
        elif action == "acknowledge":
            status = TeamWorkflowStatus.ACKNOWLEDGED
            response_payload.update(_coerce_mapping(payload))
        elif action == "complete":
            status = TeamWorkflowStatus.COMPLETED
            terminal_status = status
            response_payload.update(_coerce_mapping(payload))

        return self._mutate_record(
            record,
            status=status,
            action=action,
            actor_kind=actor_kind,
            actor_id=actor_id,
            payload=payload,
            response_payload=response_payload,
            terminal=terminal_status,
        )

    def _validate_authority(
        self,
        record: TeamWorkflowRecord,
        *,
        action: str,
        actor: TeamActor | None,
        actor_kind: TeamWorkflowActorKind,
    ) -> None:
        if actor_kind is TeamWorkflowActorKind.HOST:
            return
        if actor is None or actor.team is None or actor.team.team_id != record.team_id or actor.member is None:
            raise TeamWorkflowError(
                "invalid_team_state",
                "The caller does not have an active runtime team for this workflow",
                workflow_id=record.workflow_id,
                team_id=record.team_id,
            )
        if record.workflow_kind is TeamWorkflowKind.PERMISSION:
            if actor.member.role is not TeamRole.LEADER:
                raise TeamWorkflowError(
                    "authority_denied",
                    "Only the team leader can resolve permission workflows",
                    workflow_id=record.workflow_id,
                    member_id=actor.member.member_id,
                )
            return
        if actor.member.member_id == record.responder_member_id:
            return
        if actor.member.role is TeamRole.LEADER:
            return
        raise TeamWorkflowError(
            "authority_denied",
            "Only the targeted teammate or team leader can resolve this shutdown workflow",
            workflow_id=record.workflow_id,
            member_id=actor.member.member_id,
        )

    def _mutate_record(
        self,
        record: TeamWorkflowRecord,
        *,
        status: TeamWorkflowStatus,
        action: str,
        actor_kind: TeamWorkflowActorKind,
        actor_id: str | None,
        payload: Mapping[str, Any] | None,
        response_payload: Mapping[str, Any] | None = None,
        terminal: TeamWorkflowStatus | None = None,
        message_id: str | None = None,
    ) -> TeamWorkflowRecord:
        transition = TeamWorkflowTransition(
            transition_id=uuid4().hex,
            action=action,
            actor_kind=actor_kind,
            actor_id=actor_id,
            payload=_coerce_mapping(payload),
        )
        message_ids = list(record.message_ids)
        if message_id is not None and message_id not in message_ids:
            message_ids.append(message_id)
        return replace(
            record,
            status=status,
            response_payload=None if response_payload is None else dict(response_payload),
            transition_history=record.transition_history + (transition,),
            message_ids=tuple(message_ids),
            updated_at=utc_now(),
            terminal_at=utc_now() if terminal is not None else record.terminal_at,
        )

    def _event_type_for_transition(self, record: TeamWorkflowRecord) -> str:
        if record.status is TeamWorkflowStatus.WAITING_HOST:
            return "team.workflow.updated"
        if record.status is TeamWorkflowStatus.ACKNOWLEDGED:
            return "team.workflow.updated"
        if record.status is TeamWorkflowStatus.COMPLETED:
            return "team.workflow.completed"
        if record.status is TeamWorkflowStatus.REJECTED:
            return "team.workflow.rejected"
        if record.status is TeamWorkflowStatus.TIMED_OUT:
            return "team.workflow.timed_out"
        if record.status is TeamWorkflowStatus.FORCED_CLOSED:
            return "team.workflow.forced_closed"
        return "team.workflow.updated"

    async def _emit_workflow_request(
        self,
        record: TeamWorkflowRecord,
        *,
        recipient_member_id: str | None = None,
    ) -> TeamWorkflowRecord:
        resolved_recipient = recipient_member_id or record.responder_member_id
        if self._message_bus is None or resolved_recipient is None:
            return record
        control_type = f"{record.workflow_kind.value}_request"
        protocol = build_workflow_request_protocol(record)
        try:
            envelope = await self._message_bus.send_control_message(
                team_id=record.team_id,
                sender_member_id=record.requester_member_id,
                recipient_member_id=resolved_recipient,
                control_type=control_type,
                correlation_id=record.workflow_id,
                payload={
                    **protocol.to_dict(),
                    "workflow_priority": workflow_priority(record.workflow_kind),
                },
            )
        except Exception:
            return record
        if envelope.message_id in record.message_ids:
            return record
        updated = self._mutate_record(
            record,
            status=record.status,
            action="transport_request",
            actor_kind=TeamWorkflowActorKind.RUNTIME,
            actor_id="message_bus",
            payload={"message_id": envelope.message_id},
            response_payload=record.response_payload,
            message_id=envelope.message_id,
        )
        self._store.save(updated)
        return updated

    async def _emit_workflow_response(
        self,
        record: TeamWorkflowRecord,
        *,
        action: str,
        actor_kind: TeamWorkflowActorKind,
        actor_id: str | None,
        payload: Mapping[str, Any] | None,
    ) -> None:
        if self._message_bus is None or record.leader_session_id is None:
            return
        team = self._control_plane.get_team(record.team_id)
        if team is None:
            return
        sender_member_id = self._response_transport_sender_member_id(
            team=team,
            record=record,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )
        control_type = f"{record.workflow_kind.value}_response"
        protocol = build_workflow_response_protocol(
            record,
            action=action,
            actor_kind=actor_kind,
            actor_id=actor_id,
            payload=payload,
        )
        try:
            envelope = await self._message_bus.send_control_message(
                team_id=record.team_id,
                sender_member_id=sender_member_id,
                recipient_member_id=team.leader_member_id,
                control_type=control_type,
                correlation_id=record.workflow_id,
                payload=protocol.to_dict(),
                allow_workflow_response=True,
            )
        except Exception:
            return
        if envelope.message_id in record.message_ids:
            return
        updated = self._mutate_record(
            record,
            status=record.status,
            action="transport_response",
            actor_kind=TeamWorkflowActorKind.RUNTIME,
            actor_id="message_bus",
            payload={"message_id": envelope.message_id, "response_action": action},
            response_payload=record.response_payload,
            message_id=envelope.message_id,
        )
        self._store.save(updated)

    def _response_transport_sender_member_id(
        self,
        *,
        team: TeamRecord,
        record: TeamWorkflowRecord,
        actor_kind: TeamWorkflowActorKind,
        actor_id: str | None,
    ) -> str:
        if actor_kind in {TeamWorkflowActorKind.LEADER, TeamWorkflowActorKind.TEAMMATE}:
            candidate = _coerce_optional_string(actor_id)
            if candidate:
                member = self._control_plane.get_member(team.team_id, candidate)
                if member is not None and member.active:
                    return member.member_id
        if actor_kind is TeamWorkflowActorKind.RUNTIME:
            candidate = _coerce_optional_string(actor_id)
            if candidate:
                member = self._control_plane.get_member(team.team_id, candidate)
                if member is not None and member.active:
                    return member.member_id
        responder_member_id = _coerce_optional_string(record.responder_member_id)
        if responder_member_id:
            responder = self._control_plane.get_member(team.team_id, responder_member_id)
            if responder is not None and responder.active:
                return responder.member_id
        return team.leader_member_id

    async def _emit_workflow_event(
        self,
        event_type: str,
        record: TeamWorkflowRecord,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        host = getattr(self._runtime_services, "host", None)
        if host is None or not hasattr(host, "emit_team_event"):
            return
        await host.emit_team_event(
            TeamEvent(
                event_id=uuid4().hex,
                event_type=event_type,
                team_id=record.team_id,
                leader_session_id=record.leader_session_id or "",
                member_id=record.requester_member_id,
                correlation_id=record.workflow_id,
                payload={
                    **workflow_record_to_payload(record),
                    **_coerce_mapping(payload),
                },
            )
        )

    def _resolve_waiters(self, record: TeamWorkflowRecord) -> None:
        waiters = tuple(self._terminal_waiters.pop(record.workflow_id, ()))
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(record)

    def _workflow_lock(self, workflow_id: str) -> asyncio.Lock:
        lock = self._workflow_locks.get(workflow_id)
        if lock is None:
            lock = asyncio.Lock()
            self._workflow_locks[workflow_id] = lock
        return lock

    def _require_record(self, workflow_id: str) -> TeamWorkflowRecord:
        record = self._store.load(workflow_id)
        if record is None:
            raise TeamWorkflowError("not_found", f"Workflow '{workflow_id}' was not found", workflow_id=workflow_id)
        return record

    def _schedule_deadline(self, record: TeamWorkflowRecord) -> None:
        self._cancel_deadline(record.workflow_id)
        if record.terminal or record.deadline_at is None:
            return
        delay = max((record.deadline_at - utc_now()).total_seconds(), 0.0)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._deadline_tasks[record.workflow_id] = loop.create_task(
            self._deadline_worker(record.workflow_id, delay)
        )

    def _cancel_deadline(self, workflow_id: str) -> None:
        task = self._deadline_tasks.pop(workflow_id, None)
        if task is not None:
            task.cancel()

    async def _deadline_worker(self, workflow_id: str, delay_seconds: float) -> None:
        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            return
        try:
            async with self._workflow_lock(workflow_id):
                record = self._store.load(workflow_id)
                if record is None or record.terminal:
                    return
                terminal_status = (
                    TeamWorkflowStatus.FORCED_CLOSED
                    if record.workflow_kind is TeamWorkflowKind.SHUTDOWN
                    else TeamWorkflowStatus.TIMED_OUT
                )
                updated = self._mutate_record(
                    record,
                    status=terminal_status,
                    action="deadline_expired",
                    actor_kind=TeamWorkflowActorKind.RUNTIME,
                    actor_id="deadline",
                    payload={"deadline_at": _utc_isoformat(record.deadline_at) if record.deadline_at else None},
                    response_payload={
                        **(record.response_payload or {}),
                        "deadline_expired": True,
                    },
                    terminal=terminal_status,
                )
                self._store.save(updated)
                await self._emit_workflow_event(
                    "team.workflow.timed_out"
                    if updated.status is TeamWorkflowStatus.TIMED_OUT
                    else "team.workflow.forced_closed",
                    updated,
                    payload={"deadline_expired": True},
                )
                await self._emit_workflow_response(
                    updated,
                    action="deadline_expired",
                    actor_kind=TeamWorkflowActorKind.RUNTIME,
                    actor_id="deadline",
                    payload=updated.response_payload,
                )
                self._resolve_waiters(updated)
        finally:
            self._deadline_tasks.pop(workflow_id, None)

    def _tracked_records(
        self,
        records: tuple[TeamWorkflowRecord, ...],
        *,
        pending_only: bool | None,
    ) -> tuple[TeamWorkflowRecord, ...]:
        refreshed: list[TeamWorkflowRecord] = []
        for record in records:
            current, _ = self._refresh_record_deadline(record)
            self._schedule_deadline(current)
            refreshed.append(current)
        if pending_only is True:
            refreshed = [record for record in refreshed if not record.terminal]
        elif pending_only is False:
            refreshed = [record for record in refreshed if record.terminal]
        refreshed.sort(key=lambda item: (item.created_at, item.workflow_id))
        return tuple(refreshed)

    def _refresh_record_deadline(
        self,
        record: TeamWorkflowRecord,
    ) -> tuple[TeamWorkflowRecord, bool]:
        if record.terminal or record.deadline_at is None or record.deadline_at > utc_now():
            return record, False
        terminal_status = (
            TeamWorkflowStatus.FORCED_CLOSED
            if record.workflow_kind is TeamWorkflowKind.SHUTDOWN
            else TeamWorkflowStatus.TIMED_OUT
        )
        updated = self._mutate_record(
            record,
            status=terminal_status,
            action="deadline_expired",
            actor_kind=TeamWorkflowActorKind.RUNTIME,
            actor_id="deadline",
            payload={"deadline_at": _utc_isoformat(record.deadline_at)},
            response_payload={
                **(record.response_payload or {}),
                "deadline_expired": True,
            },
            terminal=terminal_status,
        )
        self._store.save(updated)
        self._cancel_deadline(updated.workflow_id)
        return updated, True


def _actor_kind(actor: TeamActor) -> TeamWorkflowActorKind:
    if actor.member is None:
        return TeamWorkflowActorKind.HOST
    if actor.member.role is TeamRole.LEADER:
        return TeamWorkflowActorKind.LEADER
    return TeamWorkflowActorKind.TEAMMATE


def _utc_isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def _coerce_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _coerce_optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, payload: dict[str, Any], *, replace_existing: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".tmp-{path.name}-{uuid4().hex}")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists() and not replace_existing:
        temp.unlink(missing_ok=True)
        raise FileExistsError(path)
    temp.replace(path)


__all__ = [
    "FileBackedTeamWorkflowStore",
    "InMemoryTeamWorkflowStore",
    "RuntimeTeamWorkflowService",
    "TeamWorkflowActorKind",
    "TeamWorkflowError",
    "TeamWorkflowKind",
    "TeamWorkflowProtocolKind",
    "TeamWorkflowRecord",
    "TeamWorkflowRequestProtocol",
    "TeamWorkflowResponseProtocol",
    "TeamWorkflowStatus",
    "TeamWorkflowStore",
    "TeamWorkflowTransition",
    "TERMINAL_WORKFLOW_STATUSES",
    "allowed_workflow_actions",
    "build_workflow_request_protocol",
    "build_workflow_response_protocol",
    "parse_workflow_request_protocol",
    "parse_workflow_response_protocol",
    "workflow_priority",
    "workflow_record_to_payload",
    "workflow_request_summary",
    "workflow_response_summary",
]
