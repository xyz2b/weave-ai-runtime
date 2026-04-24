from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping
from uuid import uuid4

from ..contracts import MessageAttachment, MessageRole, RuntimeMessage
from ..runtime_services import RuntimeServices
from .models import (
    IngressAdmissionKind,
    IngressReplayOutput,
    SessionIngressResult,
    SessionIngressSnapshot,
)

if TYPE_CHECKING:
    from .controller import InboundEvent

_CONTROL_METADATA_KEYS = frozenset(
    {
        "admission_kind",
        "ingress_reason",
        "prompt_updates",
        "private_updates",
        "replay_outputs",
        "replay_text",
        "replay_role",
        "replay_visibility",
        "replay_source",
        "replay_metadata",
        "team_delivery_ack",
        "ingress_priority",
        "role",
        "source",
        "visibility",
        "transcript_visible",
    }
)


@dataclass(slots=True)
class SessionIngressProcessor:
    def process(
        self,
        event: InboundEvent,
        *,
        session_snapshot: SessionIngressSnapshot,
        runtime_services: RuntimeServices,
    ) -> SessionIngressResult:
        metadata = _copy_mapping(getattr(event, "metadata", None))
        event_type = _event_type_name(event)
        admission_kind, invalid_admission_kind = _resolve_admission_kind(event_type, metadata)
        reason = str(
            metadata.get("ingress_reason")
            or ("invalid_admission_kind" if invalid_admission_kind is not None else admission_kind.value)
        )
        normalized_messages = self._build_normalized_messages(
            event,
            metadata=metadata,
            event_type=event_type,
            admission_kind=admission_kind,
        )
        replay_outputs = self._build_replay_outputs(
            event,
            metadata=metadata,
            event_type=event_type,
            admission_kind=admission_kind,
        )
        prompt_updates = _merge_context_updates(
            runtime_services.metadata.get("ingress_prompt_defaults"),
            session_snapshot.metadata.get("ingress_prompt_defaults"),
            metadata.get("prompt_updates"),
        )
        private_updates = _merge_context_updates(
            runtime_services.metadata.get("ingress_private_defaults"),
            session_snapshot.metadata.get("ingress_private_defaults"),
            _metadata_private_updates(metadata),
            _invalid_admission_private_updates(invalid_admission_kind),
            metadata.get("private_updates"),
        )

        if admission_kind == IngressAdmissionKind.ADMIT_TURN:
            return SessionIngressResult.admit_turn(
                normalized_messages=normalized_messages,
                replay_outputs=replay_outputs,
                prompt_updates=prompt_updates,
                private_updates=private_updates,
                reason=reason,
            )
        if admission_kind == IngressAdmissionKind.LOCAL_ONLY:
            return SessionIngressResult.local_only(
                normalized_messages=normalized_messages,
                replay_outputs=replay_outputs,
                private_updates=private_updates,
                reason=reason,
            )
        if admission_kind == IngressAdmissionKind.TRANSCRIPT_ONLY:
            return SessionIngressResult.transcript_only(
                normalized_messages=normalized_messages,
                replay_outputs=replay_outputs,
                private_updates=private_updates,
                reason=reason,
            )
        if admission_kind == IngressAdmissionKind.REPLAY_ONLY:
            return SessionIngressResult.replay_only(
                replay_outputs=replay_outputs,
                private_updates=private_updates,
                reason=reason,
            )
        return SessionIngressResult.reject(
            replay_outputs=replay_outputs,
            private_updates=private_updates,
            reason=reason,
        )

    def _build_normalized_messages(
        self,
        event: InboundEvent,
        *,
        metadata: dict[str, Any],
        event_type: str,
        admission_kind: IngressAdmissionKind,
    ) -> tuple[RuntimeMessage, ...]:
        if admission_kind in (IngressAdmissionKind.REPLAY_ONLY, IngressAdmissionKind.REJECT):
            return ()
        content = str(getattr(event, "content", ""))
        if not content and not _wants_transcript_entry(admission_kind, metadata):
            return ()
        if admission_kind == IngressAdmissionKind.LOCAL_ONLY and not _wants_transcript_entry(
            admission_kind,
            metadata,
        ):
            return ()
        message = RuntimeMessage(
            message_id=uuid4().hex,
            role=_resolve_message_role(event_type, metadata),
            content=content,
            attachments=_coerce_attachments(metadata),
            metadata=_normalized_message_metadata(metadata, event_type),
        )
        return (message,)

    def _build_replay_outputs(
        self,
        event: InboundEvent,
        *,
        metadata: dict[str, Any],
        event_type: str,
        admission_kind: IngressAdmissionKind,
    ) -> tuple[IngressReplayOutput, ...]:
        explicit = metadata.get("replay_outputs")
        if isinstance(explicit, list):
            outputs: list[IngressReplayOutput] = []
            for raw_output in explicit:
                if not isinstance(raw_output, Mapping):
                    continue
                outputs.append(
                    IngressReplayOutput(
                        output_id=str(raw_output.get("output_id") or uuid4().hex),
                        role=_coerce_message_role(raw_output.get("role"), fallback=MessageRole.NOTIFICATION),
                        content=str(raw_output.get("content") or ""),
                        visibility=str(raw_output.get("visibility") or "host"),
                        source=str(raw_output.get("source") or event_type),
                        metadata=_copy_mapping(raw_output.get("metadata")),
                    )
                )
            return tuple(outputs)

        replay_text = metadata.get("replay_text")
        if isinstance(replay_text, str) and replay_text:
            return (
                IngressReplayOutput(
                    output_id=uuid4().hex,
                    role=_coerce_message_role(metadata.get("replay_role"), fallback=MessageRole.NOTIFICATION),
                    content=replay_text,
                    visibility=str(metadata.get("replay_visibility") or "host"),
                    source=str(metadata.get("replay_source") or event_type),
                    metadata=_copy_mapping(metadata.get("replay_metadata")),
                ),
            )

        if admission_kind == IngressAdmissionKind.LOCAL_ONLY and str(getattr(event, "content", "")):
            return (
                IngressReplayOutput(
                    output_id=uuid4().hex,
                    role=MessageRole.NOTIFICATION,
                    content=str(getattr(event, "content", "")),
                    visibility="host",
                    source=event_type,
                ),
            )
        return ()


