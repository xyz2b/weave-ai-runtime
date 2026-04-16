from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..contracts import RuntimeMessage
from ..definitions import AgentDefinition


@dataclass(frozen=True, slots=True)
class CompactionPolicy:
    enabled: bool = True
    force: bool = False
    max_message_count: int | None = None
    max_characters: int | None = None
    keep_recent_messages: int = 4
    summary_line_limit: int = 6
    summary_line_width: int = 120
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_runtime_context(
        cls,
        runtime_context: Mapping[str, Any] | None,
        *,
        default: "CompactionPolicy | None" = None,
    ) -> "CompactionPolicy":
        base = default or cls()
        if runtime_context is None:
            return base

        raw_policy = runtime_context.get("compaction_policy")
        if raw_policy is None:
            raw_policy = {}
        if raw_policy is False:
            return cls(enabled=False)
        if raw_policy is True:
            raw_policy = {}
        if not isinstance(raw_policy, Mapping):
            return base

        return cls(
            enabled=_coerce_bool(raw_policy.get("enabled"), default=base.enabled),
            force=_coerce_bool(
                runtime_context.get("force_compaction", raw_policy.get("force")),
                default=base.force,
            ),
            max_message_count=_coerce_int(
                raw_policy.get("max_message_count"),
                default=base.max_message_count,
            ),
            max_characters=_coerce_int(
                raw_policy.get("max_characters"),
                default=base.max_characters,
            ),
            keep_recent_messages=max(
                0,
                _coerce_int(raw_policy.get("keep_recent_messages"), default=base.keep_recent_messages) or 0,
            ),
            summary_line_limit=max(
                1,
                _coerce_int(raw_policy.get("summary_line_limit"), default=base.summary_line_limit) or 1,
            ),
            summary_line_width=max(
                40,
                _coerce_int(raw_policy.get("summary_line_width"), default=base.summary_line_width) or 40,
            ),
            metadata={
                **dict(base.metadata),
                **{
                    str(key): value
                    for key, value in raw_policy.items()
                    if str(key)
                    not in {
                        "enabled",
                        "force",
                        "max_message_count",
                        "max_characters",
                        "keep_recent_messages",
                        "summary_line_limit",
                        "summary_line_width",
                    }
                },
            },
        )


@dataclass(frozen=True, slots=True)
class ContextPressure:
    message_count: int
    character_count: int
    max_message_count: int | None = None
    max_characters: int | None = None
    message_limit_exceeded: bool = False
    character_limit_exceeded: bool = False
    triggered: bool = False


@dataclass(frozen=True, slots=True)
class CompactionRequest:
    session_id: str
    turn_id: str
    agent: AgentDefinition
    cwd: str
    messages: tuple[RuntimeMessage, ...]
    runtime_context: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CompactionBoundary:
    boundary_id: str
    start_index: int
    end_index: int
    source_message_ids: tuple[str, ...]
    preserved_message_ids: tuple[str, ...]
    message_count_before: int
    message_count_after: int
    trigger: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompactionSummary:
    summary_id: str
    text: str
    source_message_ids: tuple[str, ...]
    message_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompactionContinuation:
    mode: str
    summary_id: str | None = None
    resume_message_id: str | None = None
    resumable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompactionStepResult:
    strategy_name: str
    applied: bool
    messages: tuple[RuntimeMessage, ...]
    fragments: tuple[str, ...] = ()
    summary: CompactionSummary | None = None
    boundary: CompactionBoundary | None = None
    continuation: CompactionContinuation | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompactionResult:
    messages: tuple[RuntimeMessage, ...]
    policy: CompactionPolicy
    pressure: ContextPressure
    applied: bool = False
    steps: tuple[CompactionStepResult, ...] = ()
    fragments: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> CompactionSummary | None:
        for step in reversed(self.steps):
            if step.summary is not None:
                return step.summary
        return None

    @property
    def boundary(self) -> CompactionBoundary | None:
        for step in reversed(self.steps):
            if step.boundary is not None:
                return step.boundary
        return None

    @property
    def continuation(self) -> CompactionContinuation | None:
        for step in reversed(self.steps):
            if step.continuation is not None:
                return step.continuation
        return None


def serialize_compaction_policy(policy: CompactionPolicy) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "force": policy.force,
        "max_message_count": policy.max_message_count,
        "max_characters": policy.max_characters,
        "keep_recent_messages": policy.keep_recent_messages,
        "summary_line_limit": policy.summary_line_limit,
        "summary_line_width": policy.summary_line_width,
        "metadata": dict(policy.metadata),
    }


def serialize_context_pressure(pressure: ContextPressure) -> dict[str, Any]:
    return {
        "message_count": pressure.message_count,
        "character_count": pressure.character_count,
        "max_message_count": pressure.max_message_count,
        "max_characters": pressure.max_characters,
        "message_limit_exceeded": pressure.message_limit_exceeded,
        "character_limit_exceeded": pressure.character_limit_exceeded,
        "triggered": pressure.triggered,
    }


def serialize_compaction_boundary(boundary: CompactionBoundary | None) -> dict[str, Any] | None:
    if boundary is None:
        return None
    return {
        "boundary_id": boundary.boundary_id,
        "start_index": boundary.start_index,
        "end_index": boundary.end_index,
        "source_message_ids": list(boundary.source_message_ids),
        "preserved_message_ids": list(boundary.preserved_message_ids),
        "message_count_before": boundary.message_count_before,
        "message_count_after": boundary.message_count_after,
        "trigger": boundary.trigger,
        "metadata": dict(boundary.metadata),
    }


def serialize_compaction_summary(summary: CompactionSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {
        "summary_id": summary.summary_id,
        "text": summary.text,
        "source_message_ids": list(summary.source_message_ids),
        "message_count": summary.message_count,
        "metadata": dict(summary.metadata),
    }


def serialize_compaction_continuation(
    continuation: CompactionContinuation | None,
) -> dict[str, Any] | None:
    if continuation is None:
        return None
    return {
        "mode": continuation.mode,
        "summary_id": continuation.summary_id,
        "resume_message_id": continuation.resume_message_id,
        "resumable": continuation.resumable,
        "metadata": dict(continuation.metadata),
    }


def serialize_compaction_step(step: CompactionStepResult) -> dict[str, Any]:
    return {
        "strategy_name": step.strategy_name,
        "applied": step.applied,
        "fragments": list(step.fragments),
        "summary": serialize_compaction_summary(step.summary),
        "boundary": serialize_compaction_boundary(step.boundary),
        "continuation": serialize_compaction_continuation(step.continuation),
        "metadata": dict(step.metadata),
    }


def serialize_compaction_result(result: CompactionResult) -> dict[str, Any]:
    payload = {
        "applied": result.applied,
        "policy": serialize_compaction_policy(result.policy),
        "pressure": serialize_context_pressure(result.pressure),
        "fragments": list(result.fragments),
        "summary": serialize_compaction_summary(result.summary),
        "boundary": serialize_compaction_boundary(result.boundary),
        "continuation": serialize_compaction_continuation(result.continuation),
        "steps": [serialize_compaction_step(step) for step in result.steps],
        "metadata": dict(result.metadata),
    }
    return payload


def latest_compaction_payload(messages: Sequence[RuntimeMessage]) -> dict[str, Any] | None:
    for message in reversed(messages):
        payload = message.metadata.get("compaction")
        if isinstance(payload, Mapping):
            return dict(payload)
    return None


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _coerce_int(value: object, *, default: int | None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default
