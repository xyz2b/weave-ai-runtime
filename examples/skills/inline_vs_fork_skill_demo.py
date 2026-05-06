from __future__ import annotations

from pathlib import Path

from examples._shared.common import run_async, temporary_workspace

from weavert import AgentDefinition, SkillDefinition
from weavert.definitions import SkillExecutionContext
from weavert.permissions import AllowAllPermissionService
from weavert.runtime_kernel import (
    BuiltinPackConfig,
    RuntimeConfig,
    RuntimeDistribution,
    assemble_runtime,
)
from weavert.testing import ScriptedModelClient, text_batch

INLINE_TEXT = "inline note for demo-user"
FORK_SUMMARY = "forked child wrote a scoped summary"


def _fork_batch(request):
    assert request.agent is not None
    assert request.agent.name == "skill-writer"
    return text_batch(
        request_id="req-inline-vs-fork-1",
        text=FORK_SUMMARY,
    )


def main() -> None:
    with temporary_workspace() as workspace:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=Path(workspace),
                distribution=RuntimeDistribution.CORE,
                model_client=ScriptedModelClient([_fork_batch]),
                builtins=BuiltinPackConfig(
                    extra_agents=[
                        AgentDefinition(
                            name="skill-writer",
                            description="Writes one-line skill outputs.",
                            prompt="Write one concise summary.",
                        )
                    ],
                    extra_skills=[
                        SkillDefinition(
                            name="inline-note",
                            description="Return an inline system note.",
                            content="inline note for ${ARG1}",
                            execution_context=SkillExecutionContext.INLINE,
                        ),
                        SkillDefinition(
                            name="fork-note",
                            description="Delegate the note to a child agent.",
                            content="fork note for ${ARG1}",
                            execution_context=SkillExecutionContext.FORK,
                            agent="skill-writer",
                        ),
                    ],
                ),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()

        inline_result = run_async(
            runtime.skill_executor.execute(
                "inline-note",
                arguments=("demo-user",),
                session_id="inline-vs-fork-demo",
                cwd=Path(workspace),
            )
        )
        fork_result = run_async(
            runtime.skill_executor.execute(
                "fork-note",
                arguments=("demo-user",),
                session_id="inline-vs-fork-demo",
                cwd=Path(workspace),
            )
        )

        assert inline_result.mode == SkillExecutionContext.INLINE
        assert inline_result.injected_messages[0].text == INLINE_TEXT
        assert fork_result.mode == SkillExecutionContext.FORK
        assert fork_result.agent_result is not None
        assert fork_result.agent_result.messages[-1].text == FORK_SUMMARY

        print("demo: inline vs fork skill")
        print(f"inline result: {inline_result.injected_messages[0].text}")
        print(f"fork child summary: {fork_result.agent_result.messages[-1].text}")
        print("status: ok")


if __name__ == "__main__":
    main()
