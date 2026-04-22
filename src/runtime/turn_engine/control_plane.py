from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence
from uuid import uuid4

from ..compaction import (
    CompactionPolicy,
    CompactionResult,
    evaluate_context_pressure,
    serialize_compaction_boundary,
    serialize_compaction_continuation,
    serialize_compaction_result,
    serialize_compaction_summary,
)
from ..context_window import (
    MinimalRecoveryClassificationHints,
    ResolvedContextWindowSnapshot,
    coerce_model_context_window_profiles,
    coerce_resolved_context_window_snapshot,
    coerce_route_context_window_policy,
    estimate_tokens_from_fragments,
    resolve_context_window_snapshot,
    serialize_resolved_context_window_snapshot,
)
from ..contracts import (
    MessageRole,
    PromptContextEnvelope,
    RequestOverrideState,
    RuntimeMessage,
    RuntimePrivateContext,
    RuntimePrivateContextView,
    ToolResultBlock,
    merge_request_override_state,
    private_context_from_legacy_runtime_context,
)
from ..definitions import AgentDefinition
from .message_protocol import ensure_tool_result_pairing


class FailureClassification(StrEnum):
    NONE = "none"
    CONTEXT_LIMIT = "context_limit"
    OUTPUT_LIMIT = "output_limit"
    MEDIA_LIMIT = "media_limit"
    PROVIDER_OVERLOAD = "provider_overload"
    AUTH_ERROR = "auth_error"
    TOOL_SCHEMA_ERROR = "tool_schema_error"
    INTERNAL_ERROR = "internal_error"


class RecoveryAction(StrEnum):
    HALT = "halt"
    CONTINUE_SAME_TURN = "continue_same_turn"
    REBUILD_REQUEST = "rebuild_request"
    COMPACT_AND_RETRY = "compact_and_retry"
    RETRY_WITH_OVERRIDE = "retry_with_override"


class StopDisposition(StrEnum):
    HALT_FAILURE = "halt_failure"
    BLOCK_SESSION = "block_session"
    CONTINUE_SAME_TURN = "continue_same_turn"
    ALLOW_TERMINAL = "allow_terminal"


class ContextPreparationEffectKind(StrEnum):
    CONTEXT_WINDOW_DECISION = "context_window_decision"
    BUDGET_DECISION = "context_window_decision"
    PROJECTION = "projection"
    COMPACTION = "compaction"
    SPILLOVER = "spillover"
    SIDECAR_RESTART = "sidecar_restart"
    REQUEST_SHAPING = "request_shaping"


class BudgetAction(StrEnum):
    INLINE = "inline"
    SUMMARIZE = "summarize"
    EXTERNALIZE = "externalize"


class ContextWindowHookFailureMode(StrEnum):
    PASS_THROUGH = "pass_through"
    FAIL_PREPARE = "fail_prepare"


ContextBudgetHookFailureMode = ContextWindowHookFailureMode


@dataclass(frozen=True, slots=True)
class NormalizedRecoveryInput:
    terminal_reason: str | None = None
    failure_class: FailureClassification = FailureClassification.NONE
    retryable: bool = False
    provider_error_code: str | None = None
    error: str | None = None
    abort_reason: str | None = None
    produced_tool_calls: bool = False
    tool_call_count: int = 0
    max_turns_exhausted: bool = False
    tool_executor_unavailable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def interrupted(self) -> bool:
        tool_failure_abort = self.abort_reason is not None and str(self.abort_reason).startswith(
            "tool_failure:"
        )
        return (
            (self.abort_reason is not None and not tool_failure_abort)
            or (self.terminal_reason == "interrupted" and not tool_failure_abort)
        )

    @property
    def terminal_failure(self) -> bool:
        return (
            self.failure_class != FailureClassification.NONE
            or self.interrupted
            or self.max_turns_exhausted
            or self.tool_executor_unavailable
        )


@dataclass(frozen=True, slots=True)
class RecoveryState:
    retry_counters: dict[str, int] = field(default_factory=dict)
    prior_compaction_attempts: dict[str, int] = field(default_factory=dict)
    active_failure_class: FailureClassification | None = None
    pending_override_snapshot: RequestOverrideState | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "retry_counters", dict(self.retry_counters))
        object.__setattr__(self, "prior_compaction_attempts", dict(self.prior_compaction_attempts))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def retry_count(self, failure_class: FailureClassification) -> int:
        return int(self.retry_counters.get(failure_class.value, 0))

    def compaction_attempt_count(self, failure_class: FailureClassification) -> int:
        return int(self.prior_compaction_attempts.get(failure_class.value, 0))

    def after_decision(
        self,
        recovery_input: NormalizedRecoveryInput,
        decision: "RecoveryDecision",
    ) -> "RecoveryState":
        retry_counters = dict(self.retry_counters)
        prior_compaction_attempts = dict(self.prior_compaction_attempts)
        active_failure_class = (
            recovery_input.failure_class
            if recovery_input.failure_class != FailureClassification.NONE
            else None
        )
        if active_failure_class is not None and decision.action != RecoveryAction.HALT:
            if decision.action == RecoveryAction.COMPACT_AND_RETRY:
                prior_compaction_attempts[active_failure_class.value] = (
                    prior_compaction_attempts.get(active_failure_class.value, 0) + 1
                )
            else:
                retry_counters[active_failure_class.value] = (
                    retry_counters.get(active_failure_class.value, 0) + 1
                )
        return RecoveryState(
            retry_counters=retry_counters,
            prior_compaction_attempts=prior_compaction_attempts,
            active_failure_class=active_failure_class,
            pending_override_snapshot=decision.request_override or self.pending_override_snapshot,
            metadata={
                **self.metadata,
                "last_action": decision.action.value,
                "last_reason": decision.reason,
            },
        )

    def clear_pending_override(self) -> "RecoveryState":
        if self.pending_override_snapshot is None:
            return self
        return RecoveryState(
            retry_counters=self.retry_counters,
            prior_compaction_attempts=self.prior_compaction_attempts,
            active_failure_class=self.active_failure_class,
            pending_override_snapshot=None,
            metadata=self.metadata,
        )

    def serialize(self) -> dict[str, Any]:
        return {
            "retry_counters": dict(self.retry_counters),
            "prior_compaction_attempts": dict(self.prior_compaction_attempts),
            "active_failure_class": (
                self.active_failure_class.value if self.active_failure_class is not None else None
            ),
            "pending_override_snapshot": (
                self.pending_override_snapshot.serialize()
                if self.pending_override_snapshot is not None
                else None
            ),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    action: RecoveryAction
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
    injected_messages: tuple[RuntimeMessage, ...] = ()
    request_override: RequestOverrideState | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        metadata = dict(self.metadata)
        metadata.setdefault("recovery_action", self.action.value)
        metadata.setdefault("recovery_reason", self.reason)
        if self.request_override is not None:
            sources = sorted(
                {
                    source
                    for source in (
                        *self.request_override.field_sources.values(),
                        self.request_override.source,
                    )
                    if source
                }
            )
            if sources:
                metadata.setdefault("override_sources", sources)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "injected_messages", tuple(self.injected_messages))


@dataclass(frozen=True, slots=True)
class StopPhaseOutcome:
    disposition: StopDisposition = StopDisposition.ALLOW_TERMINAL
    matched_hook_owners: tuple[str, ...] = ()
    additional_context: tuple[str, ...] = ()
    notifications: tuple[str, ...] = ()
    injected_messages: tuple[RuntimeMessage, ...] = ()
    request_override: RequestOverrideState | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched_hook_owners", tuple(self.matched_hook_owners))
        object.__setattr__(self, "additional_context", tuple(self.additional_context))
        object.__setattr__(self, "notifications", tuple(self.notifications))
        object.__setattr__(self, "injected_messages", tuple(self.injected_messages))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def continue_execution(self) -> bool:
        return self.disposition != StopDisposition.BLOCK_SESSION


@dataclass(frozen=True, slots=True)
class ContextPreparationEffect:
    kind: ContextPreparationEffectKind
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class PreparedContext:
    active_messages: tuple[RuntimeMessage, ...]
    prompt_context: PromptContextEnvelope
    private_context_updates: dict[str, Any] = field(default_factory=dict)
    generation: int = 1
    effects: tuple[ContextPreparationEffect, ...] = ()
    requires_sidecar_restart: bool = False
    transcript_messages: tuple[RuntimeMessage, ...] | None = None
    context_window: ResolvedContextWindowSnapshot | None = None
    context_window_policy_tag: str | None = None
    pressure: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "active_messages", tuple(self.active_messages))
        object.__setattr__(self, "private_context_updates", dict(self.private_context_updates))
        object.__setattr__(self, "effects", tuple(self.effects))
        object.__setattr__(self, "pressure", dict(self.pressure))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.transcript_messages is not None:
            object.__setattr__(self, "transcript_messages", tuple(self.transcript_messages))

    def effect_kinds(self) -> tuple[str, ...]:
        return tuple(effect.kind.value for effect in self.effects)

    def with_prompt_context(self, prompt_context: PromptContextEnvelope) -> "PreparedContext":
        return replace(self, prompt_context=prompt_context)


