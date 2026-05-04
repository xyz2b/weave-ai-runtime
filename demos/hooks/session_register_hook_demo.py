from __future__ import annotations

from demos._shared.common import (
    AllowAllPermissionService,
    close_session_and_wait_for_background_memory,
    extract_tool_result,
    print_json,
    run_async,
    run_session_prompt,
    temporary_workspace,
)
from weavert.testing import ScriptedModelClient, text_batch, tool_call_batch

from weavert import AgentDefinition, ToolDefinition, ToolTraits
from weavert.hooks import (
    HookInventoryQuery,
    match_tool,
    on_pre_tool_use,
    rewrite_input,
)
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime


def _echo_tool():
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
    with temporary_workspace() as workspace:
        client = ScriptedModelClient(
            [
                tool_call_batch(
                    request_id="req-hook-1",
                    tool_name="echo",
                    tool_input={"value": "original"},
                    call_id="call-echo",
                ),
                text_batch(
                    request_id="req-hook-2",
                    text="session hook demo complete",
                ),
            ]
        )
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                model_client=client,
                builtins=BuiltinPackConfig(
                    tools_enabled=False,
                    agents_enabled=False,
                    skills_enabled=False,
                    extra_agents=[
                        AgentDefinition(
                            name="main-router",
                            description="Routes the hook demo.",
                            prompt="Use the echo tool once.",
                            tools=("*",),
                        )
                    ],
                    extra_tools=[_echo_tool()],
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        session = runtime.create_session(session_id="demo-hook")
        try:
            handle = session.register_hook(
                on_pre_tool_use(
                    lambda _payload: rewrite_input({"value": "hook-updated"}),
                    match=match_tool("echo"),
                    effects=(rewrite_input,),
                )
            )
            messages = run_async(run_session_prompt(session, "Rewrite the next echo tool call."))
            tool_result = extract_tool_result(messages, "call-echo")
            inventory = session.list_hooks(HookInventoryQuery(phase="PreToolUse"))

            assert tool_result == {"echo": "hook-updated"}
            assert messages[-1].text == "session hook demo complete"
            assert len(inventory) == 1

            print("demo: session.register_hook")
            print(f"hook activation: {handle.activation_state.value}")
            print(f"registered hooks: {len(inventory)}")
            print_json("tool result", tool_result)
            print("status: ok")
        finally:
            run_async(
                close_session_and_wait_for_background_memory(
                    session,
                    memory_service=runtime.services.memory,
                )
            )


if __name__ == "__main__":
    main()
