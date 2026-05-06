from __future__ import annotations

from pathlib import Path

from examples._shared.common import run_async, temporary_workspace

from weavert import AgentDefinition, ToolDefinition, ToolTraits
from weavert.hooks import (
    HookDispatchTraceQuery,
    HookInventoryQuery,
    match_tool,
    rewrite_input,
)
from weavert.hosts import SdkHostRuntime
from weavert.permissions import AllowAllPermissionService
from weavert.runtime_kernel import (
    BuiltinPackConfig,
    RuntimeConfig,
    RuntimeDistribution,
    assemble_runtime,
)
from weavert.testing import ScriptedModelClient, extract_tool_result, text_batch, tool_call_batch


def _echo_tool() -> ToolDefinition:
    return ToolDefinition(
        name="echo",
        description="Return the provided value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
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
                    request_id="req-host-hook-1",
                    tool_name="echo",
                    tool_input={"value": "original"},
                    call_id="call-host-hook-echo",
                ),
                text_batch(
                    request_id="req-host-hook-2",
                    text="host hook demo complete",
                ),
            ]
        )
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=Path(workspace),
                distribution=RuntimeDistribution.CORE,
                model_client=client,
                builtins=BuiltinPackConfig(
                    tools_enabled=False,
                    agents_enabled=False,
                    skills_enabled=False,
                    extra_agents=[
                        AgentDefinition(
                            name="main-router",
                            description="Routes the host hook demo.",
                            prompt="Use the echo tool once.",
                            tools=("*",),
                        )
                    ],
                    extra_tools=[_echo_tool()],
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        host = SdkHostRuntime(name="sdk")
        bound = runtime.bind_host(host)
        bound.hooks.on_pre_tool_use(
            lambda _payload: rewrite_input({"value": "from-host"}),
            match=match_tool("echo"),
            effects=(rewrite_input,),
        )
        run_async(bound.startup())
        run_async(bound.ready())
        session = bound.sessions.create_session(session_id="host-hook-demo")
        report = run_async(
            bound.sessions.run_prompt_report_in_session(
                session,
                "Call echo once.",
            )
        )
        tool_result = extract_tool_result(report.messages, "call-host-hook-echo")
        inventory = bound.hooks.list_hooks(
            HookInventoryQuery(session_id="host-hook-demo", phase="PreToolUse")
        )
        traces = bound.hooks.list_hook_dispatch_traces(
            HookDispatchTraceQuery(session_id="host-hook-demo", phase="PreToolUse")
        )

        assert tool_result == {"echo": "from-host"}
        assert len(inventory) == 1
        assert inventory[0].activation_state.value == "active"
        assert len(traces) == 1

        run_async(session.close())
        run_async(bound.shutdown())

        print("demo: bound.hooks.on_pre_tool_use")
        print("hook source: host")
        print(f"hook activation: {inventory[0].activation_state.value}")
        print(f"dispatch traces: {len(traces)}")
        print("status: ok")


if __name__ == "__main__":
    main()
