from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol
from uuid import uuid4

from .contracts import utc_now
from .definitions import IsolationMode, PermissionMode
from .hosts.base import HostExtensionEvent

if TYPE_CHECKING:
    from .runtime_services import RuntimeServices
    from .teammate_orchestration import PersistentTeammateOrchestrator

_SCHEMA_VERSION = 1
_RESERVED_MEMBER_NAMES = frozenset({"leader", "*"})
_MEMBER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class TeamRole(StrEnum):
    LEADER = "leader"
    TEAMMATE = "teammate"


class TeamStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class TeamMemberStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class TeamRecord:
    team_id: str
    leader_session_id: str
    leader_member_id: str
    name: str | None = None
    status: TeamStatus = TeamStatus.ACTIVE
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    deleted_at: datetime | None = None
    context_metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = _SCHEMA_VERSION

    @property
    def active(self) -> bool:
        return self.status is TeamStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "team_id": self.team_id,
            "leader_session_id": self.leader_session_id,
            "leader_member_id": self.leader_member_id,
            "name": self.name,
            "status": self.status.value,
            "created_at": _utc_isoformat(self.created_at),
            "updated_at": _utc_isoformat(self.updated_at),
            "deleted_at": _utc_isoformat(self.deleted_at) if self.deleted_at is not None else None,
            "context_metadata": dict(self.context_metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamRecord":
        payload = dict(value)
        status = str(payload.get("status") or TeamStatus.ACTIVE.value)
        return cls(
            schema_version=int(payload.get("schema_version") or _SCHEMA_VERSION),
            team_id=str(payload.get("team_id") or ""),
            leader_session_id=str(payload.get("leader_session_id") or ""),
            leader_member_id=str(payload.get("leader_member_id") or ""),
            name=_coerce_optional_string(payload.get("name")),
            status=TeamStatus(status),
            created_at=_parse_utc_timestamp(payload.get("created_at")) or utc_now(),
            updated_at=_parse_utc_timestamp(payload.get("updated_at")) or utc_now(),
            deleted_at=_parse_utc_timestamp(payload.get("deleted_at")),
            context_metadata=_coerce_mapping(payload.get("context_metadata")),
        )


@dataclass(frozen=True, slots=True)
class TeamMemberRecord:
    team_id: str
    member_id: str
    name: str
    role: TeamRole
    status: TeamMemberStatus = TeamMemberStatus.ACTIVE
    agent_name: str | None = None
    session_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    removed_at: datetime | None = None
    execution_defaults: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = _SCHEMA_VERSION

    @property
    def active(self) -> bool:
        return self.status is TeamMemberStatus.ACTIVE

    def with_status(self, status: TeamMemberStatus) -> "TeamMemberRecord":
        removed_at = utc_now() if status is TeamMemberStatus.REMOVED else None
        return replace(
            self,
            status=status,
            removed_at=removed_at,
            updated_at=utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "team_id": self.team_id,
            "member_id": self.member_id,
            "name": self.name,
            "role": self.role.value,
            "status": self.status.value,
            "agent_name": self.agent_name,
            "session_id": self.session_id,
            "created_at": _utc_isoformat(self.created_at),
            "updated_at": _utc_isoformat(self.updated_at),
            "removed_at": _utc_isoformat(self.removed_at) if self.removed_at is not None else None,
            "execution_defaults": _json_safe_copy(self.execution_defaults),
            "metadata": _json_safe_copy(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamMemberRecord":
        payload = dict(value)
        return cls(
            schema_version=int(payload.get("schema_version") or _SCHEMA_VERSION),
            team_id=str(payload.get("team_id") or ""),
            member_id=str(payload.get("member_id") or ""),
            name=str(payload.get("name") or ""),
            role=TeamRole(str(payload.get("role") or TeamRole.TEAMMATE.value)),
            status=TeamMemberStatus(str(payload.get("status") or TeamMemberStatus.ACTIVE.value)),
            agent_name=_coerce_optional_string(payload.get("agent_name")),
            session_id=_coerce_optional_string(payload.get("session_id")),
            created_at=_parse_utc_timestamp(payload.get("created_at")) or utc_now(),
            updated_at=_parse_utc_timestamp(payload.get("updated_at")) or utc_now(),
            removed_at=_parse_utc_timestamp(payload.get("removed_at")),
            execution_defaults=_coerce_mapping(payload.get("execution_defaults")),
            metadata=_coerce_mapping(payload.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class TeamLeaderBinding:
    leader_session_id: str
    team_id: str
    created_at: datetime = field(default_factory=utc_now)
    schema_version: int = _SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "leader_session_id": self.leader_session_id,
            "team_id": self.team_id,
            "created_at": _utc_isoformat(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamLeaderBinding":
        payload = dict(value)
        return cls(
            schema_version=int(payload.get("schema_version") or _SCHEMA_VERSION),
            leader_session_id=str(payload.get("leader_session_id") or ""),
            team_id=str(payload.get("team_id") or ""),
            created_at=_parse_utc_timestamp(payload.get("created_at")) or utc_now(),
        )


@dataclass(frozen=True, slots=True)
class TeamActor:
    session_id: str
    team: TeamRecord | None = None
    member: TeamMemberRecord | None = None

    @property
    def team_id(self) -> str | None:
        return self.team.team_id if self.team is not None else None

    @property
    def role(self) -> TeamRole | None:
        if self.member is not None:
            return self.member.role
        return None

    @property
    def is_leader(self) -> bool:
        return self.member is not None and self.member.role is TeamRole.LEADER

    @property
    def is_teammate(self) -> bool:
        return self.member is not None and self.member.role is TeamRole.TEAMMATE


@dataclass(frozen=True, slots=True)
class TeamEvent:
    event_id: str
    event_type: str
    team_id: str
    leader_session_id: str
    occurred_at: datetime = field(default_factory=utc_now)
    member_id: str | None = None
    message_id: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "team_id": self.team_id,
            "leader_session_id": self.leader_session_id,
            "occurred_at": _utc_isoformat(self.occurred_at),
            "member_id": self.member_id,
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "payload": _json_safe_copy(self.payload),
        }


TEAM_EXTENSION_EVENT_NAMESPACE = "runtime.team"
TEAM_EXTENSION_EVENT_SCHEMA_VERSION = "1.0"


def team_event_to_extension_event(event: TeamEvent) -> HostExtensionEvent:
    return HostExtensionEvent(
        namespace=TEAM_EXTENSION_EVENT_NAMESPACE,
        schema_version=TEAM_EXTENSION_EVENT_SCHEMA_VERSION,
        event_type=event.event_type,
        event_id=event.event_id,
        occurred_at=event.occurred_at,
        correlation_id=event.correlation_id,
        payload=event.to_dict(),
    )


class TeamControlError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details)


class TeamStore(Protocol):
    def load_team(self, team_id: str) -> TeamRecord | None: ...

    def create_team(self, team: TeamRecord, leader_member: TeamMemberRecord) -> TeamRecord: ...

    def save_team(self, team: TeamRecord) -> TeamRecord: ...

    def active_team_for_leader_session(self, leader_session_id: str) -> TeamRecord | None: ...

    def delete_leader_binding(self, leader_session_id: str) -> None: ...

    def save_member(self, member: TeamMemberRecord) -> TeamMemberRecord: ...

    def load_member(self, team_id: str, member_id: str) -> TeamMemberRecord | None: ...

    def list_members(
        self,
        team_id: str,
        *,
        active_only: bool = True,
        include_leader: bool = True,
    ) -> tuple[TeamMemberRecord, ...]: ...

    def find_member_by_name(self, team_id: str, name: str) -> TeamMemberRecord | None: ...

    def tombstone_team(self, team: TeamRecord) -> TeamRecord: ...

    def remove_member(self, team_id: str, member_id: str) -> TeamMemberRecord | None: ...

    def purge_team(self, team_id: str) -> None: ...


class InMemoryTeamStore:
    def __init__(self) -> None:
        self._teams: dict[str, TeamRecord] = {}
        self._members: dict[tuple[str, str], TeamMemberRecord] = {}
        self._leader_bindings: dict[str, TeamLeaderBinding] = {}

    def load_team(self, team_id: str) -> TeamRecord | None:
        return self._teams.get(str(team_id))

    def create_team(self, team: TeamRecord, leader_member: TeamMemberRecord) -> TeamRecord:
        if team.team_id in self._teams:
            raise FileExistsError(team.team_id)
        if team.leader_session_id in self._leader_bindings:
            raise FileExistsError(team.leader_session_id)
        self._teams[team.team_id] = team
        self.save_member(leader_member)
        self._leader_bindings[team.leader_session_id] = TeamLeaderBinding(
            leader_session_id=team.leader_session_id,
            team_id=team.team_id,
        )
        return team

    def save_team(self, team: TeamRecord) -> TeamRecord:
        self._teams[team.team_id] = team
        return team

    def active_team_for_leader_session(self, leader_session_id: str) -> TeamRecord | None:
        binding = self._leader_bindings.get(str(leader_session_id))
        if binding is None:
            return None
        team = self.load_team(binding.team_id)
        if team is None or not team.active:
            self._leader_bindings.pop(str(leader_session_id), None)
            return None
        return team

    def delete_leader_binding(self, leader_session_id: str) -> None:
        self._leader_bindings.pop(str(leader_session_id), None)

    def save_member(self, member: TeamMemberRecord) -> TeamMemberRecord:
        self._members[(member.team_id, member.member_id)] = member
        return member

    def load_member(self, team_id: str, member_id: str) -> TeamMemberRecord | None:
        return self._members.get((str(team_id), str(member_id)))

    def list_members(
        self,
        team_id: str,
        *,
        active_only: bool = True,
        include_leader: bool = True,
    ) -> tuple[TeamMemberRecord, ...]:
        members = [
            member
            for (candidate_team_id, _), member in self._members.items()
            if candidate_team_id == str(team_id)
        ]
        filtered = []
        for member in sorted(members, key=lambda item: (item.created_at, item.member_id)):
            if active_only and not member.active:
                continue
            if not include_leader and member.role is TeamRole.LEADER:
                continue
            filtered.append(member)
        return tuple(filtered)

    def find_member_by_name(self, team_id: str, name: str) -> TeamMemberRecord | None:
        normalized = str(name)
        for member in self.list_members(team_id):
            if member.name == normalized:
                return member
        return None

    def tombstone_team(self, team: TeamRecord) -> TeamRecord:
        tombstoned = replace(
            team,
            status=TeamStatus.DELETED,
            deleted_at=utc_now(),
            updated_at=utc_now(),
        )
        self.save_team(tombstoned)
        self.delete_leader_binding(team.leader_session_id)
        return tombstoned

    def remove_member(self, team_id: str, member_id: str) -> TeamMemberRecord | None:
        member = self.load_member(team_id, member_id)
        if member is None:
            return None
        removed = member.with_status(TeamMemberStatus.REMOVED)
        self.save_member(removed)
        return removed

    def purge_team(self, team_id: str) -> None:
        normalized_team_id = str(team_id)
        self._teams.pop(normalized_team_id, None)
        self._members = {
            key: value
            for key, value in self._members.items()
            if key[0] != normalized_team_id
        }
        self._leader_bindings = {
            key: value
            for key, value in self._leader_bindings.items()
            if value.team_id != normalized_team_id
        }


class FileBackedTeamStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def load_team(self, team_id: str) -> TeamRecord | None:
        path = self._team_path(team_id)
        if not path.exists():
            return None
        return TeamRecord.from_dict(_read_json(path))

    def create_team(self, team: TeamRecord, leader_member: TeamMemberRecord) -> TeamRecord:
        team_path = self._team_path(team.team_id)
        binding_path = self._binding_path(team.leader_session_id)
        if team_path.exists():
            raise FileExistsError(team_path)
        if binding_path.exists():
            raise FileExistsError(binding_path)
        try:
            _atomic_write_json(team_path, team.to_dict())
            self.save_member(leader_member)
            _atomic_write_json(
                binding_path,
                TeamLeaderBinding(
                    leader_session_id=team.leader_session_id,
                    team_id=team.team_id,
                ).to_dict(),
            )
        except Exception:
            shutil.rmtree(team_path.parent, ignore_errors=True)
            binding_path.unlink(missing_ok=True)
            raise
        return team

    def save_team(self, team: TeamRecord) -> TeamRecord:
        _atomic_write_json(self._team_path(team.team_id), team.to_dict(), replace_existing=True)
        return team

    def active_team_for_leader_session(self, leader_session_id: str) -> TeamRecord | None:
        binding_path = self._binding_path(leader_session_id)
        if not binding_path.exists():
            return None
        binding = TeamLeaderBinding.from_dict(_read_json(binding_path))
        team = self.load_team(binding.team_id)
        if team is None or not team.active:
            binding_path.unlink(missing_ok=True)
            return None
        return team

    def delete_leader_binding(self, leader_session_id: str) -> None:
        self._binding_path(leader_session_id).unlink(missing_ok=True)

    def save_member(self, member: TeamMemberRecord) -> TeamMemberRecord:
        _atomic_write_json(self._member_path(member.team_id, member.member_id), member.to_dict(), replace_existing=True)
        return member

    def load_member(self, team_id: str, member_id: str) -> TeamMemberRecord | None:
        path = self._member_path(team_id, member_id)
        if not path.exists():
            return None
        return TeamMemberRecord.from_dict(_read_json(path))

    def list_members(
        self,
        team_id: str,
        *,
        active_only: bool = True,
        include_leader: bool = True,
    ) -> tuple[TeamMemberRecord, ...]:
        members_root = self._members_root(team_id)
        if not members_root.exists():
            return ()
        members: list[TeamMemberRecord] = []
        for path in sorted(members_root.glob("*.json")):
            member = TeamMemberRecord.from_dict(_read_json(path))
            if active_only and not member.active:
                continue
            if not include_leader and member.role is TeamRole.LEADER:
                continue
            members.append(member)
        return tuple(members)

    def find_member_by_name(self, team_id: str, name: str) -> TeamMemberRecord | None:
        normalized = str(name)
        for member in self.list_members(team_id):
            if member.name == normalized:
                return member
        return None

    def tombstone_team(self, team: TeamRecord) -> TeamRecord:
        tombstoned = replace(
            team,
            status=TeamStatus.DELETED,
            deleted_at=utc_now(),
            updated_at=utc_now(),
        )
        self.save_team(tombstoned)
        self.delete_leader_binding(team.leader_session_id)
        return tombstoned

    def remove_member(self, team_id: str, member_id: str) -> TeamMemberRecord | None:
        member = self.load_member(team_id, member_id)
        if member is None:
            return None
        removed = member.with_status(TeamMemberStatus.REMOVED)
        self.save_member(removed)
        return removed

    def purge_team(self, team_id: str) -> None:
        shutil.rmtree(self._team_root(team_id), ignore_errors=True)

    def _team_root(self, team_id: str) -> Path:
        return self._root / "teams" / team_id

    def _team_path(self, team_id: str) -> Path:
        return self._team_root(team_id) / "team.json"

    def _members_root(self, team_id: str) -> Path:
        return self._team_root(team_id) / "members"

    def _member_path(self, team_id: str, member_id: str) -> Path:
        return self._members_root(team_id) / f"{member_id}.json"

    def _binding_path(self, leader_session_id: str) -> Path:
        return self._root / "leaders" / f"{leader_session_id}.json"


class RuntimeTeamRunnerManager:
    def __init__(
        self,
        *,
        teammates: PersistentTeammateOrchestrator,
        runtime_services: RuntimeServices,
    ) -> None:
        self._teammates = teammates
        self._runtime_services = runtime_services
        self._drain_tasks: dict[tuple[str, str], asyncio.Task[tuple[Any, ...] | None]] = {}

    async def register_member(self, team: TeamRecord, member: TeamMemberRecord) -> None:
        if member.role is TeamRole.LEADER:
            return
        working_directory = str(member.execution_defaults.get("cwd") or self._runtime_services.metadata.get("cwd") or ".")
        metadata = {
            "team_member_id": member.member_id,
            "team_member_name": member.name,
            "team_role": member.role.value,
            "leader_session_id": team.leader_session_id,
            **_coerce_mapping(member.metadata),
        }
        self._teammates.register_teammate(
            team_id=team.team_id,
            teammate_id=member.member_id,
            agent_name=str(member.agent_name or "main-router"),
            session_id=team.leader_session_id,
            working_directory=working_directory,
            metadata=metadata,
        )

    async def dispatch_message(
        self,
        *,
        team: TeamRecord,
        member: TeamMemberRecord,
        prompt: str,
        sender: Mapping[str, Any],
        correlation_id: str | None = None,
        payload_metadata: Mapping[str, Any] | None = None,
    ) -> str:
        defaults = member.execution_defaults
        envelope = self._teammates.publish_work_item(
            team_id=team.team_id,
            teammate_id=member.member_id,
            prompt=prompt,
            sender=sender,
            kind="team_message",
            correlation_id=correlation_id,
            payload={
                "metadata": {
                    "team_member_id": member.member_id,
                    "team_member_name": member.name,
                    "team_role": member.role.value,
                    "leader_session_id": team.leader_session_id,
                    **_coerce_mapping(payload_metadata),
                }
            },
            requested_model_route=_coerce_optional_string(defaults.get("model_route")),
            requested_model=_coerce_optional_string(defaults.get("model")),
            requested_permission_mode=_coerce_optional_string(defaults.get("permission_mode")),
            requested_isolation=_coerce_optional_string(defaults.get("isolation")),
            max_turns=_coerce_optional_int(defaults.get("max_turns")),
        )
        self.ensure_runner(team_id=team.team_id, member_id=member.member_id)
        return envelope.message_id

    def ensure_runner(self, *, team_id: str, member_id: str) -> None:
        key = (team_id, member_id)
        task = self._drain_tasks.get(key)
        if task is not None and not task.done():
            return
        self._drain_tasks[key] = asyncio.create_task(self._drain_loop(team_id=team_id, member_id=member_id))

    async def wait_for_idle(self, *, team_id: str, member_id: str) -> None:
        task = self._drain_tasks.get((team_id, member_id))
        if task is not None:
            await asyncio.shield(task)

    async def remove_member(
        self,
        *,
        team: TeamRecord,
        member: TeamMemberRecord,
        requester_member_id: str,
        requester_name: str,
        reason: str,
    ) -> None:
        team_id = team.team_id
        member_id = member.member_id
        key = (team_id, member_id)
        workflow_service = self._runtime_services.resolve_team_workflows()
        if workflow_service is None:
            task = self._drain_tasks.pop(key, None)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await self._teammates.remove_teammate(team_id=team_id, teammate_id=member_id)
            return

        workflow = await workflow_service.create_shutdown_workflow(
            team=team,
            requester_member_id=requester_member_id,
            requester_name=requester_name,
            responder_member_id=member.member_id,
            responder_name=member.name,
            request_payload={"reason": reason, "member_id": member.member_id, "member_name": member.name},
        )
        snapshot = self._teammates.begin_shutdown(
            team_id=team.team_id,
            teammate_id=member.member_id,
            workflow_id=workflow.workflow_id,
        )
        current = workflow_service.get(workflow.workflow_id)
        if current is not None and str(getattr(current.status, "value", current.status)) == "pending":
            from .team_workflows import TeamWorkflowActorKind

            await workflow_service.acknowledge_shutdown(
                workflow.workflow_id,
                actor_kind=TeamWorkflowActorKind.TEAMMATE,
                actor_id=member.member_id,
                payload={"teammate_id": member.member_id, "accepted": True},
            )
        if snapshot is None or not snapshot.current_work_attached:
            await self._teammates.complete_shutdown(
                team_id=team.team_id,
                teammate_id=member.member_id,
                workflow_id=workflow.workflow_id,
            )
        terminal = await workflow_service.wait_for_terminal(workflow.workflow_id)
        task = self._drain_tasks.pop(key, None)
        if task is not None and not task.done() and str(getattr(terminal.status, "value", terminal.status)) in {
            "forced_closed",
            "timed_out",
        }:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._teammates.remove_teammate(team_id=team_id, teammate_id=member_id)

    async def shutdown_team(
        self,
        *,
        team: TeamRecord,
        members: tuple[TeamMemberRecord, ...],
        requester_member_id: str,
        requester_name: str,
        reason: str,
    ) -> None:
        for member in members:
            if member.role is TeamRole.TEAMMATE:
                await self.remove_member(
                    team=team,
                    member=member,
                    requester_member_id=requester_member_id,
                    requester_name=requester_name,
                    reason=reason,
                )

    async def _drain_loop(self, *, team_id: str, member_id: str) -> tuple[Any, ...] | None:
        try:
            return await self._teammates.drain_teammate(team_id=team_id, teammate_id=member_id)
        finally:
            self._drain_tasks.pop((team_id, member_id), None)


class RuntimeTeamControlPlane:
    def __init__(
        self,
        *,
        store: TeamStore,
        runtime_services: RuntimeServices,
        runner_manager: RuntimeTeamRunnerManager,
    ) -> None:
        self._store = store
        self._runtime_services = runtime_services
        self._runner_manager = runner_manager

    @property
    def store(self) -> TeamStore:
        return self._store

    @property
    def runner_manager(self) -> RuntimeTeamRunnerManager:
        return self._runner_manager

    def get_team(self, team_id: str) -> TeamRecord | None:
        return self._store.load_team(team_id)

    def get_member(self, team_id: str, member_id: str) -> TeamMemberRecord | None:
        return self._store.load_member(team_id, member_id)

    def list_members(
        self,
        team_id: str,
        *,
        active_only: bool = True,
        include_leader: bool = True,
    ) -> tuple[TeamMemberRecord, ...]:
        return self._store.list_members(team_id, active_only=active_only, include_leader=include_leader)

    def active_team_for_leader_session(self, leader_session_id: str) -> TeamRecord | None:
        return self._store.active_team_for_leader_session(leader_session_id)

    def resolve_actor(self, *, session_id: str, extensions: Mapping[str, Any]) -> TeamActor:
        team: TeamRecord | None = None
        team_id = _coerce_optional_string(extensions.get("team_id"))
        if team_id is not None:
            team = self._store.load_team(team_id)
            if team is not None and not team.active:
                team = None
        if team is None:
            team = self._store.active_team_for_leader_session(session_id)
        if team is None:
            return TeamActor(session_id=session_id)

        member_id = _coerce_optional_string(extensions.get("team_member_id")) or _coerce_optional_string(
            extensions.get("teammate_id")
        )
        if member_id is not None:
            member = self._store.load_member(team.team_id, member_id)
            if member is not None and member.active:
                return TeamActor(session_id=session_id, team=team, member=member)

        role = _coerce_optional_string(extensions.get("team_role"))
        if team.leader_session_id == session_id or role == TeamRole.LEADER.value:
            leader = self._store.load_member(team.team_id, team.leader_member_id)
            if leader is not None and leader.active:
                return TeamActor(session_id=session_id, team=team, member=leader)
        return TeamActor(session_id=session_id, team=team)

    async def create_team(
        self,
        *,
        session_id: str,
        extensions: Mapping[str, Any],
        name: str | None,
    ) -> tuple[TeamRecord, bool]:
        actor = self.resolve_actor(session_id=session_id, extensions=extensions)
        if actor.is_teammate:
            raise TeamControlError(
                "authority_denied",
                "Teammates cannot create nested teams",
                team_id=actor.team_id,
                member_id=actor.member.member_id if actor.member is not None else None,
            )

        existing = self._store.active_team_for_leader_session(session_id)
        created = False
        if existing is None:
            team = TeamRecord(
                team_id=uuid4().hex,
                leader_session_id=session_id,
                leader_member_id=uuid4().hex,
                name=name,
                context_metadata={"team_scope": "runtime"},
            )
            leader = TeamMemberRecord(
                team_id=team.team_id,
                member_id=team.leader_member_id,
                name=TeamRole.LEADER.value,
                role=TeamRole.LEADER,
                session_id=session_id,
                metadata={"leader_session_id": session_id},
            )
            try:
                self._store.create_team(team, leader)
            except FileExistsError:
                existing = self._store.active_team_for_leader_session(session_id)
                if existing is None:
                    raise
            else:
                existing = team
                created = True
                await self._emit_event(
                    event_type="team.lifecycle.created",
                    team=team,
                    member_id=leader.member_id,
                    payload={"name": team.name, "created": True},
                )
        team = existing
        if team is None:
            raise TeamControlError("invalid_team_state", "Unable to create or load an active team")

        leader = self._store.load_member(team.team_id, team.leader_member_id)
        if leader is None:
            raise TeamControlError(
                "invalid_team_state",
                "Active team is missing its leader member record",
                team_id=team.team_id,
            )
        await self._sync_leader_private_context(team=team, leader=leader)
        if not created:
            await self._emit_event(
                event_type="team.lifecycle.reused",
                team=team,
                member_id=leader.member_id,
                payload={"name": team.name, "created": False},
            )
        return team, created

    async def register_member(
        self,
        *,
        session_id: str,
        extensions: Mapping[str, Any],
        name: str,
        agent_name: str,
        execution_defaults: Mapping[str, Any],
    ) -> TeamMemberRecord:
        actor = self.resolve_actor(session_id=session_id, extensions=extensions)
        team, leader = self._require_leader(actor)
        normalized_name = _validate_member_name(name)
        if self._store.find_member_by_name(team.team_id, normalized_name) is not None:
            raise TeamControlError(
                "duplicate_member_name",
                f"Team member name '{normalized_name}' is already in use",
                team_id=team.team_id,
                name=normalized_name,
            )
        member = TeamMemberRecord(
            team_id=team.team_id,
            member_id=uuid4().hex,
            name=normalized_name,
            role=TeamRole.TEAMMATE,
            agent_name=agent_name,
            session_id=team.leader_session_id,
            execution_defaults=_normalize_execution_defaults(execution_defaults),
            metadata={"leader_session_id": team.leader_session_id},
        )
        self._store.save_member(member)
        await self._runner_manager.register_member(team, member)
        await self._emit_event(
            event_type="team.member.spawned",
            team=team,
            member_id=member.member_id,
            payload={
                "name": member.name,
                "agent": member.agent_name,
                "requested_by": leader.member_id,
            },
        )
        return member

    async def remove_member(
        self,
        *,
        session_id: str,
        extensions: Mapping[str, Any],
        member_id: str,
    ) -> TeamMemberRecord:
        actor = self.resolve_actor(session_id=session_id, extensions=extensions)
        team, leader = self._require_leader(actor)
        if member_id == team.leader_member_id:
            raise TeamControlError(
                "authority_denied",
                "The leader member cannot be removed without deleting the team",
                team_id=team.team_id,
                member_id=member_id,
            )
        member = self._store.load_member(team.team_id, member_id)
        if member is None or not member.active:
            raise TeamControlError(
                "not_found",
                f"Team member '{member_id}' was not found",
                team_id=team.team_id,
                member_id=member_id,
            )
        await self._runner_manager.remove_member(
            team=team,
            member=member,
            requester_member_id=leader.member_id,
            requester_name=leader.name,
            reason="member_removed",
        )
        removed = self._store.remove_member(team.team_id, member_id) or member
        await self._emit_event(
            event_type="team.member.removed",
            team=team,
            member_id=member_id,
            payload={"name": removed.name},
        )
        return removed

    async def delete_team(
        self,
        *,
        session_id: str,
        extensions: Mapping[str, Any],
    ) -> TeamRecord:
        actor = self.resolve_actor(session_id=session_id, extensions=extensions)
        team, leader = self._require_leader(actor)
        members = self._store.list_members(team.team_id)
        await self._runner_manager.shutdown_team(
            team=team,
            members=members,
            requester_member_id=leader.member_id,
            requester_name=leader.name,
            reason="team_deleted",
        )
        for member in members:
            if member.member_id == team.leader_member_id:
                continue
            self._store.remove_member(team.team_id, member.member_id)
        tombstoned = self._store.tombstone_team(team)
        self._store.remove_member(team.team_id, team.leader_member_id)
        await self._clear_leader_private_context(team=tombstoned)
        await self._emit_event(
            event_type="team.lifecycle.deleted",
            team=tombstoned,
            member_id=leader.member_id,
            payload={"deleted": True},
        )
        return tombstoned

    def team_private_context(self, team: TeamRecord, member: TeamMemberRecord) -> dict[str, Any]:
        return {
            "team_id": team.team_id,
            "team_role": member.role.value,
            "team_member_id": member.member_id,
            "team_member_name": member.name,
            "leader_session_id": team.leader_session_id,
        }

    def require_active_team(self, *, session_id: str, extensions: Mapping[str, Any]) -> TeamRecord:
        actor = self.resolve_actor(session_id=session_id, extensions=extensions)
        if actor.team is None:
            raise TeamControlError(
                "invalid_team_state",
                "The caller does not have an active runtime team",
                session_id=session_id,
            )
        return actor.team

    def _require_leader(self, actor: TeamActor) -> tuple[TeamRecord, TeamMemberRecord]:
        if actor.team is None or actor.member is None:
            raise TeamControlError(
                "invalid_team_state",
                "The caller does not have an active runtime team",
                session_id=actor.session_id,
            )
        if actor.member.role is not TeamRole.LEADER:
            raise TeamControlError(
                "authority_denied",
                "Only the team leader can manage team lifecycle",
                team_id=actor.team.team_id,
                member_id=actor.member.member_id,
            )
        return actor.team, actor.member

    async def _sync_leader_private_context(self, *, team: TeamRecord, leader: TeamMemberRecord) -> None:
        await self._queue_session_private_updates(
            team.leader_session_id,
            self.team_private_context(team, leader),
        )

    async def _clear_leader_private_context(self, *, team: TeamRecord) -> None:
        await self._queue_session_private_updates(
            team.leader_session_id,
            {
                "team_id": None,
                "team_role": None,
                "team_member_id": None,
                "team_member_name": None,
                "leader_session_id": None,
            },
        )

    async def _queue_session_private_updates(self, session_id: str, updates: Mapping[str, Any]) -> None:
        session = self._runtime_services.session_registry.get(session_id)
        if session is None:
            return
        from .session_runtime import InboundEvent, InboundEventType

        await session.submit_runtime_event(
            InboundEvent(
                event_type=InboundEventType.HOST_EVENT,
                content="",
                metadata={
                    "admission_kind": "local_only",
                    "private_updates": dict(updates),
                    "source": "team_control_plane",
                    "visibility": "private",
                },
            ),
            drain=False,
        )

    async def _emit_event(
        self,
        *,
        event_type: str,
        team: TeamRecord,
        member_id: str | None = None,
        message_id: str | None = None,
        correlation_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        event = TeamEvent(
            event_id=uuid4().hex,
            event_type=event_type,
            team_id=team.team_id,
            leader_session_id=team.leader_session_id,
            member_id=member_id,
            message_id=message_id,
            correlation_id=correlation_id,
            payload=_coerce_mapping(payload),
        )
        if self._runtime_services.host is not None and hasattr(self._runtime_services.host, "emit_extension_event"):
            await self._runtime_services.host.emit_extension_event(team_event_to_extension_event(event))


def _normalize_execution_defaults(value: Mapping[str, Any]) -> dict[str, Any]:
    defaults = _coerce_mapping(value)
    normalized: dict[str, Any] = {}
    cwd = _coerce_optional_string(defaults.get("cwd"))
    if cwd is not None:
        normalized["cwd"] = cwd
    model = _coerce_optional_string(defaults.get("model"))
    if model is not None:
        normalized["model"] = model
    model_route = _coerce_optional_string(defaults.get("model_route"))
    if model_route is not None:
        normalized["model_route"] = model_route
    permission_mode = _coerce_optional_string(defaults.get("permission_mode"))
    if permission_mode is not None:
        normalized["permission_mode"] = PermissionMode(permission_mode).value
    isolation = _coerce_optional_string(defaults.get("isolation"))
    if isolation is not None:
        normalized["isolation"] = IsolationMode(isolation).value
    max_turns = _coerce_optional_int(defaults.get("max_turns"))
    if max_turns is not None:
        normalized["max_turns"] = max_turns
    return normalized


def _validate_member_name(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        raise TeamControlError("invalid_request", "Team member name must be non-empty")
    if normalized in _RESERVED_MEMBER_NAMES:
        raise TeamControlError(
            "invalid_request",
            f"Team member name '{normalized}' is reserved",
            name=normalized,
        )
    if not _MEMBER_NAME_PATTERN.fullmatch(normalized):
        raise TeamControlError(
            "invalid_request",
            "Team member names may contain only letters, numbers, '.', '_' and '-'",
            name=normalized,
        )
    return normalized


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


def _json_safe_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): inner for key, inner in value.items()}


def _coerce_mapping(value: object) -> dict[str, Any]:
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
    "FileBackedTeamStore",
    "InMemoryTeamStore",
    "RuntimeTeamControlPlane",
    "RuntimeTeamRunnerManager",
    "TeamStore",
    "TeamActor",
    "TeamControlError",
    "TeamEvent",
    "TeamLeaderBinding",
    "TeamMemberRecord",
    "TeamMemberStatus",
    "TeamRecord",
    "TeamRole",
    "TeamStatus",
]
