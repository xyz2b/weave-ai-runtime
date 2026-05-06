from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Iterable, Mapping, Sequence
from urllib import request as urllib_request
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
from .platform import (
    HOOK_EFFECT_FIELDS,
    SOURCE_PRECEDENCE,
    HookActivationState,
    HookDispatchTrace,
    HookDispatchTraceQuery,
    HookEffectContract,
    HookHandlerKind,
    HookHandlerManifest,
    HookIgnoredEffect,
    HookInventoryEntry,
    HookInventoryQuery,
    HookMatch,
    HookPhaseTier,
    HookRegistrationHandle,
    HookRegistrationRequest,
    HookRegistrationScope,
    HookScopeLifetime,
    HookSourceKind,
    HookTraceRegistration,
    PUBLIC_PHASE_CONTRACTS,
    is_advanced_phase,
    is_public_phase,
    phase_contract_for,
)

HookHandler = Any


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
    phase: RuntimeHookPhase | str
    dispatch_id: str | None = None
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
    matched_registrations: tuple[HookTraceRegistration, ...] = ()
    blocked_registrations: tuple[HookTraceRegistration, ...] = ()
    ignored_effects: tuple[HookIgnoredEffect, ...] = ()
    winner_summary: dict[str, Any] = field(default_factory=dict)
    applied_outcome: dict[str, Any] = field(default_factory=dict)
    dispatch_trace: HookDispatchTrace | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "matched_registrations", tuple(self.matched_registrations))
        object.__setattr__(self, "blocked_registrations", tuple(self.blocked_registrations))
        object.__setattr__(self, "ignored_effects", tuple(self.ignored_effects))
        object.__setattr__(self, "winner_summary", dict(self.winner_summary))
        object.__setattr__(self, "applied_outcome", dict(self.applied_outcome))


