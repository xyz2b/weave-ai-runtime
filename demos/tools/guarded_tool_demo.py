from __future__ import annotations

from pathlib import Path

from demos._shared.common import run_async, temporary_workspace

from weavert import ToolDefinition, ToolTraits, ValidationOutcome
from weavert.definitions import (
    PermissionBehavior,
    PermissionDecision,
    ToolClassifierInput,
    ToolExecutionSemantics,
    ToolRiskLevel,
)
from weavert.permissions import (
    AllowAllPermissionService,
    PermissionContext,
    ReadOnlyPermissionService,
)
from weavert.registries import ToolRegistry
from weavert.runtime_services import RuntimeServices
from weavert.tool_runtime import ToolCall, ToolContext, ToolScheduler


def _guarded_tool() -> ToolDefinition:
    async def validate_input(tool_input, _context):
        value = tool_input["value"].strip()
        if not value:
            return ValidationOutcome(False, "value must not be blank")
        return ValidationOutcome(
            True,
            updated_input={"value": value, "mode": tool_input["mode"]},
        )

    async def check_permissions(tool_input, _context):
        if tool_input["mode"] == "write":
            return PermissionDecision(PermissionBehavior.ASK, "write approval required")
        return PermissionDecision(PermissionBehavior.ALLOW)

    async def execute(tool_input, _context):
        return {
            "guard": "passed",
            "mode": tool_input["mode"],
            "value": tool_input["value"],
        }

    return ToolDefinition(
        name="guarded_echo",
        description="Validate schema handling, permission policy, and stable tool outcomes.",
        input_schema={
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "mode": {"type": "string", "enum": ["read", "write"]},
            },
            "required": ["value", "mode"],
            "additionalProperties": False,
        },
        semantics=ToolExecutionSemantics(
            is_read_only=lambda tool_input, _context: tool_input["mode"] == "read",
            is_concurrency_safe=lambda _tool_input, _context: True,
            to_classifier_input=lambda tool_input, _context: ToolClassifierInput(
                operation=f"guarded_echo:{tool_input['mode']}",
                summary=f"Guarded echo in {tool_input['mode']} mode",
                risk_level=(
                    ToolRiskLevel.READ
                    if tool_input["mode"] == "read"
                    else ToolRiskLevel.WRITE
                ),
                side_effects=tool_input["mode"] == "write",
                tags=("demo", "guarded"),
            ),
        ),
        traits=ToolTraits(read_only=False, concurrency_safe=True),
        validate_input=validate_input,
        check_permissions=check_permissions,
        execute=execute,
    )


async def _run_case(permission_service, payload):
    registry = ToolRegistry()
    registry.register(_guarded_tool())
    context = ToolContext(
        session_id="guarded-tool-demo",
        turn_id="guarded-tool-turn",
        agent_name="main-router",
        cwd=Path.cwd(),
        tool_registry=registry,
        runtime_services=RuntimeServices(permissions=permission_service),
        permission_context=PermissionContext(session_id="guarded-tool-demo"),
    )
    return (
        await ToolScheduler(registry).run(
            [ToolCall("call-guarded-tool", "guarded_echo", payload)],
            context,
        )
    )[0]


def main() -> None:
    with temporary_workspace() as workspace:
        schema_invalid = run_async(_run_case(ReadOnlyPermissionService(), {"mode": "write"}))
        input_invalid = run_async(
            _run_case(
                AllowAllPermissionService(),
                {"value": "   ", "mode": "read"},
            )
        )
        denied = run_async(
            _run_case(
                ReadOnlyPermissionService(),
                {"value": "ship", "mode": "write"},
            )
        )
        allowed = run_async(
            _run_case(
                AllowAllPermissionService(),
                {"value": "ship", "mode": "write"},
            )
        )

        assert workspace.exists()
        assert schema_invalid.status.value == "error"
        assert "required field missing" in (schema_invalid.error or "")
        assert input_invalid.status.value == "error"
        assert input_invalid.error == "value must not be blank"
        assert denied.status.value == "denied"
        assert denied.error == "Read-only preset blocks write requests"
        assert allowed.status.value == "success"
        assert allowed.output == {
            "guard": "passed",
            "mode": "write",
            "value": "ship",
        }

        print("demo: guarded tool")
        print("schema validation: rejected invalid input")
        print("input validation: rejected blank value")
        print("permission path: denied")
        print("permission path: allowed")
        print("status: ok")


if __name__ == "__main__":
    main()
