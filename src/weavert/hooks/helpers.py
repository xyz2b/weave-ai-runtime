from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from typing import Any, Callable, Iterable, Mapping

from .models import HookEffect, HookStopDisposition, RuntimeHookPhase
from .platform import (
    HOOK_EFFECT_FIELDS,
    HookEffectClass,
    HookEffectContract,
    HookHandlerKind,
    HookHandlerManifest,
    HookMatch,
    HookRegistrationRequest,
    HookRegistrationScope,
    HookScopeLifetime,
    STABLE_PUBLIC_PHASE_CONTRACTS,
)

_DECLARED_EFFECT_CONTRACT_ATTR = "__weavert_hook_effect_contract__"
_EFFECT_FACTORY_CONTRACT_ATTR = "__weavert_hook_effect_factory_contract__"
_EFFECT_CLASS_ORDER = tuple(HookEffectClass)


class HookScopeShortcut(StrEnum):
    SESSION = "session"
    TURN = "turn"
    TEMPLATE = "template"


@dataclass(frozen=True, slots=True)
class HookAuthoringEffect(HookEffect):
    contract: HookEffectContract = field(default_factory=HookEffectContract)

    def __post_init__(self) -> None:
        object.__setattr__(self, "additional_context", tuple(str(item) for item in self.additional_context))
        object.__setattr__(
            self,
            "updated_input",
            None if self.updated_input is None else dict(self.updated_input),
        )
        object.__setattr__(self, "notifications", tuple(str(item) for item in self.notifications))
        object.__setattr__(
            self,
            "elicitation_result",
            None if self.elicitation_result is None else dict(self.elicitation_result),
        )
        if self.stop_disposition is not None and not isinstance(
            self.stop_disposition,
            HookStopDisposition,
        ):
            object.__setattr__(
                self,
                "stop_disposition",
                HookStopDisposition(str(self.stop_disposition)),
            )
        object.__setattr__(self, "injected_messages", tuple(self.injected_messages))
        object.__setattr__(
            self,
            "request_override",
            None if self.request_override is None else dict(self.request_override),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "contract", _coerce_effect_contract(self.contract))


def session_scope(
    *,
    session_id: str | None = None,
    inherit_to_children: bool = False,
    cleanup_boundary: str | None = None,
) -> HookRegistrationScope:
    return HookRegistrationScope(
        lifetime=HookScopeLifetime.SESSION,
        session_id=session_id,
        inherit_to_children=inherit_to_children,
        cleanup_boundary=cleanup_boundary,
    )


def turn_scope(
    *,
    turn_id: str | None = None,
    session_id: str | None = None,
    inherit_to_children: bool = False,
    cleanup_boundary: str | None = None,
) -> HookRegistrationScope:
    return HookRegistrationScope(
        lifetime=HookScopeLifetime.TURN,
        turn_id=turn_id,
        session_id=session_id,
        inherit_to_children=inherit_to_children,
        cleanup_boundary=cleanup_boundary,
    )


def template_scope(
    *,
    inherit_to_children: bool = False,
    cleanup_boundary: str | None = None,
) -> HookRegistrationScope:
    return HookRegistrationScope(
        lifetime=HookScopeLifetime.SESSION_TEMPLATE,
        inherit_to_children=inherit_to_children,
        cleanup_boundary=cleanup_boundary,
    )


def match_any() -> HookMatch:
    return HookMatch(target="*")


def match_target(target: str) -> HookMatch:
    return HookMatch(target=str(target or "*"))


def match_pattern(pattern: str) -> HookMatch:
    return HookMatch(target=str(pattern or "*"))


def match_tool(tool_name: str) -> HookMatch:
    return match_target(tool_name)


def match_tool_pattern(pattern: str) -> HookMatch:
    return match_pattern(pattern)