@dataclass(slots=True)
class _RegistrationRecord:
    registration_id: str
    source_kind: HookSourceKind
    source_ref: str
    owner: str
    phase: str
    session_id: str | None
    turn_id: str | None
    scope: HookRegistrationScope
    matcher: str
    handler_manifest: HookHandlerManifest
    contract: HookEffectContract
    once: bool
    metadata: dict[str, Any]
    activation_state: HookActivationState
    precedence: tuple[int, int, int, int]
    precedence_key: str
    local_order: int
    activation_turn_id: str | None = None
    parent_registration_id: str | None = None
    rejection_reason: str | None = None
    descendant_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class HookBus:
    metadata: dict[str, Any] = field(default_factory=dict)
    _records: dict[str, _RegistrationRecord] = field(default_factory=dict)
    _session_order: dict[str, list[str]] = field(default_factory=dict)
    _template_order: list[str] = field(default_factory=list)
    _dispatch_traces: dict[str, list[HookDispatchTrace]] = field(default_factory=dict)
    _materialized_templates: dict[str, set[str]] = field(default_factory=dict)
    _callback_bindings: dict[str, HookHandler] = field(default_factory=dict)
    _external_handler_policy: dict[tuple[str | None, HookHandlerKind], bool] = field(default_factory=dict)
    _creation_counter: int = 0
    _dispatch_counter: int = 0

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

    def bind_callback(self, name: str, handler: HookHandler) -> None:
        self._callback_bindings[str(name)] = handler

    def set_handler_policy(
        self,
        kind: HookHandlerKind | str,
        *,
        allowed: bool,
        phase: RuntimeHookPhase | str | None = None,
    ) -> None:
        normalized_kind = HookHandlerKind(str(kind))
        normalized_phase = str(phase) if phase is not None else None
        self._external_handler_policy[(normalized_phase, normalized_kind)] = bool(allowed)

    def register_request(
        self,
        request: HookRegistrationRequest | Mapping[str, Any],
        *,
        source_kind: HookSourceKind | str,
        owner: str | None = None,
        source_ref: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        default_scope_lifetime: HookScopeLifetime = HookScopeLifetime.SESSION,
        allowed_phase_contracts: Mapping[str, Any] = PUBLIC_PHASE_CONTRACTS,
        allow_turn_scope: bool = True,
        local_order: int = 0,
    ) -> HookRegistrationHandle:
        normalized_source_kind = HookSourceKind(str(source_kind))
        normalized_request = _coerce_registration_request(
            request,
            default_scope_lifetime=default_scope_lifetime,
            turn_id=turn_id,
            session_id=session_id,
        )
        resolved_owner = normalized_request.owner_hint or owner or f"{normalized_source_kind.value}:{uuid4().hex}"
        resolved_source_ref = normalized_request.source_ref or source_ref or resolved_owner
        phase_name = str(normalized_request.phase)
        scope = _resolve_scope(
            normalized_request.scope,
            session_id=session_id,
            turn_id=turn_id,
            default_lifetime=default_scope_lifetime,
        )
        creation_index = self._next_creation_index()
        handle = HookRegistrationHandle(
            registration_id=uuid4().hex,
            source_kind=normalized_source_kind,
            owner=resolved_owner,
            phase=phase_name,
            scope=scope,
            _bus=self,
        )

        rejection_reason = _validate_request(
            normalized_request,
            source_kind=normalized_source_kind,
            scope=scope,
            phase_name=phase_name,
            callback_bindings=self._callback_bindings,
            require_bound_callbacks=scope.lifetime != HookScopeLifetime.SESSION_TEMPLATE,
            allowed_phase_contracts=allowed_phase_contracts,
            allow_turn_scope=allow_turn_scope,
        )
        if rejection_reason is not None:
            self._records[handle.registration_id] = _RegistrationRecord(
                registration_id=handle.registration_id,
                source_kind=normalized_source_kind,
                source_ref=resolved_source_ref,
                owner=resolved_owner,
                phase=phase_name,
                session_id=session_id,
                turn_id=scope.turn_id,
                scope=scope,
                matcher=normalized_request.match.target,
                handler_manifest=normalized_request.handler,
                contract=normalized_request.contract,
                once=normalized_request.once,
                metadata=dict(normalized_request.metadata),
                activation_state=HookActivationState.REJECTED,
                precedence=(SOURCE_PRECEDENCE[normalized_source_kind], creation_index, local_order, creation_index),
                precedence_key=f"{normalized_source_kind.value}/{creation_index}/{local_order}",
                local_order=local_order,
                activation_turn_id=turn_id,
                rejection_reason=rejection_reason,
            )
            handle._activation_state = HookActivationState.REJECTED
            return handle

        activation_state = (
            HookActivationState.PENDING_ACTIVATION
            if scope.lifetime == HookScopeLifetime.SESSION_TEMPLATE
            else HookActivationState.ACTIVE
        )
        if scope.lifetime == HookScopeLifetime.SESSION_TEMPLATE:
            precedence = (
                SOURCE_PRECEDENCE[normalized_source_kind],
                creation_index,
                local_order,
                creation_index,
            )
            precedence_key = f"{normalized_source_kind.value}/{creation_index}/{local_order}"
            self._template_order.append(handle.registration_id)
        else:
            target_session_id = session_id or scope.session_id
            assert target_session_id is not None
            precedence_epoch = self._next_session_precedence_epoch(target_session_id)
            precedence = (
                SOURCE_PRECEDENCE[normalized_source_kind],
                precedence_epoch,
                local_order,
                creation_index,
            )
            precedence_key = f"{normalized_source_kind.value}/{precedence_epoch}/{local_order}"
            self._session_order.setdefault(target_session_id, []).append(handle.registration_id)

        self._records[handle.registration_id] = _RegistrationRecord(
            registration_id=handle.registration_id,
            source_kind=normalized_source_kind,
            source_ref=resolved_source_ref,
            owner=resolved_owner,
            phase=phase_name,
            session_id=session_id or scope.session_id,
            turn_id=scope.turn_id,
            scope=scope,
            matcher=normalized_request.match.target,
            handler_manifest=normalized_request.handler,
            contract=normalized_request.contract,
            once=normalized_request.once,
            metadata=dict(normalized_request.metadata),
            activation_state=activation_state,
            precedence=precedence,
            precedence_key=precedence_key,
            local_order=local_order,
            activation_turn_id=turn_id,
        )
        handle._activation_state = activation_state
        return handle

    def register_document(
        self,
        *,
        hooks: Mapping[str, Any],
        source_kind: HookSourceKind | str,
        owner: str,
        source_ref: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        default_scope_lifetime: HookScopeLifetime = HookScopeLifetime.SESSION,
    ) -> tuple[HookRegistrationHandle, ...]:
        requests = _normalize_authoring_document(
            hooks,
            default_scope_lifetime=default_scope_lifetime,
            session_id=session_id,
            turn_id=turn_id,
        )
        handles: list[HookRegistrationHandle] = []
        for index, request in enumerate(requests):
            handles.append(
                self.register_request(
                    request,
                    source_kind=source_kind,
                    owner=owner,
                    source_ref=source_ref,
                    session_id=session_id,
                    turn_id=turn_id,
                    default_scope_lifetime=default_scope_lifetime,
                    local_order=index,
                )
            )
        return tuple(handles)

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
        request = HookRegistrationRequest(
            phase=str(RuntimeHookPhase(str(phase))),
            match=HookMatch(target=str(matcher or "*")),
            scope=HookRegistrationScope(
                lifetime=HookScopeLifetime.TURN if turn_id is not None else HookScopeLifetime.SESSION,
                turn_id=turn_id,
                session_id=session_id,
            ),
            handler=HookHandlerManifest(kind=HookHandlerKind.CALLBACK, callback=handler),
            owner_hint=owner,
            once=once,
            metadata=dict(metadata or {}),
        )
        handle = self.register_request(
            request,
            source_kind=HookSourceKind.COMPAT,
            owner=owner,
            source_ref=owner,
            session_id=session_id,
            turn_id=turn_id,
            default_scope_lifetime=(
                HookScopeLifetime.TURN if turn_id is not None else HookScopeLifetime.SESSION
            ),
        )
        return HookRegistration(
            session_id=session_id,
            owner=owner,
            phase=RuntimeHookPhase(str(phase)),
            registration_id=handle.registration_id,
            handler=handler,
            turn_id=turn_id,
            matcher=matcher,
            once=once,
            metadata=dict(metadata or {}),
        )

    def register_handlers(
        self,
        *,
        session_id: str,
        owner: str,
        hooks: Mapping[str, Any],
        turn_id: str | None = None,
    ) -> tuple[HookRegistration, ...]:
        handles = self.register_document(
            hooks=hooks,
            source_kind=HookSourceKind.DEFINITION,
            owner=owner,
            source_ref=owner,
            session_id=session_id,
            turn_id=turn_id,
            default_scope_lifetime=(
                HookScopeLifetime.TURN if turn_id is not None else HookScopeLifetime.SESSION
            ),
        )
        registrations: list[HookRegistration] = []
        for handle in handles:
            record = self._records[handle.registration_id]
            registrations.append(
                HookRegistration(
                    session_id=session_id,
                    owner=record.owner,
                    phase=RuntimeHookPhase(record.phase),
                    registration_id=record.registration_id,
                    handler=record.handler_manifest.callback or _noop_handler,
                    turn_id=record.turn_id,
                    matcher=record.matcher if record.matcher != "*" else None,
                    once=record.once,
                    metadata=dict(record.metadata),
                )
            )
        return tuple(registrations)

    def registration_state(self, registration_id: str) -> HookActivationState:
        record = self._records.get(registration_id)
        if record is None:
            return HookActivationState.RELEASED
        return record.activation_state

    def materialize_session(self, session_id: str) -> None:
        materialized = self._materialized_templates.setdefault(session_id, set())
        for template_id in tuple(self._template_order):
            if template_id in materialized:
                continue
            template = self._records.get(template_id)
            if template is None or template.activation_state != HookActivationState.PENDING_ACTIVATION:
                continue
            if _callback_handler_rejection_reason(
                template.handler_manifest,
                callback_bindings=self._callback_bindings,
                require_bound_callbacks=True,
            ) is not None:
                continue
            descendant_id = uuid4().hex
            creation_index = self._next_creation_index()
            precedence_epoch = self._next_session_precedence_epoch(session_id)
            descendant = _RegistrationRecord(
                registration_id=descendant_id,
                source_kind=template.source_kind,
                source_ref=template.source_ref,
                owner=template.owner,
                phase=template.phase,
                session_id=session_id,
                turn_id=None,
                scope=HookRegistrationScope(
                    lifetime=HookScopeLifetime.SESSION,
                    inherit_to_children=template.scope.inherit_to_children,
                    session_id=session_id,
                    cleanup_boundary=template.scope.cleanup_boundary,
                ),
                matcher=template.matcher,
                handler_manifest=template.handler_manifest,
                contract=template.contract,
                once=template.once,
                metadata=dict(template.metadata),
                activation_state=HookActivationState.ACTIVE,
                precedence=(
                    SOURCE_PRECEDENCE[template.source_kind],
                    precedence_epoch,
                    template.local_order,
                    creation_index,
                ),
                precedence_key=f"{template.source_kind.value}/{precedence_epoch}/{template.local_order}",
                local_order=template.local_order,
                activation_turn_id=None,
                parent_registration_id=template.registration_id,
            )
            self._records[descendant_id] = descendant
            self._session_order.setdefault(session_id, []).append(descendant_id)
            template.descendant_ids.add(descendant_id)
            materialized.add(template_id)

    def release_registration(self, registration_id: str) -> HookActivationState:
        record = self._records.get(registration_id)
        if record is None:
            return HookActivationState.RELEASED
        if record.activation_state in {
            HookActivationState.RELEASED,
            HookActivationState.EXPIRED,
            HookActivationState.REJECTED,
        }:
            return record.activation_state
        record.activation_state = HookActivationState.RELEASED
        for descendant_id in tuple(record.descendant_ids):
            descendant = self._records.get(descendant_id)
            if descendant is not None and descendant.activation_state == HookActivationState.ACTIVE:
                descendant.activation_state = HookActivationState.RELEASED
        return record.activation_state

    def release_owner(self, session_id: str, owner: str) -> None:
        for record_id in tuple(self._session_order.get(session_id, ())):
            record = self._records.get(record_id)
            if record is None or record.owner != owner:
                continue
            if record.activation_state == HookActivationState.ACTIVE:
                record.activation_state = HookActivationState.RELEASED

    def clear_session(self, session_id: str) -> None:
        for record_id in tuple(self._session_order.get(session_id, ())):
            record = self._records.get(record_id)
            if record is None:
                continue
            if record.activation_state == HookActivationState.ACTIVE:
                record.activation_state = HookActivationState.EXPIRED

    def release_turn(self, session_id: str, turn_id: str | None) -> None:
        if turn_id is None:
            return
        for record_id in tuple(self._session_order.get(session_id, ())):
            record = self._records.get(record_id)
            if record is None:
                continue
            if (
                record.activation_state == HookActivationState.ACTIVE
                and record.scope.lifetime == HookScopeLifetime.TURN
                and record.turn_id == turn_id
            ):
                record.activation_state = HookActivationState.EXPIRED

    def list_hooks(
        self,
        query: HookInventoryQuery | Mapping[str, Any] | None = None,
    ) -> tuple[HookInventoryEntry, ...]:
        normalized_query = _coerce_inventory_query(query)
        records = [
            record
            for record in self._records.values()
            if _record_matches_inventory_query(record, normalized_query)
        ]
        records.sort(key=lambda item: (item.session_id or "", item.precedence, item.registration_id))
        return tuple(_inventory_entry(record) for record in _slice_with_cursor(records, normalized_query.cursor, normalized_query.limit))

    def list_hook_dispatch_traces(
        self,
        query: HookDispatchTraceQuery | Mapping[str, Any] | None = None,
    ) -> tuple[HookDispatchTrace, ...]:
        normalized_query = _coerce_trace_query(query)
        traces: list[HookDispatchTrace] = []
        source_lists: Iterable[list[HookDispatchTrace]]
        if normalized_query.session_id is None:
            source_lists = self._dispatch_traces.values()
        else:
            source_lists = (self._dispatch_traces.get(normalized_query.session_id, []),)
        for trace_list in source_lists:
            for trace in trace_list:
                if _trace_matches_query(trace, normalized_query):
                    traces.append(trace)
        traces.sort(key=_dispatch_trace_sort_key)
        return tuple(_slice_with_cursor(traces, normalized_query.cursor, normalized_query.limit))

    async def dispatch(
        self,
        session_id: str,
        payload: Any,
        *,
        dispatch_context: Mapping[str, Any] | Any | None = None,
    ) -> HookDispatchResult:
        self.materialize_session(session_id)
        phase_name = str(_payload_field(payload, "phase"))
        try:
            phase: RuntimeHookPhase | str = RuntimeHookPhase(phase_name)
        except ValueError:
            phase = phase_name
        payload_turn_id = _payload_field(payload, "turn_id")
        normalized_dispatch_context = _coerce_dispatch_context(dispatch_context)
        effective_turn_id = (
            _coerce_optional_string(payload_turn_id)
            or _coerce_optional_string(normalized_dispatch_context.get("turn_id"))
        )
        target = _match_target(payload)
        candidate_records = [
            self._records[record_id]
            for record_id in self._session_order.get(session_id, ())
            if record_id in self._records
        ]
        active_records = [
            record
            for record in candidate_records
            if record.activation_state == HookActivationState.ACTIVE
            and record.phase == phase_name
            and _turn_scope_matches(record, effective_turn_id)
            and _dispatch_visibility_matches(
                record,
                turn_id=effective_turn_id,
                dispatch_context=normalized_dispatch_context,
            )
        ]
        active_records.sort(key=lambda item: item.precedence)
        phase_contract = phase_contract_for(phase_name)

        matched_records: list[_RegistrationRecord] = []
        blocked_entries: list[HookTraceRegistration] = []
        filtered_effects: list[tuple[_RegistrationRecord, HookEffect]] = []
        ignored_effects: list[HookIgnoredEffect] = []
        once_to_expire: list[_RegistrationRecord] = []

        for record in active_records:
            if not _matches(record.matcher, target):
                continue
            matched_records.append(record)
            raw_effects, block_reason = await self._invoke_record(record, payload, phase_contract)
            if block_reason is not None:
                blocked_entries.append(_trace_registration(record, reason=block_reason))
                continue
            for raw_effect in raw_effects:
                effect, ignored = _sanitize_effect(
                    raw_effect,
                    record=record,
                    phase_name=phase_name,
                    declared_contract=record.contract,
                )
                ignored_effects.extend(ignored)
                filtered_effects.append((record, effect))
            if record.once:
                once_to_expire.append(record)

        (
            additional_context,
            updated_input,
            continue_execution,
            notifications,
            elicitation_result,
            stop_disposition,
            injected_messages,
            request_override,
            merged_metadata,
            winner_summary,
            effects,
        ) = _aggregate_dispatch_result(
            phase=phase,
            effects=filtered_effects,
        )

        dispatch_id = f"hookdisp_{self._next_dispatch_index()}"
        matched_entries = tuple(_trace_registration(record) for record in matched_records)
        applied_outcome = {
            "continuation_blocked": not continue_execution,
            "request_override_applied": request_override is not None,
            "elicitation_satisfied_by_hook": elicitation_result is not None,
            "notifications_emitted": len(notifications),
            "matched_hooks": [record.registration_id for record in matched_records],
            "ignored_effect_count": len(ignored_effects),
        }
        if request_override is not None:
            applied_outcome["request_override"] = request_override.serialize()
        dispatch_trace = HookDispatchTrace(
            dispatch_id=dispatch_id,
            session_id=session_id,
            turn_id=effective_turn_id,
            phase=phase_name,
            matched_registrations=matched_entries,
            blocked_registrations=tuple(blocked_entries),
            ignored_effects=tuple(ignored_effects),
            winner_summary=winner_summary,
            applied_outcome=applied_outcome,
            metadata={
                "tier": phase_contract.tier.value,
                "main_loop_layer": phase_contract.main_loop_layer,
                "child_execution": _dispatch_context_is_child_execution(normalized_dispatch_context),
            },
        )
        self._dispatch_traces.setdefault(session_id, []).append(dispatch_trace)

        for record in once_to_expire:
            if record.activation_state == HookActivationState.ACTIVE:
                record.activation_state = HookActivationState.EXPIRED

        return HookDispatchResult(
            session_id=session_id,
            phase=phase,
            dispatch_id=dispatch_id,
            effects=effects,
            matched_owners=tuple(record.owner for record in matched_records),
            additional_context=additional_context,
            updated_input=updated_input,
            continue_execution=continue_execution,
            notifications=notifications,
            elicitation_result=elicitation_result,
            stop_disposition=stop_disposition,
            injected_messages=injected_messages,
            request_override=request_override,
            metadata=merged_metadata,
            matched_registrations=matched_entries,
            blocked_registrations=tuple(blocked_entries),
            ignored_effects=tuple(ignored_effects),
            winner_summary=winner_summary,
            applied_outcome=applied_outcome,
            dispatch_trace=dispatch_trace,
        )

    async def _invoke_record(
        self,
        record: _RegistrationRecord,
        payload: Any,
        phase_contract: Any,
    ) -> tuple[tuple[HookEffect, ...], str | None]:
        manifest = record.handler_manifest
        if manifest.kind.external and not phase_contract.external_handler_allowed:
            return (), "phase_external_handler_denied"
        if manifest.kind.external and not self._handler_allowed(manifest.kind, record.phase):
            return (), "policy_denied"
        try:
            raw = await self._invoke_handler_manifest(record, payload)
        except asyncio.TimeoutError:
            return (), "timeout"
        except Exception as exc:  # pragma: no cover - defensive boundary
            return (), f"handler_error:{type(exc).__name__}"
        return _coerce_effects(raw), None

    async def _invoke_handler_manifest(
        self,
        record: _RegistrationRecord,
        payload: Any,
    ) -> Any:
        manifest = record.handler_manifest
        timeout_seconds = manifest.timeout_ms / 1000 if manifest.timeout_ms is not None else None

        async def _invoke() -> Any:
            if manifest.static_effect is not None:
                return manifest.static_effect
            if manifest.kind == HookHandlerKind.CALLBACK:
                handler = manifest.callback
                if handler is None and manifest.binding is not None:
                    handler = self._callback_bindings.get(manifest.binding)
                if handler is None:
                    raise RuntimeError("unresolved_callback_binding")
                return await _maybe_await(handler(payload))
            if manifest.kind == HookHandlerKind.HTTP:
                return await self._invoke_http_handler(manifest, payload)
            if manifest.kind == HookHandlerKind.COMMAND:
                return await self._invoke_command_handler(manifest, payload)
            if manifest.kind == HookHandlerKind.AGENT:
                agent_handler = self.metadata.get("hook_agent_handler")
                if callable(agent_handler):
                    return await _maybe_await(agent_handler(manifest, payload))
                raise RuntimeError("agent_adapter_unavailable")
            if manifest.kind == HookHandlerKind.PROMPT:
                prompt_handler = self.metadata.get("hook_prompt_handler")
                if callable(prompt_handler):
                    return await _maybe_await(prompt_handler(manifest, payload))
                raise RuntimeError("prompt_adapter_unavailable")
            raise RuntimeError(f"Unsupported hook handler kind: {manifest.kind!r}")

        if timeout_seconds is None:
            return await _invoke()
        return await asyncio.wait_for(_invoke(), timeout=timeout_seconds)

    async def _invoke_http_handler(
        self,
        manifest: HookHandlerManifest,
        payload: Any,
    ) -> Any:
        if manifest.endpoint is None:
            raise RuntimeError("http_endpoint_missing")

        def _perform() -> Any:
            body = json.dumps(_payload_to_json(payload)).encode("utf-8")
            req = urllib_request.Request(
                manifest.endpoint,
                data=body,
                headers={"content-type": "application/json"},
                method=manifest.method,
            )
            with urllib_request.urlopen(req, timeout=(manifest.timeout_ms or 1000) / 1000) as response:
                data = response.read()
            if not data:
                return None
            text = data.decode("utf-8")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"metadata": {"raw_response": text}}

        return await asyncio.to_thread(_perform)

    async def _invoke_command_handler(
        self,
        manifest: HookHandlerManifest,
        payload: Any,
    ) -> Any:
        if not manifest.command:
            raise RuntimeError("command_missing")
        process = await asyncio.create_subprocess_exec(
            *manifest.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(json.dumps(_payload_to_json(payload)).encode("utf-8"))
        if process.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="ignore") or "command_hook_failed")
        if not stdout:
            return None
        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError:
            return {"metadata": {"raw_stdout": stdout.decode("utf-8", errors="ignore")}}

    def _handler_allowed(self, kind: HookHandlerKind, phase: str) -> bool:
        if kind == HookHandlerKind.CALLBACK:
            return True
        specific = self._external_handler_policy.get((phase, kind))
        if specific is not None:
            return specific
        generic = self._external_handler_policy.get((None, kind))
        if generic is not None:
            return generic
        return False

    def _next_creation_index(self) -> int:
        self._creation_counter += 1
        return self._creation_counter

    def _next_dispatch_index(self) -> int:
        self._dispatch_counter += 1
        return self._dispatch_counter

    def _next_session_precedence_epoch(self, session_id: str) -> int:
        epochs = self.metadata.setdefault("session_precedence_epochs", {})
        current = int(epochs.get(session_id, 0)) + 1
        epochs[session_id] = current
        return current


