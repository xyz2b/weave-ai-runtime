from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from math import ceil
from typing import Any, Iterable, Mapping, Sequence


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    return {str(key): item for key, item in value.items()}


def _coerce_optional_string(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _coerce_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (float, int)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_sequence(value: object) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _selector_has_pattern(selector: str) -> bool:
    return any(char in selector for char in "*?[]")


@dataclass(frozen=True, slots=True)
class TokenEstimationHint:
    tokenizer_name: str | None = None
    chars_per_token: float | None = None
    advisory_only: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    def estimate_tokens(self, text_length: int) -> int | None:
        if text_length <= 0:
            return 0
        if self.chars_per_token is None or self.chars_per_token <= 0:
            return None
        return max(1, ceil(text_length / self.chars_per_token))


@dataclass(frozen=True, slots=True)
class RecoveryClassificationRule:
    stop_reasons: tuple[str, ...] = ()
    provider_error_codes: tuple[str, ...] = ()
    http_statuses: tuple[int, ...] = ()
    message_substrings: tuple[str, ...] = ()
    retryable: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stop_reasons", tuple(str(item) for item in self.stop_reasons))
        object.__setattr__(
            self,
            "provider_error_codes",
            tuple(str(item) for item in self.provider_error_codes),
        )
        object.__setattr__(
            self,
            "http_statuses",
            tuple(
                status
                for item in self.http_statuses
                if (status := _coerce_optional_int(item)) is not None
            ),
        )
        object.__setattr__(
            self,
            "message_substrings",
            tuple(str(item) for item in self.message_substrings),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class MinimalRecoveryClassificationHints:
    context_limit: RecoveryClassificationRule
    output_limit: RecoveryClassificationRule | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ModelContextWindowProfile:
    provider_name: str | None = None
    model_selector: str | None = None
    profile_name: str | None = None
    max_input_tokens: int | None = None
    reserved_output_tokens: int | None = None
    token_estimation_hint: TokenEstimationHint | None = None
    recovery_classification_hints: MinimalRecoveryClassificationHints | None = None
    source: str = "integration"
    confidence: str = "high"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def selector_kind(self) -> str:
        if self.model_selector is None:
            return "provider_default"
        if _selector_has_pattern(self.model_selector):
            return "pattern"
        return "exact"

    def matches(
        self,
        *,
        provider_name: str | None,
        model_name: str | None,
    ) -> bool:
        if self.provider_name is not None and provider_name is not None and self.provider_name != provider_name:
            return False
        if self.model_selector is None:
            return True
        if model_name is None:
            return False
        if _selector_has_pattern(self.model_selector):
            return fnmatch(model_name, self.model_selector)
        return self.model_selector == model_name


@dataclass(frozen=True, slots=True)
class RouteContextWindowPolicy:
    profile_ref: str | None = None
    narrow_to_max_input_tokens: int | None = None
    reserved_output_tokens_override: int | None = None
    trigger_buffer_tokens: int | None = None
    fallback_mode: str | None = None
    policy_tag: str | None = None
    source: str | None = None
    confidence: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ResolvedContextWindowSnapshot:
    provider_name: str | None = None
    model_name: str | None = None
    route_name: str | None = None
    profile_name: str | None = None
    max_input_tokens: int | None = None
    reserved_output_tokens: int | None = None
    remaining_input_tokens: int | None = None
    estimated_input_tokens: int | None = None
    token_estimation_hint: TokenEstimationHint | None = None
    fallback_mode: str = "reactive_only"
    recovery_classification_hints: MinimalRecoveryClassificationHints | None = None
    source: str = "unknown"
    confidence: str = "unknown"
    trigger_buffer_tokens: int | None = None
    policy_tag: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def known(self) -> bool:
        return self.max_input_tokens is not None


def serialize_token_estimation_hint(value: TokenEstimationHint | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "tokenizer_name": value.tokenizer_name,
        "chars_per_token": value.chars_per_token,
        "advisory_only": value.advisory_only,
        "metadata": dict(value.metadata),
    }


def coerce_token_estimation_hint(value: object) -> TokenEstimationHint | None:
    if isinstance(value, TokenEstimationHint):
        return value
    if not isinstance(value, Mapping):
        return None
    return TokenEstimationHint(
        tokenizer_name=_coerce_optional_string(value.get("tokenizer_name")),
        chars_per_token=_coerce_optional_float(value.get("chars_per_token")),
        advisory_only=bool(value.get("advisory_only", True)),
        metadata=_copy_mapping(value.get("metadata")),
    )


def serialize_recovery_classification_rule(
    value: RecoveryClassificationRule | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "stop_reasons": list(value.stop_reasons),
        "provider_error_codes": list(value.provider_error_codes),
        "http_statuses": list(value.http_statuses),
        "message_substrings": list(value.message_substrings),
        "retryable": value.retryable,
        "metadata": dict(value.metadata),
    }


def coerce_recovery_classification_rule(value: object) -> RecoveryClassificationRule | None:
    if isinstance(value, RecoveryClassificationRule):
        return value
    if not isinstance(value, Mapping):
        return None
    return RecoveryClassificationRule(
        stop_reasons=tuple(str(item) for item in _coerce_sequence(value.get("stop_reasons"))),
        provider_error_codes=tuple(
            str(item) for item in _coerce_sequence(value.get("provider_error_codes"))
        ),
        http_statuses=tuple(
            status
            for item in _coerce_sequence(value.get("http_statuses"))
            if (status := _coerce_optional_int(item)) is not None
        ),
        message_substrings=tuple(
            str(item) for item in _coerce_sequence(value.get("message_substrings"))
        ),
        retryable=(
            value.get("retryable")
            if isinstance(value.get("retryable"), bool) or value.get("retryable") is None
            else None
        ),
        metadata=_copy_mapping(value.get("metadata")),
    )


def serialize_minimal_recovery_classification_hints(
    value: MinimalRecoveryClassificationHints | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "context_limit": serialize_recovery_classification_rule(value.context_limit),
        "output_limit": serialize_recovery_classification_rule(value.output_limit),
        "metadata": dict(value.metadata),
    }


def coerce_minimal_recovery_classification_hints(
    value: object,
) -> MinimalRecoveryClassificationHints | None:
    if isinstance(value, MinimalRecoveryClassificationHints):
        return value
    if not isinstance(value, Mapping):
        return None
    context_limit = coerce_recovery_classification_rule(value.get("context_limit"))
    if context_limit is None:
        return None
    return MinimalRecoveryClassificationHints(
        context_limit=context_limit,
        output_limit=coerce_recovery_classification_rule(value.get("output_limit")),
        metadata=_copy_mapping(value.get("metadata")),
    )


def serialize_model_context_window_profile(
    value: ModelContextWindowProfile | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "provider_name": value.provider_name,
        "model_selector": value.model_selector,
        "profile_name": value.profile_name,
        "max_input_tokens": value.max_input_tokens,
        "reserved_output_tokens": value.reserved_output_tokens,
        "token_estimation_hint": serialize_token_estimation_hint(value.token_estimation_hint),
        "recovery_classification_hints": serialize_minimal_recovery_classification_hints(
            value.recovery_classification_hints
        ),
        "source": value.source,
        "confidence": value.confidence,
        "metadata": dict(value.metadata),
    }


def coerce_model_context_window_profile(value: object) -> ModelContextWindowProfile | None:
    if isinstance(value, ModelContextWindowProfile):
        return value
    if not isinstance(value, Mapping):
        return None
    return ModelContextWindowProfile(
        provider_name=_coerce_optional_string(value.get("provider_name")),
        model_selector=_coerce_optional_string(value.get("model_selector")),
        profile_name=_coerce_optional_string(value.get("profile_name")),
        max_input_tokens=_coerce_optional_int(value.get("max_input_tokens")),
        reserved_output_tokens=_coerce_optional_int(value.get("reserved_output_tokens")),
        token_estimation_hint=coerce_token_estimation_hint(value.get("token_estimation_hint")),
        recovery_classification_hints=coerce_minimal_recovery_classification_hints(
            value.get("recovery_classification_hints")
        ),
        source=_coerce_optional_string(value.get("source")) or "integration",
        confidence=_coerce_optional_string(value.get("confidence")) or "high",
        metadata=_copy_mapping(value.get("metadata")),
    )


def serialize_route_context_window_policy(
    value: RouteContextWindowPolicy | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "profile_ref": value.profile_ref,
        "narrow_to_max_input_tokens": value.narrow_to_max_input_tokens,
        "reserved_output_tokens_override": value.reserved_output_tokens_override,
        "trigger_buffer_tokens": value.trigger_buffer_tokens,
        "fallback_mode": value.fallback_mode,
        "policy_tag": value.policy_tag,
        "source": value.source,
        "confidence": value.confidence,
        "metadata": dict(value.metadata),
    }


def coerce_route_context_window_policy(value: object) -> RouteContextWindowPolicy | None:
    if isinstance(value, RouteContextWindowPolicy):
        return value
    if not isinstance(value, Mapping):
        return None
    return RouteContextWindowPolicy(
        profile_ref=_coerce_optional_string(value.get("profile_ref")),
        narrow_to_max_input_tokens=_coerce_optional_int(value.get("narrow_to_max_input_tokens")),
        reserved_output_tokens_override=_coerce_optional_int(
            value.get("reserved_output_tokens_override")
        ),
        trigger_buffer_tokens=_coerce_optional_int(value.get("trigger_buffer_tokens")),
        fallback_mode=_coerce_optional_string(value.get("fallback_mode")),
        policy_tag=_coerce_optional_string(value.get("policy_tag")),
        source=_coerce_optional_string(value.get("source")),
        confidence=_coerce_optional_string(value.get("confidence")),
        metadata=_copy_mapping(value.get("metadata")),
    )


def serialize_resolved_context_window_snapshot(
    value: ResolvedContextWindowSnapshot | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "provider_name": value.provider_name,
        "model_name": value.model_name,
        "route_name": value.route_name,
        "profile_name": value.profile_name,
        "max_input_tokens": value.max_input_tokens,
        "reserved_output_tokens": value.reserved_output_tokens,
        "remaining_input_tokens": value.remaining_input_tokens,
        "estimated_input_tokens": value.estimated_input_tokens,
        "token_estimation_hint": serialize_token_estimation_hint(value.token_estimation_hint),
        "fallback_mode": value.fallback_mode,
        "recovery_classification_hints": serialize_minimal_recovery_classification_hints(
            value.recovery_classification_hints
        ),
        "source": value.source,
        "confidence": value.confidence,
        "trigger_buffer_tokens": value.trigger_buffer_tokens,
        "policy_tag": value.policy_tag,
        "metadata": dict(value.metadata),
    }


def coerce_resolved_context_window_snapshot(
    value: object,
) -> ResolvedContextWindowSnapshot | None:
    if isinstance(value, ResolvedContextWindowSnapshot):
        return value
    if not isinstance(value, Mapping):
        return None
    return ResolvedContextWindowSnapshot(
        provider_name=_coerce_optional_string(value.get("provider_name")),
        model_name=_coerce_optional_string(value.get("model_name")),
        route_name=_coerce_optional_string(value.get("route_name")),
        profile_name=_coerce_optional_string(value.get("profile_name")),
        max_input_tokens=_coerce_optional_int(value.get("max_input_tokens")),
        reserved_output_tokens=_coerce_optional_int(value.get("reserved_output_tokens")),
        remaining_input_tokens=_coerce_optional_int(value.get("remaining_input_tokens")),
        estimated_input_tokens=_coerce_optional_int(value.get("estimated_input_tokens")),
        token_estimation_hint=coerce_token_estimation_hint(value.get("token_estimation_hint")),
        fallback_mode=_coerce_optional_string(value.get("fallback_mode")) or "reactive_only",
        recovery_classification_hints=coerce_minimal_recovery_classification_hints(
            value.get("recovery_classification_hints")
        ),
        source=_coerce_optional_string(value.get("source")) or "unknown",
        confidence=_coerce_optional_string(value.get("confidence")) or "unknown",
        trigger_buffer_tokens=_coerce_optional_int(value.get("trigger_buffer_tokens")),
        policy_tag=_coerce_optional_string(value.get("policy_tag")),
        metadata=_copy_mapping(value.get("metadata")),
    )


def coerce_model_context_window_profiles(value: object) -> tuple[ModelContextWindowProfile, ...]:
    if isinstance(value, tuple) and all(isinstance(item, ModelContextWindowProfile) for item in value):
        return value
    profiles: list[ModelContextWindowProfile] = []
    for item in _coerce_sequence(value):
        profile = coerce_model_context_window_profile(item)
        if profile is not None:
            profiles.append(profile)
    return tuple(profiles)


def validate_model_context_window_profiles(
    profiles: Sequence[ModelContextWindowProfile],
) -> tuple[str, ...]:
    diagnostics: list[str] = []
    seen_exact: set[tuple[str | None, str]] = set()
    seen_default: set[str | None] = set()
    seen_pattern: set[tuple[str | None, str]] = set()
    seen_profile_refs: set[tuple[str | None, str]] = set()
    for profile in profiles:
        if profile.profile_name is not None:
            key = (profile.provider_name, profile.profile_name)
            if key in seen_profile_refs:
                diagnostics.append(
                    f"duplicate_profile_ref:{profile.provider_name or '<any>'}:{profile.profile_name}"
                )
            seen_profile_refs.add(key)
        if profile.model_selector is None:
            if profile.provider_name in seen_default:
                diagnostics.append(f"duplicate_provider_default:{profile.provider_name or '<any>'}")
            seen_default.add(profile.provider_name)
            continue
        if _selector_has_pattern(profile.model_selector):
            key = (profile.provider_name, profile.model_selector)
            if key in seen_pattern:
                diagnostics.append(
                    f"duplicate_pattern_profile:{profile.provider_name or '<any>'}:{profile.model_selector}"
                )
            seen_pattern.add(key)
            continue
        key = (profile.provider_name, profile.model_selector)
        if key in seen_exact:
            diagnostics.append(
                f"duplicate_exact_profile:{profile.provider_name or '<any>'}:{profile.model_selector}"
            )
        seen_exact.add(key)
    return tuple(diagnostics)


def resolve_context_window_profile(
    *,
    provider_name: str | None,
    model_name: str | None,
    profiles: Sequence[ModelContextWindowProfile],
    profile_ref: str | None = None,
) -> ModelContextWindowProfile | None:
    if profile_ref is not None:
        by_ref = [
            profile
            for profile in profiles
            if profile.profile_name == profile_ref
            and (profile.provider_name is None or provider_name is None or profile.provider_name == provider_name)
        ]
        if len(by_ref) > 1:
            raise ValueError(
                f"Ambiguous context window profile_ref for provider {provider_name or '<any>'}: {profile_ref}"
            )
        if by_ref:
            return by_ref[0]
        raise ValueError(
            f"Unknown context window profile_ref for provider {provider_name or '<any>'}: {profile_ref}"
        )

    exact_matches: list[ModelContextWindowProfile] = []
    pattern_matches: list[ModelContextWindowProfile] = []
    default_matches: list[ModelContextWindowProfile] = []
    for profile in profiles:
        if not profile.matches(provider_name=provider_name, model_name=model_name):
            continue
        if profile.selector_kind == "exact":
            exact_matches.append(profile)
            continue
        if profile.selector_kind == "pattern":
            pattern_matches.append(profile)
            continue
        default_matches.append(profile)
    for matches, label in (
        (exact_matches, "exact"),
        (pattern_matches, "pattern"),
        (default_matches, "provider_default"),
    ):
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous {label} context window profiles for provider {provider_name or '<any>'}"
            )
        if matches:
            return matches[0]
    return None


def resolve_context_window_snapshot(
    *,
    provider_name: str | None,
    model_name: str | None,
    route_name: str | None,
    profiles: Sequence[ModelContextWindowProfile],
    route_policy: RouteContextWindowPolicy | None = None,
    estimated_input_tokens: int | None = None,
) -> ResolvedContextWindowSnapshot:
    profile = resolve_context_window_profile(
        provider_name=provider_name,
        model_name=model_name,
        profiles=profiles,
        profile_ref=route_policy.profile_ref if route_policy is not None else None,
    )
    max_input_tokens = profile.max_input_tokens if profile is not None else None
    reserved_output_tokens = profile.reserved_output_tokens if profile is not None else None
    token_estimation_hint = profile.token_estimation_hint if profile is not None else None
    recovery_hints = profile.recovery_classification_hints if profile is not None else None
    source = profile.source if profile is not None else "unknown"
    confidence = profile.confidence if profile is not None else "unknown"
    profile_name = profile.profile_name if profile is not None else None
    trigger_buffer_tokens = route_policy.trigger_buffer_tokens if route_policy is not None else None
    route_applied = False

    if route_policy is not None:
        if route_policy.narrow_to_max_input_tokens is not None:
            if max_input_tokens is None:
                max_input_tokens = route_policy.narrow_to_max_input_tokens
            else:
                max_input_tokens = min(max_input_tokens, route_policy.narrow_to_max_input_tokens)
            route_applied = True
        if route_policy.reserved_output_tokens_override is not None:
            reserved_output_tokens = route_policy.reserved_output_tokens_override
            route_applied = True
        if route_applied:
            source = route_policy.source or "route_override"
            confidence = route_policy.confidence or confidence

    fallback_mode = "proactive_and_reactive" if max_input_tokens is not None else "reactive_only"
    if route_policy is not None and route_policy.fallback_mode is not None:
        fallback_mode = route_policy.fallback_mode
    if max_input_tokens is None:
        fallback_mode = "reactive_only"

    remaining_input_tokens = None
    if max_input_tokens is not None and estimated_input_tokens is not None:
        remaining_input_tokens = max_input_tokens - (reserved_output_tokens or 0) - estimated_input_tokens

    return ResolvedContextWindowSnapshot(
        provider_name=provider_name,
        model_name=model_name,
        route_name=route_name,
        profile_name=profile_name,
        max_input_tokens=max_input_tokens,
        reserved_output_tokens=reserved_output_tokens,
        remaining_input_tokens=remaining_input_tokens,
        estimated_input_tokens=estimated_input_tokens,
        token_estimation_hint=token_estimation_hint,
        fallback_mode=fallback_mode,
        recovery_classification_hints=recovery_hints,
        source=source,
        confidence=confidence,
        trigger_buffer_tokens=trigger_buffer_tokens,
        policy_tag=route_policy.policy_tag if route_policy is not None else None,
        metadata={
            "profile_ref": route_policy.profile_ref if route_policy is not None else None,
            "route_policy_applied": route_applied,
        },
    )


def estimate_tokens_from_text(
    text: str,
    *,
    hint: TokenEstimationHint | None = None,
    default_chars_per_token: float = 4.0,
) -> int:
    if not text:
        return 0
    estimator = hint or TokenEstimationHint(chars_per_token=default_chars_per_token, advisory_only=True)
    estimated = estimator.estimate_tokens(len(text))
    if estimated is None:
        return max(1, ceil(len(text) / default_chars_per_token))
    return estimated


def estimate_tokens_from_fragments(
    fragments: Iterable[str],
    *,
    hint: TokenEstimationHint | None = None,
    default_chars_per_token: float = 4.0,
) -> int:
    total_length = sum(len(fragment) for fragment in fragments if fragment)
    estimator = hint or TokenEstimationHint(chars_per_token=default_chars_per_token, advisory_only=True)
    estimated = estimator.estimate_tokens(total_length)
    if estimated is None:
        return max(1, ceil(total_length / default_chars_per_token)) if total_length else 0
    return estimated


__all__ = [
    "MinimalRecoveryClassificationHints",
    "ModelContextWindowProfile",
    "RecoveryClassificationRule",
    "ResolvedContextWindowSnapshot",
    "RouteContextWindowPolicy",
    "TokenEstimationHint",
    "coerce_minimal_recovery_classification_hints",
    "coerce_model_context_window_profile",
    "coerce_model_context_window_profiles",
    "coerce_recovery_classification_rule",
    "coerce_resolved_context_window_snapshot",
    "coerce_route_context_window_policy",
    "coerce_token_estimation_hint",
    "estimate_tokens_from_fragments",
    "estimate_tokens_from_text",
    "resolve_context_window_profile",
    "resolve_context_window_snapshot",
    "serialize_minimal_recovery_classification_hints",
    "serialize_model_context_window_profile",
    "serialize_recovery_classification_rule",
    "serialize_resolved_context_window_snapshot",
    "serialize_route_context_window_policy",
    "serialize_token_estimation_hint",
    "validate_model_context_window_profiles",
]
