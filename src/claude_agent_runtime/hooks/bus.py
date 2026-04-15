from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

from .models import HookEffect, RuntimeHookPhase

HookHandler = Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class HookRegistration:
    session_id: str
    owner: str
    phase: RuntimeHookPhase
    registration_id: str
    handler: HookHandler
    matcher: str | None = None
    once: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HookDispatchResult:
    session_id: str
    phase: RuntimeHookPhase
    effects: tuple[HookEffect, ...] = ()
    matched_owners: tuple[str, ...] = ()
    additional_context: tuple[str, ...] = ()
    updated_input: dict[str, Any] | None = None
    continue_execution: bool = True
    notifications: tuple[str, ...] = ()
    elicitation_result: dict[str, Any] | None = None


@dataclass(slots=True)
class HookBus:
    metadata: dict[str, Any] = field(default_factory=dict)
    _registrations: dict[str, list[HookRegistration]] = field(default_factory=dict)

    async def collect(self, **kwargs: Any) -> tuple[str, ...]:
        _ = kwargs
        return ()

    def register(
        self,
        *,
        session_id: str,
        owner: str,
        phase: RuntimeHookPhase | str,
        handler: HookHandler,
        matcher: str | None = None,
        once: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> HookRegistration:
        registration = HookRegistration(
            session_id=session_id,
            owner=owner,
            phase=RuntimeHookPhase(str(phase)),
            registration_id=uuid4().hex,
            handler=handler,
            matcher=matcher,
            once=once,
            metadata=dict(metadata or {}),
        )
        self._registrations.setdefault(session_id, []).append(registration)
        return registration

    def register_handlers(
        self,
        *,
        session_id: str,
        owner: str,
        hooks: Mapping[str, Any],
    ) -> tuple[HookRegistration, ...]:
        registrations: list[HookRegistration] = []
        for raw_phase, raw_entries in hooks.items():
            phase = RuntimeHookPhase(str(raw_phase))
            entries: Sequence[Any]
            if isinstance(raw_entries, (list, tuple)):
                entries = tuple(raw_entries)
            else:
                entries = (raw_entries,)
            for entry in entries:
                parsed = self._parse_entry(entry)
                if parsed is None:
                    continue
                registrations.append(
                    self.register(
                        session_id=session_id,
                        owner=owner,
                        phase=phase,
                        handler=parsed["handler"],
                        matcher=parsed.get("matcher"),
                        once=bool(parsed.get("once", False)),
                        metadata=parsed.get("metadata"),
                    )
                )
        return tuple(registrations)

    def release_owner(self, session_id: str, owner: str) -> None:
        registrations = self._registrations.get(session_id, [])
        self._registrations[session_id] = [
            registration for registration in registrations if registration.owner != owner
        ]

    def clear_session(self, session_id: str) -> None:
        self._registrations.pop(session_id, None)

    async def dispatch(
        self,
        session_id: str,
        payload: Any,
    ) -> HookDispatchResult:
        phase = RuntimeHookPhase(str(getattr(payload, "phase")))
        registrations = tuple(self._registrations.get(session_id, ()))
        target = _match_target(payload)
        matched: list[HookRegistration] = []
        effects: list[HookEffect] = []
        to_remove: set[str] = set()
        for registration in registrations:
            if registration.phase != phase:
                continue
            if not _matches(registration.matcher, target):
                continue
            matched.append(registration)
            raw_effect = await _maybe_await(registration.handler(payload))
            effects.extend(_coerce_effects(raw_effect))
            if registration.once:
                to_remove.add(registration.registration_id)

        if to_remove:
            self._registrations[session_id] = [
                registration
                for registration in self._registrations.get(session_id, [])
                if registration.registration_id not in to_remove
            ]

        return _aggregate_dispatch_result(session_id, phase, matched, effects)

    @staticmethod
    def _parse_entry(entry: Any) -> dict[str, Any] | None:
        if callable(entry):
            return {"handler": entry}
        if isinstance(entry, Mapping):
            handler = entry.get("handler")
            if callable(handler):
                return {
                    "handler": handler,
                    "matcher": entry.get("matcher"),
                    "once": entry.get("once", False),
                    "metadata": dict(entry.get("metadata", {})) if isinstance(entry.get("metadata"), Mapping) else {},
                }
            if "effect" in entry:
                effect = entry["effect"]

                async def static_handler(_: Any, value: Any = effect) -> Any:
                    return value

                return {
                    "handler": static_handler,
                    "matcher": entry.get("matcher"),
                    "once": entry.get("once", False),
                    "metadata": dict(entry.get("metadata", {})) if isinstance(entry.get("metadata"), Mapping) else {},
                }
        return None


def _aggregate_dispatch_result(
    session_id: str,
    phase: RuntimeHookPhase,
    registrations: Sequence[HookRegistration],
    effects: Sequence[HookEffect],
) -> HookDispatchResult:
    additional_context: list[str] = []
    notifications: list[str] = []
    updated_input: dict[str, Any] | None = None
    continue_execution = True
    elicitation_result: dict[str, Any] | None = None
    for effect in effects:
        additional_context.extend(effect.additional_context)
        notifications.extend(effect.notifications)
        if effect.updated_input is not None:
            updated_input = dict(effect.updated_input)
        continue_execution = continue_execution and effect.continue_execution
        if effect.elicitation_result is not None:
            elicitation_result = dict(effect.elicitation_result)
    return HookDispatchResult(
        session_id=session_id,
        phase=phase,
        effects=tuple(effects),
        matched_owners=tuple(registration.owner for registration in registrations),
        additional_context=tuple(additional_context),
        updated_input=updated_input,
        continue_execution=continue_execution,
        notifications=tuple(notifications),
        elicitation_result=elicitation_result,
    )


def _coerce_effects(value: Any) -> tuple[HookEffect, ...]:
    if value is None:
        return ()
    if isinstance(value, HookEffect):
        return (value,)
    if isinstance(value, str):
        return (HookEffect(additional_context=(value,)),)
    if isinstance(value, Mapping):
        return (_coerce_effect(value),)
    if isinstance(value, Iterable):
        effects: list[HookEffect] = []
        for item in value:
            effects.extend(_coerce_effects(item))
        return tuple(effects)
    return ()


def _coerce_effect(value: Mapping[str, Any]) -> HookEffect:
    additional_context = value.get("additional_context", ())
    notifications = value.get("notifications", ())
    return HookEffect(
        additional_context=tuple(str(item) for item in additional_context),
        updated_input=dict(value["updated_input"]) if isinstance(value.get("updated_input"), Mapping) else None,
        continue_execution=bool(value.get("continue_execution", True)),
        notifications=tuple(str(item) for item in notifications),
        elicitation_result=dict(value["elicitation_result"])
        if isinstance(value.get("elicitation_result"), Mapping)
        else None,
    )


def _matches(matcher: str | None, target: str | None) -> bool:
    if matcher is None or matcher == "*":
        return True
    if target is None:
        return False
    if any(char in matcher for char in "*?[]"):
        return fnmatch(target, matcher)
    return matcher == target


def _match_target(payload: Any) -> str | None:
    for field_name in ("tool_name", "agent_name", "kind", "reason", "final_status", "prompt", "message"):
        value = getattr(payload, field_name, None)
        if value is not None:
            return str(value)
    return None


__all__ = ["HookBus", "HookDispatchResult", "HookRegistration"]


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