def _aggregate_dispatch_result(
    *,
    phase: RuntimeHookPhase | str,
    effects: Sequence[tuple[_RegistrationRecord, HookEffect]],
) -> tuple[
    tuple[str, ...],
    dict[str, Any] | None,
    bool,
    tuple[str, ...],
    dict[str, Any] | None,
    HookStopDisposition,
    tuple[RuntimeMessage, ...],
    RequestOverrideState | None,
    dict[str, Any],
    dict[str, Any],
    tuple[HookEffect, ...],
]:
    additional_context: list[str] = []
    notifications: list[str] = []
    updated_input: dict[str, Any] | None = None
    continue_execution = True
    elicitation_result: dict[str, Any] | None = None
    injected_messages: list[RuntimeMessage] = []
    request_override: RequestOverrideState | None = None
    metadata: dict[str, Any] = {}
    dispositions: list[tuple[_RegistrationRecord, HookStopDisposition]] = []
    gate_contributors: list[str] = []
    winner_summary: dict[str, Any] = {}
    aggregated_effects: list[HookEffect] = []

    for record, effect in effects:
        aggregated_effects.append(effect)
        if effect.additional_context:
            additional_context.extend(effect.additional_context)
            winner_summary.setdefault("additional_context", {"contributing_registrations": []})
            winner_summary["additional_context"]["contributing_registrations"].append(
                record.registration_id
            )
        if effect.notifications:
            notifications.extend(effect.notifications)
            winner_summary.setdefault("notifications", {"contributing_registrations": []})
            winner_summary["notifications"]["contributing_registrations"].append(record.registration_id)
        if effect.updated_input is not None:
            updated_input = dict(effect.updated_input)
            winner_summary["updated_input"] = {
                "winner_registration_id": record.registration_id,
                "owner": record.owner,
            }
        if not effect.continue_execution:
            continue_execution = False
            gate_contributors.append(record.registration_id)
        if effect.elicitation_result is not None:
            elicitation_result = dict(effect.elicitation_result)
            winner_summary["elicitation_result"] = {
                "winner_registration_id": record.registration_id,
                "owner": record.owner,
            }
        if effect.injected_messages:
            coerced = _coerce_injected_messages(effect.injected_messages)
            injected_messages.extend(coerced)
            winner_summary.setdefault("injected_messages", {"contributing_registrations": []})
            winner_summary["injected_messages"]["contributing_registrations"].append(
                record.registration_id
            )
        if effect.request_override is not None:
            request_override = merge_request_override_state(
                request_override,
                _stamp_request_override(
                    effect.request_override,
                    registration_id=record.registration_id,
                    owner=record.owner,
                    source_kind=record.source_kind,
                ),
            )
            if request_override is not None:
                winner_summary["request_override"] = {
                    "field_sources": dict(request_override.field_sources),
                    "source": request_override.source,
                }
        if effect.metadata:
            metadata.update(dict(effect.metadata))
            winner_summary["metadata"] = {
                "winner_registration_id": record.registration_id,
                "owner": record.owner,
            }
        disposition = _coerce_stop_disposition(effect.stop_disposition)
        if disposition is None and phase == RuntimeHookPhase.STOP and not effect.continue_execution:
            disposition = HookStopDisposition.BLOCK_SESSION
        if disposition is not None:
            dispositions.append((record, disposition))

    stop_disposition = _aggregate_stop_disposition(tuple(disposition for _, disposition in dispositions))
    if dispositions:
        winning_record_id = None
        for record, disposition in dispositions:
            if disposition == stop_disposition:
                winning_record_id = record.registration_id
        winner_summary["stop_disposition"] = {
            "winner_registration_id": winning_record_id,
            "value": stop_disposition.value,
        }
    if gate_contributors:
        winner_summary["continue_execution"] = {
            "value": False,
            "contributing_registrations": gate_contributors,
        }
    if phase == RuntimeHookPhase.STOP:
        continue_execution = stop_disposition not in {
            HookStopDisposition.BLOCK_SESSION,
            HookStopDisposition.HALT_FAILURE,
        }
    return (
        tuple(additional_context),
        updated_input,
        continue_execution,
        tuple(notifications),
        elicitation_result,
        stop_disposition,
        tuple(injected_messages),
        request_override,
        metadata,
        winner_summary,
        tuple(aggregated_effects),
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
        else value.get("request_override"),
        metadata=dict(value["metadata"]) if isinstance(value.get("metadata"), Mapping) else {},
    )


