from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol
from uuid import uuid4

from .contracts import utc_now
from .team_control_plane import (
    TeamControlError,
    TeamEvent,
    TeamMemberRecord,
    TeamRole,
    TeamStatus,
)
from .team_workflows import (
    TeamWorkflowKind,
    parse_workflow_request_protocol,
    parse_workflow_response_protocol,
    workflow_priority,
)

if TYPE_CHECKING:
    from .runtime_services import RuntimeServices
    from .team_control_plane import RuntimeTeamControlPlane, TeamRecord

_SCHEMA_VERSION = 1


class TeamMessageKind(StrEnum):
    DIRECT = "direct"
    BROADCAST = "broadcast"
    CONTROL = "control"


@dataclass(frozen=True, slots=True)
class TeamSender:
    member_id: str
    role: TeamRole
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "role": self.role.value,
            "name": self.name,
        }

    @classmethod
    def from_member(cls, member: TeamMemberRecord) -> "TeamSender":
        return cls(member_id=member.member_id, role=member.role, name=member.name)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamSender":
        payload = dict(value)
        return cls(
            member_id=str(payload.get("member_id") or ""),
            role=TeamRole(str(payload.get("role") or TeamRole.TEAMMATE.value)),
            name=str(payload.get("name") or ""),
        )


