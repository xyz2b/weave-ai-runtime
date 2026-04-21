from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from .bus import HookBus


HookCallback = Callable[[Any], Any]


class HookPhaseTier(StrEnum):
    KERNEL_PUBLIC = "kernel_public"
    CONTROL_PLANE_PUBLIC = "control_plane_public"
    INTERNAL_ONLY = "internal_only"


class HookEffectClass(StrEnum):
    OBSERVE = "observe"
    TRANSFORM = "transform"
    DECIDE = "decide"
    SIDECAR = "sidecar"


class HookHandlerKind(StrEnum):
    CALLBACK = "callback"
    HTTP = "http"
    COMMAND = "command"
    AGENT = "agent"
    PROMPT = "prompt"

    @property
    def external(self) -> bool:
        return self is not HookHandlerKind.CALLBACK


class HookSourceKind(StrEnum):
    RUNTIME_CONFIG = "runtime_config"
    HOST_API = "host_api"
    DEFINITION = "definition"
    SESSION_API = "session_api"
    TURN_API = "turn_api"
    COMPAT = "compat"


class HookScopeLifetime(StrEnum):
    SESSION_TEMPLATE = "session-template"
    SESSION = "session"
    TURN = "turn"


class HookActivationState(StrEnum):
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class HookMatch:
    target: str = "*"

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", str(self.target or "*"))


@dataclass(frozen=True, slots=True)
class HookRegistrationScope:
    lifetime: HookScopeLifetime
    inherit_to_children: bool = False
    turn_id: str | None = None
    session_id: str | None = None
    cleanup_boundary: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lifetime", HookScopeLifetime(self.lifetime))

    @property
    def default_cleanup_boundary(self) -> str:
        if self.cleanup_boundary is not None:
            return self.cleanup_boundary
        if self.lifetime == HookScopeLifetime.TURN:
            return "turn_end"
        if self.lifetime == HookScopeLifetime.SESSION:
            return "session_end"
        return "template_release"


@dataclass(frozen=True, slots=True)
class HookEffectContract:
    effect_classes: tuple[HookEffectClass, ...] = ()
    effect_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "effect_classes",
            tuple(HookEffectClass(value) for value in self.effect_classes),
        )
        object.__setattr__(
            self,
            "effect_fields",
            tuple(str(value) for value in self.effect_fields if str(value).strip()),
        )


@dataclass(frozen=True, slots=True)
class HookHandlerManifest:
    kind: HookHandlerKind
    binding: str | None = None
    callback: HookCallback | None = field(default=None, repr=False, compare=False)
    endpoint: str | None = None
    method: str = "POST"
    command: tuple[str, ...] = ()
    agent_name: str | None = None
    prompt: str | None = None
    timeout_ms: int | None = None
    response_contract: str | None = None
    policy_tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    static_effect: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", HookHandlerKind(self.kind))
        object.__setattr__(self, "method", str(self.method or "POST").upper())
        object.__setattr__(self, "command", tuple(str(item) for item in self.command))
        object.__setattr__(self, "policy_tags", tuple(str(item) for item in self.policy_tags))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def handler_kind(self) -> str:
        return self.kind.value


@dataclass(frozen=True, slots=True)
class HookRegistrationRequest:
    phase: str
    match: HookMatch = field(default_factory=HookMatch)
    scope: HookRegistrationScope = field(
        default_factory=lambda: HookRegistrationScope(HookScopeLifetime.SESSION)
    )
    handler: HookHandlerManifest = field(
        default_factory=lambda: HookHandlerManifest(kind=HookHandlerKind.CALLBACK)
    )
    contract: HookEffectContract = field(default_factory=HookEffectContract)
    owner_hint: str | None = None
    source_ref: str | None = None
    once: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", str(self.phase))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(slots=True)
class HookRegistrationHandle:
    registration_id: str
    source_kind: HookSourceKind
    owner: str
    phase: str
    scope: HookRegistrationScope
    _bus: HookBus | None = field(default=None, repr=False)
    _activation_state: HookActivationState = HookActivationState.PENDING_ACTIVATION

    @property
    def activation_state(self) -> HookActivationState:
        if self._bus is None:
            return self._activation_state
        return self._bus.registration_state(self.registration_id)

    def release(self) -> HookActivationState:
        if self._bus is None:
            self._activation_state = HookActivationState.RELEASED
            return self._activation_state
        self._activation_state = self._bus.release_registration(self.registration_id)
        return self._activation_state


