from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .bus import HookBus
from .helpers import build_callback_hook_request
from .models import RuntimeHookPhase
from .platform import (
    HookDispatchTraceQuery,
    HookInventoryQuery,
    HookRegistrationHandle,
    HookRegistrationRequest,
    HookScopeLifetime,
    HookSourceKind,
)

_InventoryQuery = HookInventoryQuery | Mapping[str, Any] | None
_TraceQuery = HookDispatchTraceQuery | Mapping[str, Any] | None
_ValueFactory = Callable[[], Any]

_STABLE_PHASE_METHODS: tuple[tuple[str, str], ...] = (
    ("on_session_start", RuntimeHookPhase.SESSION_START.value),
    ("on_session_end", RuntimeHookPhase.SESSION_END.value),
    ("on_pre_tool_use", RuntimeHookPhase.PRE_TOOL_USE.value),
    ("on_post_tool_use", RuntimeHookPhase.POST_TOOL_USE.value),
    ("on_post_tool_use_failure", RuntimeHookPhase.POST_TOOL_USE_FAILURE.value),
    ("on_stop", RuntimeHookPhase.STOP.value),
    ("on_notification", RuntimeHookPhase.NOTIFICATION.value),
    ("on_elicitation", RuntimeHookPhase.ELICITATION.value),
    ("on_elicitation_result", RuntimeHookPhase.ELICITATION_RESULT.value),
    ("on_pre_model_request", RuntimeHookPhase.PRE_MODEL_REQUEST.value),
    ("on_post_model_response", RuntimeHookPhase.POST_MODEL_RESPONSE.value),
)

_ADVANCED_PHASE_METHODS: tuple[tuple[str, str], ...] = (
    ("on_user_prompt_submit", RuntimeHookPhase.USER_PROMPT_SUBMIT.value),
    ("on_subagent_stop", RuntimeHookPhase.SUBAGENT_STOP.value),
    ("on_pre_compact", RuntimeHookPhase.PRE_COMPACT.value),
    ("on_post_compact", RuntimeHookPhase.POST_COMPACT.value),
    ("on_pre_context_assemble", RuntimeHookPhase.PRE_CONTEXT_ASSEMBLE.value),
    ("on_post_context_assemble", RuntimeHookPhase.POST_CONTEXT_ASSEMBLE.value),
    ("on_recovery_decision", RuntimeHookPhase.RECOVERY_DECISION.value),
)

_PUBLIC_PHASE_METHODS: tuple[tuple[str, str], ...] = _STABLE_PHASE_METHODS + _ADVANCED_PHASE_METHODS


def _coerce_factory(value: Any) -> _ValueFactory:
    if callable(value):
        return value
    return lambda: value


@dataclass(frozen=True, slots=True)
class _HookRegistrarContext:
    bus: HookBus
    source_kind: HookSourceKind
    owner_factory: _ValueFactory
    source_ref_factory: _ValueFactory
    session_id_factory: _ValueFactory
    turn_id_factory: _ValueFactory
    default_scope_lifetime_factory: _ValueFactory
    list_hooks_callback: Callable[[_InventoryQuery], tuple[Any, ...]]
    list_hook_dispatch_traces_callback: Callable[[_TraceQuery], tuple[Any, ...]]

    @property
    def default_scope_lifetime(self) -> HookScopeLifetime:
        return HookScopeLifetime(self.default_scope_lifetime_factory())

    def register_request(
        self,
        request: HookRegistrationRequest | Mapping[str, Any],
    ) -> HookRegistrationHandle:
        return self.bus.register_request(
            request,
            source_kind=self.source_kind,
            owner=self.owner_factory(),
            source_ref=self.source_ref_factory(),
            session_id=self.session_id_factory(),
            turn_id=self.turn_id_factory(),
            default_scope_lifetime=self.default_scope_lifetime,
        )

    def list_hooks(self, query: _InventoryQuery = None) -> tuple[Any, ...]:
        return self.list_hooks_callback(query)

    def list_hook_dispatch_traces(self, query: _TraceQuery = None) -> tuple[Any, ...]:
        return self.list_hook_dispatch_traces_callback(query)


class _HookSurfaceBase:
    def __init__(self, context: _HookRegistrarContext) -> None:
        self._context = context

    def list_hooks(self, query: _InventoryQuery = None) -> tuple[Any, ...]:
        return self._context.list_hooks(query)

    def list_hook_dispatch_traces(self, query: _TraceQuery = None) -> tuple[Any, ...]:
        return self._context.list_hook_dispatch_traces(query)


class HookRawRegistrar(_HookSurfaceBase):
    def register(
        self,
        request: HookRegistrationRequest | Mapping[str, Any],
    ) -> HookRegistrationHandle:
        return self._context.register_request(request)


class _CallbackHookSurface(_HookSurfaceBase):
    def _register_callback(
        self,
        phase: str,
        handler: object,
        *,
        match: object = None,
        effects: object = (),
        once: bool = False,
        metadata: Mapping[str, Any] | None = None,
        owner_hint: str | None = None,
        source_ref: str | None = None,
    ) -> HookRegistrationHandle:
        request = build_callback_hook_request(
            phase,
            handler,
            match=match,
            scope=self._context.default_scope_lifetime,
            effects=effects,
            once=once,
            metadata=metadata,
            owner_hint=owner_hint,
            source_ref=source_ref,
            allowed_phases=None,
        )
        return self._context.register_request(request)


class HookTypedRegistrar(_CallbackHookSurface):
    pass


class HookAdvancedRegistrar(_CallbackHookSurface):
    @property
    def simple(self) -> "HookAdvancedRegistrar":
        return self

    @property
    def raw(self) -> HookRawRegistrar:
        return HookRawRegistrar(self._context)


