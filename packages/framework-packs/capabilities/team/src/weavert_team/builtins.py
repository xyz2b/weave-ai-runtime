from __future__ import annotations

from weavert.builtins.definition_helpers import static_semantics
from weavert.definitions import (
    DefinitionOrigin,
    DefinitionSource,
    ToolClassifierInput,
    ToolDefinition,
    ToolPresentationEmphasis,
    ToolRiskLevel,
    ToolUsePresentation,
    ValidationOutcome,
)
from .tool_impls import (
    team_create_tool,
    team_delete_tool,
    team_respond_tool,
    team_send_tool,
    team_spawn_tool,
    validate_team_create_tool,
    validate_team_respond_tool,
    validate_team_send_tool,
    validate_team_spawn_tool,
)


def team_builtin_tools() -> tuple[ToolDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        ToolDefinition(
            name="team_create",
            aliases=("TeamCreate",),
            description="Create or reuse the caller's active runtime-owned team.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "team_id": {"type": "string"},
                    "leader_session_id": {"type": "string"},
                    "name": {"type": ["string", "null"]},
                    "created": {"type": "boolean"},
                },
                "required": ["team_id", "leader_session_id", "name", "created"],
                "additionalProperties": True,
            },
            semantics=static_semantics(
                read_only=False,
                concurrency_safe=False,
                tool_use_presentation=lambda _tool_input, _context: ToolUsePresentation(
                    title="Create team",
                    emphasis=ToolPresentationEmphasis.NORMAL,
                ),
                classifier_input=lambda _tool_input, _context: ToolClassifierInput(
                    operation="team_create",
                    summary="Create or reuse team",
                    risk_level=ToolRiskLevel.WRITE,
                    side_effects=True,
                    tags=("team", "lifecycle"),
                ),
            ),
            validate_input=validate_team_create_tool,
            execute=team_create_tool,
            runtime_execution_class="privileged",
            origin=origin,
        ),
        ToolDefinition(
            name="team_spawn",
            aliases=("TeamSpawn",),
            description="Spawn a persistent teammate in the caller's active runtime-owned team.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "agent": {"type": "string"},
                    "cwd": {"type": "string"},
                    "model": {"type": "string"},
                    "model_route": {"type": "string"},
                    "permission_mode": {
                        "type": "string",
                        "enum": [
                            "default",
                            "plan",
                            "acceptEdits",
                            "bypassPermissions",
                            "dontAsk",
                            "auto",
                            "bubble",
                        ],
                    },
                    "isolation": {"type": "string", "enum": ["none", "worktree", "remote"]},
                    "max_turns": {"type": "integer", "minimum": 1},
                },
                "required": ["name", "agent"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "team_id": {"type": "string"},
                    "member_id": {"type": "string"},
                    "name": {"type": "string"},
                    "agent": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["team_id", "member_id", "name", "agent", "status"],
                "additionalProperties": True,
            },
            semantics=static_semantics(
                read_only=False,
                concurrency_safe=False,
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Spawn teammate",
                    subtitle=tool_input.get("name"),
                    emphasis=ToolPresentationEmphasis.NORMAL,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="team_spawn",
                    summary=f"Spawn teammate: {tool_input['name']}",
                    risk_level=ToolRiskLevel.DELEGATE,
                    side_effects=True,
                    tags=("team", "delegate"),
                ),
            ),
            validate_input=validate_team_spawn_tool,
            execute=team_spawn_tool,
            runtime_execution_class="privileged",
            origin=origin,
        ),
        ToolDefinition(
            name="team_send",
            aliases=("TeamSend",),
            description="Send a structured message to the leader, a teammate, or the whole active team.",
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["to", "message"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "team_id": {"type": "string"},
                    "message_id": {"type": "string"},
                    "to": {"type": "string"},
                    "delivery_count": {"type": "integer", "minimum": 0},
                    "queued": {"type": "boolean"},
                },
                "required": ["team_id", "message_id", "to", "delivery_count", "queued"],
                "additionalProperties": True,
            },
            semantics=static_semantics(
                read_only=False,
                concurrency_safe=False,
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Send team message",
                    subtitle=tool_input.get("to"),
                    emphasis=ToolPresentationEmphasis.NORMAL,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="team_send",
                    summary=f"Send team message: {tool_input['to']}",
                    risk_level=ToolRiskLevel.WRITE,
                    side_effects=True,
                    tags=("team", "message"),
                ),
            ),
            validate_input=validate_team_send_tool,
            execute=team_send_tool,
            runtime_execution_class="privileged",
            origin=origin,
        ),
        ToolDefinition(
            name="team_respond",
            aliases=("TeamRespond",),
            description="Resolve a pending team control workflow with a typed response action.",
            input_schema={
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "action": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["workflow_id", "action"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "team_id": {"type": "string"},
                    "workflow_kind": {"type": "string"},
                    "status": {"type": "string"},
                    "allowed_actions": {"type": "array", "items": {"type": "string"}},
                    "terminal": {"type": "boolean"},
                },
                "required": ["workflow_id", "team_id", "workflow_kind", "status", "allowed_actions", "terminal"],
                "additionalProperties": True,
            },
            semantics=static_semantics(
                read_only=False,
                concurrency_safe=False,
                tool_use_presentation=lambda tool_input, _context: ToolUsePresentation(
                    title="Respond to workflow",
                    subtitle=tool_input.get("workflow_id"),
                    emphasis=ToolPresentationEmphasis.NORMAL,
                ),
                classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="team_respond",
                    summary=f"Respond to team workflow: {tool_input['workflow_id']}",
                    risk_level=ToolRiskLevel.WRITE,
                    side_effects=True,
                    tags=("team", "workflow"),
                ),
            ),
            validate_input=validate_team_respond_tool,
            execute=team_respond_tool,
            runtime_execution_class="privileged",
            origin=origin,
        ),
        ToolDefinition(
            name="team_delete",
            aliases=("TeamDelete",),
            description="Delete the caller's active runtime-owned team and tear down teammate state.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "team_id": {"type": "string"},
                    "deleted": {"type": "boolean"},
                },
                "required": ["team_id", "deleted"],
                "additionalProperties": True,
            },
            semantics=static_semantics(
                read_only=False,
                concurrency_safe=False,
                tool_use_presentation=lambda _tool_input, _context: ToolUsePresentation(
                    title="Delete team",
                    emphasis=ToolPresentationEmphasis.NORMAL,
                ),
                classifier_input=lambda _tool_input, _context: ToolClassifierInput(
                    operation="team_delete",
                    summary="Delete active team",
                    risk_level=ToolRiskLevel.WRITE,
                    side_effects=True,
                    tags=("team", "lifecycle"),
                ),
            ),
            execute=team_delete_tool,
            runtime_execution_class="privileged",
            origin=origin,
        ),
    )


__all__ = ["team_builtin_tools"]
