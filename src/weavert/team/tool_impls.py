from __future__ import annotations

from typing import Any

from ..builtins.tool_impls import (
    _normalize_optional_string,
    _resolve_path,
    _structured_error,
    validate_agent_registry_entry,
)
from ..contracts import ExecutionResult
from ..definitions import IsolationMode, PermissionMode, ValidationOutcome
from ..team_control_plane import TeamControlError
from ..team_workflows import TeamWorkflowError, workflow_record_to_payload
from ..tool_runtime import ToolContext


def validate_team_create_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    name = _normalize_optional_string(tool_input.get("name"))
    normalized: dict[str, Any] = {}
    if name is not None:
        normalized["name"] = name
    return ValidationOutcome(True, updated_input=normalized)


async def team_create_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    plane = _team_control_plane(context)
    if plane is None:
        return _structured_error("unavailable", "Runtime team control plane is not configured")
    try:
        team, created = await plane.create_team(
            session_id=context.session_id,
            extensions=context.private_context.extensions,
            name=_normalize_optional_string(tool_input.get("name")),
        )
    except TeamControlError as exc:
        return _team_error_result(exc)
    return {
        "team_id": team.team_id,
        "leader_session_id": team.leader_session_id,
        "name": team.name,
        "created": created,
    }


def validate_team_spawn_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    registry_outcome = validate_agent_registry_entry(tool_input, context)
    if not registry_outcome.valid:
        return registry_outcome
    name = _normalize_optional_string(tool_input.get("name"))
    agent = _normalize_optional_string(tool_input.get("agent"))
    if name is None:
        return ValidationOutcome(False, "name must be non-empty")
    if agent is None:
        return ValidationOutcome(False, "agent must be non-empty")
    normalized: dict[str, Any] = {"name": name, "agent": agent}
    cwd = _normalize_optional_string(tool_input.get("cwd"))
    if cwd is not None:
        try:
            resolved_cwd = _resolve_path(context.cwd, cwd, context=context)
        except ValueError as exc:
            return ValidationOutcome(False, str(exc))
        if not resolved_cwd.exists():
            return ValidationOutcome(False, f"cwd does not exist: {resolved_cwd}")
        if not resolved_cwd.is_dir():
            return ValidationOutcome(False, f"cwd is not a directory: {resolved_cwd}")
        normalized["cwd"] = str(resolved_cwd)
    for key in ("model", "model_route"):
        value = _normalize_optional_string(tool_input.get(key))
        if value is not None:
            normalized[key] = value
    permission_mode = _normalize_optional_string(tool_input.get("permission_mode"))
    if permission_mode is not None:
        try:
            normalized["permission_mode"] = PermissionMode(permission_mode).value
        except ValueError:
            return ValidationOutcome(False, f"Invalid permission_mode: {permission_mode}")
    isolation = _normalize_optional_string(tool_input.get("isolation"))
    if isolation is not None:
        try:
            normalized["isolation"] = IsolationMode(isolation).value
        except ValueError:
            return ValidationOutcome(False, f"Invalid isolation: {isolation}")
    max_turns = tool_input.get("max_turns")
    if max_turns is not None:
        if not isinstance(max_turns, int) or max_turns < 1:
            return ValidationOutcome(False, "max_turns must be a positive integer")
        normalized["max_turns"] = max_turns
    return ValidationOutcome(True, updated_input=normalized)


async def team_spawn_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    plane = _team_control_plane(context)
    if plane is None:
        return _structured_error("unavailable", "Runtime team control plane is not configured")
    try:
        member = await plane.register_member(
            session_id=context.session_id,
            extensions=context.private_context.extensions,
            name=tool_input["name"],
            agent_name=tool_input["agent"],
            execution_defaults=_team_member_execution_defaults(context, tool_input),
        )
        return {
            "team_id": member.team_id,
            "member_id": member.member_id,
            "name": member.name,
            "agent": member.agent_name,
            "status": member.status.value,
        }
    except TeamControlError as exc:
        return _team_error_result(exc)


def validate_team_send_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    to = _normalize_optional_string(tool_input.get("to"))
    message = _normalize_optional_string(tool_input.get("message"))
    if to is None:
        return ValidationOutcome(False, "to must be non-empty")
    if message is None:
        return ValidationOutcome(False, "message must be non-empty")
    return ValidationOutcome(True, updated_input={"to": to, "message": message})


