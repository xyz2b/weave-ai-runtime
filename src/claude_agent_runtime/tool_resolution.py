from __future__ import annotations

from dataclasses import replace
from typing import Any

from .definitions import (
    PermissionBehavior,
    PermissionDecision,
    ResolvedToolExecutionSemantics,
    ToolCallStatus,
    ToolDefinition,
)
from .hooks import PreToolUsePayload
from .tool_lifecycle import (
    PermissionAllowed,
    PermissionDenied,
    ResolvedToolCall,
    ToolCallEnvelope,
    ToolResolutionStatus,
)
from .tool_runtime import ToolContext, _dispatch_hook, maybe_await, validate_input_schema


async def resolve_tool_call(
    envelope: ToolCallEnvelope,
    context: ToolContext,
    *,
    executor_tier: str,
    model_capabilities: Any = None,
) -> ResolvedToolCall:
    canonical_tool_name = _resolve_canonical_tool_name(envelope.raw_tool_name, context)
    definition = None if canonical_tool_name is None else _get_tool_definition(canonical_tool_name, context)
    call_context = context.for_call(
        tool_use_id=envelope.tool_use_id,
        replay_index=envelope.sequence_index,
        assistant_message_id=envelope.assistant_message_id,
        canonical_tool_name=canonical_tool_name,
        executor_tier=executor_tier,
        model_capabilities=model_capabilities,
    )
    capability_context = call_context.capability_context
    if definition is None or capability_context is None:
        return ResolvedToolCall(
            envelope=envelope,
            resolution_status=ToolResolutionStatus.INVALID,
            canonical_tool_name=canonical_tool_name,
            tool_definition_ref=None,
            execution_input=None,
            observable_input=None,
            resolved_semantics=None,
            permission_decision=None,
            scheduler_lane=None,
            replay_index=envelope.sequence_index,
            capability_context=capability_context or call_context.for_call(
                tool_use_id=envelope.tool_use_id,
                replay_index=envelope.sequence_index,
                assistant_message_id=envelope.assistant_message_id,
                canonical_tool_name=canonical_tool_name,
                executor_tier=executor_tier,
                model_capabilities=model_capabilities,
            ).capability_context,
        )

    if call_context.tool_pool and not _tool_available_in_pool(envelope.raw_tool_name, call_context.tool_pool):
        return ResolvedToolCall(
            envelope=envelope,
            resolution_status=ToolResolutionStatus.DENIED,
            canonical_tool_name=canonical_tool_name,
            tool_definition_ref=definition,
            execution_input=None,
            observable_input=None,
            resolved_semantics=None,
            permission_decision=PermissionDenied(
                denied_status=_denied_status(PermissionBehavior.DENY),
                message=f"Tool '{envelope.raw_tool_name}' is not available in the current execution policy",
                source="policy",
                audit_metadata={"available_tools": [tool.name for tool in call_context.tool_pool]},
            ),
            scheduler_lane=None,
            replay_index=envelope.sequence_index,
            capability_context=capability_context,
        )

    try:
        normalized_input = validate_input_schema(definition.input_schema, envelope.raw_input)
    except Exception as exc:
        return ResolvedToolCall(
            envelope=envelope,
            resolution_status=ToolResolutionStatus.INVALID,
            canonical_tool_name=canonical_tool_name,
            tool_definition_ref=definition,
            execution_input=None,
            observable_input=dict(envelope.raw_input),
            resolved_semantics=None,
            permission_decision=None,
            scheduler_lane=None,
            replay_index=envelope.sequence_index,
            capability_context=capability_context,
        )

    if definition.validate_input is not None:
        validation = await maybe_await(definition.validate_input(normalized_input, call_context))
        if not validation.valid:
            return ResolvedToolCall(
                envelope=envelope,
                resolution_status=ToolResolutionStatus.INVALID,
                canonical_tool_name=canonical_tool_name,
                tool_definition_ref=definition,
                execution_input=None,
                observable_input=dict(normalized_input),
                resolved_semantics=None,
                permission_decision=None,
                scheduler_lane=None,
                replay_index=envelope.sequence_index,
                capability_context=capability_context,
            )
        if validation.updated_input is not None:
            normalized_input = validation.updated_input

    pre_tool_hook = await _dispatch_hook(
        call_context,
        PreToolUsePayload(
            session_id=call_context.session_id,
            tool_name=definition.name,
            tool_input=dict(normalized_input),
            turn_id=call_context.turn_id,
        ),
    )
    if pre_tool_hook.updated_input is not None:
        normalized_input = pre_tool_hook.updated_input
    call_context.pending_hook_effect = pre_tool_hook
    if not pre_tool_hook.continue_execution:
        return ResolvedToolCall(
            envelope=envelope,
            resolution_status=ToolResolutionStatus.DENIED,
            canonical_tool_name=canonical_tool_name,
            tool_definition_ref=definition,
            execution_input=None,
            observable_input=dict(normalized_input),
            resolved_semantics=None,
            permission_decision=PermissionDenied(
                denied_status=_denied_status(PermissionBehavior.DENY),
                message="Tool use blocked by runtime hook",
                source="hook",
                audit_metadata={"matched_hooks": list(pre_tool_hook.matched_owners)},
            ),
            scheduler_lane=None,
            replay_index=envelope.sequence_index,
            capability_context=capability_context,
        )

    permission_decision = PermissionDecision(PermissionBehavior.ALLOW)
    if definition.check_permissions is not None:
        permission_decision = await maybe_await(
            definition.check_permissions(normalized_input, call_context)
        )
    normalized_input = permission_decision.updated_input or normalized_input

    if call_context.runtime_services is not None:
        permission_decision = await call_context.runtime_services.permissions.authorize(
            definition,
            normalized_input,
            permission_decision,
            call_context,
        )
        normalized_input = permission_decision.updated_input or normalized_input
    elif permission_decision.behavior == PermissionBehavior.ASK:
        if call_context.permission_handler is None:
            permission_decision = PermissionDecision(
                behavior=PermissionBehavior.DENY,
                message=permission_decision.message or "Permission required",
                updated_input=normalized_input,
                details=dict(permission_decision.details),
            )
        else:
            permission_decision = await call_context.permission_handler(
                definition,
                normalized_input,
                permission_decision,
                call_context,
            )
            normalized_input = permission_decision.updated_input or normalized_input

    if permission_decision.behavior != PermissionBehavior.ALLOW:
        return ResolvedToolCall(
            envelope=envelope,
            resolution_status=ToolResolutionStatus.DENIED,
            canonical_tool_name=canonical_tool_name,
            tool_definition_ref=definition,
            execution_input=dict(normalized_input),
            observable_input=dict(normalized_input),
            resolved_semantics=None,
            permission_decision=PermissionDenied(
                denied_status=_denied_status(permission_decision.behavior),
                message=permission_decision.message or "Tool use denied",
                source=str(permission_decision.details.get("source", "policy")),
                audit_metadata=dict(permission_decision.details),
            ),
            scheduler_lane=None,
            replay_index=envelope.sequence_index,
            capability_context=capability_context,
        )

    resolved_semantics = await resolve_execution_semantics(
        definition,
        normalized_input,
        call_context,
    )
    return ResolvedToolCall(
        envelope=envelope,
        resolution_status=ToolResolutionStatus.EXECUTABLE,
        canonical_tool_name=canonical_tool_name,
        tool_definition_ref=definition,
        execution_input=dict(normalized_input),
        observable_input=dict(normalized_input),
        resolved_semantics=resolved_semantics,
        permission_decision=PermissionAllowed(
            source=str(permission_decision.details.get("source", "policy")),
            updated_input=dict(normalized_input),
            user_modified=permission_decision.updated_input is not None,
            audit_metadata=dict(permission_decision.details),
        ),
        scheduler_lane=None,
        replay_index=envelope.sequence_index,
        capability_context=capability_context,
    )