@dataclass(frozen=True, slots=True)
class ContextWindowCandidate:
    candidate_id: str
    tool_use_id: str
    tool_name: str | None = None
    message_index: int = 0
    block_index: int = 0
    is_error: bool = False
    content: Any = None
    tool_result_summary: Mapping[str, Any] | None = None
    estimated_token_count: int | None = None
    serialized_size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ProviderContextWindowHints:
    provider_name: str | None = None
    model_name: str | None = None
    requested_model_route: str | None = None
    invocation_mode: Any = None
    max_input_tokens: int | None = None
    reserved_output_tokens: int | None = None
    remaining_input_tokens: int | None = None
    fallback_mode: str | None = None
    source: str | None = None
    confidence: str | None = None
    context_window_policy_tag: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extensions", dict(self.extensions))


@dataclass(frozen=True, slots=True)
class ContextWindowDecision:
    candidate_id: str
    action: BudgetAction
    summary_text: str | None = None
    reason: str | None = None
    artifact_metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ContextWindowPlan:
    decisions: tuple[ContextWindowDecision, ...] = ()
    policy_tag: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "decisions", tuple(self.decisions))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@dataclass(frozen=True, slots=True)
class ContextWindowRequest:
    turn_id: str
    attempt_index: int
    candidates: tuple[ContextWindowCandidate, ...] = ()
    transcript_messages: tuple[RuntimeMessage, ...] = ()
    prompt_context: PromptContextEnvelope = field(default_factory=PromptContextEnvelope)
    private_context: RuntimePrivateContextView = field(default_factory=RuntimePrivateContextView)
    provider_hints: ProviderContextWindowHints | None = None
    prior_plan: ContextWindowPlan | None = None


class ContextWindowHook(Protocol):
    def plan(self, request: ContextWindowRequest) -> ContextWindowPlan | None: ...


BudgetCandidate = ContextWindowCandidate
ProviderBudgetHints = ProviderContextWindowHints
BudgetDecision = ContextWindowDecision
BudgetPlan = ContextWindowPlan
ContextBudgetRequest = ContextWindowRequest
ContextBudgetHook = ContextWindowHook


@dataclass(frozen=True, slots=True)
class ContextControlPlaneConfig:
    projection_max_messages: int | None = None
    context_window_hook: ContextWindowHook | Any = None
    context_window_hook_failure_mode: ContextWindowHookFailureMode = (
        ContextWindowHookFailureMode.PASS_THROUGH
    )
    context_window_hook_timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def budget_hook(self) -> ContextWindowHook | Any:
        return self.context_window_hook

    @property
    def budget_hook_failure_mode(self) -> ContextWindowHookFailureMode:
        return self.context_window_hook_failure_mode

    @property
    def budget_hook_timeout_seconds(self) -> float | None:
        return self.context_window_hook_timeout_seconds

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ContextControlPlaneConfig":
        if not isinstance(value, Mapping):
            return cls()
        deprecation_diagnostics: list[str] = []
        for legacy_key, canonical_key in (
            ("budget_hook", "context_window_hook"),
            ("budget_hook_failure_mode", "context_window_hook_failure_mode"),
            ("budget_hook_timeout_seconds", "context_window_hook_timeout_seconds"),
        ):
            if legacy_key in value and canonical_key not in value:
                deprecation_diagnostics.append(f"deprecated_config_key:{legacy_key}")
        failure_mode = value.get("context_window_hook_failure_mode", value.get("budget_hook_failure_mode"))
        resolved_failure_mode = ContextWindowHookFailureMode.PASS_THROUGH
        if failure_mode is not None:
            try:
                resolved_failure_mode = ContextWindowHookFailureMode(str(failure_mode))
            except ValueError:
                resolved_failure_mode = ContextWindowHookFailureMode.PASS_THROUGH
        return cls(
            projection_max_messages=_coerce_optional_int(value.get("projection_max_messages")),
            context_window_hook=value.get("context_window_hook", value.get("budget_hook")),
            context_window_hook_failure_mode=resolved_failure_mode,
            context_window_hook_timeout_seconds=_coerce_optional_float(
                value.get("context_window_hook_timeout_seconds", value.get("budget_hook_timeout_seconds"))
            ),
            metadata={
                **(
                    {"deprecation_diagnostics": tuple(deprecation_diagnostics)}
                    if deprecation_diagnostics
                    else {}
                ),
                **{
                    str(key): item
                    for key, item in value.items()
                    if str(key)
                    not in {
                        "projection_max_messages",
                        "context_window_hook",
                        "context_window_hook_failure_mode",
                        "context_window_hook_timeout_seconds",
                        "budget_hook",
                        "budget_hook_failure_mode",
                        "budget_hook_timeout_seconds",
                    }
                },
            },
        )

    @classmethod
    def resolve(
        cls,
        *,
        runtime_default: Mapping[str, Any] | None = None,
        agent_config: Mapping[str, Any] | None = None,
        turn_override: Mapping[str, Any] | None = None,
    ) -> "ContextControlPlaneConfig":
        merged: dict[str, Any] = {}
        for candidate in (runtime_default, agent_config, turn_override):
            if isinstance(candidate, Mapping):
                merged.update(candidate)
        return cls.from_mapping(merged)


class ContextControlPlane(Protocol):
    async def prepare(
        self,
        *,
        session_id: str,
        turn_id: str,
        attempt_index: int,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope,
        private_context: RuntimePrivateContext,
        runtime_context: Mapping[str, Any] | None = None,
        prior_prepared: PreparedContext | None = None,
        resolved_config: ContextControlPlaneConfig | None = None,
        transcript_store: Any | None = None,
    ) -> PreparedContext: ...


class RecoveryPolicy(Protocol):
    def evaluate(
        self,
        recovery_input: NormalizedRecoveryInput,
        *,
        stop_outcome: StopPhaseOutcome | None = None,
        recovery_state: RecoveryState | None = None,
        prepared_context: PreparedContext | None = None,
    ) -> RecoveryDecision: ...


