from __future__ import annotations

from examples._shared.common import (
    AllowAllPermissionService,
    demo_workspace,
    discovery_source,
    extract_tool_result,
    print_json,
    run_async,
    temporary_workspace,
)
from weavert_testing import ScriptedModelClient, text_batch, tool_call_batch

from weavert import AgentDefinition
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime

FIXTURE_ROOT = demo_workspace("tools", "workspace")


def main() -> None:
    with temporary_workspace(FIXTURE_ROOT) as workspace:
        client = ScriptedModelClient(
            [
                tool_call_batch(
                    request_id="req-tool-1",
                    tool_name="report_status",
                    tool_input={"service": "runtime-extension-demos"},
                    call_id="call-report-status",
                ),
                text_batch(
                    request_id="req-tool-2",
                    text="file-backed tool demo complete",
                ),
            ]
        )
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                model_client=client,
                discovery_sources=(discovery_source(workspace),),
                builtins=BuiltinPackConfig(
                    tools_enabled=False,
                    agents_enabled=False,
                    skills_enabled=False,
                    extra_agents=[
                        AgentDefinition(
                            name="main-router",
                            description="Routes the tool demo.",
                            prompt="Use the available tool to inspect the project.",
                            tools=("*",),
                        )
                    ],
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        messages = run_async(runtime.run_prompt("Inspect the demo tool.", session_id="demo-tool"))
        tool_result = extract_tool_result(messages, "call-report-status")
        first_request = client.requests[0]

        assert first_request.turn_context.available_tools == ("report_status",)
        assert tool_result == {
            "discovery_root": ".weavert/tools",
            "service": "runtime-extension-demos",
            "workspace_kind": "temporary-copy",
        }
        assert messages[-1].text == "file-backed tool demo complete"

        print("demo: file-backed tool")
        print(f"available tools: {', '.join(first_request.turn_context.available_tools)}")
        print_json("tool result", tool_result)
        print("status: ok")


if __name__ == "__main__":
    main()
