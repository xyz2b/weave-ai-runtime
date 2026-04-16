from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Mapping

from ..definitions import PermissionBehavior, PermissionDecision, PermissionMode


class PermissionTarget(StrEnum):
    TOOL = "tool"
    SKILL = "skill"
    AGENT = "agent"
    HOST = "host"


@dataclass(frozen=True, slots=True)
class PermissionRule:
    selector: str
    behavior: PermissionBehavior
    target: PermissionTarget | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(self, request: "PermissionRequest") -> bool:
        if self.target is not None and self.target != request.target:
            return False
        if self.selector == "*":
            return True
        return self.selector == request.name


@dataclass(frozen=True, slots=True)
class PermissionContext:
    session_id: str
    mode: PermissionMode = PermissionMode.DEFAULT
    rules: tuple[PermissionRule, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_rule(self, rule: PermissionRule) -> "PermissionContext":
        return replace(self, rules=self.rules + (rule,))


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    session_id: str
    turn_id: str | None
    target: PermissionTarget
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    context: PermissionContext | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_payload(self, payload: Mapping[str, Any]) -> "PermissionRequest":
        return replace(self, payload=dict(payload))


@dataclass(frozen=True, slots=True)
class PermissionOutcome:
    behavior: PermissionBehavior
    message: str | None = None
    updated_input: dict[str, Any] | None = None
    details: dict[str, Any] = field(default_factory=dict)
    source: str | None = None

    def to_decision(self) -> PermissionDecision:
        return PermissionDecision(
            behavior=self.behavior,
            message=self.message,
            updated_input=None if self.updated_input is None else dict(self.updated_input),
            details={
                **dict(self.details),
                **({"source": self.source} if self.source is not None else {}),
            },
        )


def coerce_permission_outcome(
    value: PermissionDecision | PermissionOutcome | None,
) -> PermissionOutcome:
    if value is None:
        return PermissionOutcome(PermissionBehavior.ALLOW)
    if isinstance(value, PermissionOutcome):
        return value
    return PermissionOutcome(
        behavior=value.behavior,
        message=value.message,
        updated_input=None if value.updated_input is None else dict(value.updated_input),
        details=dict(value.details),
    )


__all__ = [
    "PermissionContext",
    "PermissionOutcome",
    "PermissionRequest",
    "PermissionRule",
    "PermissionTarget",
    "coerce_permission_outcome",
]