class HookTurnRegistrar(_CallbackHookSurface):
    @property
    def simple(self) -> "HookTurnRegistrar":
        return self

    @property
    def raw(self) -> HookRawRegistrar:
        return HookRawRegistrar(self._context)


class SessionHookAdvancedRegistrar(HookAdvancedRegistrar):
    def __init__(
        self,
        context: _HookRegistrarContext,
        *,
        turn_context_factory: Callable[[], _HookRegistrarContext],
    ) -> None:
        super().__init__(context)
        self._turn_context_factory = turn_context_factory

    @property
    def turn(self) -> HookTurnRegistrar:
        return HookTurnRegistrar(self._turn_context_factory())


class ConfiguredHookRegistrar(_CallbackHookSurface):
    def __init__(
        self,
        context: _HookRegistrarContext,
        *,
        turn_context_factory: Callable[[], _HookRegistrarContext] | None = None,
    ) -> None:
        super().__init__(context)
        self._turn_context_factory = turn_context_factory

    @property
    def simple(self) -> "ConfiguredHookRegistrar":
        return self

    @property
    def typed(self) -> HookTypedRegistrar:
        return HookTypedRegistrar(self._context)

    @property
    def raw(self) -> HookRawRegistrar:
        return HookRawRegistrar(self._context)

    @property
    def advanced(self) -> HookAdvancedRegistrar:
        if self._turn_context_factory is None:
            return HookAdvancedRegistrar(self._context)
        return SessionHookAdvancedRegistrar(
            self._context,
            turn_context_factory=self._turn_context_factory,
        )


def _make_phase_method(phase: str) -> Callable[..., HookRegistrationHandle]:
    def phase_method(
        self: _CallbackHookSurface,
        handler: object,
        *,
        match: object = None,
        effects: object = (),
        once: bool = False,
        metadata: Mapping[str, Any] | None = None,
        owner_hint: str | None = None,
        source_ref: str | None = None,
    ) -> HookRegistrationHandle:
        return self._register_callback(
            phase,
            handler,
            match=match,
            effects=effects,
            once=once,
            metadata=metadata,
            owner_hint=owner_hint,
            source_ref=source_ref,
        )

    return phase_method


for _method_name, _phase_name in _STABLE_PHASE_METHODS:
    setattr(ConfiguredHookRegistrar, _method_name, _make_phase_method(_phase_name))
    setattr(HookTypedRegistrar, _method_name, _make_phase_method(_phase_name))

for _method_name, _phase_name in _ADVANCED_PHASE_METHODS:
    setattr(HookAdvancedRegistrar, _method_name, _make_phase_method(_phase_name))

for _method_name, _phase_name in _PUBLIC_PHASE_METHODS:
    setattr(HookTurnRegistrar, _method_name, _make_phase_method(_phase_name))


def build_configured_hook_registrar(
    *,
    bus: HookBus,
    source_kind: HookSourceKind | str,
    owner: str | Callable[[], str | None] | None,
    source_ref: str | Callable[[], str | None] | None,
    session_id: str | Callable[[], str | None] | None,
    turn_id: str | Callable[[], str | None] | None,
    default_scope_lifetime: HookScopeLifetime | Callable[[], HookScopeLifetime],
    list_hooks: Callable[[_InventoryQuery], tuple[Any, ...]],
    list_hook_dispatch_traces: Callable[[_TraceQuery], tuple[Any, ...]],
    turn_source_kind: HookSourceKind | str | None = None,
    turn_owner: str | Callable[[], str | None] | None = None,
    turn_source_ref: str | Callable[[], str | None] | None = None,
    turn_session_id: str | Callable[[], str | None] | None = None,
    turn_turn_id: str | Callable[[], str | None] | None = None,
    turn_default_scope_lifetime: HookScopeLifetime | Callable[[], HookScopeLifetime] = HookScopeLifetime.TURN,
) -> ConfiguredHookRegistrar:
    base_context = _HookRegistrarContext(
        bus=bus,
        source_kind=HookSourceKind(str(source_kind)),
        owner_factory=_coerce_factory(owner),
        source_ref_factory=_coerce_factory(source_ref),
        session_id_factory=_coerce_factory(session_id),
        turn_id_factory=_coerce_factory(turn_id),
        default_scope_lifetime_factory=_coerce_factory(default_scope_lifetime),
        list_hooks_callback=list_hooks,
        list_hook_dispatch_traces_callback=list_hook_dispatch_traces,
    )
    turn_context_factory: Callable[[], _HookRegistrarContext] | None = None
    if turn_source_kind is not None:
        turn_context_factory = lambda: _HookRegistrarContext(
            bus=bus,
            source_kind=HookSourceKind(str(turn_source_kind)),
            owner_factory=_coerce_factory(turn_owner),
            source_ref_factory=_coerce_factory(turn_source_ref),
            session_id_factory=_coerce_factory(turn_session_id),
            turn_id_factory=_coerce_factory(turn_turn_id),
            default_scope_lifetime_factory=_coerce_factory(turn_default_scope_lifetime),
            list_hooks_callback=list_hooks,
            list_hook_dispatch_traces_callback=list_hook_dispatch_traces,
        )
    return ConfiguredHookRegistrar(
        base_context,
        turn_context_factory=turn_context_factory,
    )


__all__ = [
    "ConfiguredHookRegistrar",
    "HookAdvancedRegistrar",
    "HookRawRegistrar",
    "HookTurnRegistrar",
    "HookTypedRegistrar",
    "build_configured_hook_registrar",
]
