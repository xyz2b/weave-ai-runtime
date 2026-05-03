from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..control_plane import resolve_host_runtime
from ..definitions import PermissionBehavior, PermissionDecision, PermissionMode, ToolDefinition
from .models import (
    PermissionContext,
    PermissionOutcome,
    PermissionRequest,
    PermissionRule,
    PermissionTarget,
    coerce_permission_outcome,
)


@dataclass(slots=True)
class PermissionEngine:
    default_mode: PermissionMode = PermissionMode.DEFAULT
    default_rules: tuple[PermissionRule, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

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

    async def evaluate(
        self,
        request: PermissionRequest,
        *,
        initial_decision: PermissionDecision | PermissionOutcome | None = None,
        hook_result: Any = None,
        runtime_context: Any = None,
    ) -> PermissionOutcome:
        permission_context = self._resolve_context(request.context)
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
        if mode == PermissionMode.BYPASS_PERMISSIONS:
            return PermissionOutcome(
                PermissionBehavior.ALLOW,
                updated_input=payload,
                details={"mode": mode.value},
                source="mode",
            )

        rule = self._matching_rule(permission_context, request)
        if rule is not None:
            outcome = PermissionOutcome(
                behavior=rule.behavior,
                message=rule.message or outcome.message,
                updated_input=payload,
                details={**outcome.details, **rule.metadata, "rule": rule.selector},
                source="rule",
            )
        else:
            outcome = PermissionOutcome(
                behavior=outcome.behavior,
                message=outcome.message,
                updated_input=payload,
                details=dict(outcome.details),
                source=outcome.source,
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

    def _resolve_context(self, context: PermissionContext | None) -> PermissionContext:
        if context is not None:
            return PermissionContext(
                session_id=context.session_id,
                mode=context.mode,
                rules=context.rules or self.default_rules,
                metadata={**self.metadata, **context.metadata},
            )
        return PermissionContext(
            session_id="",
            mode=self.default_mode,
            rules=self.default_rules,
            metadata=dict(self.metadata),
        )

    @staticmethod
    def _matching_rule(
        context: PermissionContext,
        request: PermissionRequest,
    ) -> PermissionRule | None:
        matched: PermissionRule | None = None
        for rule in context.rules:
            if rule.matches(request):
                matched = rule
        return matched


__all__ = ["PermissionEngine"]


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