def _sanitize_effect(
    effect: HookEffect,
    *,
    record: _RegistrationRecord,
    phase_name: str,
    declared_contract: HookEffectContract,
) -> tuple[HookEffect, tuple[HookIgnoredEffect, ...]]:
    phase_contract = phase_contract_for(phase_name)
    allowed_fields = set(phase_contract.effect_fields)
    if declared_contract.restrict_fields and declared_contract.effect_fields:
        allowed_fields &= set(declared_contract.effect_fields)
    runtime_contract = _coerce_effect_contract(getattr(effect, "contract", None))
    if runtime_contract.effect_fields:
        allowed_fields &= set(runtime_contract.effect_fields)
    ignored: list[HookIgnoredEffect] = []
    values = {
        "additional_context": effect.additional_context if effect.additional_context else None,
        "updated_input": effect.updated_input,
        "continue_execution": False if effect.continue_execution is False else None,
        "notifications": effect.notifications if effect.notifications else None,
        "elicitation_result": effect.elicitation_result,
        "stop_disposition": effect.stop_disposition,
        "injected_messages": effect.injected_messages if effect.injected_messages else None,
        "request_override": effect.request_override,
        "metadata": effect.metadata if effect.metadata else None,
    }
    filtered: dict[str, Any] = {}
    for field_name in HOOK_EFFECT_FIELDS:
        field_value = values.get(field_name)
        if field_value is None:
            continue
        if field_name not in allowed_fields:
            ignored.append(
                HookIgnoredEffect(
                    registration_id=record.registration_id,
                    field=field_name,
                    reason=f"phase_contract:{phase_name}",
                )
            )
            continue
        filtered[field_name] = field_value
    return _coerce_effect(filtered), tuple(ignored)


