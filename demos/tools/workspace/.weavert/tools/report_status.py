from __future__ import annotations

from weavert.definitions import ToolDefinition, ToolTraits


def execute(tool_input, context):
    _ = context
    return {
        "discovery_root": ".weavert/tools",
        "service": tool_input["service"],
        "workspace_kind": "temporary-copy",
    }


TOOL_DEFINITION = ToolDefinition(
    name="report_status",
    description="Report a deterministic demo payload from a file-backed tool.",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string"},
        },
        "required": ["service"],
        "additionalProperties": False,
    },
    traits=ToolTraits(read_only=True, concurrency_safe=True),
    execute=execute,
)
