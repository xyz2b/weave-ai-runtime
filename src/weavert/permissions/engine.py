from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..control_plane import resolve_host_runtime
from ..definitions import (
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    ToolClassifierInput,
    ToolDefinition,
)
from .models import (
    PermissionContext,
    PermissionEvaluationExplanation,
    PermissionOutcome,
    PermissionPolicy,
    PermissionPolicyEvaluation,
    PermissionRequest,
    PermissionRequestMatchSnapshot,
    PermissionRule,
    PermissionRuleEvaluation,
    PermissionTarget,
    coerce_permission_outcome,
)


@dataclass(slots=True)
class PermissionEngine:
    default_mode: PermissionMode = PermissionMode.DEFAULT
    default_rules: tuple[PermissionRule, ...] = ()
    default_policies: tuple[PermissionPolicy, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.default_rules = tuple(self.default_rules)
        self.default_policies = tuple(self.default_policies)
        self.metadata = dict(self.metadata)

    async def authorize(
        self,
        definition: ToolDefinition,
        tool_input: dict[str, Any],
        decision: PermissionDecision,
        context: Any,
    ) -> PermissionDecision:
        permission_context = getattr(context, "permission_context", None)
        request = PermissionRequest(
            session_id=getattr(context, "session_id", ""),
            turn_id=getattr(context, "turn_id", None),
            target=PermissionTarget.TOOL,
            name=definition.name,
            payload=dict(tool_input),
            context=permission_context,
            message=decision.message,
            metadata={
                "definition": definition,
                "decision": decision,
                "runtime_context": context,
            },
        )
        hook_result = getattr(context, "pending_hook_effect", None)
        outcome = await self.evaluate(
            request,
            initial_decision=decision,
            hook_result=hook_result,
            runtime_context=context,
        )
        return outcome.to_decision()

    def resolve_context(
        self,
        context: PermissionContext | None,
        *,
        session_id: str,
    ) -> PermissionContext:
        return self._resolve_context(context, session_id=session_id)

    def resolve_policies(
        self,
        context: PermissionContext | None,
        *,
        session_id: str,
    ) -> tuple[PermissionPolicy, ...]:
        resolved_context = self.resolve_context(context, session_id=session_id)
        return self._resolved_policies(resolved_context)

    async def evaluate(
        self,
        request: PermissionRequest,
        *,
        initial_decision: PermissionDecision | PermissionOutcome | None = None,
        hook_result: Any = None,
        runtime_context: Any = None,
    ) -> PermissionOutcome:
        permission_context = self._resolve_context(request.context, session_id=request.session_id)
        outcome = coerce_permission_outcome(initial_decision)
        payload = dict(outcome.updated_input or request.payload)

        if hook_result is not None:
            if getattr(hook_result, "updated_input", None) is not None:
                payload = dict(hook_result.updated_input)
            if not getattr(hook_result, "continue_execution", True):
                return PermissionOutcome(
                    PermissionBehavior.DENY,
                    message="Execution blocked by runtime hook",
                    updated_input=payload,
                    details={"source": "hook"},
                    source="hook",
                )

        mode = permission_context.mode
        snapshot = await self._build_request_snapshot(
            request,
            permission_context=permission_context,
            runtime_context=runtime_context,
        )

        if mode == PermissionMode.BYPASS_PERMISSIONS:
            return PermissionOutcome(
                PermissionBehavior.ALLOW,
                updated_input=payload,
                details={"mode": mode.value},
                source="mode",
            )

        outcome = self._apply_policy_stack(
            permission_context,
            request,
            snapshot=snapshot,
            payload=payload,
            base_outcome=outcome,
        )

        if outcome.behavior == PermissionBehavior.ASK and mode == PermissionMode.DONT_ASK:
            return PermissionOutcome(
                PermissionBehavior.DENY,
                message=outcome.message or "Interactive permission prompts are disabled",
                updated_input=payload,
                details={**outcome.details, "mode": mode.value},
                source="mode",
            )

        if outcome.behavior != PermissionBehavior.ASK:
            return outcome

        host_runtime = resolve_host_runtime(runtime_context)

        if mode == PermissionMode.BUBBLE:
            return PermissionOutcome(
                PermissionBehavior.ASK,
                message=outcome.message or "Permission request bubbled to caller",
                updated_input=payload,
                details={**outcome.details, "mode": mode.value, "bubbled": True},
                source="mode",
            )

        if host_runtime is None or not hasattr(host_runtime, "request_permission"):
            return PermissionOutcome(
                PermissionBehavior.DENY,
                message=outcome.message or "Permission required",
                updated_input=payload,
                details={**outcome.details, "source": "host_missing"},
                source="host",
            )

        host_outcome = await _maybe_await(
            host_runtime.request_permission(request.with_payload(payload))
        )
        resolved = coerce_permission_outcome(host_outcome)
        resolved_payload = resolved.updated_input
        if resolved_payload is None:
            resolved_payload = payload
        return PermissionOutcome(
            behavior=resolved.behavior,
            message=resolved.message,
            updated_input=resolved_payload,
            details={**outcome.details, **dict(resolved.details)},
            source=resolved.source or "host",
        )

    def _resolve_context(
        self,
        context: PermissionContext | None,
        *,
        session_id: str,
    ) -> PermissionContext:
        if context is not None:
            return PermissionContext(
                session_id=context.session_id,
                mode=context.mode,
                rules=context.rules or self.default_rules,
                policies=self.default_policies + context.policies,
                metadata={**self.metadata, **context.metadata},
            )
        return PermissionContext(
            session_id=session_id,
            mode=self.default_mode,
            rules=self.default_rules,
            policies=self.default_policies,
            metadata=dict(self.metadata),
        )

    def _apply_policy_stack(
        self,
        context: PermissionContext,
        request: PermissionRequest,
        *,
        snapshot: PermissionRequestMatchSnapshot,
        payload: dict[str, Any],
        base_outcome: PermissionOutcome,
    ) -> PermissionOutcome:
        policies = self._resolved_policies(context)
        if not policies:
            return PermissionOutcome(
                behavior=base_outcome.behavior,
                message=base_outcome.message,
                updated_input=payload,
                details=dict(base_outcome.details),
                source=base_outcome.source,
            )

        layer_results = [self._evaluate_policy(policy, request, snapshot=snapshot, policy_index=index) for index, policy in enumerate(policies)]
        winner = next((result for result in reversed(layer_results) if result.outcome is not None), None)
        explanation = PermissionEvaluationExplanation(
            request=snapshot,
            layers=tuple(result.evaluation for result in layer_results),
            winning_layer_index=None if winner is None else winner.evaluation.policy_index,
            metadata={"policy_count": len(layer_results)},
        )
        details = dict(base_outcome.details)
        details["policy_explanation"] = explanation.to_dict()
        details.setdefault("policy_composition", explanation.composition)

        if winner is None:
            return PermissionOutcome(
                behavior=base_outcome.behavior,
                message=base_outcome.message,
                updated_input=payload,
                details=details,
                source=base_outcome.source,
            )

        details.update(winner.details)
        message = winner.outcome.message
        if message is None and winner.outcome.behavior == base_outcome.behavior:
            message = base_outcome.message
        return PermissionOutcome(
            behavior=winner.outcome.behavior,
            message=message,
            updated_input=payload,
            details=details,
            source=winner.outcome.source or base_outcome.source,
        )

    def _resolved_policies(
        self,
        context: PermissionContext,
    ) -> tuple[PermissionPolicy, ...]:
        policies = list(context.policies)
        if context.rules:
            policies.append(
                PermissionPolicy(
                    name="legacy-rules",
                    rules=context.rules,
                    source="rule",
                )
            )
        return tuple(policies)

    def _evaluate_policy(
        self,
        policy: PermissionPolicy,
        request: PermissionRequest,
        *,
        snapshot: PermissionRequestMatchSnapshot,
        policy_index: int,
    ) -> _PolicyLayerResult:
        matched_rules: list[PermissionRuleEvaluation] = []
        winner_rule: PermissionRule | None = None
        winner_details: dict[str, Any] = {}

        for rule_index, rule in enumerate(policy.rules):
            if not rule.matches(request, snapshot):
                continue
            matched_rules.append(
                PermissionRuleEvaluation(
                    rule_index=rule_index,
                    selector=rule.selector,
                    behavior=rule.behavior,
                    target=rule.target,
                    message=rule.message,
                    scopes=rule.scopes,
                    risk_levels=rule.risk_levels,
                    operations=rule.operations,
                    tags=rule.tags,
                    read_only=rule.read_only,
                    metadata=rule.metadata,
                )
            )
            winner_rule = rule
            winner_details = {**policy.metadata, **rule.metadata}

        fallback_used = False
        decision: PermissionBehavior | None = None
        message: str | None = None
        if winner_rule is not None:
            decision = winner_rule.behavior
            message = winner_rule.message
        elif policy.fallback_behavior is not None:
            fallback_used = True
            decision = policy.fallback_behavior
            message = policy.fallback_message
            winner_details = {**policy.metadata, **policy.fallback_metadata}

        source = policy.source
        evaluation = PermissionPolicyEvaluation(
            policy_name=policy.name,
            policy_index=policy_index,
            decision=decision,
            matched_rules=tuple(matched_rules),
            fallback_used=fallback_used,
            fallback_behavior=policy.fallback_behavior if fallback_used else None,
            fallback_message=policy.fallback_message if fallback_used else None,
            source=source,
            metadata=dict(policy.metadata),
        )

        if decision is None:
            return _PolicyLayerResult(outcome=None, details={}, evaluation=evaluation)

        resolved_details = dict(winner_details)
        resolved_details.setdefault("policy_name", policy.name)
        resolved_details.setdefault("policy_index", policy_index)
        if winner_rule is not None:
            resolved_details.setdefault("policy_rule", winner_rule.selector)
        if policy.source is not None:
            resolved_details.setdefault("policy_source", policy.source)
        if policy.source == "preset":
            resolved_details.setdefault("preset_target", request.target.value)
        outcome = PermissionOutcome(
            behavior=decision,
            message=message,
            details=resolved_details,
            source=policy.source or "policy",
        )
        return _PolicyLayerResult(outcome=outcome, details=resolved_details, evaluation=evaluation)

    async def _build_request_snapshot(
        self,
        request: PermissionRequest,
        *,
        permission_context: PermissionContext,
        runtime_context: Any,
    ) -> PermissionRequestMatchSnapshot:
        candidate_names = [request.name]
        scopes = {
            request.target.value,
            f"target:{request.target.value}",
            "session",
            f"session:{request.session_id}",
            f"name:{request.name}",
        }
        if request.turn_id is not None:
            scopes.add("turn")
            scopes.add(f"turn:{request.turn_id}")

        explicit_scopes = (
            *permission_context.policy_scopes,
            *_coerce_scope_tokens(request.metadata),
            *_coerce_scope_tokens(_as_mapping(runtime_context)),
        )
        scopes.update(explicit_scopes)

        agent_name = _lookup_value(runtime_context, "agent_name")
        if agent_name is not None:
            scopes.add(f"agent:{agent_name}")

        query_source = _lookup_value(runtime_context, "query_source")
        if query_source is not None:
            scopes.add(f"query:{query_source}")

        spawn_mode = _lookup_value(runtime_context, "spawn_mode")
        if spawn_mode is not None:
            scopes.add(f"spawn:{_stringify_value(spawn_mode)}")

        depth = _lookup_value(runtime_context, "delegation_depth")
        if depth is not None:
            normalized_depth = str(depth)
            scopes.add(f"delegation-depth:{normalized_depth}")
            scopes.add("delegated" if normalized_depth != "0" else "root")

        read_only: bool | None = None
        risk_level = None
        operation: str | None = None
        tags: tuple[str, ...] = ()
        extra_metadata: dict[str, Any] = {}

        if request.target == PermissionTarget.TOOL:
            definition = request.metadata.get("definition")
            if isinstance(definition, ToolDefinition):
                candidate_names.extend(definition.aliases)
                call_context = request.metadata.get("runtime_context", runtime_context)
                read_only_value = await _maybe_await(
                    definition.execution_semantics.is_read_only(request.payload, call_context)
                )
                classifier_input = await _maybe_await(
                    definition.execution_semantics.to_classifier_input(request.payload, call_context)
                )
                read_only = bool(read_only_value)
                if isinstance(classifier_input, ToolClassifierInput):
                    risk_level = classifier_input.risk_level
                    operation = classifier_input.operation
                    tags = tuple(str(tag) for tag in classifier_input.tags)
                    if classifier_input.target_paths:
                        extra_metadata["target_paths"] = list(classifier_input.target_paths)
                        scopes.update(f"path:{path}" for path in classifier_input.target_paths)
                    if classifier_input.target_urls:
                        extra_metadata["target_urls"] = list(classifier_input.target_urls)
                        scopes.update(f"url:{url}" for url in classifier_input.target_urls)

        return PermissionRequestMatchSnapshot(
            target=request.target,
            name=request.name,
            candidate_names=tuple(dict.fromkeys(candidate_names)),
            scopes=tuple(sorted(scopes)),
            risk_level=risk_level,
            operation=operation,
            read_only=read_only,
            tags=tags,
            metadata=extra_metadata,
        )


__all__ = ["PermissionEngine"]


@dataclass(frozen=True, slots=True)
class _PolicyLayerResult:
    outcome: PermissionOutcome | None
    details: dict[str, Any]
    evaluation: PermissionPolicyEvaluation


def _coerce_scope_tokens(metadata: Mapping[str, Any] | None) -> tuple[str, ...]:
    if metadata is None:
        return ()
    raw = metadata.get("policy_scopes", metadata.get("scopes", metadata.get("scope")))
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (list, tuple, set, frozenset)):
        return tuple(str(value) for value in raw)
    return (str(raw),)


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    metadata = getattr(value, "metadata", None)
    if isinstance(metadata, Mapping):
        return metadata
    return None


def _lookup_value(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    if hasattr(value, key):
        return getattr(value, key)
    metadata = getattr(value, "metadata", None)
    if isinstance(metadata, Mapping):
        return metadata.get(key)
    return None


def _stringify_value(value: Any) -> str:
    candidate = getattr(value, "value", value)
    return str(candidate)


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
