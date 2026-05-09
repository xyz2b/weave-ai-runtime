# Add a Tool

## Who is this for?

Users adding a reusable execution capability such as file inspection, API lookup, or structured project analysis.

## Prerequisites

- a starter-generated or otherwise working project
- a `.weavert/tools/` directory
- a capability that benefits from structured input and output

## The file-backed authoring rule

The supported file-backed path is a Python module under `.weavert/tools/`.
JSON and YAML tool definition files are not the default supported execution path here.

## Steps

1. Create `.weavert/tools/check_file.py`
2. Export a concrete `ToolDefinition`
3. Keep the schema explicit and the behavior narrow
4. Add traits and permission checks that match reality
5. Run your project or a focused example to validate the tool contract

Minimal example:

```python
from weavert import ToolDefinition, ToolTraits


def execute(tool_input, context):
    path = context.cwd / tool_input["file_name"]
    return {"exists": path.exists(), "path": str(path)}


TOOL_DEFINITION = ToolDefinition(
    name="check_file",
    description="Check whether a file exists under the current workspace.",
    input_schema={
        "type": "object",
        "properties": {"file_name": {"type": "string"}},
        "required": ["file_name"],
        "additionalProperties": False,
    },
    traits=ToolTraits(read_only=True, concurrency_safe=True),
    execute=execute,
)
```

## Stable fields worth using

The most important fields are usually:

- `name`
- `description`
- `input_schema`
- `traits`
- `validate_input`
- `check_permissions`
- `execute`

## Canonical guarded-tool pattern

When a tool needs stronger safety, the usual combination is:

1. `validate_input`
   - reject malformed or incomplete requests early
2. `check_permissions`
   - let the runtime or host permission path participate explicitly
3. accurate `traits`
   - mark read-only, destructive, or concurrency-sensitive behavior honestly

This is the best first step before embedding the tool inside a larger workflow.

## Schema guidance for live OpenAI routes

If the tool may run through the bundled OpenAI path, keep these authoring rules in mind:

- prefer explicit object schemas
- prefer explicit array item schemas
- keep `additionalProperties` closed unless you truly need open objects
- avoid schema-valued `additionalProperties` for the bundled strict-tool export path

The transport layer may normalize optional fields for strict provider compatibility, but your runtime-level authoring model should still remain explicit and small.

## Expected result

The runtime discovers your tool from `.weavert/tools/`, exposes it to eligible agents, and can validate inputs before execution.

## Next step

Run `python3 -B -m examples.tools.file_backed_tool_demo` or `python3 -B -m examples.tools.guarded_tool_demo` to validate the seam in isolation.

## See also

- `../concepts/tools-agents-skills.md`
- `../guides/testing-and-observability.md`
- `../deep-dives/weavert-definition-authoring-guide.md`
