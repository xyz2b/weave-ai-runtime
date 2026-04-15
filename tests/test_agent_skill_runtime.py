import asyncio
import json
from pathlib import Path

from claude_agent_runtime.agent_runtime import AgentInvocation, AgentRuntime
from claude_agent_runtime.definitions import (
    AgentDefinition,
    IsolationMode,
    SkillDefinition,
    SkillExecutionContext,
    ToolDefinition,
    ToolTraits,
)
from claude_agent_runtime.registries import AgentRegistry, SkillRegistry, ToolRegistry
from claude_agent_runtime.skill_runtime import SkillExecutor
from claude_agent_runtime.tasking import TaskManager
from claude_agent_runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, TurnEngine


class FakeModelClient:
    def __init__(self, event_batches: list[list[ModelStreamEvent]]) -> None:
        self._event_batches = [list(batch) for batch in event_batches]
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        batch = self._event_batches.pop(0)
        for event in batch:
            yield event


def test_agent_runtime_routes_and_skill_executor_supports_inline_and_fork(
    tmp_path: Path,
) -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="echo",
            description="echo values",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            execute=lambda tool_input, _: {"echo": tool_input["value"]},
        )
    )

    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentDefinition(name="main-router", description="router", prompt="route", tools=("*",))
    )
    agent_registry.register(
        AgentDefinition(
            name="verification",
            description="verify",
            prompt="verify",
            tools=("*",),
            isolation=IsolationMode.WORKTREE,
        )
    )
    agent_registry.register(
        AgentDefinition(name="general-purpose", description="general", prompt="general", tools=("*",))
    )

    skill_registry = SkillRegistry()
    skill_registry.register(
        SkillDefinition(
            name="inline-skill",
            description="inline",
            content="Inline skill for $ARGUMENTS in ${CLAUDE_SESSION_ID}",
        )
    )
    skill_registry.register(
        SkillDefinition(
            name="fork-skill",
            description="fork",
            content="Forked skill ${ARG1}",
            execution_context=SkillExecutionContext.FORK,
            agent="general-purpose",
        )
    )

    model_client = FakeModelClient(
        [
            [ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "direct answer"})],
            [ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "subagent answer"})],
            [ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "background answer"})],
            [ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "forked answer"})],
        ]
    )
    task_manager = TaskManager()
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        task_manager=task_manager,
    )
    agent_runtime = AgentRuntime(
        turn_engine=engine,
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        task_manager=task_manager,
    )
    skill_executor = SkillExecutor(skill_registry=skill_registry, agent_runtime=agent_runtime)

    direct_answer = asyncio.run(
        agent_runtime.invoke(
            AgentInvocation(
                agent_name="main-router",
                prompt="Answer directly",
                session_id="session",
                cwd=tmp_path,
            )
        )
    )
    assert direct_answer.messages[-1].text == "direct answer"

    direct_tool = asyncio.run(
        agent_runtime.invoke(
            AgentInvocation(
                agent_name="main-router",
                prompt='/tool echo {"value": "hi"}',
                session_id="session",
                cwd=tmp_path,
            )
        )
    )
    assert json.loads(direct_tool.messages[0].text)["echo"] == "hi"

    direct_skill = asyncio.run(
        agent_runtime.invoke(
            AgentInvocation(
                agent_name="main-router",
                prompt="/skill inline-skill src/app.py",
                session_id="session",
                cwd=tmp_path,
            )
        )
    )
    assert "src/app.py" in direct_skill.messages[0].text
    assert "session" in direct_skill.messages[0].text

    direct_subagent = asyncio.run(
        agent_runtime.invoke(
            AgentInvocation(
                agent_name="main-router",
                prompt="/agent verification run checks",
                session_id="session",
                cwd=tmp_path,
            )
        )
    )
    assert direct_subagent.messages[-1].text == "subagent answer"
    assert direct_subagent.isolation_mode == IsolationMode.WORKTREE

    background = asyncio.run(
        agent_runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="background run",
                session_id="session",
                cwd=tmp_path,
                background=True,
            )
        )
    )
    assert background.status == "running"
    assert background.background is True
    completed_background = asyncio.run(agent_runtime.wait_for_background(background.task_id))
    assert completed_background.notification is not None
    assert agent_runtime.notifications[-1].text == "Background agent 'verification' completed"

    inline = asyncio.run(
        skill_executor.execute(
            "inline-skill",
            arguments=["tests/test_file.py"],
            session_id="session",
            cwd=tmp_path,
        )
    )
    assert inline.injected_messages[0].text.endswith("tests/test_file.py in session")

    forked = asyncio.run(
        skill_executor.execute(
            "fork-skill",
            arguments=["ARG"],
            session_id="session",
            cwd=tmp_path,
        )
    )
    assert forked.agent_result is not None
    assert forked.agent_result.messages[-1].text == "forked answer"