async def resolve_execution_semantics(
    definition: ToolDefinition,
    tool_input: dict[str, Any],
    context: ToolContext,
) -> ResolvedToolExecutionSemantics:
    semantics = definition.execution_semantics
    return ResolvedToolExecutionSemantics(
        read_only=bool(await maybe_await(semantics.is_read_only(tool_input, context))),
        concurrency_safe=bool(
            await maybe_await(semantics.is_concurrency_safe(tool_input, context))
        ),
        interrupt_behavior=await maybe_await(semantics.interrupt_behavior(tool_input, context)),
        failure_policy=await maybe_await(semantics.failure_policy(tool_input, context)),
        tool_use_presentation=await maybe_await(
            semantics.render_tool_use_message(tool_input, context)
        ),
        tool_result_summary=await maybe_await(
            semantics.render_tool_result_summary(tool_input, context)
        ),
        classifier_input=await maybe_await(semantics.to_classifier_input(tool_input, context)),
    )


def with_scheduler_lane(
    resolved_call: ResolvedToolCall,
    lane: Any,
) -> ResolvedToolCall:
    return replace(resolved_call, scheduler_lane=lane)


def _resolve_canonical_tool_name(name: str, context: ToolContext) -> str | None:
    registry = context.tool_registry
    if registry is not None:
        definition = registry.get(name)
        if definition is not None:
            return definition.name
    catalog = context.tool_catalog
    if catalog is None:
        return name
    resolved = catalog.resolve_alias(name)
    if resolved is not None:
        return resolved
    entry = catalog.get(name)
    return None if entry is None else entry.name


def _get_tool_definition(name: str, context: ToolContext) -> ToolDefinition | None:
    registry = context.tool_registry
    if registry is None:
        return None
    return registry.get(name)


def _denied_status(behavior: PermissionBehavior) -> Any:
    return (
        ToolCallStatus.CANCELLED
        if behavior == PermissionBehavior.ASK
        else ToolCallStatus.DENIED
    )


def _tool_available_in_pool(
    requested_name: str,
    pool: tuple[ToolDefinition, ...],
) -> bool:
    return any(definition.matches(requested_name) for definition in pool)