def _matches(matcher: str | None, target: str | None) -> bool:
    if matcher is None or matcher == "*":
        return True
    if target is None:
        return False
    if any(char in matcher for char in "*?[]"):
        return fnmatch(target, matcher)
    return matcher == target


def _match_target(payload: Any) -> str | None:
    for field_name in (
        "tool_name",
        "agent_name",
        "kind",
        "reason",
        "final_status",
        "prompt",
        "message",
        "candidate_action",
    ):
        value = _payload_field(payload, field_name)
        if value is not None:
            return str(value)
    return None


def _payload_field(payload: Any, name: str) -> Any:
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)


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


def _coerce_injected_messages(values: Sequence[Any]) -> list[RuntimeMessage]:
    messages: list[RuntimeMessage] = []
    for value in values:
        if isinstance(value, RuntimeMessage):
            messages.append(value)
            continue
        if isinstance(value, str):
            messages.append(
                RuntimeMessage(
                    message_id=uuid4().hex,
                    role=MessageRole.HOOK,
                    content=value,
                    metadata={"source": "hook"},
                )
            )
            continue
        if isinstance(value, Mapping):
            role = MessageRole(str(value.get("role", MessageRole.HOOK.value)))
            raw_content = value.get("content", ())
            if isinstance(raw_content, str):
                content = raw_content
            elif isinstance(raw_content, Sequence):
                content = tuple(deserialize_content_blocks(raw_content))
            else:
                content = str(raw_content)
            messages.append(
                RuntimeMessage(
                    message_id=str(value.get("message_id") or uuid4().hex),
                    role=role,
                    content=content,
                    metadata=dict(value.get("metadata", {})) if isinstance(value.get("metadata"), Mapping) else {},
                )
            )
    return messages