@dataclass(frozen=True, slots=True)
class HookInventoryQuery:
    session_id: str | None = None
    turn_id: str | None = None
    phase: str | None = None
    owner: str | None = None
    source_kind: HookSourceKind | str | None = None
    activation_state: HookActivationState | str | None = None
    include_inactive: bool = False
    limit: int | None = None
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.source_kind is not None and not isinstance(self.source_kind, HookSourceKind):
            object.__setattr__(self, "source_kind", HookSourceKind(str(self.source_kind)))
        if self.activation_state is not None and not isinstance(
            self.activation_state,
            HookActivationState,
        ):
            object.__setattr__(
                self,
                "activation_state",
                HookActivationState(str(self.activation_state)),
            )


@dataclass(frozen=True, slots=True)
class HookDispatchTraceQuery:
    session_id: str | None = None
    turn_id: str | None = None
    phase: str | None = None
    owner: str | None = None
    source_kind: HookSourceKind | str | None = None
    limit: int | None = None
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.source_kind is not None and not isinstance(self.source_kind, HookSourceKind):
            object.__setattr__(self, "source_kind", HookSourceKind(str(self.source_kind)))


@dataclass(frozen=True, slots=True)
class HookInventoryEntry:
    registration_id: str
    activation_state: HookActivationState
    source_kind: HookSourceKind
    source_ref: str
    owner: str
    phase: str
    scope: HookRegistrationScope
    handler_kind: HookHandlerKind
    matcher_summary: str
    precedence_key: str
    session_id: str | None = None
    turn_id: str | None = None
    parent_registration_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "activation_state", HookActivationState(self.activation_state))
        object.__setattr__(self, "source_kind", HookSourceKind(self.source_kind))
        object.__setattr__(self, "handler_kind", HookHandlerKind(self.handler_kind))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class HookTraceRegistration:
    registration_id: str
    source_kind: HookSourceKind
    source_ref: str
    owner: str
    phase: str
    handler_kind: HookHandlerKind
    matcher: str
    precedence_key: str
    activation_state: HookActivationState
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", HookSourceKind(self.source_kind))
        object.__setattr__(self, "handler_kind", HookHandlerKind(self.handler_kind))
        object.__setattr__(self, "activation_state", HookActivationState(self.activation_state))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class HookIgnoredEffect:
    registration_id: str
    field: str
    reason: str


@dataclass(frozen=True, slots=True)
class HookDispatchTrace:
    dispatch_id: str
    session_id: str
    turn_id: str | None
    phase: str
    matched_registrations: tuple[HookTraceRegistration, ...] = ()
    blocked_registrations: tuple[HookTraceRegistration, ...] = ()
    ignored_effects: tuple[HookIgnoredEffect, ...] = ()
    winner_summary: dict[str, Any] = field(default_factory=dict)
    applied_outcome: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched_registrations", tuple(self.matched_registrations))
        object.__setattr__(self, "blocked_registrations", tuple(self.blocked_registrations))
        object.__setattr__(self, "ignored_effects", tuple(self.ignored_effects))
        object.__setattr__(self, "winner_summary", dict(self.winner_summary))
        object.__setattr__(self, "applied_outcome", dict(self.applied_outcome))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class HookPhaseContract:
    phase: str
    tier: HookPhaseTier
    minimum_payload_fields: tuple[str, ...]
    effect_classes: tuple[HookEffectClass, ...]
    effect_fields: tuple[str, ...]
    external_handler_allowed: bool = False
    main_loop_layer: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimum_payload_fields", tuple(str(item) for item in self.minimum_payload_fields))
        object.__setattr__(
            self,
            "effect_classes",
            tuple(HookEffectClass(item) for item in self.effect_classes),
        )
        object.__setattr__(self, "effect_fields", tuple(str(item) for item in self.effect_fields))


