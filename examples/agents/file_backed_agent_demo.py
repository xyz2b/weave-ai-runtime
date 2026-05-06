from __future__ import annotations

from examples._shared.common import demo_workspace, discovery_source, run_async, temporary_workspace
from weavert_testing import ScriptedModelClient, text_batch

from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime

FIXTURE_ROOT = demo_workspace("agents", "workspace")


def _agent_batch(request):
    assert request.agent is not None
    assert request.agent.name == "release-reviewer"
    return text_batch(
        request_id="req-agent-1",
        text="release reviewer approved the demo workspace",
    )


def main() -> None:
    with temporary_workspace(FIXTURE_ROOT) as workspace:
        client = ScriptedModelClient([_agent_batch])
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                model_client=client,
                discovery_sources=(discovery_source(workspace),),
                builtins=BuiltinPackConfig(
                    tools_enabled=False,
                    agents_enabled=False,
                    skills_enabled=False,
                ),
            )
        )

        messages = run_async(
            runtime.run_prompt(
                "Give a release verdict for this workspace.",
                session_id="demo-agent",
                agent_name="release-reviewer",
            )
        )
        agent = runtime.kernel.agent_registry.get("release-reviewer")

        assert agent is not None
        assert client.requests[0].turn_context.agent_name == "release-reviewer"
        assert messages[-1].text == "release reviewer approved the demo workspace"

        print("demo: file-backed agent")
        print(f"agent: {agent.name}")
        print(f"description: {agent.description}")
        print(f"assistant reply: {messages[-1].text}")
        print("status: ok")


if __name__ == "__main__":
    main()