def _stamp_request_override(
    value: object,
    *,
    registration_id: str,
    owner: str,
    source_kind: HookSourceKind,
) -> RequestOverrideState | None:
    state = coerce_request_override_state(value)
    if state is None:
        return None
    source = state.source or registration_id
    field_sources = dict(state.field_sources)
    if state.requested_model is not None:
        field_sources.setdefault("requested_model", source)
    if state.requested_effort is not None:
        field_sources.setdefault("requested_effort", source)
    if state.requested_model_route is not None:
        field_sources.setdefault("requested_model_route", source)
    if state.invocation_mode_override is not None:
        field_sources.setdefault("invocation_mode_override", source)
    if state.max_output_tokens_override is not None:
        field_sources.setdefault("max_output_tokens_override", source)
    metadata = dict(state.metadata)
    metadata.setdefault("registration_id", registration_id)
    metadata.setdefault("owner", owner)
    metadata.setdefault("source_kind", source_kind.value)
    sources = {str(item) for item in metadata.get("sources", ()) if str(item).strip()}
    sources.add(source)
    metadata["sources"] = sorted(sources)
    return RequestOverrideState(
        requested_model=state.requested_model,
        requested_effort=state.requested_effort,
        requested_model_route=state.requested_model_route,
        invocation_mode_override=state.invocation_mode_override,
        max_output_tokens_override=state.max_output_tokens_override,
        source=source,
        field_sources=field_sources,
        resumable=state.resumable,
        metadata=metadata,
    )


def _validate_request(
    request: HookRegistrationRequest,
    *,
    source_kind: HookSourceKind,
    scope: HookRegistrationScope,
    phase_name: str,
    callback_bindings: Mapping[str, HookHandler] | None = None,
    require_bound_callbacks: bool,
    allowed_phase_contracts: Mapping[str, Any],
    allow_turn_scope: bool,
) -> str | None:
    phase_contract = phase_contract_for(phase_name)
    if not is_public_phase(phase_name):
        return "phase_not_public"
    if phase_name not in allowed_phase_contracts:
        if is_advanced_phase(phase_name):
            return "advanced_phase_requires_advanced_surface"
        return "phase_not_allowed_for_surface"
    if scope.lifetime == HookScopeLifetime.TURN and scope.turn_id is None:
        return "invalid_turn_scope"
    if scope.lifetime == HookScopeLifetime.TURN and not allow_turn_scope:
        return "turn_scope_requires_advanced_surface"
    if scope.lifetime == HookScopeLifetime.SESSION and scope.session_id is None:
        return "invalid_session_scope"
    if request.handler.kind.external and not phase_contract.external_handler_allowed:
        return "external_handler_not_allowed_for_phase"
    callback_rejection = _callback_handler_rejection_reason(
        request.handler,
        callback_bindings=callback_bindings,
        require_bound_callbacks=require_bound_callbacks,
    )
    if callback_rejection is not None:
        return callback_rejection
    if request.contract.effect_classes:
        allowed_classes = set(phase_contract.effect_classes)
        unsupported_classes = sorted(set(request.contract.effect_classes) - allowed_classes)
        if unsupported_classes:
            return "unsupported_effect_classes:" + ",".join(item.value for item in unsupported_classes)
    if request.contract.effect_fields:
        allowed_fields = set(phase_contract.effect_fields)
        unsupported = sorted(set(request.contract.effect_fields) - allowed_fields)
        if unsupported:
            return "unsupported_effect_fields:" + ",".join(unsupported)
    if source_kind in {HookSourceKind.RUNTIME_CONFIG, HookSourceKind.HOST_API} and scope.lifetime == HookScopeLifetime.TURN:
        return "template_scope_cannot_be_turn"
    return None


def _callback_handler_rejection_reason(
    manifest: HookHandlerManifest,
    *,
    callback_bindings: Mapping[str, HookHandler] | None,
    require_bound_callbacks: bool,
) -> str | None:
    if manifest.kind != HookHandlerKind.CALLBACK:
        return None
    if manifest.static_effect is not None or manifest.callback is not None:
        return None
    if manifest.binding is None:
        return "callback_handler_missing_target"
    if require_bound_callbacks and (callback_bindings is None or manifest.binding not in callback_bindings):
        return "unresolved_callback_binding"
    return None


def _resolve_scope(
    scope: HookRegistrationScope,
    *,
    session_id: str | None,
    turn_id: str | None,
    default_lifetime: HookScopeLifetime,
) -> HookRegistrationScope:
    resolved_turn_id = scope.turn_id or turn_id
    resolved_session_id = scope.session_id or session_id
    if scope.lifetime == HookScopeLifetime.TURN:
        return HookRegistrationScope(
            lifetime=scope.lifetime,
            inherit_to_children=scope.inherit_to_children,
            turn_id=resolved_turn_id,
            session_id=resolved_session_id,
            cleanup_boundary=scope.cleanup_boundary,
        )
    if scope.lifetime == HookScopeLifetime.SESSION:
        if resolved_session_id is None and default_lifetime == HookScopeLifetime.SESSION_TEMPLATE:
            return HookRegistrationScope(
                lifetime=HookScopeLifetime.SESSION_TEMPLATE,
                inherit_to_children=scope.inherit_to_children,
                turn_id=None,
                session_id=None,
                cleanup_boundary=scope.cleanup_boundary,
            )
        return HookRegistrationScope(
            lifetime=scope.lifetime,
            inherit_to_children=scope.inherit_to_children,
            turn_id=None,
            session_id=resolved_session_id,
            cleanup_boundary=scope.cleanup_boundary,
        )
    return HookRegistrationScope(
        lifetime=scope.lifetime,
        inherit_to_children=scope.inherit_to_children,
        turn_id=None,
        session_id=None,
        cleanup_boundary=scope.cleanup_boundary,
    )


def _coerce_registration_request(
    value: HookRegistrationRequest | Mapping[str, Any],
    *,
    default_scope_lifetime: HookScopeLifetime,
    turn_id: str | None,
    session_id: str | None,
) -> HookRegistrationRequest:
    if isinstance(value, HookRegistrationRequest):
        scope = _coerce_scope(
            value.scope,
            default_lifetime=default_scope_lifetime,
            turn_id=turn_id,
            session_id=session_id,
        )
        return HookRegistrationRequest(
            phase=value.phase,
            match=_coerce_match(value.match),
            scope=scope,
            handler=_coerce_handler_manifest(value.handler),
            contract=_coerce_effect_contract(value.contract),
            owner_hint=value.owner_hint,
            source_ref=value.source_ref,
            once=value.once,
            metadata=value.metadata,
        )
    if not isinstance(value, Mapping):
        raise TypeError("Hook registration request must be a mapping or HookRegistrationRequest")
    phase = str(value.get("phase") or value.get("name") or "")
    match = _coerce_match(value.get("match", value.get("matcher")))
    scope = _coerce_scope(
        value.get("scope"),
        default_lifetime=default_scope_lifetime,
        turn_id=turn_id,
        session_id=session_id,
    )
    handler = _coerce_handler_manifest(value.get("handler"), effect=value.get("effect"))
    contract = _coerce_effect_contract(value.get("contract"))
    return HookRegistrationRequest(
        phase=phase,
        match=match,
        scope=scope,
        handler=handler,
        contract=contract,
        owner_hint=_coerce_optional_string(value.get("owner_hint")),
        source_ref=_coerce_optional_string(value.get("source_ref")),
        once=bool(value.get("once", False)),
        metadata=dict(value.get("metadata", {})) if isinstance(value.get("metadata"), Mapping) else {},
    )