def _resolve_admission_kind(
    event_type: str,
    metadata: Mapping[str, Any],
) -> tuple[IngressAdmissionKind, str | None]:
    raw = metadata.get("admission_kind")
    if isinstance(raw, str):
        try:
            return IngressAdmissionKind(raw), None
        except ValueError:
            return IngressAdmissionKind.REJECT, raw
    if event_type in {"user_prompt", "system_message"}:
        return IngressAdmissionKind.ADMIT_TURN, None
    if event_type == "task_notification":
        return IngressAdmissionKind.TRANSCRIPT_ONLY, None
    if event_type == "host_event":
        return IngressAdmissionKind.LOCAL_ONLY, None
    return IngressAdmissionKind.REJECT, None


def _event_type_name(event: InboundEvent) -> str:
    event_type = getattr(event, "event_type", None)
    value = getattr(event_type, "value", event_type)
    return str(value or "unknown")


def _resolve_message_role(event_type: str, metadata: Mapping[str, Any]) -> MessageRole:
    explicit = metadata.get("role")
    if explicit is not None:
        return _coerce_message_role(explicit, fallback=MessageRole.USER)
    if event_type == "system_message":
        return MessageRole.SYSTEM
    if event_type == "task_notification":
        return MessageRole.NOTIFICATION
    return MessageRole.USER


def _coerce_message_role(value: object, *, fallback: MessageRole) -> MessageRole:
    if isinstance(value, MessageRole):
        return value
    if isinstance(value, str):
        return MessageRole(value)
    return fallback


def _normalized_message_metadata(metadata: Mapping[str, Any], event_type: str) -> dict[str, Any]:
    filtered = {str(key): value for key, value in metadata.items() if key not in _CONTROL_METADATA_KEYS}
    source = metadata.get("source")
    visibility = metadata.get("visibility")
    if isinstance(source, str) and source:
        filtered.setdefault("source", source)
    elif event_type != "user_prompt":
        filtered.setdefault("source", event_type)
    if isinstance(visibility, str) and visibility:
        filtered.setdefault("visibility", visibility)
    elif event_type != "user_prompt":
        filtered.setdefault("visibility", "transcript")
    return filtered


def _metadata_private_updates(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in metadata.items() if key not in _CONTROL_METADATA_KEYS}


def _invalid_admission_private_updates(raw_value: str | None) -> dict[str, Any]:
    if raw_value is None:
        return {}
    return {"invalid_admission_kind": raw_value}


def _copy_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _merge_context_updates(*values: object) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        for key, item in value.items():
            merged[str(key)] = item
    return merged


def _wants_transcript_entry(admission_kind: IngressAdmissionKind, metadata: Mapping[str, Any]) -> bool:
    explicit = metadata.get("transcript_visible")
    if isinstance(explicit, bool):
        return explicit
    return admission_kind in (
        IngressAdmissionKind.ADMIT_TURN,
        IngressAdmissionKind.TRANSCRIPT_ONLY,
    )


def _coerce_attachments(metadata: Mapping[str, Any]) -> tuple[MessageAttachment, ...]:
    raw = metadata.get("attachments")
    if not isinstance(raw, list):
        return ()
    attachments: list[MessageAttachment] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        path = item.get("path")
        name = item.get("name")
        if not isinstance(path, str) or not path.strip():
            continue
        if not isinstance(name, str) or not name.strip():
            name = path.strip().split("/")[-1] or path.strip()
        mime_type = item.get("mime_type")
        attachments.append(
            MessageAttachment(
                name=name.strip(),
                path=path.strip(),
                mime_type=str(mime_type).strip() if mime_type else None,
                metadata={
                    str(key): value
                    for key, value in item.items()
                    if key not in {"name", "path", "mime_type"}
                },
            )
        )
    return tuple(attachments)