def rewrite_input(
    updated_input: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> HookAuthoringEffect:
    if not isinstance(updated_input, Mapping):
        raise TypeError("rewrite_input expects a mapping")
    metadata_values = dict(metadata or {})
    return HookAuthoringEffect(
        updated_input=dict(updated_input),
        metadata=metadata_values,
        contract=_merge_effect_contracts(
            _effect_contract(
                effect_classes=(HookEffectClass.TRANSFORM,),
                effect_fields=("updated_input",),
            ),
            _metadata_contract(metadata_values),
        ),
    )


def block_execution(
    *notifications: str,
    stop_disposition: HookStopDisposition | str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> HookAuthoringEffect:
    normalized_notifications = _normalize_strings(notifications)
    metadata_values = dict(metadata or {})
    effect_classes = [HookEffectClass.DECIDE]
    effect_fields = ["continue_execution"]
    if normalized_notifications:
        effect_classes.append(HookEffectClass.SIDECAR)
        effect_fields.append("notifications")
    normalized_stop_disposition = _coerce_stop_disposition(stop_disposition)
    if normalized_stop_disposition is not None:
        effect_fields.append("stop_disposition")
    return HookAuthoringEffect(
        continue_execution=False,
        notifications=normalized_notifications,
        stop_disposition=normalized_stop_disposition,
        metadata=metadata_values,
        contract=_merge_effect_contracts(
            _effect_contract(
                effect_classes=tuple(effect_classes),
                effect_fields=tuple(effect_fields),
            ),
            _metadata_contract(metadata_values),
        ),
    )


def notify(
    message: str,
    *additional_messages: str,
    metadata: Mapping[str, Any] | None = None,
) -> HookAuthoringEffect:
    notifications = _normalize_strings((message, *additional_messages))
    if not notifications:
        raise ValueError("notify expects at least one message")
    metadata_values = dict(metadata or {})
    return HookAuthoringEffect(
        notifications=notifications,
        metadata=metadata_values,
        contract=_merge_effect_contracts(
            _effect_contract(
                effect_classes=(HookEffectClass.SIDECAR,),
                effect_fields=("notifications",),
            ),
            _metadata_contract(metadata_values),
        ),
    )


def respond_to_elicitation(
    response: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> HookAuthoringEffect:
    if not isinstance(response, Mapping):
        raise TypeError("respond_to_elicitation expects a mapping")
    metadata_values = dict(metadata or {})
    return HookAuthoringEffect(
        elicitation_result=dict(response),
        metadata=metadata_values,
        contract=_merge_effect_contracts(
            _effect_contract(
                effect_classes=(HookEffectClass.DECIDE,),
                effect_fields=("elicitation_result",),
            ),
            _metadata_contract(metadata_values),
        ),
    )


def declares_effects(*effects: object) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    declared_contract = _merge_effect_contracts(*(_contract_from_declaration(item) for item in effects))
    if not declared_contract.effect_classes and not declared_contract.effect_fields:
        raise ValueError("declares_effects expects at least one effect helper or effect contract")

    def decorator(callback: Callable[..., Any]) -> Callable[..., Any]:
        if not callable(callback):
            raise TypeError("declares_effects can only be applied to callables")
        merged = _merge_effect_contracts(
            _declared_contract_for_callable(callback),
            declared_contract,
        )
        try:
            setattr(callback, _DECLARED_EFFECT_CONTRACT_ATTR, merged)
            return callback
        except AttributeError:
            @wraps(callback)
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                return callback(*args, **kwargs)

            setattr(wrapped, _DECLARED_EFFECT_CONTRACT_ATTR, merged)
            return wrapped

    return decorator


def on_session_start(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.SESSION_START.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_session_end(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.SESSION_END.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_pre_tool_use(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.PRE_TOOL_USE.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_post_tool_use(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.POST_TOOL_USE.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_post_tool_use_failure(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.POST_TOOL_USE_FAILURE.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_stop(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.STOP.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_notification(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.NOTIFICATION.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_elicitation(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.ELICITATION.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_elicitation_result(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.ELICITATION_RESULT.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_pre_model_request(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.PRE_MODEL_REQUEST.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def on_post_model_response(
    handler: object,
    *,
    match: object = None,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str = HookScopeShortcut.SESSION,
    effects: object = (),
    once: bool = False,
    metadata: Mapping[str, Any] | None = None,
    owner_hint: str | None = None,
    source_ref: str | None = None,
) -> HookRegistrationRequest:
    return _build_hook_request(
        RuntimeHookPhase.POST_MODEL_RESPONSE.value,
        handler,
        match=match,
        scope=scope,
        effects=effects,
        once=once,
        metadata=metadata,
        owner_hint=owner_hint,
        source_ref=source_ref,
    )


def _build_hook_request(
    phase: str,
    handler: object,
    *,
    match: object,
    scope: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str,
    effects: object,
    once: bool,
    metadata: Mapping[str, Any] | None,
    owner_hint: str | None,
    source_ref: str | None,
) -> HookRegistrationRequest:
    if phase not in STABLE_PUBLIC_PHASE_CONTRACTS:
        raise ValueError(
            f"Hook authoring helpers only support stable public phases; use HookRegistrationRequest for {phase!r}"
        )
    return HookRegistrationRequest(
        phase=phase,
        match=_coerce_match(match),
        scope=_coerce_scope(scope),
        handler=_coerce_handler(handler),
        contract=_merge_effect_contracts(
            _contract_from_handler(handler),
            _contract_from_declaration(effects),
        ),
        owner_hint=owner_hint,
        source_ref=source_ref,
        once=once,
        metadata=dict(metadata or {}),
    )


def _coerce_handler(handler: object) -> HookHandlerManifest:
    if isinstance(handler, HookHandlerManifest):
        if handler.kind != HookHandlerKind.CALLBACK:
            raise ValueError("Hook authoring helpers only support callback handlers")
        return handler
    if callable(handler):
        return HookHandlerManifest(kind=HookHandlerKind.CALLBACK, callback=handler)
    return HookHandlerManifest(kind=HookHandlerKind.CALLBACK, static_effect=handler)


def _coerce_match(value: object) -> HookMatch:
    if value is None:
        return match_any()
    if isinstance(value, HookMatch):
        return value
    if isinstance(value, str):
        return HookMatch(target=value)
    if isinstance(value, Mapping):
        return HookMatch(target=str(value.get("target") or value.get("matcher") or "*"))
    raise TypeError("Hook match must be a string, mapping, HookMatch, or None")


def _coerce_scope(
    value: HookRegistrationScope | HookScopeLifetime | HookScopeShortcut | str,
) -> HookRegistrationScope:
    if isinstance(value, HookRegistrationScope):
        return value
    if isinstance(value, HookScopeLifetime):
        lifetime = value
    else:
        raw_value = str(value or HookScopeShortcut.SESSION.value).strip().lower()
        if raw_value == HookScopeShortcut.SESSION.value:
            lifetime = HookScopeLifetime.SESSION
        elif raw_value == HookScopeShortcut.TURN.value:
            lifetime = HookScopeLifetime.TURN
        elif raw_value in {HookScopeShortcut.TEMPLATE.value, HookScopeLifetime.SESSION_TEMPLATE.value}:
            lifetime = HookScopeLifetime.SESSION_TEMPLATE
        else:
            raise ValueError(f"Unsupported hook scope shortcut: {value!r}")
    return HookRegistrationScope(lifetime=lifetime)


def _coerce_effect_contract(value: object) -> HookEffectContract:
    if isinstance(value, HookEffectContract):
        return HookEffectContract(
            effect_classes=value.effect_classes,
            effect_fields=value.effect_fields,
        )
    if isinstance(value, Mapping):
        return HookEffectContract(
            effect_classes=tuple(value.get("effect_classes", ()) or ()),
            effect_fields=tuple(value.get("effect_fields", ()) or ()),
        )
    if value is None:
        return HookEffectContract()
    raise TypeError("Effect contract declarations must be HookEffectContract, mapping, or None")


def _contract_from_handler(handler: object) -> HookEffectContract:
    if callable(handler):
        return _declared_contract_for_callable(handler)
    return _contract_from_declaration(handler)


def _declared_contract_for_callable(callback: object) -> HookEffectContract:
    return _coerce_effect_contract(getattr(callback, _DECLARED_EFFECT_CONTRACT_ATTR, None))


def _contract_from_declaration(value: object) -> HookEffectContract:
    if value is None:
        return HookEffectContract()
    if isinstance(value, HookAuthoringEffect):
        return value.contract
    if isinstance(value, HookEffectContract):
        return value
    if isinstance(value, Mapping):
        return _coerce_effect_contract(value)
    if callable(value):
        return _coerce_effect_contract(getattr(value, _EFFECT_FACTORY_CONTRACT_ATTR, None))
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, HookEffect)):
        return _merge_effect_contracts(*(_contract_from_declaration(item) for item in value))
    return HookEffectContract()


def _merge_effect_contracts(*contracts: HookEffectContract) -> HookEffectContract:
    effect_classes: list[HookEffectClass] = []
    effect_fields: list[str] = []
    seen_classes: set[HookEffectClass] = set()
    seen_fields: set[str] = set()
    for contract in contracts:
        if not isinstance(contract, HookEffectContract):
            continue
        for effect_class in contract.effect_classes:
            if effect_class not in seen_classes:
                seen_classes.add(effect_class)
                effect_classes.append(effect_class)
        for field_name in contract.effect_fields:
            if field_name not in seen_fields:
                seen_fields.add(field_name)
                effect_fields.append(field_name)
    ordered_classes = tuple(
        effect_class
        for effect_class in _EFFECT_CLASS_ORDER
        if effect_class in seen_classes
    )
    ordered_fields = tuple(field_name for field_name in HOOK_EFFECT_FIELDS if field_name in seen_fields)
    return HookEffectContract(
        effect_classes=ordered_classes or tuple(effect_classes),
        effect_fields=ordered_fields or tuple(effect_fields),
    )


def _effect_contract(
    *,
    effect_classes: tuple[HookEffectClass, ...],
    effect_fields: tuple[str, ...],
) -> HookEffectContract:
    return HookEffectContract(
        effect_classes=effect_classes,
        effect_fields=effect_fields,
    )


def _metadata_contract(metadata: Mapping[str, Any]) -> HookEffectContract:
    if not metadata:
        return HookEffectContract()
    return HookEffectContract(effect_fields=("metadata",))


def _normalize_strings(values: Iterable[object]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            normalized.append(text)
    return tuple(normalized)


def _coerce_stop_disposition(
    value: HookStopDisposition | str | None,
) -> HookStopDisposition | None:
    if value is None or isinstance(value, HookStopDisposition):
        return value
    return HookStopDisposition(str(value))


def _register_effect_factory(
    factory: Callable[..., HookAuthoringEffect],
    contract: HookEffectContract,
) -> Callable[..., HookAuthoringEffect]:
    setattr(factory, _EFFECT_FACTORY_CONTRACT_ATTR, contract)
    return factory


_register_effect_factory(
    rewrite_input,
    _effect_contract(
        effect_classes=(HookEffectClass.TRANSFORM,),
        effect_fields=("updated_input",),
    ),
)
_register_effect_factory(
    block_execution,
    _effect_contract(
        effect_classes=(HookEffectClass.DECIDE,),
        effect_fields=("continue_execution",),
    ),
)
_register_effect_factory(
    notify,
    _effect_contract(
        effect_classes=(HookEffectClass.SIDECAR,),
        effect_fields=("notifications",),
    ),
)
_register_effect_factory(
    respond_to_elicitation,
    _effect_contract(
        effect_classes=(HookEffectClass.DECIDE,),
        effect_fields=("elicitation_result",),
    ),
)


__all__ = [
    "HookAuthoringEffect",
    "HookScopeShortcut",
    "block_execution",
    "declares_effects",
    "match_any",
    "match_pattern",
    "match_target",
    "match_tool",
    "match_tool_pattern",
    "notify",
    "on_elicitation",
    "on_elicitation_result",
    "on_notification",
    "on_post_model_response",
    "on_post_tool_use",
    "on_post_tool_use_failure",
    "on_pre_model_request",
    "on_pre_tool_use",
    "on_session_end",
    "on_session_start",
    "on_stop",
    "respond_to_elicitation",
    "rewrite_input",
    "session_scope",
    "template_scope",
    "turn_scope",
]
