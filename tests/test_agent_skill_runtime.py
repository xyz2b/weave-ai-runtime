import asyncio
import json
from pathlib import Path

from claude_agent_runtime.agent_runtime import AgentInvocation, AgentRuntime
from claude_agent_runtime.contracts import MessageRole, ToolResultBlock
from claude_agent_runtime.definitions import (
    AgentDefinition,
    IsolationMode,
    SkillDefinition,
    SkillExecutionContext,
    ToolDefinition,
    ToolTraits,
)
from claude_agent_runtime.registries import AgentRegistry, SkillRegistry, ToolRegistry
from claude_agent_runtime.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime
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
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "direct answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "subagent answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-3"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "background answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-4"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "forked answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
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


def test_assembled_runtime_executes_model_generated_agent_and_skill_tools(
    tmp_path: Path,
) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agent-main-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "agent",
                        "tool_input": {"agent": "verification", "prompt": "run checks"},
                        "call_id": "call-agent-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agent-sub"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "subagent answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agent-main-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "agent delegation done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-skill-main-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "fork-skill", "arguments": ["ARG"]},
                        "call_id": "call-skill-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-skill-sub"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "forked answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-skill-main-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "skill delegation done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                extra_agents=[
                    AgentDefinition(
                        name="verification",
                        description="verify",
                        prompt="verify",
                        tools=("*",),
                        isolation=IsolationMode.WORKTREE,
                    ),
                    AgentDefinition(
                        name="general-purpose",
                        description="general",
                        prompt="general",
                        tools=("*",),
                    ),
                ],
                extra_skills=[
                    SkillDefinition(
                        name="fork-skill",
                        description="fork",
                        content="Forked skill ${ARG1}",
                        execution_context=SkillExecutionContext.FORK,
                        agent="general-purpose",
                    )
                ],
            ),
        )
    )

    agent_messages = asyncio.run(runtime.run_prompt("Run agent tool", session_id="session-agent"))
    skill_messages = asyncio.run(runtime.run_prompt("Run skill tool", session_id="session-skill"))

    agent_tool_result_message = next(
        message
        for message in agent_messages
        if message.role == MessageRole.USER and any(isinstance(block, ToolResultBlock) for block in message.content)
    )
    agent_tool_result = next(
        block for block in agent_tool_result_message.content if isinstance(block, ToolResultBlock)
    )
    assert agent_tool_result.content["agent"] == "verification"
    assert agent_tool_result.content["status"] == "completed"
    assert agent_tool_result.content["messages"][-1]["content"][0]["text"] == "subagent answer"
    assert agent_messages[-1].text == "agent delegation done"

    skill_tool_result_message = next(
        message
        for message in skill_messages
        if message.role == MessageRole.USER and any(isinstance(block, ToolResultBlock) for block in message.content)
    )
    skill_tool_result = next(
        block for block in skill_tool_result_message.content if isinstance(block, ToolResultBlock)
    )
    assert skill_tool_result.content["skill"] == "fork-skill"
    assert skill_tool_result.content["mode"] == SkillExecutionContext.FORK.value
    assert skill_tool_result.content["agent_result"]["messages"][-1]["content"][0]["text"] == "forked answer"
    assert skill_messages[-1].text == "skill delegation done"