@dataclass(frozen=True, slots=True)
class TeamMessageDelivery:
    delivery_id: str
    recipient_member_id: str
    recipient_role: TeamRole
    recipient_name: str
    route: str
    queued: bool = True
    created_at: datetime = field(default_factory=utc_now)
    delivered_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def pending(self) -> bool:
        return self.delivered_at is None

    def mark_delivered(self) -> "TeamMessageDelivery":
        return replace(self, queued=False, delivered_at=utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "recipient_member_id": self.recipient_member_id,
            "recipient_role": self.recipient_role.value,
            "recipient_name": self.recipient_name,
            "route": self.route,
            "queued": self.queued,
            "created_at": _utc_isoformat(self.created_at),
            "delivered_at": _utc_isoformat(self.delivered_at) if self.delivered_at is not None else None,
            "metadata": {str(key): value for key, value in self.metadata.items()},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamMessageDelivery":
        payload = dict(value)
        return cls(
            delivery_id=str(payload.get("delivery_id") or ""),
            recipient_member_id=str(payload.get("recipient_member_id") or ""),
            recipient_role=TeamRole(str(payload.get("recipient_role") or TeamRole.TEAMMATE.value)),
            recipient_name=str(payload.get("recipient_name") or ""),
            route=str(payload.get("route") or ""),
            queued=bool(payload.get("queued", True)),
            created_at=_parse_utc_timestamp(payload.get("created_at")) or utc_now(),
            delivered_at=_parse_utc_timestamp(payload.get("delivered_at")),
            metadata=_coerce_mapping(payload.get("metadata")),
        )


@dataclass(frozen=True, slots=True)
class TeamMessageEnvelope:
    message_id: str
    team_id: str
    sender: TeamSender
    kind: TeamMessageKind
    public_to: str
    content: str
    deliveries: tuple[TeamMessageDelivery, ...]
    created_at: datetime = field(default_factory=utc_now)
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "deliveries", tuple(self.deliveries))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "message_id": self.message_id,
            "team_id": self.team_id,
            "sender": self.sender.to_dict(),
            "kind": self.kind.value,
            "public_to": self.public_to,
            "content": self.content,
            "deliveries": [delivery.to_dict() for delivery in self.deliveries],
            "created_at": _utc_isoformat(self.created_at),
            "correlation_id": self.correlation_id,
            "metadata": _coerce_mapping(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TeamMessageEnvelope":
        payload = dict(value)
        deliveries = payload.get("deliveries")
        return cls(
            schema_version=int(payload.get("schema_version") or _SCHEMA_VERSION),
            message_id=str(payload.get("message_id") or ""),
            team_id=str(payload.get("team_id") or ""),
            sender=TeamSender.from_dict(_coerce_mapping(payload.get("sender"))),
            kind=TeamMessageKind(str(payload.get("kind") or TeamMessageKind.DIRECT.value)),
            public_to=str(payload.get("public_to") or ""),
            content=str(payload.get("content") or ""),
            deliveries=tuple(
                TeamMessageDelivery.from_dict(item)
                for item in deliveries
                if isinstance(item, Mapping)
            )
            if isinstance(deliveries, list)
            else (),
            created_at=_parse_utc_timestamp(payload.get("created_at")) or utc_now(),
            correlation_id=_coerce_optional_string(payload.get("correlation_id")),
            metadata=_coerce_mapping(payload.get("metadata")),
        )


class TeamMessageStore(Protocol):
    def publish(self, envelope: TeamMessageEnvelope) -> TeamMessageEnvelope: ...

    def save(self, envelope: TeamMessageEnvelope) -> TeamMessageEnvelope: ...

    def load(self, team_id: str, message_id: str) -> TeamMessageEnvelope | None: ...

    def list_messages(
        self,
        team_id: str,
        *,
        recipient_member_id: str | None = None,
    ) -> tuple[TeamMessageEnvelope, ...]: ...


class InMemoryTeamMessageStore:
    def __init__(self) -> None:
        self._messages: dict[tuple[str, str], TeamMessageEnvelope] = {}

    def publish(self, envelope: TeamMessageEnvelope) -> TeamMessageEnvelope:
        key = (envelope.team_id, envelope.message_id)
        if key in self._messages:
            raise FileExistsError(envelope.message_id)
        self._messages[key] = envelope
        return envelope

    def save(self, envelope: TeamMessageEnvelope) -> TeamMessageEnvelope:
        self._messages[(envelope.team_id, envelope.message_id)] = envelope
        return envelope

    def load(self, team_id: str, message_id: str) -> TeamMessageEnvelope | None:
        return self._messages.get((str(team_id), str(message_id)))

    def list_messages(
        self,
        team_id: str,
        *,
        recipient_member_id: str | None = None,
    ) -> tuple[TeamMessageEnvelope, ...]:
        messages = [
            envelope
            for (candidate_team_id, _), envelope in self._messages.items()
            if candidate_team_id == str(team_id)
        ]
        if recipient_member_id is not None:
            messages = [
                envelope
                for envelope in messages
                if any(
                    delivery.recipient_member_id == recipient_member_id
                    for delivery in envelope.deliveries
                )
            ]
        messages.sort(key=lambda envelope: (envelope.created_at, envelope.message_id))
        return tuple(messages)


class FileBackedTeamMessageBus:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def publish(self, envelope: TeamMessageEnvelope) -> TeamMessageEnvelope:
        _atomic_write_json(self._message_path(envelope.team_id, envelope.message_id), envelope.to_dict())
        return envelope

    def save(self, envelope: TeamMessageEnvelope) -> TeamMessageEnvelope:
        _atomic_write_json(
            self._message_path(envelope.team_id, envelope.message_id),
            envelope.to_dict(),
            replace_existing=True,
        )
        return envelope

    def load(self, team_id: str, message_id: str) -> TeamMessageEnvelope | None:
        path = self._message_path(team_id, message_id)
        if not path.exists():
            return None
        return TeamMessageEnvelope.from_dict(_read_json(path))

    def list_messages(
        self,
        team_id: str,
        *,
        recipient_member_id: str | None = None,
    ) -> tuple[TeamMessageEnvelope, ...]:
        team_root = self._root / "teams" / team_id / "messages"
        if not team_root.exists():
            return ()
        messages: list[TeamMessageEnvelope] = []
        for path in sorted(team_root.glob("*.json")):
            envelope = TeamMessageEnvelope.from_dict(_read_json(path))
            if recipient_member_id is not None and not any(
                delivery.recipient_member_id == recipient_member_id for delivery in envelope.deliveries
            ):
                continue
            messages.append(envelope)
        messages.sort(key=lambda envelope: (envelope.created_at, envelope.message_id))
        return tuple(messages)

    def _message_path(self, team_id: str, message_id: str) -> Path:
        return self._root / "teams" / team_id / "messages" / f"{message_id}.json"


class RuntimeTeamMessageBus:
    def __init__(
        self,
        *,
        store: TeamMessageStore,
        control_plane: RuntimeTeamControlPlane,
        runtime_services: RuntimeServices,
    ) -> None:
        self._store = store
        self._control_plane = control_plane
        self._runtime_services = runtime_services

    @property
    def store(self) -> TeamMessageStore:
        return self._store

    async def send_public_message(
        self,
        *,
        session_id: str,
        extensions: Mapping[str, Any],
        to: str,
        message: str,
    ) -> TeamMessageEnvelope:
        actor = self._control_plane.resolve_actor(session_id=session_id, extensions=extensions)
        if actor.team is None or actor.member is None:
            raise TeamControlError(
                "invalid_team_state",
                "The caller does not have an active runtime team",
                session_id=session_id,
            )
        team = actor.team
        sender = actor.member
        recipients, kind = self._resolve_public_recipients(team=team, sender=sender, to=to)
        envelope = TeamMessageEnvelope(
            message_id=uuid4().hex,
            team_id=team.team_id,
            sender=TeamSender.from_member(sender),
            kind=kind,
            public_to=to,
            content=message,
            deliveries=tuple(
                TeamMessageDelivery(
                    delivery_id=uuid4().hex,
                    recipient_member_id=member.member_id,
                    recipient_role=member.role,
                    recipient_name=member.name,
                    route="leader_ingress" if member.role is TeamRole.LEADER else "teammate_runner",
                    metadata={"public_to": to},
                )
                for member in recipients
            ),
        )
        self._store.publish(envelope)
        for delivery in envelope.deliveries:
            await self._route_delivery(team=team, envelope=envelope, delivery=delivery)
        return envelope

    async def send_control_message(
        self,
        *,
        team_id: str,
        sender_member_id: str,
        recipient_member_id: str,
        control_type: str,
        payload: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
        allow_workflow_response: bool = False,
    ) -> TeamMessageEnvelope:
        team = self._control_plane.get_team(team_id)
        if team is None or team.status is TeamStatus.DELETED:
            raise TeamControlError("invalid_team_state", "Team is not active", team_id=team_id)
        normalized_control_type = str(control_type).strip()
        normalized_payload = _coerce_mapping(payload)
        if not allow_workflow_response and (
            normalized_control_type.endswith("_response")
            or parse_workflow_response_protocol(normalized_payload) is not None
        ):
            raise TeamControlError(
                "invalid_request",
                "Workflow responses must use the runtime-owned workflow response surfaces",
                team_id=team_id,
                control_type=normalized_control_type,
            )
        sender = self._control_plane.get_member(team_id, sender_member_id)
        recipient = self._control_plane.get_member(team_id, recipient_member_id)
        if sender is None or not sender.active:
            raise TeamControlError("not_found", "Sender was not found", team_id=team_id, member_id=sender_member_id)
        if recipient is None or not recipient.active:
            raise TeamControlError(
                "not_found",
                "Recipient was not found",
                team_id=team_id,
                member_id=recipient_member_id,
            )
        envelope = TeamMessageEnvelope(
            message_id=uuid4().hex,
            team_id=team_id,
            sender=TeamSender.from_member(sender),
            kind=TeamMessageKind.CONTROL,
            public_to=recipient.name,
            content=normalized_control_type,
            deliveries=(
                TeamMessageDelivery(
                    delivery_id=uuid4().hex,
                    recipient_member_id=recipient.member_id,
                    recipient_role=recipient.role,
                    recipient_name=recipient.name,
                    route="leader_ingress" if recipient.role is TeamRole.LEADER else "teammate_runner",
                    metadata={"control_type": normalized_control_type, **normalized_payload},
                ),
            ),
            correlation_id=correlation_id or uuid4().hex,
            metadata={"control_type": normalized_control_type, **normalized_payload},
        )
        self._store.publish(envelope)
        await self._route_delivery(team=team, envelope=envelope, delivery=envelope.deliveries[0])
        return envelope

    async def acknowledge_delivery(
        self,
        *,
        team_id: str,
        message_id: str,
        delivery_id: str,
    ) -> bool:
        envelope = self._store.load(team_id, message_id)
        if envelope is None:
            return False
        updated = False
        deliveries: list[TeamMessageDelivery] = []
        for delivery in envelope.deliveries:
            if delivery.delivery_id == delivery_id and delivery.pending:
                deliveries.append(delivery.mark_delivered())
                updated = True
                continue
            deliveries.append(delivery)
        if not updated:
            return False
        self._store.save(replace(envelope, deliveries=tuple(deliveries)))
        return True

    async def replay_pending_leader_messages(self, *, session_id: str) -> int:
        team = self._control_plane.active_team_for_leader_session(session_id)
        if team is None:
            return 0
        leader = self._control_plane.get_member(team.team_id, team.leader_member_id)
        if leader is None or not leader.active:
            return 0
        replayed = 0
        for envelope in self._store.list_messages(team.team_id, recipient_member_id=leader.member_id):
            for delivery in envelope.deliveries:
                if (
                    delivery.recipient_member_id != leader.member_id
                    or delivery.route != "leader_ingress"
                    or not delivery.pending
                ):
                    continue
                await self._route_to_leader(team=team, envelope=envelope, delivery=delivery)
                replayed += 1
        return replayed

    async def _route_delivery(
        self,
        *,
        team: TeamRecord,
        envelope: TeamMessageEnvelope,
        delivery: TeamMessageDelivery,
    ) -> None:
        if delivery.recipient_role is TeamRole.LEADER:
            await self._route_to_leader(team=team, envelope=envelope, delivery=delivery)
            return
        await self._route_to_teammate(team=team, envelope=envelope, delivery=delivery)

    def _resolve_public_recipients(
        self,
        *,
        team: TeamRecord,
        sender: TeamMemberRecord,
        to: str,
    ) -> tuple[tuple[TeamMemberRecord, ...], TeamMessageKind]:
        normalized = str(to).strip()
        if not normalized:
            raise TeamControlError("invalid_request", "team_send requires a non-empty recipient")
        members = self._control_plane.list_members(team.team_id)
        if normalized == "*":
            return (
                tuple(member for member in members if member.member_id != sender.member_id),
                TeamMessageKind.BROADCAST,
            )
        if normalized == TeamRole.LEADER.value:
            leader = self._control_plane.get_member(team.team_id, team.leader_member_id)
            if leader is None or not leader.active:
                raise TeamControlError(
                    "invalid_team_state",
                    "The active team is missing its leader member",
                    team_id=team.team_id,
                )
            return ((leader,), TeamMessageKind.DIRECT)
        if any(token in normalized for token in ("/", ":", "\\")):
            raise TeamControlError(
                "invalid_recipient",
                "Public team recipients resolve only within the caller's active team",
                team_id=team.team_id,
                recipient=normalized,
            )
        member = self._control_plane.store.find_member_by_name(team.team_id, normalized)
        if member is None or not member.active or member.role is TeamRole.LEADER:
            raise TeamControlError(
                "invalid_recipient",
                f"No active teammate named '{normalized}' exists in the caller's active team",
                team_id=team.team_id,
                recipient=normalized,
            )
        return ((member,), TeamMessageKind.DIRECT)

    async def _route_to_leader(
        self,
        *,
        team: TeamRecord,
        envelope: TeamMessageEnvelope,
        delivery: TeamMessageDelivery,
    ) -> None:
        session = self._runtime_services.session_registry.get(team.leader_session_id)
        event = self._leader_ingress_event(team=team, envelope=envelope, delivery=delivery)
        drained = False
        status = None
        if session is not None:
            status = getattr(getattr(session, "state", None), "status", None)
            drain = str(getattr(status, "value", status) or "") == "waiting"
            drained = await session.submit_runtime_event(event, drain=drain)
        await self._emit_team_event(
            event_type="team.message.routed",
            team=team,
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
            member_id=delivery.recipient_member_id,
            payload={
                "route": delivery.route,
                "recipient_name": delivery.recipient_name,
                "queued": True,
                "drained": drained,
                "session_status": str(getattr(status, "value", status) or "offline"),
                "kind": envelope.kind.value,
                "public_to": envelope.public_to,
            },
        )

    async def _route_to_teammate(
        self,
        *,
        team: TeamRecord,
        envelope: TeamMessageEnvelope,
        delivery: TeamMessageDelivery,
    ) -> None:
        member = self._control_plane.get_member(team.team_id, delivery.recipient_member_id)
        if member is None or not member.active:
            raise TeamControlError(
                "invalid_recipient",
                "The resolved teammate recipient is no longer active",
                team_id=team.team_id,
                recipient_member_id=delivery.recipient_member_id,
            )
        prompt = self._teammate_prompt(envelope)
        payload_metadata = {
            "team_message_id": envelope.message_id,
            "team_message_kind": envelope.kind.value,
            "team_message_to": envelope.public_to,
            "team_sender_member_id": envelope.sender.member_id,
            "team_sender_name": envelope.sender.name,
            "team_sender_role": envelope.sender.role.value,
            "correlation_id": envelope.correlation_id,
            **_coerce_mapping(envelope.metadata),
            **_coerce_mapping(delivery.metadata),
        }
        await self._control_plane.runner_manager.dispatch_message(
            team=team,
            member=member,
            prompt=prompt,
            sender={"type": envelope.sender.role.value, "id": envelope.sender.member_id},
            correlation_id=envelope.correlation_id,
            payload_metadata=payload_metadata,
        )
        await self._emit_team_event(
            event_type="team.message.routed",
            team=team,
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
            member_id=member.member_id,
            payload={
                "route": delivery.route,
                "recipient_name": member.name,
                "queued": True,
                "kind": envelope.kind.value,
                "public_to": envelope.public_to,
            },
        )

    def _leader_ingress_event(
        self,
        *,
        team: TeamRecord,
        envelope: TeamMessageEnvelope,
        delivery: TeamMessageDelivery,
    ) -> Any:
        from .session_runtime import InboundEvent, InboundEventType

        if envelope.kind is TeamMessageKind.CONTROL:
            control_type = str(envelope.metadata.get("control_type") or envelope.content)
            request_protocol = parse_workflow_request_protocol(envelope.metadata)
            if request_protocol is not None and self._workflow_request_is_actionable(
                team=team,
                workflow_id=request_protocol.workflow_id,
                workflow_kind=request_protocol.workflow_kind,
            ):
                workflow_private = {
                    "workflow_id": request_protocol.workflow_id,
                    "workflow_kind": request_protocol.workflow_kind.value,
                    "requester_member_id": request_protocol.requester_member_id,
                    "requester_name": request_protocol.requester_name,
                    "allowed_actions": list(request_protocol.allowed_actions),
                }
                return InboundEvent(
                    event_type=InboundEventType.HOST_EVENT,
                    content=request_protocol.summary
                    or f"Team workflow '{request_protocol.workflow_id}' requires a response",
                    metadata={
                        "admission_kind": "admit_turn",
                        "role": "user",
                        "source": "team_workflow_request",
                        "visibility": "transcript",
                        "workflow_id": request_protocol.workflow_id,
                        "workflow_kind": request_protocol.workflow_kind.value,
                        "workflow_requester_member_id": request_protocol.requester_member_id,
                        "workflow_requester_name": request_protocol.requester_name,
                        "team_delivery_ack": {
                            "team_id": team.team_id,
                            "message_id": envelope.message_id,
                            "delivery_id": delivery.delivery_id,
                        },
                        "ingress_priority": int(
                            envelope.metadata.get("workflow_priority")
                            or workflow_priority(request_protocol.workflow_kind)
                        ),
                        "private_updates": {
                            "team_last_workflow_request": workflow_private,
                            "team_workflow_requests": {
                                request_protocol.workflow_id: workflow_private,
                            },
                            "team_last_control_message": {
                                "team_id": team.team_id,
                                "message_id": envelope.message_id,
                                "control_type": control_type,
                                "sender_member_id": envelope.sender.member_id,
                                "sender_name": envelope.sender.name,
                                "correlation_id": envelope.correlation_id,
                                "content": envelope.content,
                                "payload": _coerce_mapping(envelope.metadata),
                            },
                        },
                    },
                )
            response_protocol = parse_workflow_response_protocol(envelope.metadata)
            if response_protocol is not None:
                logical_sender = _workflow_response_logical_sender(
                    envelope=envelope,
                    response_protocol=response_protocol,
                )
                return InboundEvent(
                    event_type=InboundEventType.HOST_EVENT,
                    content="",
                    metadata={
                        "admission_kind": "replay_only",
                        "team_delivery_ack": {
                            "team_id": team.team_id,
                            "message_id": envelope.message_id,
                            "delivery_id": delivery.delivery_id,
                        },
                        "private_updates": {
                            "team_last_workflow_update": {
                                "workflow_id": response_protocol.workflow_id,
                                "workflow_kind": response_protocol.workflow_kind.value,
                                "status": response_protocol.status.value,
                                "response_action": response_protocol.response_action,
                                "actor_kind": response_protocol.actor_kind.value,
                                "actor_id": response_protocol.actor_id,
                            },
                            "team_last_control_message": {
                                "team_id": team.team_id,
                                "message_id": envelope.message_id,
                                "control_type": control_type,
                                "sender_member_id": logical_sender["sender_member_id"],
                                "sender_name": logical_sender["sender_name"],
                                "sender_role": logical_sender["sender_role"],
                                "transport_sender_member_id": envelope.sender.member_id,
                                "transport_sender_name": envelope.sender.name,
                                "transport_sender_role": envelope.sender.role.value,
                                "actor_kind": response_protocol.actor_kind.value,
                                "actor_id": response_protocol.actor_id,
                                "correlation_id": envelope.correlation_id,
                                "content": envelope.content,
                                "payload": _coerce_mapping(envelope.metadata),
                            },
                        },
                        "replay_outputs": [
                            {
                                "output_id": uuid4().hex,
                                "role": "notification",
                                "content": response_protocol.summary
                                or f"Team workflow '{response_protocol.workflow_id}' updated",
                                "visibility": "host",
                                "source": "team_workflow_update",
                                "metadata": {
                                    "team_id": team.team_id,
                                    "message_id": envelope.message_id,
                                    "correlation_id": envelope.correlation_id,
                                    "workflow_id": response_protocol.workflow_id,
                                    "actor_kind": response_protocol.actor_kind.value,
                                    "actor_id": response_protocol.actor_id,
                                },
                            }
                        ],
                        "source": "team_workflow_update",
                        "visibility": "private",
                    },
                )
            return InboundEvent(
                event_type=InboundEventType.HOST_EVENT,
                content="",
                metadata={
                    "admission_kind": "replay_only",
                    "team_delivery_ack": {
                        "team_id": team.team_id,
                        "message_id": envelope.message_id,
                        "delivery_id": delivery.delivery_id,
                    },
                    "private_updates": {
                        "team_last_control_message": {
                            "team_id": team.team_id,
                            "message_id": envelope.message_id,
                            "control_type": control_type,
                            "sender_member_id": envelope.sender.member_id,
                            "sender_name": envelope.sender.name,
                            "correlation_id": envelope.correlation_id,
                            "content": envelope.content,
                            "payload": _coerce_mapping(envelope.metadata),
                        }
                    },
                    "replay_outputs": [
                        {
                            "output_id": uuid4().hex,
                            "role": "notification",
                            "content": f"Team control message '{control_type}' from {envelope.sender.name}",
                            "visibility": "host",
                            "source": "team_control",
                            "metadata": {
                                "team_id": team.team_id,
                                "message_id": envelope.message_id,
                                "correlation_id": envelope.correlation_id,
                            },
                        }
                    ],
                    "source": "team_control_message",
                    "visibility": "private",
                },
            )
        content = f"Message from {envelope.sender.name}: {envelope.content}"
        return InboundEvent(
            event_type=InboundEventType.HOST_EVENT,
            content=content,
            metadata={
                "admission_kind": "admit_turn",
                "role": "user",
                "source": "team_message",
                "visibility": "transcript",
                "team_id": team.team_id,
                "team_message_id": envelope.message_id,
                "team_message_kind": envelope.kind.value,
                "team_sender_member_id": envelope.sender.member_id,
                "team_sender_name": envelope.sender.name,
                "team_sender_role": envelope.sender.role.value,
                "team_recipient_member_id": delivery.recipient_member_id,
                "correlation_id": envelope.correlation_id,
                "team_delivery_ack": {
                    "team_id": team.team_id,
                    "message_id": envelope.message_id,
                    "delivery_id": delivery.delivery_id,
                },
                "private_updates": {
                    "team_last_message": {
                        "team_id": team.team_id,
                        "message_id": envelope.message_id,
                        "sender_member_id": envelope.sender.member_id,
                        "sender_name": envelope.sender.name,
                        "public_to": envelope.public_to,
                        "correlation_id": envelope.correlation_id,
                    }
                },
            },
        )

    def _teammate_prompt(self, envelope: TeamMessageEnvelope) -> str:
        if envelope.kind is TeamMessageKind.CONTROL:
            request_protocol = parse_workflow_request_protocol(envelope.metadata)
            if request_protocol is not None and request_protocol.summary:
                return request_protocol.summary
            response_protocol = parse_workflow_response_protocol(envelope.metadata)
            if response_protocol is not None and response_protocol.summary:
                return response_protocol.summary
            return f"Team control message from {envelope.sender.name}: {envelope.content}"
        return f"Team message from {envelope.sender.name}: {envelope.content}"

    def _workflow_request_is_actionable(
        self,
        *,
        team: TeamRecord,
        workflow_id: str,
        workflow_kind: TeamWorkflowKind,
    ) -> bool:
        if not str(workflow_id).strip():
            return False
        workflow_service = (
            self._runtime_services.resolve_team_workflows()
            if hasattr(self._runtime_services, "resolve_team_workflows")
            else getattr(self._runtime_services, "team_workflows", None)
        )
        if workflow_service is None or not hasattr(workflow_service, "get"):
            return False
        record = workflow_service.get(workflow_id)
        if record is None:
            return False
        if record.team_id != team.team_id or record.terminal:
            return False
        if workflow_kind is TeamWorkflowKind.PERMISSION:
            return bool(record.allowed_actions)
        return bool(record.allowed_actions)

    async def _emit_team_event(
        self,
        *,
        event_type: str,
        team: TeamRecord,
        member_id: str | None = None,
        message_id: str | None = None,
        correlation_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if self._runtime_services.host is None or not hasattr(self._runtime_services.host, "emit_team_event"):
            return
        await self._runtime_services.host.emit_team_event(
            TeamEvent(
                event_id=uuid4().hex,
                event_type=event_type,
                team_id=team.team_id,
                leader_session_id=team.leader_session_id,
                member_id=member_id,
                message_id=message_id,
                correlation_id=correlation_id,
                payload=_coerce_mapping(payload),
            )
        )


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
        return {str(key): inner for key, inner in value.items()}
    return {}


def _workflow_response_logical_sender(
    *,
    envelope: TeamMessageEnvelope,
    response_protocol: Any,
) -> dict[str, Any]:
    actor_kind = str(getattr(response_protocol, "actor_kind", "") or "")
    actor_id = _coerce_optional_string(getattr(response_protocol, "actor_id", None))
    if actor_kind == "host":
        return {
            "sender_member_id": None,
            "sender_name": actor_id or "host",
            "sender_role": "host",
        }
    if actor_kind == "runtime":
        return {
            "sender_member_id": actor_id if actor_id == envelope.sender.member_id else None,
            "sender_name": actor_id or "runtime",
            "sender_role": "runtime",
        }
    return {
        "sender_member_id": envelope.sender.member_id,
        "sender_name": envelope.sender.name,
        "sender_role": envelope.sender.role.value,
    }


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
    "FileBackedTeamMessageBus",
    "InMemoryTeamMessageStore",
    "RuntimeTeamMessageBus",
    "TeamMessageDelivery",
    "TeamMessageEnvelope",
    "TeamMessageKind",
    "TeamMessageStore",
    "TeamSender",
]