async def team_send_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    bus = _team_message_bus(context)
    if bus is None:
        return _structured_error("unavailable", "Runtime team message bus is not configured")
    try:
        envelope = await bus.send_public_message(
            session_id=context.session_id,
            extensions=context.private_context.extensions,
            to=tool_input["to"],
            message=tool_input["message"],
        )
    except TeamControlError as exc:
        return _team_error_result(exc)
    return {
        "team_id": envelope.team_id,
        "message_id": envelope.message_id,
        "to": envelope.public_to,
        "delivery_count": len(envelope.deliveries),
        "queued": bool(envelope.deliveries),
    }


async def team_delete_tool(
    _: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    plane = _team_control_plane(context)
    if plane is None:
        return _structured_error("unavailable", "Runtime team control plane is not configured")
    try:
        team = await plane.delete_team(
            session_id=context.session_id,
            extensions=context.private_context.extensions,
        )
    except TeamControlError as exc:
        return _team_error_result(exc)
    return {"team_id": team.team_id, "deleted": True}


def validate_team_respond_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    workflow_id = _normalize_optional_string(tool_input.get("workflow_id"))
    action = _normalize_optional_string(tool_input.get("action"))
    if workflow_id is None:
        return ValidationOutcome(False, "workflow_id must be non-empty")
    if action is None:
        return ValidationOutcome(False, "action must be non-empty")
    normalized: dict[str, Any] = {"workflow_id": workflow_id, "action": action}
    payload = tool_input.get("payload")
    if payload is not None:
        if not isinstance(payload, dict):
            return ValidationOutcome(False, "payload must be an object")
        normalized["payload"] = payload
    return ValidationOutcome(True, updated_input=normalized)


async def team_respond_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    workflows = _team_workflow_service(context)
    if workflows is None:
        return _structured_error("unavailable", "Runtime team workflow service is not configured")
    try:
        record = await workflows.respond_model(
            session_id=context.session_id,
            extensions=context.private_context.extensions,
            workflow_id=tool_input["workflow_id"],
            action=tool_input["action"],
            payload=tool_input.get("payload"),
        )
    except TeamWorkflowError as exc:
        return _structured_error(exc.code, str(exc), **exc.details)
    return workflow_record_to_payload(record)


def _team_error_result(exc: TeamControlError) -> ExecutionResult[dict[str, Any]]:
    return _structured_error(exc.code, str(exc), **exc.details)


def _context_team_id(context: ToolContext) -> str | None:
    team_id = context.private_context.extensions.get("team_id")
    return _normalize_optional_string(team_id)


def _team_control_plane(context: ToolContext):
    services = context.runtime_services
    if services is None:
        return None
    return services.resolve_team_control_plane()


def _team_message_bus(context: ToolContext):
    services = context.runtime_services
    if services is None:
        return None
    return services.resolve_team_message_bus()


def _team_workflow_service(context: ToolContext):
    services = context.runtime_services
    if services is None:
        return None
    return services.resolve_team_workflows()


def _team_member_execution_defaults(context: ToolContext, tool_input: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "cwd": tool_input.get("cwd") or str(context.cwd),
    }
    model = _normalize_optional_string(tool_input.get("model"))
    if model is not None:
        defaults["model"] = model
    model_route = _normalize_optional_string(tool_input.get("model_route"))
    if model_route is not None:
        defaults["model_route"] = model_route
    elif context.private_context.resolved_model_route is not None:
        defaults["model_route"] = context.private_context.resolved_model_route
    permission_mode = _normalize_optional_string(tool_input.get("permission_mode"))
    if permission_mode is not None:
        defaults["permission_mode"] = permission_mode
    elif context.permission_context is not None and getattr(context.permission_context, "mode", None) is not None:
        defaults["permission_mode"] = context.permission_context.mode.value
    isolation = _normalize_optional_string(tool_input.get("isolation"))
    if isolation is not None:
        defaults["isolation"] = isolation
    max_turns = tool_input.get("max_turns")
    if max_turns is not None:
        defaults["max_turns"] = max_turns
    return defaults


__all__ = [
    "team_create_tool",
    "team_delete_tool",
    "team_respond_tool",
    "team_send_tool",
    "team_spawn_tool",
    "validate_team_create_tool",
    "validate_team_respond_tool",
    "validate_team_send_tool",
    "validate_team_spawn_tool",
]