def _coerce_match(value: object) -> HookMatch:
    if isinstance(value, HookMatch):
        return value
    if isinstance(value, str):
        return HookMatch(target=value)
    if isinstance(value, Mapping):
        return HookMatch(target=str(value.get("target") or value.get("matcher") or "*"))
    return HookMatch()


def _coerce_scope(
    value: object,
    *,
    default_lifetime: HookScopeLifetime,
    turn_id: str | None,
    session_id: str | None,
) -> HookRegistrationScope:
    if isinstance(value, HookRegistrationScope):
        return value
    if isinstance(value, Mapping):
        raw_lifetime = value.get("lifetime", default_lifetime.value)
        return HookRegistrationScope(
            lifetime=HookScopeLifetime(str(raw_lifetime)),
            inherit_to_children=bool(value.get("inherit_to_children", False)),
            turn_id=_coerce_optional_string(value.get("turn_id")) or turn_id,
            session_id=_coerce_optional_string(value.get("session_id")) or session_id,
            cleanup_boundary=_coerce_optional_string(value.get("cleanup_boundary")),
        )
    return HookRegistrationScope(
        lifetime=default_lifetime,
        turn_id=turn_id if default_lifetime == HookScopeLifetime.TURN else None,
        session_id=session_id if default_lifetime != HookScopeLifetime.SESSION_TEMPLATE else None,
    )


def _coerce_effect_contract(value: object) -> HookEffectContract:
    if isinstance(value, HookEffectContract):
        return value
    if not isinstance(value, Mapping):
        return HookEffectContract()
    effect_classes = tuple(value.get("effect_classes", ()) or ())
    effect_fields = tuple(value.get("effect_fields", ()) or ())
    return HookEffectContract(
        effect_classes=effect_classes,
        effect_fields=effect_fields,
        restrict_fields=bool(value.get("restrict_fields", True)),
    )


def _coerce_handler_manifest(value: object, *, effect: object = None) -> HookHandlerManifest:
    if isinstance(value, HookHandlerManifest):
        return value
    if callable(value):
        return HookHandlerManifest(kind=HookHandlerKind.CALLBACK, callback=value)
    if isinstance(value, Mapping):
        if "ref" in value:
            return HookHandlerManifest(
                kind=HookHandlerKind.CALLBACK,
                binding=_coerce_optional_string(value.get("ref")),
            )
        raw_kind = value.get("kind", HookHandlerKind.CALLBACK.value)
        kind = HookHandlerKind(str(raw_kind))
        raw_command = value.get("command", ())
        command: tuple[str, ...]
        if isinstance(raw_command, str):
            command = (raw_command,)
        elif isinstance(raw_command, Sequence):
            command = tuple(str(item) for item in raw_command)
        else:
            command = ()
        return HookHandlerManifest(
            kind=kind,
            binding=_coerce_optional_string(value.get("binding")),
            callback=value.get("callback") if callable(value.get("callback")) else None,
            endpoint=_coerce_optional_string(value.get("endpoint")),
            method=_coerce_optional_string(value.get("method")) or "POST",
            command=command,
            agent_name=_coerce_optional_string(value.get("agent") or value.get("agent_name")),
            prompt=_coerce_optional_string(value.get("prompt")),
            timeout_ms=_coerce_optional_int(value.get("timeout_ms")),
            response_contract=_coerce_optional_string(value.get("response_contract")),
            policy_tags=tuple(str(item) for item in value.get("policy_tags", ()) or ()),
            metadata=dict(value.get("metadata", {})) if isinstance(value.get("metadata"), Mapping) else {},
            static_effect=value.get("effect"),
        )
    if effect is not None:
        return HookHandlerManifest(kind=HookHandlerKind.CALLBACK, static_effect=effect)
    return HookHandlerManifest(kind=HookHandlerKind.CALLBACK)


def _normalize_authoring_document(
    hooks: Mapping[str, Any],
    *,
    default_scope_lifetime: HookScopeLifetime,
    session_id: str | None,
    turn_id: str | None,
) -> tuple[HookRegistrationRequest, ...]:
    if "registrations" in hooks:
        handlers = hooks.get("handlers", {})
        requests: list[HookRegistrationRequest] = []
        for raw_registration in hooks.get("registrations", ()) or ():
            if not isinstance(raw_registration, Mapping):
                continue
            registration = dict(raw_registration)
            handler_value = registration.get("handler")
            if isinstance(handler_value, Mapping) and "ref" in handler_value and isinstance(handlers, Mapping):
                ref = str(handler_value.get("ref"))
                resolved = handlers.get(ref)
                if resolved is not None:
                    registration["handler"] = resolved
            requests.append(
                _coerce_registration_request(
                    registration,
                    default_scope_lifetime=default_scope_lifetime,
                    turn_id=turn_id,
                    session_id=session_id,
                )
            )
        return tuple(requests)

    requests: list[HookRegistrationRequest] = []
    for raw_phase, raw_entries in hooks.items():
        if raw_phase in {"handlers", "registrations"}:
            continue
        entries = raw_entries if isinstance(raw_entries, (list, tuple)) else (raw_entries,)
        for entry in entries:
            if callable(entry):
                requests.append(
                    HookRegistrationRequest(
                        phase=str(raw_phase),
                        match=HookMatch(),
                        scope=HookRegistrationScope(
                            lifetime=default_scope_lifetime,
                            turn_id=turn_id if default_scope_lifetime == HookScopeLifetime.TURN else None,
                            session_id=session_id if default_scope_lifetime != HookScopeLifetime.SESSION_TEMPLATE else None,
                        ),
                        handler=HookHandlerManifest(kind=HookHandlerKind.CALLBACK, callback=entry),
                    )
                )
                continue
            if isinstance(entry, Mapping):
                requests.append(
                    HookRegistrationRequest(
                        phase=str(raw_phase),
                        match=_coerce_match(entry.get("match", entry.get("matcher"))),
                        scope=_coerce_scope(
                            entry.get("scope"),
                            default_lifetime=default_scope_lifetime,
                            turn_id=turn_id,
                            session_id=session_id,
                        ),
                        handler=_coerce_handler_manifest(entry.get("handler"), effect=entry.get("effect")),
                        contract=_coerce_effect_contract(entry.get("contract")),
                        once=bool(entry.get("once", False)),
                        metadata=dict(entry.get("metadata", {})) if isinstance(entry.get("metadata"), Mapping) else {},
                    )
                )
    return tuple(requests)