_PUBLIC_PHASE_CONTRACTS: tuple[HookPhaseContract, ...] = (
    HookPhaseContract(
        phase="SessionStart",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "config_snapshot"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.SIDECAR),
        effect_fields=("additional_context", "notifications", "metadata"),
        main_loop_layer="session_lifecycle",
    ),
    HookPhaseContract(
        phase="UserPromptSubmit",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "turn_id", "prompt", "attachments"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.TRANSFORM, HookEffectClass.SIDECAR),
        effect_fields=("additional_context", "notifications", "metadata"),
        main_loop_layer="turn_ingress_and_context_prep",
    ),
    HookPhaseContract(
        phase="PreToolUse",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "turn_id", "tool_name", "tool_input"),
        effect_classes=(
            HookEffectClass.OBSERVE,
            HookEffectClass.TRANSFORM,
            HookEffectClass.DECIDE,
            HookEffectClass.SIDECAR,
        ),
        effect_fields=("updated_input", "continue_execution", "notifications", "metadata"),
        external_handler_allowed=True,
        main_loop_layer="tool_execution_boundary",
    ),
    HookPhaseContract(
        phase="PostToolUse",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "turn_id", "tool_name", "tool_input", "tool_result"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.DECIDE, HookEffectClass.SIDECAR),
        effect_fields=("continue_execution", "notifications", "metadata"),
        external_handler_allowed=True,
        main_loop_layer="tool_execution_boundary",
    ),
    HookPhaseContract(
        phase="PostToolUseFailure",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "turn_id", "tool_name", "tool_input", "error_message"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.SIDECAR),
        effect_fields=("notifications", "metadata"),
        main_loop_layer="tool_execution_boundary",
    ),
    HookPhaseContract(
        phase="Stop",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "turn_id", "reason"),
        effect_classes=(
            HookEffectClass.OBSERVE,
            HookEffectClass.TRANSFORM,
            HookEffectClass.DECIDE,
            HookEffectClass.SIDECAR,
        ),
        effect_fields=(
            "additional_context",
            "continue_execution",
            "stop_disposition",
            "notifications",
            "injected_messages",
            "request_override",
            "metadata",
        ),
        external_handler_allowed=True,
        main_loop_layer="terminal_and_recovery",
    ),
    HookPhaseContract(
        phase="SubagentStop",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "turn_id", "agent_name", "status"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.SIDECAR),
        effect_fields=("notifications", "metadata"),
        main_loop_layer="cross_cutting",
    ),
    HookPhaseContract(
        phase="SessionEnd",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "final_status"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.SIDECAR),
        effect_fields=("notifications", "metadata"),
        main_loop_layer="session_lifecycle",
    ),
    HookPhaseContract(
        phase="Notification",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "message", "level"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.SIDECAR),
        effect_fields=("notifications", "metadata"),
        main_loop_layer="cross_cutting",
    ),
    HookPhaseContract(
        phase="Elicitation",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "prompt", "kind"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.DECIDE, HookEffectClass.SIDECAR),
        effect_fields=("elicitation_result", "notifications", "metadata"),
        external_handler_allowed=True,
        main_loop_layer="cross_cutting",
    ),
    HookPhaseContract(
        phase="ElicitationResult",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "prompt", "response"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.SIDECAR),
        effect_fields=("notifications", "metadata"),
        main_loop_layer="cross_cutting",
    ),
    HookPhaseContract(
        phase="PreCompact",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "token_count"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.SIDECAR),
        effect_fields=("notifications", "metadata"),
        main_loop_layer="turn_ingress_and_context_prep",
    ),
    HookPhaseContract(
        phase="PostCompact",
        tier=HookPhaseTier.KERNEL_PUBLIC,
        minimum_payload_fields=("session_id", "summary_id"),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.SIDECAR),
        effect_fields=("notifications", "metadata"),
        main_loop_layer="turn_ingress_and_context_prep",
    ),
    HookPhaseContract(
        phase="PreContextAssemble",
        tier=HookPhaseTier.CONTROL_PLANE_PUBLIC,
        minimum_payload_fields=(
            "session_id",
            "turn_id",
            "active_messages",
            "attachment_descriptors",
            "runtime_metadata_view",
        ),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.TRANSFORM, HookEffectClass.SIDECAR),
        effect_fields=("additional_context", "notifications", "metadata"),
        main_loop_layer="turn_ingress_and_context_prep",
    ),
    HookPhaseContract(
        phase="PostContextAssemble",
        tier=HookPhaseTier.CONTROL_PLANE_PUBLIC,
        minimum_payload_fields=(
            "session_id",
            "turn_id",
            "prompt_context_envelope",
            "context_generation",
            "request_input_view",
        ),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.TRANSFORM, HookEffectClass.SIDECAR),
        effect_fields=("additional_context", "request_override", "notifications", "metadata"),
        external_handler_allowed=True,
        main_loop_layer="turn_ingress_and_context_prep",
    ),
    HookPhaseContract(
        phase="PreModelRequest",
        tier=HookPhaseTier.CONTROL_PLANE_PUBLIC,
        minimum_payload_fields=(
            "session_id",
            "turn_id",
            "context_generation",
            "request_envelope",
            "request_metadata",
        ),
        effect_classes=(
            HookEffectClass.OBSERVE,
            HookEffectClass.TRANSFORM,
            HookEffectClass.DECIDE,
            HookEffectClass.SIDECAR,
        ),
        effect_fields=("continue_execution", "request_override", "notifications", "metadata"),
        external_handler_allowed=True,
        main_loop_layer="attempt_request_shaping",
    ),
    HookPhaseContract(
        phase="PostModelResponse",
        tier=HookPhaseTier.CONTROL_PLANE_PUBLIC,
        minimum_payload_fields=(
            "session_id",
            "turn_id",
            "request_id",
            "provider_stop_reason",
            "usage",
            "response_envelope",
        ),
        effect_classes=(HookEffectClass.OBSERVE, HookEffectClass.TRANSFORM, HookEffectClass.SIDECAR),
        effect_fields=("request_override", "injected_messages", "notifications", "metadata"),
        external_handler_allowed=True,
        main_loop_layer="attempt_request_shaping",
    ),
    HookPhaseContract(
        phase="RecoveryDecision",
        tier=HookPhaseTier.CONTROL_PLANE_PUBLIC,
        minimum_payload_fields=(
            "session_id",
            "turn_id",
            "attempt_index",
            "recovery_input",
            "candidate_action",
            "failure_class",
        ),
        effect_classes=(
            HookEffectClass.OBSERVE,
            HookEffectClass.TRANSFORM,
            HookEffectClass.DECIDE,
            HookEffectClass.SIDECAR,
        ),
        effect_fields=("continue_execution", "request_override", "injected_messages", "metadata"),
        external_handler_allowed=True,
        main_loop_layer="terminal_and_recovery",
    ),
)


