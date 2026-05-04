from __future__ import annotations

from demos._shared.common import (
    AllowAllPermissionService,
    demo_workspace,
    discovery_source,
    run_async,
    temporary_workspace,
)
from weavert.testing import ScriptedModelClient, text_batch

from weavert import AgentDefinition
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime

FIXTURE_ROOT = demo_workspace("skills", "workspace")


def _skill_batch(request):
    assert request.agent is not None
    assert request.agent.name == "skill-writer"
    assert any("runtime-extension-demos" in message.text for message in request.messages)
    return text_batch(
        request_id="req-skill-1",
        text="release summary: runtime-extension-demos is ready",
    )


def main() -> None:
    with temporary_workspace(FIXTURE_ROOT) as workspace:
        client = ScriptedModelClient([_skill_batch])
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
                            name="skill-writer",
                            description="Drafts short release summaries.",
                            prompt="Write one-sentence release summaries.",
                        )
                    ],
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        result = run_async(
            runtime.skill_executor.execute(
                "release-summary",
                arguments=("runtime-extension-demos",),
                session_id="demo-skill",
                cwd=workspace,
            )
        )

        assert result.skill_name == "release-summary"
        assert result.mode.value == "fork"
        assert result.agent_result is not None
        assert result.agent_result.agent_name == "skill-writer"
        assert result.agent_result.messages[-1].text == "release summary: runtime-extension-demos is ready"

        print("demo: file-backed skill")
        print(f"skill: {result.skill_name}")
        print(f"mode: {result.mode.value}")
        print(f"child agent: {result.agent_result.agent_name}")
        print(f"assistant reply: {result.agent_result.messages[-1].text}")
        print("status: ok")


if __name__ == "__main__":
    main()
