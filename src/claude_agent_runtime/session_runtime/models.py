from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..contracts import (
    ContentBlock,
    MessageRole,
    RuntimeMessage,
    SessionCommand,
    SessionCommandType,
    SessionState,
    SessionStatus,
    coerce_content_blocks,
    content_blocks_to_text,
)


class IngressAdmissionKind(StrEnum):
    ADMIT_TURN = "admit_turn"
    LOCAL_ONLY = "local_only"
    TRANSCRIPT_ONLY = "transcript_only"
    REPLAY_ONLY = "replay_only"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class IngressAdmission:
    kind: IngressAdmissionKind
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def admits_turn(self) -> bool:
        return self.kind == IngressAdmissionKind.ADMIT_TURN


@dataclass(frozen=True, slots=True)
class IngressReplayOutput:
    output_id: str
    role: MessageRole
    content: tuple[ContentBlock, ...]
    visibility: str = "host"
    source: str = "ingress"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", coerce_content_blocks(self.content))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def text(self) -> str:
        return content_blocks_to_text(self.content)


@dataclass(frozen=True, slots=True)
class SessionIngressResult:
    admission: IngressAdmission
    normalized_messages: tuple[RuntimeMessage, ...] = ()
    replay_outputs: tuple[IngressReplayOutput, ...] = ()
    prompt_updates: dict[str, Any] = field(default_factory=dict)
    private_updates: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_messages", tuple(self.normalized_messages))
        object.__setattr__(self, "replay_outputs", tuple(self.replay_outputs))
        object.__setattr__(self, "prompt_updates", dict(self.prompt_updates))
        object.__setattr__(self, "private_updates", dict(self.private_updates))
        self._validate()

    @property
    def admits_turn(self) -> bool:
        return self.admission.admits_turn

    @classmethod
    def admit_turn(
        cls,
        *,
        normalized_messages: tuple[RuntimeMessage, ...],
        replay_outputs: tuple[IngressReplayOutput, ...] = (),
        prompt_updates: dict[str, Any] | None = None,
        private_updates: dict[str, Any] | None = None,
        reason: str = "admitted",
        metadata: dict[str, Any] | None = None,
    ) -> SessionIngressResult:
        return cls(
            admission=IngressAdmission(
                kind=IngressAdmissionKind.ADMIT_TURN,
                reason=reason,
                metadata=dict(metadata or {}),
            ),
            normalized_messages=normalized_messages,
            replay_outputs=replay_outputs,
            prompt_updates=dict(prompt_updates or {}),
            private_updates=dict(private_updates or {}),
        )

    @classmethod
    def local_only(
        cls,
        *,
        normalized_messages: tuple[RuntimeMessage, ...] = (),
        replay_outputs: tuple[IngressReplayOutput, ...] = (),
        private_updates: dict[str, Any] | None = None,
        reason: str = "local_only",
        metadata: dict[str, Any] | None = None,
    ) -> SessionIngressResult:
        return cls(
            admission=IngressAdmission(
                kind=IngressAdmissionKind.LOCAL_ONLY,
                reason=reason,
                metadata=dict(metadata or {}),
            ),
            normalized_messages=normalized_messages,
            replay_outputs=replay_outputs,
            private_updates=dict(private_updates or {}),
        )

    @classmethod
    def transcript_only(
        cls,
        *,
        normalized_messages: tuple[RuntimeMessage, ...],
        replay_outputs: tuple[IngressReplayOutput, ...] = (),
        private_updates: dict[str, Any] | None = None,
        reason: str = "transcript_only",
        metadata: dict[str, Any] | None = None,
    ) -> SessionIngressResult:
        return cls(
            admission=IngressAdmission(
                kind=IngressAdmissionKind.TRANSCRIPT_ONLY,
                reason=reason,
                metadata=dict(metadata or {}),
            ),
            normalized_messages=normalized_messages,
            replay_outputs=replay_outputs,
            private_updates=dict(private_updates or {}),
        )

    @classmethod
    def replay_only(
        cls,
        *,
        replay_outputs: tuple[IngressReplayOutput, ...],
        private_updates: dict[str, Any] | None = None,
        reason: str = "replay_only",
        metadata: dict[str, Any] | None = None,
    ) -> SessionIngressResult:
        return cls(
            admission=IngressAdmission(
                kind=IngressAdmissionKind.REPLAY_ONLY,
                reason=reason,
                metadata=dict(metadata or {}),
            ),
            replay_outputs=replay_outputs,
            private_updates=dict(private_updates or {}),
        )

    @classmethod
    def reject(
        cls,
        *,
        replay_outputs: tuple[IngressReplayOutput, ...] = (),
        private_updates: dict[str, Any] | None = None,
        reason: str = "rejected",
        metadata: dict[str, Any] | None = None,
    ) -> SessionIngressResult:
        return cls(
            admission=IngressAdmission(
                kind=IngressAdmissionKind.REJECT,
                reason=reason,
                metadata=dict(metadata or {}),
            ),
            replay_outputs=replay_outputs,
            private_updates=dict(private_updates or {}),
        )

    def _validate(self) -> None:
        kind = self.admission.kind
        if kind == IngressAdmissionKind.ADMIT_TURN and not self.normalized_messages:
            raise ValueError("admit_turn ingress results must include normalized messages")
        if kind == IngressAdmissionKind.TRANSCRIPT_ONLY and not self.normalized_messages:
            raise ValueError("transcript_only ingress results must include normalized messages")
        if kind == IngressAdmissionKind.REPLAY_ONLY and not self.replay_outputs:
            raise ValueError("replay_only ingress results must include replay outputs")
        if kind in (
            IngressAdmissionKind.LOCAL_ONLY,
            IngressAdmissionKind.TRANSCRIPT_ONLY,
            IngressAdmissionKind.REPLAY_ONLY,
            IngressAdmissionKind.REJECT,
        ) and self.prompt_updates:
            raise ValueError(f"{kind.value} ingress results cannot carry prompt updates")
        if kind in (IngressAdmissionKind.REPLAY_ONLY, IngressAdmissionKind.REJECT) and self.normalized_messages:
            raise ValueError(f"{kind.value} ingress results cannot carry normalized messages")


@dataclass(frozen=True, slots=True)
class SessionIngressSnapshot:
    session_id: str
    current_agent: str
    cwd: str
    status: SessionStatus = SessionStatus.IDLE
    active_turn_id: str | None = None
    messages: tuple[RuntimeMessage, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_state(
        cls,
        state: SessionState,
        *,
        cwd: str,
        messages: tuple[RuntimeMessage, ...] = (),
    ) -> SessionIngressSnapshot:
        return cls(
            session_id=state.session_id,
            current_agent=state.current_agent,
            cwd=cwd,
            status=state.status,
            active_turn_id=state.active_turn_id,
            messages=messages,
            metadata=state.metadata,
        )

__all__ = [
    "IngressAdmission",
    "IngressAdmissionKind",
    "IngressReplayOutput",
    "SessionCommand",
    "SessionCommandType",
    "SessionIngressResult",
    "SessionIngressSnapshot",
    "SessionState",
    "SessionStatus",
]