PUBLIC_PHASE_CONTRACTS: dict[str, HookPhaseContract] = {
    contract.phase: contract for contract in _PUBLIC_PHASE_CONTRACTS
}


SOURCE_PRECEDENCE: dict[HookSourceKind, int] = {
    HookSourceKind.RUNTIME_CONFIG: 0,
    HookSourceKind.HOST_API: 1,
    HookSourceKind.DEFINITION: 2,
    HookSourceKind.SESSION_API: 3,
    HookSourceKind.TURN_API: 4,
    HookSourceKind.COMPAT: 3,
}


HOOK_EFFECT_FIELDS: tuple[str, ...] = (
    "additional_context",
    "updated_input",
    "continue_execution",
    "notifications",
    "elicitation_result",
    "stop_disposition",
    "injected_messages",
    "request_override",
    "metadata",
)


def phase_contract_for(phase: str) -> HookPhaseContract:
    return PUBLIC_PHASE_CONTRACTS.get(
        str(phase),
        HookPhaseContract(
            phase=str(phase),
            tier=HookPhaseTier.INTERNAL_ONLY,
            minimum_payload_fields=(),
            effect_classes=(),
            effect_fields=(),
            external_handler_allowed=False,
            main_loop_layer=None,
        ),
    )


def is_public_phase(phase: str) -> bool:
    return phase_contract_for(phase).tier is not HookPhaseTier.INTERNAL_ONLY


__all__ = [
    "HOOK_EFFECT_FIELDS",
    "HookActivationState",
    "HookCallback",
    "HookDispatchTrace",
    "HookDispatchTraceQuery",
    "HookEffectClass",
    "HookEffectContract",
    "HookHandlerKind",
    "HookHandlerManifest",
    "HookIgnoredEffect",
    "HookInventoryEntry",
    "HookInventoryQuery",
    "HookMatch",
    "HookPhaseContract",
    "HookPhaseTier",
    "HookRegistrationHandle",
    "HookRegistrationRequest",
    "HookRegistrationScope",
    "HookScopeLifetime",
    "HookSourceKind",
    "HookTraceRegistration",
    "PUBLIC_PHASE_CONTRACTS",
    "SOURCE_PRECEDENCE",
    "is_public_phase",
    "phase_contract_for",
]
