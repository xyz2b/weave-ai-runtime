from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from fnmatch import fnmatch
from typing import Any, Mapping, Sequence

from ..definitions import PermissionBehavior, PermissionDecision, PermissionMode, ToolRiskLevel


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
    scopes: tuple[str, ...] = ()
    risk_levels: tuple[ToolRiskLevel, ...] = ()
    operations: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    read_only: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", _coerce_string_tuple(self.scopes))
        object.__setattr__(self, "risk_levels", _coerce_risk_levels(self.risk_levels))
        object.__setattr__(self, "operations", _coerce_string_tuple(self.operations))
        object.__setattr__(self, "tags", _coerce_string_tuple(self.tags))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def matches(
        self,
        request: "PermissionRequest",
        snapshot: "PermissionRequestMatchSnapshot | None" = None,
    ) -> bool:
        if self.target is not None and self.target != request.target:
            return False
        if not _matches_selector(
            snapshot.candidate_names if snapshot is not None else (request.name,),
            self.selector,
        ):
            return False
        if self.scopes and (
            snapshot is None or not any(_matches_selector(snapshot.scopes, scope) for scope in self.scopes)
        ):
            return False
        if self.risk_levels and (snapshot is None or snapshot.risk_level not in self.risk_levels):
            return False
        if self.operations and (
            snapshot is None
            or snapshot.operation is None
            or not any(fnmatch(snapshot.operation, operation) for operation in self.operations)
        ):
            return False
        if self.tags and (
            snapshot is None
            or not any(_matches_selector(snapshot.tags, tag) for tag in self.tags)
        ):
            return False
        if self.read_only is not None and (snapshot is None or snapshot.read_only != self.read_only):
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "selector": self.selector,
            "behavior": self.behavior.value,
        }
        if self.target is not None:
            payload["target"] = self.target.value
        if self.message is not None:
            payload["message"] = self.message
        if self.scopes:
            payload["scopes"] = list(self.scopes)
        if self.risk_levels:
            payload["risk_levels"] = [risk.value for risk in self.risk_levels]
        if self.operations:
            payload["operations"] = list(self.operations)
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.read_only is not None:
            payload["read_only"] = self.read_only
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    name: str
    rules: tuple[PermissionRule, ...] = ()
    fallback_behavior: PermissionBehavior | None = None
    fallback_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    fallback_metadata: dict[str, Any] = field(default_factory=dict)
    source: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", tuple(self.rules))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "fallback_metadata", dict(self.fallback_metadata))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "rules": [rule.to_dict() for rule in self.rules],
        }
        if self.fallback_behavior is not None:
            payload["fallback_behavior"] = self.fallback_behavior.value
        if self.fallback_message is not None:
            payload["fallback_message"] = self.fallback_message
        if self.source is not None:
            payload["source"] = self.source
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        if self.fallback_metadata:
            payload["fallback_metadata"] = dict(self.fallback_metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PermissionRequestMatchSnapshot:
    target: PermissionTarget
    name: str
    candidate_names: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    risk_level: ToolRiskLevel | None = None
    operation: str | None = None
    read_only: bool | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_names", _coerce_string_tuple(self.candidate_names) or (self.name,))
        object.__setattr__(self, "scopes", _coerce_string_tuple(self.scopes))
        object.__setattr__(self, "tags", _coerce_string_tuple(self.tags))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target": self.target.value,
            "name": self.name,
            "candidate_names": list(self.candidate_names),
            "scopes": list(self.scopes),
            "read_only": self.read_only,
            "metadata": dict(self.metadata),
        }
        if self.risk_level is not None:
            payload["risk_level"] = self.risk_level.value
        if self.operation is not None:
            payload["operation"] = self.operation
        if self.tags:
            payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True, slots=True)
