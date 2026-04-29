from __future__ import annotations

from demos._shared.common import (
    AllowAllPermissionService,
    demo_workspace,
    discovery_source,
    extract_tool_result,
    run_async,
    temporary_workspace,
)
from demos._shared.scripted_model import ScriptedModelClient, text_batch, tool_call_batch

from weavert import ToolDefinition, ToolTraits
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime

FIXTURE_ROOT = demo_workspace("skills", "workspace")


def _echo_tool() -> ToolDefinition:
    return ToolDefinition(
        name="echo",
        description="Return the provided value.",
        input_schema={
            "type": "object",
            "properties": {
                "value": {"type": "string"},
            },
            "required": ["value"],
            "additionalProperties": False,
        },
        traits=ToolTraits(read_only=True, concurrency_safe=True),
        execute=lambda tool_input, _context: {"echo": tool_input["value"]},
    )


def main() -> None:
    with temporary_workspace(FIXTURE_ROOT) as workspace:
        client = ScriptedModelClient(
            [
                tool_call_batch(
                    request_id="req-inline-skill-1",
                    tool_name="skill",
                    tool_input={"skill": "rewrite-inline"},
                    call_id="call-skill",
                ),
                tool_call_batch(
                    request_id="req-inline-skill-2",
                    tool_name="echo",
                    tool_input={"value": "original"},
                    call_id="call-echo-rewritten",
                ),
                text_batch(
                    request_id="req-inline-skill-3",
                    text="first turn complete",
                ),
                tool_call_batch(
                    request_id="req-inline-skill-4",
                    tool_name="echo",
                    tool_input={"value": "original"},
                    call_id="call-echo-original",
                ),
                text_batch(
                    request_id="req-inline-skill-5",
                    text="second turn complete",
                ),
            ]
        )
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                model_client=client,
                discovery_sources=(discovery_source(workspace),),
                builtins=BuiltinPackConfig(
                    extra_tools=[_echo_tool()],
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        first_turn = run_async(
            runtime.run_prompt(
                "Use the rewrite-inline skill before you call echo.",
                session_id="inline-skill-hook-demo",
            )
        )
        second_turn = run_async(
            runtime.run_prompt(
                "Call echo again without using any skill.",
                session_id="inline-skill-hook-demo",
            )
        )
        skill = runtime.kernel.skill_registry.get("rewrite-inline")
        first_result = extract_tool_result(first_turn, "call-echo-rewritten")
        second_result = extract_tool_result(second_turn, "call-echo-original")

        assert skill is not None
        assert skill.execution_context.value == "inline"
        assert skill.hooks
        assert first_result == {"echo": "rewritten"}
        assert second_result == {"echo": "original"}

        print("demo: inline skill hooks")
        print(f"skill: {skill.name}")
        print(f"first turn result: {first_result['echo']}")
        print(f"second turn result: {second_result['echo']}")
        print("status: ok")


if __name__ == "__main__":
    main()