class MaterialCompactionPass:
    def __init__(self, compaction_service: Any) -> None:
        self._compaction_service = compaction_service

    async def apply(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope,
        private_context: RuntimePrivateContext,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> CompactionResult:
        return await maybe_await(
            self._compaction_service.prepare_turn(
                session_id=session_id,
                turn_id=turn_id,
                agent=agent,
                cwd=cwd,
                messages=messages,
                prompt_context=prompt_context,
                private_context=private_context,
                runtime_context=dict(runtime_context or {}),
            )
        )


class DefaultContextControlPlane:
    def __init__(
        self,
        *,
        compaction_service: Any,
        default_config: ContextControlPlaneConfig | Mapping[str, Any] | None = None,
    ) -> None:
        self._compaction_service = compaction_service
        if isinstance(default_config, ContextControlPlaneConfig):
            self._default_config = default_config
        else:
            self._default_config = ContextControlPlaneConfig.from_mapping(default_config)
        self._material_compaction_pass = MaterialCompactionPass(compaction_service)

    async def prepare(
        self,
        *,
        session_id: str,
        turn_id: str,
        attempt_index: int,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope,
        private_context: RuntimePrivateContext,
        runtime_context: Mapping[str, Any] | None = None,
        prior_prepared: PreparedContext | None = None,
        resolved_config: ContextControlPlaneConfig | None = None,
        transcript_store: Any | None = None,
    ) -> PreparedContext:
        config = resolved_config or self._default_config
        active_messages = tuple(messages)
        transcript_messages: tuple[RuntimeMessage, ...] | None = None
        effects: list[ContextPreparationEffect] = []
        diagnostics: list[str] = list(config.metadata.get("deprecation_diagnostics", ()) or ())
        effective_runtime_context = dict(runtime_context or {})
        context_window = _resolve_context_window_for_prepare(
            agent=agent,
            messages=active_messages,
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=effective_runtime_context,
        )
        if context_window is not None:
            effective_runtime_context["context_window"] = serialize_resolved_context_window_snapshot(
                context_window
            )
            if context_window.policy_tag is not None:
                effective_runtime_context["context_window_policy_tag"] = context_window.policy_tag
        effective_private_context = _with_context_window_private_context(
            private_context,
            context_window,
        )
        effective_private_context = _apply_context_window_compaction_policy(
            effective_private_context,
            context_window,
        )

        active_messages, resolved_effects, resolved_diagnostics = await resolve_spillover_references(
            active_messages,
            session_id=session_id,
            transcript_store=transcript_store,
        )
        if resolved_effects:
            transcript_messages = active_messages
            effects.extend(resolved_effects)
            diagnostics.extend(resolved_diagnostics)

        budget_candidates = collect_context_window_candidates(active_messages)
        plan: ContextWindowPlan | None = None
        if config.context_window_hook is not None and budget_candidates:
            plan, budget_diagnostics = await invoke_context_window_hook(
                config.context_window_hook,
                ContextWindowRequest(
                    turn_id=turn_id,
                    attempt_index=attempt_index,
                    candidates=budget_candidates,
                    transcript_messages=active_messages,
                    prompt_context=prompt_context,
                    private_context=effective_private_context.readonly_view(),
                    provider_hints=ProviderContextWindowHints(
                        provider_name=effective_private_context.provider_name,
                        model_name=(
                            context_window.model_name
                            if context_window is not None
                            else _coerce_optional_string(runtime_context, "requested_model") or agent.model
                        ),
                        requested_model_route=effective_private_context.requested_model_route,
                        invocation_mode=effective_private_context.invocation_mode,
                        max_input_tokens=(
                            context_window.max_input_tokens if context_window is not None else None
                        ),
                        reserved_output_tokens=(
                            context_window.reserved_output_tokens if context_window is not None else None
                        ),
                        remaining_input_tokens=(
                            context_window.remaining_input_tokens if context_window is not None else None
                        ),
                        fallback_mode=context_window.fallback_mode if context_window is not None else None,
                        source=context_window.source if context_window is not None else None,
                        confidence=context_window.confidence if context_window is not None else None,
                        context_window_policy_tag=(
                            context_window.policy_tag if context_window is not None else None
                        ),
                    ),
                ),
                failure_mode=config.context_window_hook_failure_mode,
                timeout_seconds=config.context_window_hook_timeout_seconds,
            )
            diagnostics.extend(budget_diagnostics)
            if plan is not None:
                active_messages, budget_effects, apply_diagnostics = await apply_context_window_plan(
                    active_messages,
                    plan,
                    session_id=session_id,
                    turn_id=turn_id,
                    transcript_store=transcript_store,
                )
                if budget_effects:
                    transcript_messages = active_messages
                effects.extend(budget_effects)
                diagnostics.extend(apply_diagnostics)

        projected_messages, projection_metadata = apply_projection_pass(
            active_messages,
            max_active_messages=config.projection_max_messages,
        )
        if projected_messages != active_messages:
            active_messages = projected_messages
            effects.append(
                ContextPreparationEffect(
                    kind=ContextPreparationEffectKind.PROJECTION,
                    summary="Projected active context view.",
                    metadata=projection_metadata,
                )
            )

        compaction_result = await self._material_compaction_pass.apply(
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
            messages=active_messages,
            prompt_context=prompt_context,
            private_context=effective_private_context,
            runtime_context=effective_runtime_context,
        )
        if isinstance(compaction_result, CompactionResult) and compaction_result.applied:
            active_messages = tuple(compaction_result.messages)
            transcript_messages = tuple(compaction_result.messages)
            effects.append(
                ContextPreparationEffect(
                    kind=ContextPreparationEffectKind.COMPACTION,
                    summary="Material compaction rewritten turn context.",
                    metadata={
                        "compaction": serialize_compaction_result(compaction_result),
                    },
                )
            )

        prepared_prompt_context = build_prompt_envelope(
            prompt_context,
            effects=tuple(effects),
            plan=plan,
            diagnostics=tuple(diagnostics),
        )
        generation = next_context_generation(
            prior_prepared,
            active_messages=active_messages,
            prompt_context=prepared_prompt_context,
        )
        requires_sidecar_restart = (
            prior_prepared is None or generation != prior_prepared.generation
        )
        if requires_sidecar_restart and prior_prepared is not None:
            effects.append(
                ContextPreparationEffect(
                    kind=ContextPreparationEffectKind.SIDECAR_RESTART,
                    summary="Prepared context generation changed.",
                    metadata={"from_generation": prior_prepared.generation, "to_generation": generation},
                )
            )
        pressure = evaluate_context_pressure(
            active_messages,
            CompactionPolicy.from_private_context(
                effective_private_context,
                legacy_runtime_context=effective_runtime_context,
                default=CompactionPolicy(enabled=True),
            ),
        )
        context_window_policy_tag = (
            (context_window.policy_tag if context_window is not None else None)
            or (plan.policy_tag if plan is not None else None)
        )
        return PreparedContext(
            active_messages=active_messages,
            prompt_context=prepared_prompt_context,
            generation=generation,
            effects=tuple(effects),
            requires_sidecar_restart=requires_sidecar_restart,
            transcript_messages=transcript_messages,
            context_window=context_window,
            context_window_policy_tag=context_window_policy_tag,
            pressure={
                "message_count": pressure.message_count,
                "character_count": pressure.character_count,
                "triggered": pressure.triggered,
            },
            metadata={
                "effect_kinds": [effect.kind.value for effect in effects],
                "effect_summaries": [effect.summary for effect in effects if effect.summary],
                "diagnostics": diagnostics,
                "context_window": serialize_resolved_context_window_snapshot(context_window),
                "context_window_policy_tag": context_window_policy_tag,
                "budget_policy_tag": context_window_policy_tag,
                "spillover_artifact_refs": [
                    str(effect.metadata.get("artifact_ref"))
                    for effect in effects
                    if effect.metadata.get("artifact_ref") is not None
                ],
                "resolved_config": {
                    "projection_max_messages": config.projection_max_messages,
                    "context_window_hook_failure_mode": config.context_window_hook_failure_mode.value,
                    "budget_hook_failure_mode": config.context_window_hook_failure_mode.value,
                },
            },
        )


class DefaultRecoveryPolicy:
    def __init__(
        self,
        *,
        max_output_limit_retries: int = 1,
        max_provider_overload_retries: int = 1,
        max_compaction_attempts: int = 1,
    ) -> None:
        self._max_output_limit_retries = max_output_limit_retries
        self._max_provider_overload_retries = max_provider_overload_retries
        self._max_compaction_attempts = max_compaction_attempts

    def evaluate(
        self,
        recovery_input: NormalizedRecoveryInput,
        *,
        stop_outcome: StopPhaseOutcome | None = None,
        recovery_state: RecoveryState | None = None,
        prepared_context: PreparedContext | None = None,
    ) -> RecoveryDecision:
        state = recovery_state or RecoveryState()
        metadata = {
            "failure_class": recovery_input.failure_class.value,
            "retryable": recovery_input.retryable,
            "policy_tag": "default_recovery_policy",
            "retry_counters": dict(state.retry_counters),
            "prior_compaction_attempts": dict(state.prior_compaction_attempts),
        }

        if recovery_input.max_turns_exhausted:
            return RecoveryDecision(
                action=RecoveryAction.HALT,
                reason="max_turns_exhausted",
                terminal_reason="max_turns",
                metadata=metadata,
            )
        if recovery_input.interrupted:
            return RecoveryDecision(
                action=RecoveryAction.HALT,
                reason="attempt_interrupted",
                terminal_reason="interrupted",
                metadata=metadata,
            )
        if recovery_input.tool_executor_unavailable:
            return RecoveryDecision(
                action=RecoveryAction.HALT,
                reason="tool_executor_unavailable",
                terminal_reason="blocked",
                metadata=metadata,
            )

        if recovery_input.terminal_failure:
            if recovery_input.failure_class in {
                FailureClassification.CONTEXT_LIMIT,
                FailureClassification.MEDIA_LIMIT,
            } and recovery_input.retryable:
                compaction_attempts = state.compaction_attempt_count(recovery_input.failure_class)
                if compaction_attempts < self._max_compaction_attempts:
                    return RecoveryDecision(
                        action=RecoveryAction.COMPACT_AND_RETRY,
                        reason=recovery_input.failure_class.value,
                        metadata=metadata,
                    )
            if recovery_input.failure_class == FailureClassification.OUTPUT_LIMIT and recovery_input.retryable:
                retry_count = state.retry_count(FailureClassification.OUTPUT_LIMIT)
                if retry_count < self._max_output_limit_retries:
                    override = merge_request_override_state(
                        state.pending_override_snapshot,
                        RequestOverrideState(
                            max_output_tokens_override=_suggest_max_output_tokens(
                                state.pending_override_snapshot,
                                recovery_input.metadata,
                            ),
                            source="recovery:output_limit",
                            field_sources={
                                "max_output_tokens_override": "recovery:output_limit",
                            },
                            metadata={"sources": ["recovery:output_limit"]},
                        ),
                    )
                    return RecoveryDecision(
                        action=RecoveryAction.RETRY_WITH_OVERRIDE,
                        reason="output_limit",
                        request_override=override,
                        injected_messages=(_recovery_continuation_message("output_limit"),),
                        metadata=metadata,
                    )
            if (
                recovery_input.failure_class == FailureClassification.PROVIDER_OVERLOAD
                and recovery_input.retryable
                and state.retry_count(FailureClassification.PROVIDER_OVERLOAD)
                < self._max_provider_overload_retries
            ):
                return RecoveryDecision(
                    action=RecoveryAction.REBUILD_REQUEST,
                    reason="provider_overload",
                    metadata=metadata,
                )
            return RecoveryDecision(
                action=RecoveryAction.HALT,
                reason=recovery_input.failure_class.value
                if recovery_input.failure_class != FailureClassification.NONE
                else "attempt_error",
                terminal_reason=_terminal_reason_for_failure_class(recovery_input.failure_class),
                metadata=metadata,
            )

        if stop_outcome is not None:
            metadata["matched_hooks"] = list(stop_outcome.matched_hook_owners)
            if stop_outcome.disposition == StopDisposition.CONTINUE_SAME_TURN:
                return RecoveryDecision(
                    action=RecoveryAction.CONTINUE_SAME_TURN,
                    reason="stop_phase_continue",
                    injected_messages=stop_outcome.injected_messages,
                    request_override=stop_outcome.request_override,
                    metadata={**metadata, **stop_outcome.metadata},
                )
            if stop_outcome.disposition == StopDisposition.BLOCK_SESSION:
                return RecoveryDecision(
                    action=RecoveryAction.HALT,
                    reason="stop_hook_blocking",
                    terminal_reason="blocked",
                    request_override=stop_outcome.request_override,
                    metadata={**metadata, **stop_outcome.metadata},
                )

        if recovery_input.produced_tool_calls:
            return RecoveryDecision(
                action=RecoveryAction.CONTINUE_SAME_TURN,
                reason="tool_replay_continuation",
                metadata=metadata,
            )

        if prepared_context is not None:
            metadata["context_generation"] = prepared_context.generation
            metadata["context_effect_kinds"] = list(prepared_context.effect_kinds())

        return RecoveryDecision(
            action=RecoveryAction.HALT,
            reason="attempt_completed",
            terminal_reason=recovery_input.terminal_reason or "end_turn",
            metadata=metadata,
        )


def normalize_attempt_outcome(
    attempt: Any,
    *,
    prepared_context: PreparedContext | None = None,
    max_turns_exhausted: bool = False,
    tool_executor_unavailable: bool = False,
) -> NormalizedRecoveryInput:
    metadata = dict(getattr(attempt, "metadata", {}) or {})
    failure_class = _coerce_failure_class(metadata.get("failure_class"))
    stop_reason = _coerce_optional_string(metadata, "stop_reason") or getattr(
        attempt, "attempt_stop_reason", None
    )
    hinted_classification = _classify_recovery_with_context_window_hints(
        metadata=metadata,
        stop_reason=stop_reason,
        error=getattr(attempt, "error", None),
        prepared_context=prepared_context,
    )
    if failure_class is None:
        failure_class = (
            hinted_classification[0]
            if hinted_classification is not None
            else _failure_class_from_terminal_reason(stop_reason, error=getattr(attempt, "error", None))
        )
    retryable = _coerce_optional_bool(metadata.get("retryable"))
    if retryable is None:
        retryable = (
            hinted_classification[1]
            if hinted_classification is not None and hinted_classification[1] is not None
            else failure_class
            in {
                FailureClassification.CONTEXT_LIMIT,
                FailureClassification.OUTPUT_LIMIT,
                FailureClassification.MEDIA_LIMIT,
                FailureClassification.PROVIDER_OVERLOAD,
            }
        )
    return NormalizedRecoveryInput(
        terminal_reason=stop_reason,
        failure_class=failure_class,
        retryable=retryable,
        provider_error_code=_coerce_optional_string(metadata, "provider_error_code"),
        error=getattr(attempt, "error", None),
        abort_reason=getattr(attempt, "abort_reason", None),
        produced_tool_calls=bool(getattr(attempt, "produced_tool_calls", False)),
        tool_call_count=int(getattr(attempt, "tool_call_count", 0) or 0),
        max_turns_exhausted=max_turns_exhausted,
        tool_executor_unavailable=tool_executor_unavailable,
        metadata=metadata,
    )


def _resolve_context_window_for_prepare(
    *,
    agent: AgentDefinition,
    messages: Sequence[RuntimeMessage],
    prompt_context: PromptContextEnvelope,
    private_context: RuntimePrivateContext,
    runtime_context: Mapping[str, Any] | None,
) -> ResolvedContextWindowSnapshot | None:
    existing_snapshot = coerce_resolved_context_window_snapshot(
        runtime_context.get("context_window") if isinstance(runtime_context, Mapping) else None
    )
    profiles = coerce_model_context_window_profiles(
        runtime_context.get("provider_context_window_profiles") if isinstance(runtime_context, Mapping) else None
    )
    route_policy = coerce_route_context_window_policy(
        runtime_context.get("route_context_window_policy") if isinstance(runtime_context, Mapping) else None
    )
    if not profiles and existing_snapshot is not None:
        return existing_snapshot

    provider_name = (
        _coerce_optional_string(runtime_context, "provider_name") if isinstance(runtime_context, Mapping) else None
    ) or private_context.provider_name
    model_name = (
        _coerce_optional_string(runtime_context, "requested_model") if isinstance(runtime_context, Mapping) else None
    ) or agent.model
    route_name = (
        _coerce_optional_string(runtime_context, "resolved_model_route")
        if isinstance(runtime_context, Mapping)
        else None
    ) or private_context.resolved_model_route or private_context.requested_model_route

    provisional = resolve_context_window_snapshot(
        provider_name=provider_name,
        model_name=model_name,
        route_name=route_name,
        profiles=profiles,
        route_policy=route_policy,
        estimated_input_tokens=None,
    )
    estimated_input_tokens = _estimate_context_window_input_tokens(
        messages,
        prompt_context=prompt_context,
        snapshot=provisional,
    )
    return resolve_context_window_snapshot(
        provider_name=provider_name,
        model_name=model_name,
        route_name=route_name,
        profiles=profiles,
        route_policy=route_policy,
        estimated_input_tokens=estimated_input_tokens,
    )


def _estimate_context_window_input_tokens(
    messages: Sequence[RuntimeMessage],
    *,
    prompt_context: PromptContextEnvelope,
    snapshot: ResolvedContextWindowSnapshot | None,
) -> int:
    fragments = [message.text for message in messages]
    fragments.extend(prompt_context.memory_fragments)
    fragments.extend(prompt_context.hook_fragments)
    fragments.extend(prompt_context.compaction_fragments)
    if prompt_context.compaction_summary:
        fragments.append(json.dumps(prompt_context.compaction_summary, ensure_ascii=True, sort_keys=True))
    if prompt_context.compaction_boundary:
        fragments.append(json.dumps(prompt_context.compaction_boundary, ensure_ascii=True, sort_keys=True))
    if prompt_context.compaction_continuation:
        fragments.append(
            json.dumps(prompt_context.compaction_continuation, ensure_ascii=True, sort_keys=True)
        )
    return estimate_tokens_from_fragments(
        fragments,
        hint=snapshot.token_estimation_hint if snapshot is not None else None,
    )


def _with_context_window_private_context(
    private_context: RuntimePrivateContext,
    context_window: ResolvedContextWindowSnapshot | None,
) -> RuntimePrivateContext:
    if context_window is None:
        return private_context
    extensions = dict(private_context.extensions)
    extensions["context_window"] = serialize_resolved_context_window_snapshot(context_window)
    if context_window.policy_tag is not None:
        extensions["context_window_policy_tag"] = context_window.policy_tag
        extensions["budget_policy_tag"] = context_window.policy_tag
    return replace(private_context, extensions=extensions)


def _apply_context_window_compaction_policy(
    private_context: RuntimePrivateContext,
    context_window: ResolvedContextWindowSnapshot | None,
) -> RuntimePrivateContext:
    if context_window is None or not context_window.known:
        return private_context
    if context_window.fallback_mode != "proactive_and_reactive":
        return private_context
    extensions = dict(private_context.extensions)
    raw_policy = extensions.get("compaction_policy")
    if raw_policy is False:
        return private_context
    policy = dict(raw_policy) if isinstance(raw_policy, Mapping) else {}
    chars_per_token = (
        context_window.token_estimation_hint.chars_per_token
        if context_window.token_estimation_hint is not None
        and context_window.token_estimation_hint.chars_per_token is not None
        and context_window.token_estimation_hint.chars_per_token > 0
        else 4.0
    )
    trigger_buffer = max(0, context_window.trigger_buffer_tokens or 0)
    safe_token_limit = context_window.max_input_tokens - (context_window.reserved_output_tokens or 0) - trigger_buffer
    if safe_token_limit > 0:
        derived_max_characters = int(safe_token_limit * chars_per_token)
        existing_max_characters = _coerce_optional_int(policy.get("max_characters"))
        if existing_max_characters is None or existing_max_characters > derived_max_characters:
            policy["max_characters"] = derived_max_characters
    if (
        context_window.remaining_input_tokens is not None
        and context_window.remaining_input_tokens <= trigger_buffer
    ):
        policy["force"] = True
    extensions["compaction_policy"] = policy
    return replace(private_context, extensions=extensions)


def _classify_recovery_with_context_window_hints(
    *,
    metadata: Mapping[str, Any],
    stop_reason: str | None,
    error: str | None,
    prepared_context: PreparedContext | None,
) -> tuple[FailureClassification, bool | None] | None:
    snapshot = (
        prepared_context.context_window
        if prepared_context is not None and prepared_context.context_window is not None
        else coerce_resolved_context_window_snapshot(metadata.get("context_window"))
    )
    hints = snapshot.recovery_classification_hints if snapshot is not None else None
    if hints is None:
        return None
    provider_error_code = _coerce_optional_string(metadata, "provider_error_code")
    http_status = _coerce_optional_int(metadata.get("http_status"))
    error_message = " ".join(
        piece
        for piece in (
            error,
            _coerce_optional_string(metadata, "error"),
            _coerce_optional_string(metadata, "message"),
            _coerce_optional_string(metadata, "provider_message"),
        )
        if piece
    )
    if _matches_recovery_rule(
        hints.context_limit,
        stop_reason=stop_reason,
        provider_error_code=provider_error_code,
        http_status=http_status,
        error_message=error_message,
    ):
        return FailureClassification.CONTEXT_LIMIT, hints.context_limit.retryable
    if hints.output_limit is not None and _matches_recovery_rule(
        hints.output_limit,
        stop_reason=stop_reason,
        provider_error_code=provider_error_code,
        http_status=http_status,
        error_message=error_message,
    ):
        return FailureClassification.OUTPUT_LIMIT, hints.output_limit.retryable
    return None


def _matches_recovery_rule(
    rule: Any,
    *,
    stop_reason: str | None,
    provider_error_code: str | None,
    http_status: int | None,
    error_message: str,
) -> bool:
    if rule is None:
        return False
    matched = False
    if stop_reason is not None and stop_reason in getattr(rule, "stop_reasons", ()):
        matched = True
    if provider_error_code is not None and provider_error_code in getattr(rule, "provider_error_codes", ()):
        matched = True
    if http_status is not None and http_status in getattr(rule, "http_statuses", ()):
        matched = True
    lowered = error_message.lower()
    if lowered and any(fragment.lower() in lowered for fragment in getattr(rule, "message_substrings", ())):
        matched = True
    return matched


def collect_budget_candidates(
    messages: Sequence[RuntimeMessage],
) -> tuple[BudgetCandidate, ...]:
    candidates: list[BudgetCandidate] = []
    for message_index, message in enumerate(messages):
        metadata_entries = _tool_result_metadata_by_id(message.metadata)
        for block_index, block in enumerate(message.content):
            if not isinstance(block, ToolResultBlock):
                continue
            metadata = dict(metadata_entries.get(block.tool_use_id, {}))
            candidates.append(
                BudgetCandidate(
                    candidate_id=f"{message.message_id}:{block_index}:{block.tool_use_id}",
                    tool_use_id=block.tool_use_id,
                    tool_name=_coerce_optional_string(metadata, "tool_name"),
                    message_index=message_index,
                    block_index=block_index,
                    is_error=block.is_error,
                    content=block.content,
                    tool_result_summary=_coerce_mapping(metadata.get("result_summary")) or None,
                    estimated_token_count=_estimate_token_count(block.content),
                    serialized_size_bytes=_serialized_size(block.content),
                    metadata=metadata,
                )
            )
    return tuple(candidates)


def collect_context_window_candidates(
    messages: Sequence[RuntimeMessage],
) -> tuple[ContextWindowCandidate, ...]:
    return tuple(collect_budget_candidates(messages))


async def invoke_budget_hook(
    hook: ContextBudgetHook | Any,
    request: ContextBudgetRequest,
    *,
    failure_mode: ContextBudgetHookFailureMode,
    timeout_seconds: float | None,
) -> tuple[BudgetPlan | None, list[str]]:
    diagnostics: list[str] = []
    started_at = asyncio.get_running_loop().time()
    try:
        raw = await _invoke_budget_hook_callable(
            hook.plan if hasattr(hook, "plan") else hook,
            request,
            timeout_seconds=timeout_seconds,
            started_at=started_at,
        )
    except Exception as exc:
        diagnostics.append(f"context_budget_hook_error:{type(exc).__name__}")
        if failure_mode == ContextBudgetHookFailureMode.FAIL_PREPARE:
            raise
        return None, diagnostics
    if raw is None:
        return None, diagnostics
    plan = coerce_budget_plan(raw)
    if plan is None:
        diagnostics.append("context_budget_hook_unparseable")
        if failure_mode == ContextBudgetHookFailureMode.FAIL_PREPARE:
            raise ValueError("Context budget hook returned an unparsable plan")
        return None, diagnostics
    return plan, diagnostics


async def invoke_context_window_hook(
    hook: ContextWindowHook | Any,
    request: ContextWindowRequest,
    *,
    failure_mode: ContextWindowHookFailureMode,
    timeout_seconds: float | None,
) -> tuple[ContextWindowPlan | None, list[str]]:
    diagnostics: list[str] = []
    started_at = asyncio.get_running_loop().time()
    try:
        raw = await _invoke_budget_hook_callable(
            hook.plan if hasattr(hook, "plan") else hook,
            request,
            timeout_seconds=timeout_seconds,
            started_at=started_at,
        )
    except Exception as exc:
        diagnostics.append(f"context_window_hook_error:{type(exc).__name__}")
        if failure_mode == ContextWindowHookFailureMode.FAIL_PREPARE:
            raise
        return None, diagnostics
    if raw is None:
        return None, diagnostics
    plan = coerce_context_window_plan(raw)
    if plan is None:
        diagnostics.append("context_window_hook_unparseable")
        if failure_mode == ContextWindowHookFailureMode.FAIL_PREPARE:
            raise ValueError("Context window hook returned an unparsable plan")
        return None, diagnostics
    return plan, diagnostics


def coerce_budget_plan(value: object) -> BudgetPlan | None:
    if isinstance(value, BudgetPlan):
        return value
    if not isinstance(value, Mapping):
        return None
    raw_decisions = value.get("decisions", ())
    decisions: list[BudgetDecision] = []
    if isinstance(raw_decisions, Sequence):
        for raw_decision in raw_decisions:
            if not isinstance(raw_decision, Mapping):
                continue
            try:
                action = BudgetAction(str(raw_decision.get("action", "inline")))
            except ValueError:
                continue
            decisions.append(
                BudgetDecision(
                    candidate_id=str(raw_decision.get("candidate_id", "")),
                    action=action,
                    summary_text=(
                        str(raw_decision["summary_text"])
                        if raw_decision.get("summary_text") is not None
                        else None
                    ),
                    reason=(
                        str(raw_decision["reason"]) if raw_decision.get("reason") is not None else None
                    ),
                    artifact_metadata=(
                        _coerce_mapping(raw_decision.get("artifact_metadata")) or None
                    ),
                )
            )
    return BudgetPlan(
        decisions=tuple(decisions),
        policy_tag=_coerce_optional_string(value, "policy_tag"),
        metadata=_coerce_mapping(value.get("metadata")),
        diagnostics=tuple(str(item) for item in value.get("diagnostics", ()) or ()),
    )


def coerce_context_window_plan(value: object) -> ContextWindowPlan | None:
    return coerce_budget_plan(value)


async def resolve_spillover_references(
    messages: Sequence[RuntimeMessage],
    *,
    session_id: str,
    transcript_store: Any | None,
) -> tuple[tuple[RuntimeMessage, ...], tuple[ContextPreparationEffect, ...], list[str]]:
    if transcript_store is None:
        return tuple(messages), (), []

    updated_messages: list[RuntimeMessage] = []
    effects: list[ContextPreparationEffect] = []
    diagnostics: list[str] = []
    changed = False
    for message in messages:
        metadata_entries = list(message.metadata.get("tool_results", ()))
        metadata_by_tool_use = {
            str(entry.get("tool_use_id")): dict(entry)
            for entry in metadata_entries
            if isinstance(entry, Mapping)
        }
        updated_metadata = dict(message.metadata)
        updated_blocks: list[object] = []
        message_changed = False
        for block in message.content:
            if not isinstance(block, ToolResultBlock):
                updated_blocks.append(block)
                continue
            metadata_entry = metadata_by_tool_use.setdefault(
                block.tool_use_id,
                {"tool_use_id": block.tool_use_id},
            )
            artifact_ref = _coerce_optional_string(metadata_entry, "artifact_ref")
            if artifact_ref is None and isinstance(block.content, Mapping):
                raw_ref = block.content.get("artifact_ref")
                if raw_ref is not None:
                    artifact_ref = str(raw_ref)
                    metadata_entry["artifact_ref"] = artifact_ref
            if artifact_ref is None:
                updated_blocks.append(block)
                continue
            artifact = await transcript_store.load_artifact(session_id, artifact_ref)
            if artifact is not None:
                updated_blocks.append(block)
                continue
            changed = True
            message_changed = True
            diagnostics.append(f"missing_artifact:{artifact_ref}")
            metadata_entry["artifact_missing"] = True
            metadata_entry["degraded"] = True
            metadata_entry["degraded_reason"] = "artifact_unavailable"
            replacement = _missing_artifact_placeholder(block, metadata_entry, artifact_ref)
            updated_blocks.append(
                ToolResultBlock(
                    tool_use_id=block.tool_use_id,
                    content=replacement,
                    is_error=block.is_error,
                )
            )
            effects.append(
                ContextPreparationEffect(
                    kind=ContextPreparationEffectKind.SPILLOVER,
                    summary=f"Degraded missing spillover artifact {artifact_ref}.",
                    metadata={
                        "artifact_ref": artifact_ref,
                        "tool_use_id": block.tool_use_id,
                        "degraded": True,
                    },
                )
            )
        if message_changed:
            ordered_ids = [str(entry.get("tool_use_id")) for entry in metadata_entries if isinstance(entry, Mapping)]
            ordered_ids.extend(
                tool_use_id for tool_use_id in metadata_by_tool_use if tool_use_id not in ordered_ids
            )
            updated_metadata["tool_results"] = [metadata_by_tool_use[tool_use_id] for tool_use_id in ordered_ids]
            updated_messages.append(
                replace(message, content=tuple(updated_blocks), metadata=updated_metadata)
            )
            continue
        updated_messages.append(message)
    if not changed:
        return tuple(messages), (), diagnostics
    return ensure_tool_result_pairing(tuple(updated_messages)), tuple(effects), diagnostics


async def apply_budget_plan(
    messages: Sequence[RuntimeMessage],
    plan: BudgetPlan,
    *,
    session_id: str,
    turn_id: str,
    transcript_store: Any | None = None,
) -> tuple[tuple[RuntimeMessage, ...], tuple[ContextPreparationEffect, ...], list[str]]:
    candidate_ids = {candidate.candidate_id for candidate in collect_budget_candidates(messages)}
    decisions_by_id: dict[str, BudgetDecision] = {}
    diagnostics: list[str] = []
    for decision in plan.decisions:
        if decision.candidate_id not in candidate_ids:
            diagnostics.append(f"unknown_candidate:{decision.candidate_id}")
            continue
        if decision.candidate_id in decisions_by_id:
            diagnostics.append(f"duplicate_candidate:{decision.candidate_id}")
            continue
        if decision.action == BudgetAction.SUMMARIZE and not decision.summary_text:
            diagnostics.append(f"invalid_summary:{decision.candidate_id}")
            continue
        if decision.action == BudgetAction.EXTERNALIZE and transcript_store is None:
            diagnostics.append(f"invalid_externalize:{decision.candidate_id}")
            continue
        decisions_by_id[decision.candidate_id] = decision

    if not decisions_by_id:
        return tuple(messages), (), diagnostics

    updated_messages: list[RuntimeMessage] = []
    effects: list[ContextPreparationEffect] = []
    for message in messages:
        metadata_entries = list(message.metadata.get("tool_results", ()))
        metadata_by_tool_use = {
            str(entry.get("tool_use_id")): dict(entry)
            for entry in metadata_entries
            if isinstance(entry, Mapping)
        }
        updated_metadata = dict(message.metadata)
        updated_blocks: list[object] = []
        for block_index, block in enumerate(message.content):
            if not isinstance(block, ToolResultBlock):
                updated_blocks.append(block)
                continue
            candidate_id = f"{message.message_id}:{block_index}:{block.tool_use_id}"
            decision = decisions_by_id.get(candidate_id)
            if decision is None:
                updated_blocks.append(block)
                continue
            metadata_entry = metadata_by_tool_use.setdefault(block.tool_use_id, {"tool_use_id": block.tool_use_id})
            metadata_entry["decision_reason"] = decision.reason
            if plan.policy_tag is not None:
                metadata_entry["policy_tag"] = plan.policy_tag
            artifact_entry = None
            if transcript_store is not None:
                artifact_entry = await _reuse_or_persist_artifact(
                    transcript_store,
                    session_id=session_id,
                    turn_id=turn_id,
                    tool_use_id=block.tool_use_id,
                    payload=block.content,
                    metadata_entry=metadata_entry,
                    decision=decision,
                    policy_tag=plan.policy_tag,
                )
                if artifact_entry is not None:
                    metadata_entry["artifact_ref"] = artifact_entry.artifact_ref
                    metadata_entry["artifact_digest"] = artifact_entry.digest
                    metadata_entry["retention_class"] = artifact_entry.retention_class
            if decision.action == BudgetAction.SUMMARIZE and decision.summary_text is not None:
                metadata_entry["summarized"] = True
                metadata_entry["summary_text"] = decision.summary_text
                updated_blocks.append(
                    ToolResultBlock(
                        tool_use_id=block.tool_use_id,
                        content=decision.summary_text,
                        is_error=block.is_error,
                    )
                )
                effects.append(
                    ContextPreparationEffect(
                        kind=ContextPreparationEffectKind.BUDGET_DECISION,
                        summary=f"Summarized tool result {block.tool_use_id}.",
                        metadata={
                            "candidate_id": candidate_id,
                            "tool_use_id": block.tool_use_id,
                            "action": decision.action.value,
                            "reason": decision.reason,
                            "policy_tag": plan.policy_tag,
                        },
                    )
                )
                if artifact_entry is not None:
                    effects.append(
                        ContextPreparationEffect(
                            kind=ContextPreparationEffectKind.SPILLOVER,
                            summary=f"Persisted spillover artifact {artifact_entry.artifact_ref}.",
                            metadata={
                                "artifact_ref": artifact_entry.artifact_ref,
                                "tool_use_id": block.tool_use_id,
                                "action": decision.action.value,
                            },
                        )
                    )
                continue
            if decision.action == BudgetAction.EXTERNALIZE and artifact_entry is not None:
                metadata_entry["externalized"] = True
                if decision.summary_text is not None:
                    metadata_entry["summary_text"] = decision.summary_text
                updated_blocks.append(
                    ToolResultBlock(
                        tool_use_id=block.tool_use_id,
                        content=_externalized_replay_payload(
                            artifact_ref=artifact_entry.artifact_ref,
                            summary_text=decision.summary_text
                            or _coerce_optional_string(metadata_entry, "summary_text"),
                        ),
                        is_error=block.is_error,
                    )
                )
                effects.append(
                    ContextPreparationEffect(
                        kind=ContextPreparationEffectKind.BUDGET_DECISION,
                        summary=f"Externalized tool result {block.tool_use_id}.",
                        metadata={
                            "candidate_id": candidate_id,
                            "tool_use_id": block.tool_use_id,
                            "action": decision.action.value,
                            "reason": decision.reason,
                            "policy_tag": plan.policy_tag,
                            "artifact_ref": artifact_entry.artifact_ref,
                        },
                    )
                )
                effects.append(
                    ContextPreparationEffect(
                        kind=ContextPreparationEffectKind.SPILLOVER,
                        summary=f"Persisted spillover artifact {artifact_entry.artifact_ref}.",
                        metadata={
                            "artifact_ref": artifact_entry.artifact_ref,
                            "tool_use_id": block.tool_use_id,
                            "action": decision.action.value,
                        },
                    )
                )
                continue
            updated_blocks.append(block)
        if metadata_by_tool_use:
            ordered_ids = [str(entry.get("tool_use_id")) for entry in metadata_entries if isinstance(entry, Mapping)]
            ordered_ids.extend(
                tool_use_id for tool_use_id in metadata_by_tool_use if tool_use_id not in ordered_ids
            )
            updated_metadata["tool_results"] = [metadata_by_tool_use[tool_use_id] for tool_use_id in ordered_ids]
        updated_messages.append(replace(message, content=tuple(updated_blocks), metadata=updated_metadata))

    return ensure_tool_result_pairing(tuple(updated_messages)), tuple(effects), diagnostics


async def apply_context_window_plan(
    messages: Sequence[RuntimeMessage],
    plan: ContextWindowPlan,
    *,
    session_id: str,
    turn_id: str,
    transcript_store: Any | None = None,
) -> tuple[tuple[RuntimeMessage, ...], tuple[ContextPreparationEffect, ...], list[str]]:
    return await apply_budget_plan(
        messages,
        plan,
        session_id=session_id,
        turn_id=turn_id,
        transcript_store=transcript_store,
    )


def apply_projection_pass(
    messages: Sequence[RuntimeMessage],
    *,
    max_active_messages: int | None,
) -> tuple[tuple[RuntimeMessage, ...], dict[str, Any]]:
    if max_active_messages is None or len(messages) <= max_active_messages:
        return tuple(messages), {}

    system_prefix: list[RuntimeMessage] = []
    non_system_start = 0
    for index, message in enumerate(messages):
        if message.role != MessageRole.SYSTEM:
            non_system_start = index
            break
        system_prefix.append(message)
    else:
        return tuple(messages), {}

    latest_user_index = None
    for index, message in enumerate(messages):
        if message.role == MessageRole.USER:
            latest_user_index = index
    if latest_user_index is None:
        latest_user_index = len(messages) - 1

    pinned_indexes = {
        index
        for index, message in enumerate(messages)
        if message.role == MessageRole.SYSTEM or _message_requires_projection_pin(message)
    }
    pinned_indexes.add(latest_user_index)
    tail_indexes = list(range(max(non_system_start, len(messages) - max_active_messages), len(messages)))
    selected_indexes = sorted(pinned_indexes | set(tail_indexes))
    candidate_projected = tuple(messages[index] for index in selected_indexes)
    projected = ensure_tool_result_pairing(candidate_projected)
    projection_violations = check_projection_invariants(messages, projected)
    if projection_violations:
        return tuple(messages), {
            "before_count": len(messages),
            "after_count": len(messages),
            "projection_skipped": True,
            "violations": projection_violations,
        }
    return projected, {
        "before_count": len(messages),
        "after_count": len(projected),
        "latest_user_message_id": messages[latest_user_index].message_id,
    }


def check_projection_invariants(
    original_messages: Sequence[RuntimeMessage],
    projected_messages: Sequence[RuntimeMessage],
) -> tuple[str, ...]:
    violations: list[str] = []
    projected_ids = {message.message_id for message in projected_messages}

    for message in original_messages:
        if message.role != MessageRole.SYSTEM:
            break
        if message.message_id not in projected_ids:
            violations.append(f"missing_system_prompt:{message.message_id}")

    latest_user_message_id = None
    for message in reversed(original_messages):
        if message.role == MessageRole.USER:
            latest_user_message_id = message.message_id
            break
    if latest_user_message_id is not None and latest_user_message_id not in projected_ids:
        violations.append(f"missing_latest_user:{latest_user_message_id}")

    required_handles = {
        message.message_id
        for message in original_messages
        if _message_requires_projection_pin(message)
    }
    for message_id in required_handles:
        if message_id not in projected_ids:
            violations.append(f"missing_continuation_handle:{message_id}")

    original_tool_pairs = _tool_pair_signature(original_messages)
    projected_tool_pairs = _tool_pair_signature(projected_messages)
    if original_tool_pairs.intersection(projected_tool_pairs) != projected_tool_pairs:
        violations.append("tool_pairing_changed")
    original_tool_ids = _tool_result_ids(original_messages)
    projected_tool_ids = _tool_result_ids(projected_messages)
    paired_ids = original_tool_pairs
    if projected_tool_ids.intersection(paired_ids) != _assistant_tool_use_ids(projected_messages).intersection(paired_ids):
        violations.append("tool_pairing_changed")
    return tuple(violations)


def build_prompt_envelope(
    prompt_context: PromptContextEnvelope,
    *,
    effects: Sequence[ContextPreparationEffect],
    plan: ContextWindowPlan | None,
    diagnostics: Sequence[str],
) -> PromptContextEnvelope:
    extensions = dict(prompt_context.extensions)
    control_plane = dict(extensions.get("control_plane", {}))
    control_plane["effect_kinds"] = [effect.kind.value for effect in effects]
    control_plane["effects"] = [
        {
            "kind": effect.kind.value,
            "summary": effect.summary,
            "metadata": dict(effect.metadata),
        }
        for effect in effects
    ]
    if plan is not None:
        control_plane["context_window_policy_tag"] = plan.policy_tag
        control_plane["budget_policy_tag"] = plan.policy_tag
    if diagnostics:
        control_plane["diagnostics"] = list(diagnostics)

    extensions["control_plane"] = control_plane
    compaction_summary = prompt_context.compaction_summary
    compaction_boundary = prompt_context.compaction_boundary
    compaction_continuation = prompt_context.compaction_continuation
    for effect in effects:
        if effect.kind != ContextPreparationEffectKind.COMPACTION:
            continue
        compaction = _coerce_mapping(effect.metadata.get("compaction"))
        if not compaction:
            continue
        maybe_summary = _coerce_mapping(compaction.get("summary"))
        if maybe_summary:
            compaction_summary = maybe_summary
        maybe_boundary = _coerce_mapping(compaction.get("boundary"))
        if maybe_boundary:
            compaction_boundary = maybe_boundary
        maybe_continuation = _coerce_mapping(compaction.get("continuation"))
        if maybe_continuation:
            compaction_continuation = maybe_continuation
    return PromptContextEnvelope(
        memory_fragments=prompt_context.memory_fragments,
        hook_fragments=prompt_context.hook_fragments,
        compaction_fragments=prompt_context.compaction_fragments,
        attachments=prompt_context.attachments,
        session_hints=prompt_context.session_hints,
        compaction_summary=compaction_summary,
        compaction_boundary=compaction_boundary,
        compaction_continuation=compaction_continuation,
        extensions=extensions,
    )


def next_context_generation(
    prior_prepared: PreparedContext | None,
    *,
    active_messages: Sequence[RuntimeMessage],
    prompt_context: PromptContextEnvelope,
) -> int:
    if prior_prepared is None:
        return 1
    previous_signature = _prepared_signature(
        prior_prepared.active_messages,
        prior_prepared.prompt_context,
    )
    next_signature = _prepared_signature(active_messages, prompt_context)
    if previous_signature == next_signature:
        return prior_prepared.generation
    return prior_prepared.generation + 1


def _prepared_signature(
    active_messages: Sequence[RuntimeMessage],
    prompt_context: PromptContextEnvelope,
) -> str:
    message_fingerprint = [
        {
            "message_id": message.message_id,
            "role": message.role.value,
            "content": [block.__class__.__name__ for block in message.content],
            "text": message.text,
            "metadata": dict(message.metadata),
        }
        for message in active_messages
    ]
    payload = {
        "messages": message_fingerprint,
        "prompt_context": {
            "memory_fragments": list(prompt_context.memory_fragments),
            "hook_fragments": list(prompt_context.hook_fragments),
            "compaction_fragments": list(prompt_context.compaction_fragments),
            "attachments": [
                {
                    "name": attachment.name,
                    "path": attachment.path,
                    "mime_type": attachment.mime_type,
                    "metadata": dict(attachment.metadata),
                }
                for attachment in prompt_context.attachments
            ],
            "compat_metadata": prompt_context.compat_metadata(),
        },
        "compaction_summary": prompt_context.compaction_summary,
        "compaction_boundary": prompt_context.compaction_boundary,
        "compaction_continuation": prompt_context.compaction_continuation,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)


def _message_requires_projection_pin(message: RuntimeMessage) -> bool:
    if message.attachments:
        return True
    metadata = message.metadata
    if metadata.get("compaction_summary"):
        return True
    if _message_has_artifact_reference(message):
        return True
    if any(
        key in metadata
        for key in (
            "compaction",
            "compaction_continuation",
            "artifact_ref",
            "continuation_blocked",
        )
    ):
        return True
    return False


def _message_has_artifact_reference(message: RuntimeMessage) -> bool:
    if _mapping_contains_artifact_ref(message.metadata):
        return True
    return any(
        isinstance(block, ToolResultBlock) and _mapping_contains_artifact_ref(block.content)
        for block in message.content
    )


def _tool_pair_signature(messages: Sequence[RuntimeMessage]) -> set[str]:
    return _assistant_tool_use_ids(messages).intersection(_tool_result_ids(messages))


def _assistant_tool_use_ids(messages: Sequence[RuntimeMessage]) -> set[str]:
    tool_use_ids: set[str] = set()
    for message in messages:
        if message.role != MessageRole.ASSISTANT:
            continue
        for block in message.content:
            if hasattr(block, "tool_use_id"):
                tool_use_ids.add(str(getattr(block, "tool_use_id")))
    return tool_use_ids


def _tool_result_ids(messages: Sequence[RuntimeMessage]) -> set[str]:
    result_ids: set[str] = set()
    for message in messages:
        for block in message.content:
            if message.role == MessageRole.USER and isinstance(block, ToolResultBlock):
                result_ids.add(str(block.tool_use_id))
    return result_ids


def _mapping_contains_artifact_ref(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("artifact_ref") is not None:
            return True
        return any(_mapping_contains_artifact_ref(item) for item in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_mapping_contains_artifact_ref(item) for item in value)
    return False


def maybe_resume_private_context(
    private_context: RuntimePrivateContext,
    resumable_override: RequestOverrideState | None,
) -> RuntimePrivateContext:
    if resumable_override is None:
        return private_context
    extensions = dict(private_context.extensions)
    extensions["request_override"] = resumable_override.serialize()
    return private_context_from_legacy_runtime_context(
        {
            **private_context.compat_metadata(),
            "request_override": resumable_override.serialize(),
        }
    )


def _tool_result_metadata_by_id(metadata: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    entries = metadata.get("tool_results", ())
    if not isinstance(entries, Sequence):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        tool_use_id = entry.get("tool_use_id")
        if tool_use_id is None:
            continue
        result[str(tool_use_id)] = dict(entry)
    return result


async def _reuse_or_persist_artifact(
    transcript_store: Any,
    *,
    session_id: str,
    turn_id: str,
    tool_use_id: str,
    payload: Any,
    metadata_entry: Mapping[str, Any],
    decision: BudgetDecision,
    policy_tag: str | None,
) -> Any:
    artifact_ref = _coerce_optional_string(metadata_entry, "artifact_ref")
    if artifact_ref is not None:
        existing = await transcript_store.load_artifact(session_id, artifact_ref)
        if existing is not None:
            return existing.entry
    return await transcript_store.persist_artifact(
        session_id,
        turn_id=turn_id,
        kind="tool_result_spillover",
        payload=payload,
        metadata={
            "tool_use_id": tool_use_id,
            "decision_action": decision.action.value,
            "decision_reason": decision.reason,
            "policy_tag": policy_tag,
            "summary_text": decision.summary_text,
            "artifact_metadata": dict(decision.artifact_metadata or {}),
        },
        retention_class="referenced",
    )


def _externalized_replay_payload(
    *,
    artifact_ref: str,
    summary_text: str | None,
) -> dict[str, Any]:
    payload = {
        "artifact_ref": artifact_ref,
        "kind": "tool_result_spillover",
        "externalized": True,
    }
    if summary_text is not None:
        payload["summary"] = summary_text
    return payload


def _missing_artifact_placeholder(
    block: ToolResultBlock,
    metadata_entry: Mapping[str, Any],
    artifact_ref: str,
) -> str:
    summary_text = _coerce_optional_string(metadata_entry, "summary_text")
    if summary_text:
        return summary_text
    content = block.content
    if isinstance(content, Mapping):
        summary = content.get("summary")
        if summary is not None:
            normalized = str(summary).strip()
            if normalized:
                return normalized
    return f"[missing spillover artifact: {artifact_ref}]"


def _failure_class_from_terminal_reason(
    terminal_reason: str | None,
    *,
    error: str | None = None,
) -> FailureClassification:
    if terminal_reason in {"prompt_too_long", "context_limit"}:
        return FailureClassification.CONTEXT_LIMIT
    if terminal_reason in {"output_limit", "max_tokens"}:
        return FailureClassification.OUTPUT_LIMIT
    if terminal_reason in {"image_error", "media_limit"}:
        return FailureClassification.MEDIA_LIMIT
    if terminal_reason == "provider_overload":
        return FailureClassification.PROVIDER_OVERLOAD
    if terminal_reason == "auth_error":
        return FailureClassification.AUTH_ERROR
    if error is not None and terminal_reason in {"error", None}:
        return FailureClassification.INTERNAL_ERROR
    return FailureClassification.NONE


def _coerce_failure_class(value: object) -> FailureClassification | None:
    if isinstance(value, FailureClassification):
        return value
    if value is None:
        return None
    try:
        return FailureClassification(str(value))
    except ValueError:
        return None


def _terminal_reason_for_failure_class(failure_class: FailureClassification) -> str:
    mapping = {
        FailureClassification.NONE: "end_turn",
        FailureClassification.CONTEXT_LIMIT: "prompt_too_long",
        FailureClassification.OUTPUT_LIMIT: "incomplete",
        FailureClassification.MEDIA_LIMIT: "image_error",
        FailureClassification.PROVIDER_OVERLOAD: "error",
        FailureClassification.AUTH_ERROR: "error",
        FailureClassification.TOOL_SCHEMA_ERROR: "error",
        FailureClassification.INTERNAL_ERROR: "error",
    }
    return mapping[failure_class]


def _suggest_max_output_tokens(
    existing_override: RequestOverrideState | None,
    metadata: Mapping[str, Any],
) -> int:
    current = None
    if existing_override is not None:
        current = existing_override.max_output_tokens_override
    if current is None:
        current = _coerce_optional_int(metadata.get("max_output_tokens"))
    if current is None:
        return 2048
    return max(256, current * 2)


def _recovery_continuation_message(reason: str) -> RuntimeMessage:
    return RuntimeMessage(
        message_id=f"recovery-{uuid4().hex}",
        role=MessageRole.USER,
        content="Continue from your previous response.",
        metadata={"recovery_injected": True, "recovery_reason": reason},
    )


def _estimate_token_count(value: Any) -> int | None:
    size = _serialized_size(value)
    if size is None:
        return None
    return max(1, size // 4)


def _serialized_size(value: Any) -> int | None:
    try:
        return len(json.dumps(value, ensure_ascii=True, sort_keys=True, default=str))
    except TypeError:
        return None


def _coerce_optional_string(mapping: Mapping[str, Any] | None, key: str) -> str | None:
    if not isinstance(mapping, Mapping):
        return None
    value = mapping.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _coerce_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _coerce_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
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


async def maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


async def _invoke_budget_hook_callable(
    hook_callable: Any,
    request: ContextBudgetRequest,
    *,
    timeout_seconds: float | None,
    started_at: float,
) -> Any:
    if inspect.iscoroutinefunction(hook_callable):
        return await _await_with_timeout(
            hook_callable(request),
            timeout_seconds=timeout_seconds,
            started_at=started_at,
        )
    if timeout_seconds is None:
        return await maybe_await(hook_callable(request))
    result = await _await_with_timeout(
        asyncio.to_thread(hook_callable, request),
        timeout_seconds=timeout_seconds,
        started_at=started_at,
    )
    if inspect.isawaitable(result):
        return await _await_with_timeout(
            result,
            timeout_seconds=timeout_seconds,
            started_at=started_at,
        )
    return result


async def _await_with_timeout(
    value: Any,
    *,
    timeout_seconds: float | None,
    started_at: float,
) -> Any:
    if inspect.isawaitable(value):
        if timeout_seconds is None:
            return await value
        remaining = timeout_seconds - (asyncio.get_running_loop().time() - started_at)
        if remaining <= 0:
            raise TimeoutError
        return await asyncio.wait_for(value, timeout=remaining)
    return value


__all__ = [
    "BudgetAction",
    "BudgetCandidate",
    "BudgetDecision",
    "BudgetPlan",
    "ContextWindowCandidate",
    "ContextBudgetHook",
    "ContextBudgetHookFailureMode",
    "ContextBudgetRequest",
    "ContextWindowDecision",
    "ContextWindowHook",
    "ContextWindowHookFailureMode",
    "ContextWindowPlan",
    "ContextWindowRequest",
    "ContextControlPlane",
    "ContextControlPlaneConfig",
    "ContextPreparationEffect",
    "ContextPreparationEffectKind",
    "DefaultContextControlPlane",
    "DefaultRecoveryPolicy",
    "FailureClassification",
    "MaterialCompactionPass",
    "NormalizedRecoveryInput",
    "PreparedContext",
    "ProviderBudgetHints",
    "ProviderContextWindowHints",
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryPolicy",
    "RecoveryState",
    "StopDisposition",
    "StopPhaseOutcome",
    "apply_budget_plan",
    "apply_context_window_plan",
    "apply_projection_pass",
    "build_prompt_envelope",
    "check_projection_invariants",
    "collect_budget_candidates",
    "collect_context_window_candidates",
    "coerce_budget_plan",
    "coerce_context_window_plan",
    "invoke_budget_hook",
    "invoke_context_window_hook",
    "maybe_resume_private_context",
    "next_context_generation",
    "normalize_attempt_outcome",
]
