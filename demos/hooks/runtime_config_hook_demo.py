from __future__ import annotations

from demos._shared.common import (
    AllowAllPermissionService,
    close_session_and_wait_for_background_memory,
    extract_tool_result,
    run_async,
    run_session_prompt,
    temporary_workspace,
)
from demos._shared.scripted_model import ScriptedModelClient, text_batch, tool_call_batch

from weavert import AgentDefinition, ToolDefinition, ToolTraits
from weavert.hooks import HookInventoryQuery
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime


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


async def _close_sessions(memory_service, *sessions) -> None:
    for session in sessions:
        await close_session_and_wait_for_background_memory(
            session,
            memory_service=memory_service,
        )


def main() -> None:
    with temporary_workspace() as workspace:
        client = ScriptedModelClient(
            [
                tool_call_batch(
                    request_id="req-runtime-hook-1",
                    tool_name="echo",
                    tool_input={"value": "original"},
                    call_id="call-echo-session-one",
                ),
                text_batch(
                    request_id="req-runtime-hook-2",
                    text="session one complete",
                ),
                tool_call_batch(
                    request_id="req-runtime-hook-3",
                    tool_name="echo",
                    tool_input={"value": "original"},
                    call_id="call-echo-session-two",
                ),
                text_batch(
                    request_id="req-runtime-hook-4",
                    text="session two complete",
                ),
            ]
        )
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                model_client=client,
                hooks={
                    "handlers": {
                        "rewrite_echo": {
                            "kind": "callback",
                            "binding": "rewrite_echo",
                        }
                    },
                    "registrations": [
                        {
                            "phase": "PreToolUse",
                            "match": {"target": "echo"},
                            "handler": {"ref": "rewrite_echo"},
                            "contract": {"effect_fields": ["updated_input", "metadata"]},
                        }
                    ],
                },
                builtins=BuiltinPackConfig(
                    tools_enabled=False,
                    agents_enabled=False,
                    skills_enabled=False,
                    extra_agents=[
                        AgentDefinition(
                            name="main-router",
                            description="Routes the runtime-config hook demo.",
                            prompt="Use the echo tool once.",
                            tools=("*",),
                        )
                    ],
                    extra_tools=[_echo_tool()],
                ),
            )
        )
        runtime.bind_hook_callback(
            "rewrite_echo",
            lambda _payload: {"updated_input": {"value": "runtime-default"}},
        )
        runtime.services.permissions = AllowAllPermissionService()

        session_one = runtime.create_session(session_id="runtime-config-hook-one")
        session_two = runtime.create_session(session_id="runtime-config-hook-two")
        try:
            session_one_messages = run_async(
                run_session_prompt(session_one, "Call echo once in the first session.")
            )
            session_two_messages = run_async(
                run_session_prompt(session_two, "Call echo once in the second session.")
            )
            session_one_result = extract_tool_result(
                session_one_messages,
                "call-echo-session-one",
            )
            session_two_result = extract_tool_result(
                session_two_messages,
                "call-echo-session-two",
            )
            session_one_inventory = session_one.list_hooks(HookInventoryQuery(phase="PreToolUse"))
            session_two_inventory = session_two.list_hooks(HookInventoryQuery(phase="PreToolUse"))

            assert session_one_result == {"echo": "runtime-default"}
            assert session_two_result == {"echo": "runtime-default"}
            assert len(session_one_inventory) == 1
            assert len(session_two_inventory) == 1
            assert session_one_inventory[0].source_kind.value == "runtime_config"
            assert session_two_inventory[0].source_kind.value == "runtime_config"
            assert session_one_inventory[0].parent_registration_id is not None
            assert session_two_inventory[0].parent_registration_id is not None

            print("demo: RuntimeConfig(hooks=...)")
            print(f"hook source: {session_one_inventory[0].source_kind.value}")
            print(f"session one hooks: {len(session_one_inventory)}")
            print(f"session two hooks: {len(session_two_inventory)}")
            print(f"session one result: {session_one_result['echo']}")
            print(f"session two result: {session_two_result['echo']}")
            print("status: ok")
        finally:
            run_async(_close_sessions(runtime.services.memory, session_one, session_two))


if __name__ == "__main__":
    main()
