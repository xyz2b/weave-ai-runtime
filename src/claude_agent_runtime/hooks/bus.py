from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

from ..contracts import (
    MessageAttachment,
    MessageRole,
    PromptContextEnvelope,
    RequestOverrideState,
    RuntimeMessage,
    RuntimePrivateContext,
    coerce_request_override_state,
    deserialize_content_blocks,
    merge_request_override_state,
)
from .models import HookEffect, HookStopDisposition, RuntimeHookPhase

HookHandler = Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class HookRegistration:
    session_id: str
    owner: str
    phase: RuntimeHookPhase
    registration_id: str
    handler: HookHandler
    turn_id: str | None = None
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
    stop_disposition: HookStopDisposition = HookStopDisposition.ALLOW_TERMINAL
    injected_messages: tuple[RuntimeMessage, ...] = ()
    request_override: RequestOverrideState | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HookBus:
    metadata: dict[str, Any] = field(default_factory=dict)
    _registrations: dict[str, list[HookRegistration]] = field(default_factory=dict)

    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: Any,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> tuple[str, ...]:
        _ = session_id, turn_id, agent, cwd, messages, prompt_context, private_context, runtime_context
        return ()

    def register(
        self,
        *,
        session_id: str,
        owner: str,
        phase: RuntimeHookPhase | str,
        handler: HookHandler,
        turn_id: str | None = None,
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
            turn_id=turn_id,
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
        turn_id: str | None = None,
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
                        turn_id=turn_id,
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

    def release_turn(self, session_id: str, turn_id: str | None) -> None:
        if turn_id is None:
            return
        registrations = self._registrations.get(session_id, [])
        self._registrations[session_id] = [
            registration for registration in registrations if registration.turn_id != turn_id
        ]

    async def dispatch(
        self,
        session_id: str,
        payload: Any,
    ) -> HookDispatchResult:
        phase = RuntimeHookPhase(str(getattr(payload, "phase")))
        registrations = tuple(self._registrations.get(session_id, ()))
        target = _match_target(payload)
        payload_turn_id = getattr(payload, "turn_id", None)
        matched: list[HookRegistration] = []
        effects: list[HookEffect] = []
        to_remove: set[str] = set()
        for registration in registrations:
            if registration.phase != phase:
                continue
            if registration.turn_id is not None and registration.turn_id != payload_turn_id:
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
    injected_messages: list[RuntimeMessage] = []
    request_override: RequestOverrideState | None = None
    metadata: dict[str, Any] = {}
    dispositions: list[HookStopDisposition] = []
    for effect in effects:
        additional_context.extend(effect.additional_context)
        notifications.extend(effect.notifications)
        if effect.updated_input is not None:
            updated_input = dict(effect.updated_input)
        continue_execution = continue_execution and effect.continue_execution
        if effect.elicitation_result is not None:
            elicitation_result = dict(effect.elicitation_result)
        injected_messages.extend(_coerce_injected_messages(effect.injected_messages))
        request_override = merge_request_override_state(
            request_override,
            coerce_request_override_state(effect.request_override),
        )
        metadata.update(dict(effect.metadata))
        disposition = _coerce_stop_disposition(effect.stop_disposition)
        if disposition is None and phase == RuntimeHookPhase.STOP and not effect.continue_execution:
            disposition = HookStopDisposition.BLOCK_SESSION
        if disposition is not None:
            dispositions.append(disposition)
    stop_disposition = _aggregate_stop_disposition(dispositions)
    if phase == RuntimeHookPhase.STOP:
        continue_execution = stop_disposition not in {
            HookStopDisposition.BLOCK_SESSION,
            HookStopDisposition.HALT_FAILURE,
        }
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
        stop_disposition=stop_disposition,
        injected_messages=tuple(injected_messages),
        request_override=request_override,
        metadata=metadata,
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
        stop_disposition=_coerce_stop_disposition(value.get("stop_disposition")),
        injected_messages=tuple(value.get("injected_messages", ()) or ()),
        request_override=dict(value["request_override"])
        if isinstance(value.get("request_override"), Mapping)
        else None,
        metadata=dict(value["metadata"]) if isinstance(value.get("metadata"), Mapping) else {},
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


def _coerce_stop_disposition(value: object) -> HookStopDisposition | None:
    if isinstance(value, HookStopDisposition):
        return value
    if value is None:
        return None
    try:
        return HookStopDisposition(str(value))
    except ValueError:
        return None


def _aggregate_stop_disposition(
    values: Sequence[HookStopDisposition],
) -> HookStopDisposition:
    precedence = {
        HookStopDisposition.ALLOW_TERMINAL: 0,
        HookStopDisposition.CONTINUE_SAME_TURN: 1,
        HookStopDisposition.BLOCK_SESSION: 2,
        HookStopDisposition.HALT_FAILURE: 3,
    }
    winner = HookStopDisposition.ALLOW_TERMINAL
    for value in values:
        if precedence[value] > precedence[winner]:
            winner = value
    return winner


def _coerce_injected_messages(value: Any) -> tuple[RuntimeMessage, ...]:
    if value is None:
        return ()
    if isinstance(value, RuntimeMessage):
        return (value,)
    if isinstance(value, Mapping):
        message = _deserialize_runtime_message(value)
        return (message,) if message is not None else ()
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        messages: list[RuntimeMessage] = []
        for item in value:
            messages.extend(_coerce_injected_messages(item))
        return tuple(messages)
    return ()


def _deserialize_runtime_message(payload: Mapping[str, Any]) -> RuntimeMessage | None:
    role_value = payload.get("role")
    if role_value is None:
        return None
    attachments_payload = payload.get("attachments")
    attachments: list[MessageAttachment] = []
    if isinstance(attachments_payload, Sequence):
        for item in attachments_payload:
            if not isinstance(item, Mapping):
                continue
            attachments.append(
                MessageAttachment(
                    name=str(item.get("name", "")),
                    path=str(item.get("path", "")),
                    mime_type=str(item["mime_type"]) if item.get("mime_type") is not None else None,
                    metadata=dict(item.get("metadata", {}))
                    if isinstance(item.get("metadata"), Mapping)
                    else {},
                )
            )
    return RuntimeMessage(
        message_id=str(payload.get("message_id") or uuid4().hex),
        role=MessageRole(str(role_value)),
        content=deserialize_content_blocks(payload.get("content", [])),
        attachments=tuple(attachments),
        metadata=dict(payload.get("metadata", {}))
        if isinstance(payload.get("metadata"), Mapping)
        else {},
    )