def _inventory_entry(record: _RegistrationRecord) -> HookInventoryEntry:
    return HookInventoryEntry(
        registration_id=record.registration_id,
        activation_state=record.activation_state,
        source_kind=record.source_kind,
        source_ref=record.source_ref,
        owner=record.owner,
        phase=record.phase,
        scope=record.scope,
        handler_kind=record.handler_manifest.kind,
        matcher_summary=record.matcher,
        precedence_key=record.precedence_key,
        session_id=record.session_id,
        turn_id=record.turn_id,
        parent_registration_id=record.parent_registration_id,
        metadata=dict(record.metadata),
    )


def _trace_registration(record: _RegistrationRecord, *, reason: str | None = None) -> HookTraceRegistration:
    metadata = dict(record.metadata)
    if record.rejection_reason is not None:
        metadata.setdefault("rejection_reason", record.rejection_reason)
    return HookTraceRegistration(
        registration_id=record.registration_id,
        source_kind=record.source_kind,
        source_ref=record.source_ref,
        owner=record.owner,
        phase=record.phase,
        handler_kind=record.handler_manifest.kind,
        matcher=record.matcher,
        precedence_key=record.precedence_key,
        activation_state=record.activation_state,
        reason=reason,
        metadata=metadata,
    )


def _record_matches_inventory_query(record: _RegistrationRecord, query: HookInventoryQuery) -> bool:
    if query.session_id is not None and record.session_id != query.session_id:
        return False
    if query.turn_id is not None and record.turn_id != query.turn_id:
        return False
    if query.phase is not None and record.phase != query.phase:
        return False
    if query.owner is not None and record.owner != query.owner:
        return False
    if query.source_kind is not None and record.source_kind != query.source_kind:
        return False
    if query.activation_state is not None:
        return record.activation_state == query.activation_state
    if not query.include_inactive and record.activation_state != HookActivationState.ACTIVE:
        return False
    return True


def _trace_matches_query(trace: HookDispatchTrace, query: HookDispatchTraceQuery) -> bool:
    if query.session_id is not None and trace.session_id != query.session_id:
        return False
    if query.turn_id is not None and trace.turn_id != query.turn_id:
        return False
    if query.phase is not None and trace.phase != query.phase:
        return False
    if query.owner is not None:
        owners = {item.owner for item in trace.matched_registrations}
        if query.owner not in owners:
            return False
    if query.source_kind is not None:
        source_kinds = {item.source_kind for item in trace.matched_registrations}
        if query.source_kind not in source_kinds:
            return False
    return True


def _turn_scope_matches(record: _RegistrationRecord, payload_turn_id: str | None) -> bool:
    if record.scope.lifetime != HookScopeLifetime.TURN:
        return True
    return record.turn_id == payload_turn_id


def _dispatch_visibility_matches(
    record: _RegistrationRecord,
    *,
    turn_id: str | None,
    dispatch_context: Mapping[str, Any],
) -> bool:
    if not _dispatch_context_is_child_execution(dispatch_context):
        return True
    if record.scope.inherit_to_children:
        return True
    return record.activation_turn_id is not None and record.activation_turn_id == turn_id


def _dispatch_context_is_child_execution(dispatch_context: Mapping[str, Any]) -> bool:
    return (
        _coerce_optional_string(dispatch_context.get("parent_turn_id")) is not None
        or _coerce_optional_string(dispatch_context.get("parent_run_id")) is not None
    )


def _coerce_dispatch_context(value: Mapping[str, Any] | Any | None) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    metadata = getattr(value, "metadata", None)
    if isinstance(metadata, Mapping):
        return dict(metadata)
    return {}


def _dispatch_trace_sort_key(trace: HookDispatchTrace) -> tuple[int, str]:
    prefix, _, suffix = trace.dispatch_id.partition("_")
    if prefix == "hookdisp" and suffix.isdigit():
        return int(suffix), trace.dispatch_id
    return 0, trace.dispatch_id


def _coerce_inventory_query(value: HookInventoryQuery | Mapping[str, Any] | None) -> HookInventoryQuery:
    if isinstance(value, HookInventoryQuery):
        return value
    if not isinstance(value, Mapping):
        return HookInventoryQuery()
    return HookInventoryQuery(
        session_id=_coerce_optional_string(value.get("session_id")),
        turn_id=_coerce_optional_string(value.get("turn_id")),
        phase=_coerce_optional_string(value.get("phase")),
        owner=_coerce_optional_string(value.get("owner")),
        source_kind=value.get("source_kind"),
        activation_state=value.get("activation_state"),
        include_inactive=bool(value.get("include_inactive", False)),
        limit=_coerce_optional_int(value.get("limit")),
        cursor=_coerce_optional_string(value.get("cursor")),
    )


def _coerce_trace_query(value: HookDispatchTraceQuery | Mapping[str, Any] | None) -> HookDispatchTraceQuery:
    if isinstance(value, HookDispatchTraceQuery):
        return value
    if not isinstance(value, Mapping):
        return HookDispatchTraceQuery()
    return HookDispatchTraceQuery(
        session_id=_coerce_optional_string(value.get("session_id")),
        turn_id=_coerce_optional_string(value.get("turn_id")),
        phase=_coerce_optional_string(value.get("phase")),
        owner=_coerce_optional_string(value.get("owner")),
        source_kind=value.get("source_kind"),
        limit=_coerce_optional_int(value.get("limit")),
        cursor=_coerce_optional_string(value.get("cursor")),
    )


def _slice_with_cursor(values: Sequence[Any], cursor: str | None, limit: int | None) -> Sequence[Any]:
    start = 0
    if cursor is not None:
        try:
            start = max(int(cursor), 0)
        except ValueError:
            start = 0
    if limit is None or limit <= 0:
        return values[start:]
    return values[start : start + limit]


def _payload_to_json(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        return {str(key): _jsonable(inner) for key, inner in payload.items()}
    if hasattr(payload, "__dict__"):
        return {str(key): _jsonable(value) for key, value in vars(payload).items()}
    return {"value": _jsonable(payload)}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, MessageAttachment):
        return {
            "name": value.name,
            "path": value.path,
            "mime_type": value.mime_type,
            "metadata": dict(value.metadata),
        }
    if isinstance(value, PromptContextEnvelope):
        return value.compat_metadata()
    if isinstance(value, RuntimeMessage):
        return {
            "message_id": value.message_id,
            "role": value.role.value,
            "text": value.text,
            "metadata": dict(value.metadata),
        }
    if isinstance(value, RuntimePrivateContext):
        return value.compat_metadata()
    if isinstance(value, RequestOverrideState):
        return value.serialize()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return {str(key): _jsonable(inner) for key, inner in vars(value).items()}
    return str(value)


def _coerce_optional_string(value: object) -> str | None:
    if value is None:
        return None
    stringified = str(value).strip()
    return stringified or None


def _coerce_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


async def _noop_handler(_: Any) -> None:
    return None


__all__ = ["HookBus", "HookDispatchResult", "HookRegistration"]