class PermissionRuleEvaluation:
    rule_index: int
    selector: str
    behavior: PermissionBehavior
    target: PermissionTarget | None = None
    message: str | None = None
    scopes: tuple[str, ...] = ()
    risk_levels: tuple[ToolRiskLevel, ...] = ()
    operations: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    read_only: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", _coerce_string_tuple(self.scopes))
        object.__setattr__(self, "risk_levels", _coerce_risk_levels(self.risk_levels))
        object.__setattr__(self, "operations", _coerce_string_tuple(self.operations))
        object.__setattr__(self, "tags", _coerce_string_tuple(self.tags))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rule_index": self.rule_index,
            "selector": self.selector,
            "behavior": self.behavior.value,
        }
        if self.target is not None:
            payload["target"] = self.target.value
        if self.message is not None:
            payload["message"] = self.message
        if self.scopes:
            payload["scopes"] = list(self.scopes)
        if self.risk_levels:
            payload["risk_levels"] = [risk.value for risk in self.risk_levels]
        if self.operations:
            payload["operations"] = list(self.operations)
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.read_only is not None:
            payload["read_only"] = self.read_only
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PermissionPolicyEvaluation:
    policy_name: str
    policy_index: int
    decision: PermissionBehavior | None = None
    matched_rules: tuple[PermissionRuleEvaluation, ...] = ()
    fallback_used: bool = False
    fallback_behavior: PermissionBehavior | None = None
    fallback_message: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched_rules", tuple(self.matched_rules))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def winning_rule(self) -> PermissionRuleEvaluation | None:
        if not self.matched_rules:
            return None
        return self.matched_rules[-1]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "policy_name": self.policy_name,
            "policy_index": self.policy_index,
            "matched_rules": [rule.to_dict() for rule in self.matched_rules],
            "fallback_used": self.fallback_used,
            "metadata": dict(self.metadata),
        }
        if self.decision is not None:
            payload["decision"] = self.decision.value
        if self.fallback_behavior is not None:
            payload["fallback_behavior"] = self.fallback_behavior.value
        if self.fallback_message is not None:
            payload["fallback_message"] = self.fallback_message
        if self.source is not None:
            payload["source"] = self.source
        winning_rule = self.winning_rule
        if winning_rule is not None:
            payload["winning_rule"] = winning_rule.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class PermissionEvaluationExplanation:
    request: PermissionRequestMatchSnapshot
    layers: tuple[PermissionPolicyEvaluation, ...] = ()
    winning_layer_index: int | None = None
    composition: str = "ordered-policy-stack:last-decision-wins"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "layers", tuple(self.layers))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def winner(self) -> PermissionPolicyEvaluation | None:
        if self.winning_layer_index is None:
            return None
        for layer in self.layers:
            if layer.policy_index == self.winning_layer_index:
                return layer
        return None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "composition": self.composition,
            "request": self.request.to_dict(),
            "layers": [layer.to_dict() for layer in self.layers],
            "metadata": dict(self.metadata),
        }
        winner = self.winner
        if winner is not None:
            payload["winner"] = winner.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class PermissionContext:
    session_id: str
    mode: PermissionMode = PermissionMode.DEFAULT
    rules: tuple[PermissionRule, ...] = ()
    policies: tuple[PermissionPolicy, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", tuple(self.rules))
        object.__setattr__(self, "policies", tuple(self.policies))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def with_rule(self, rule: PermissionRule) -> "PermissionContext":
        return replace(self, rules=self.rules + (rule,))

    def with_policy(self, policy: PermissionPolicy) -> "PermissionContext":
        return replace(self, policies=self.policies + (policy,))

    def with_scopes(self, *scopes: str) -> "PermissionContext":
        merged = tuple(dict.fromkeys((*self.policy_scopes, *scopes)))
        metadata = dict(self.metadata)
        metadata["policy_scopes"] = merged
        return replace(self, metadata=metadata)

    @property
    def policy_scopes(self) -> tuple[str, ...]:
        return _coerce_scope_tokens(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mode": self.mode.value,
            "rules": [rule.to_dict() for rule in self.rules],
            "policies": [policy.to_dict() for policy in self.policies],
            "metadata": dict(self.metadata),
        }


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
    "PermissionEvaluationExplanation",
    "PermissionContext",
    "PermissionOutcome",
    "PermissionPolicy",
    "PermissionPolicyEvaluation",
    "PermissionRequest",
    "PermissionRequestMatchSnapshot",
    "PermissionRule",
    "PermissionRuleEvaluation",
    "PermissionTarget",
    "coerce_permission_outcome",
]


def _coerce_string_tuple(values: Sequence[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(values, str):
        return (values,)
    return tuple(str(value) for value in values)


def _coerce_risk_levels(
    values: Sequence[ToolRiskLevel | str] | tuple[ToolRiskLevel, ...],
) -> tuple[ToolRiskLevel, ...]:
    resolved: list[ToolRiskLevel] = []
    for value in values:
        if isinstance(value, ToolRiskLevel):
            resolved.append(value)
        else:
            resolved.append(ToolRiskLevel(str(value)))
    return tuple(resolved)


def _matches_selector(candidates: Sequence[str], selector: str) -> bool:
    if selector == "*":
        return True
    if any(char in selector for char in "*?[]"):
        return any(fnmatch(candidate, selector) for candidate in candidates)
    return any(candidate == selector for candidate in candidates)


def _coerce_scope_tokens(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    raw: Any = metadata.get("policy_scopes", metadata.get("scopes", metadata.get("scope")))
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, Sequence):
        return tuple(str(value) for value in raw)
    return (str(raw),)
