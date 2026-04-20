import asyncio
import json
from pathlib import Path

import pytest

from claude_agent_runtime.agent_runtime import AgentInvocation, AgentRuntime
from claude_agent_runtime.contracts import MessageRole, ToolResultBlock
from claude_agent_runtime.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    IsolationMode,
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    SkillDefinition,
    SkillExecutionContext,
    ToolDefinition,
    ToolTraits,
)
from claude_agent_runtime.hooks import RuntimeHookPhase
from claude_agent_runtime.isolation import BaseIsolationAdapter, IsolationManager, IsolationRequest
from claude_agent_runtime.permissions import PermissionTarget
from claude_agent_runtime.registries import AgentRegistry, SkillRegistry, ToolRegistry
from claude_agent_runtime.runtime_kernel import (
    BuiltinPackConfig,
    DefinitionSourcePaths,
    ModelRouteBinding,
    RuntimeConfig,
    assemble_runtime,
)
from claude_agent_runtime.runtime_services import RuntimeServices
from claude_agent_runtime.skill_runtime import SkillExecutor
from claude_agent_runtime.tasking import TaskManager
from claude_agent_runtime.tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler
from claude_agent_runtime.turn_engine import (
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    NormalizedModelCapabilities,
    TurnEngine,
    TurnStreamEventType,
)


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


class AllowingPermissionService:
    async def evaluate(self, request, *, initial_decision=None, hook_result=None, runtime_context=None):
        _ = request, initial_decision, hook_result, runtime_context
        return PermissionDecision(PermissionBehavior.ALLOW)

    async def authorize(self, definition, tool_input, decision, context):  # pragma: no cover - protocol completeness
        _ = definition, tool_input, decision, context
        return PermissionDecision(PermissionBehavior.ALLOW)


class DenyingToolPermissionService(AllowingPermissionService):
    async def authorize(self, definition, tool_input, decision, context):  # pragma: no cover - protocol completeness
        _ = tool_input, decision, context
        if definition.name == "bash":
            return PermissionDecision(PermissionBehavior.DENY, "shell denied")
        return PermissionDecision(PermissionBehavior.ALLOW)


class SkillAllowedAgentDeniedPermissionService:
    async def evaluate(self, request, *, initial_decision=None, hook_result=None, runtime_context=None):
        _ = initial_decision, hook_result, runtime_context
        if request.target == PermissionTarget.SKILL:
            return PermissionDecision(PermissionBehavior.ALLOW)
        if request.target == PermissionTarget.AGENT:
            return PermissionDecision(PermissionBehavior.DENY, "blocked child agent")
        return PermissionDecision(PermissionBehavior.ALLOW)

    async def authorize(self, definition, tool_input, decision, context):  # pragma: no cover - protocol completeness
        _ = definition, tool_input, decision, context
        return PermissionDecision(PermissionBehavior.ALLOW)


class FailingIsolationService:
    async def prepare(self, **kwargs):
        _ = kwargs
        raise RuntimeError("isolation prepare failed")

    async def cleanup(self, lease):  # pragma: no cover - protocol completeness
        _ = lease


def test_main_thread_request_exposes_available_agents_and_agents_prompt(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agents"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    agent_registry = AgentRegistry()
    agent_registry.register(AgentDefinition(name="main-router", description="router", prompt="route"))
    agent_registry.register(AgentDefinition(name="verification", description="verify", prompt="verify"))
    agent_registry.register(AgentDefinition(name="planner", description="plan", prompt="plan"))

    asyncio.run(
        TurnEngine(
            model_client=model_client,
            tool_registry=ToolRegistry(),
            agent_registry=agent_registry,
            skill_registry=SkillRegistry(),
            task_manager=TaskManager(),
        ).run_turn(
            session_id="session-agents",
            turn_id="turn-agents",
            agent=agent_registry.get("main-router"),
            cwd=str(tmp_path),
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert request.turn_context.available_agents == ("verification", "planner")
    assert "Agents:" in request.system_prompt
    assert "- verification: verify" in request.system_prompt
    assert "- planner: plan" in request.system_prompt
    assert "main-router" not in request.turn_context.available_agents


def test_agent_tool_v1_contract_normalizes_and_returns_structured_payload(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agent-structured"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "subagent answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            model_routes={
                "reviewer-route": ModelRouteBinding(
                    client=model_client,
                    default_model="default-reviewer-model",
                    provider_name="provider-reviewer",
                    capabilities=NormalizedModelCapabilities(),
                )
            },
            builtins=BuiltinPackConfig(
                agents_enabled=False,
                extra_agents=[
                    AgentDefinition(name="main-router", description="router", prompt="route", tools=("*",)),
                    AgentDefinition(name="verification", description="verify", prompt="verify"),
                ],
            ),
        )
    )
    context = ToolContext(
        session_id="session-agent-tool",
        turn_id="turn-agent-tool",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=runtime.kernel.tool_registry,
        agent_registry=runtime.kernel.agent_registry,
        skill_registry=runtime.kernel.skill_registry,
        agent_runner=runtime.run_agent_tool,
    )

    result = asyncio.run(
        ToolScheduler(runtime.kernel.tool_registry).run(
            [
                ToolCall(
                    "call-agent",
                    "agent",
                    {
                        "agent": "verification",
                        "prompt": "run checks",
                        "background": True,
                        "spawn_mode": "sync",
                        "cwd": "workspace",
                        "model": "override-model",
                        "model_route": "reviewer-route",
                        "reason": "need specialist",
                        "permission_mode": "dontAsk",
                        "isolation": "worktree",
                        "max_turns": 1,
                    },
                )
            ],
            context,
        )
    )[0]

    assert result.status == ToolCallStatus.SUCCESS
    payload = result.output
    assert payload["agent"] == "verification"
    assert payload["status"] == "completed"
    assert payload["background"] is False
    assert payload["run_id"]
    assert payload["turn_id"]
    assert payload["task_id"] is None
    assert payload["query_source"] == "agent_tool"
    assert payload["requested_model"] == "override-model"
    assert payload["requested_model_route"] == "reviewer-route"
    assert payload["resolved_model_route"] == "reviewer-route"
    assert payload["isolation_mode"] == "worktree"
    assert payload["terminal_metadata"] == {
        "stop_reason": "end_turn",
        "request_id": "req-agent-structured",
    }
    assert payload["messages"][-1]["content"][0]["text"] == "subagent answer"

    request = model_client.requests[0]
    assert request.turn_context.cwd == str(workspace.resolve())
    assert request.model == "override-model"
    assert request.requested_model_route == "reviewer-route"
    assert request.resolved_model_route == "reviewer-route"
    assert request.metadata["delegation_reason"] == "need specialist"


def test_agent_tool_rejects_invalid_cwd_input(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient([]),
            builtins=BuiltinPackConfig(
                agents_enabled=False,
                extra_agents=[
                    AgentDefinition(name="main-router", description="router", prompt="route", tools=("*",)),
                    AgentDefinition(name="verification", description="verify", prompt="verify"),
                ],
            ),
        )
    )
    context = ToolContext(
        session_id="session-invalid-agent-tool",
        turn_id="turn-invalid-agent-tool",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=runtime.kernel.tool_registry,
        agent_registry=runtime.kernel.agent_registry,
        skill_registry=runtime.kernel.skill_registry,
        agent_runner=runtime.run_agent_tool,
    )

    result = asyncio.run(
        ToolScheduler(runtime.kernel.tool_registry).run(
            [
                ToolCall(
                    "call-invalid-agent",
                    "agent",
                    {
                        "agent": "verification",
                        "prompt": "run checks",
                        "cwd": "missing-workspace",
                    },
                )
            ],
            context,
        )
    )[0]

    assert result.status == ToolCallStatus.ERROR
    assert "cwd does not exist" in (result.error or "")


def test_agent_tool_rejects_unknown_model_route(tmp_path: Path) -> None:
    model_client = FakeModelClient([])
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                agents_enabled=False,
                extra_agents=[
                    AgentDefinition(name="main-router", description="router", prompt="route", tools=("*",)),
                    AgentDefinition(name="verification", description="verify", prompt="verify"),
                ],
            ),
        )
    )
    context = ToolContext(
        session_id="session-invalid-model-route",
        turn_id="turn-invalid-model-route",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=runtime.kernel.tool_registry,
        agent_registry=runtime.kernel.agent_registry,
        skill_registry=runtime.kernel.skill_registry,
        agent_runner=runtime.run_agent_tool,
    )

    result = asyncio.run(
        ToolScheduler(runtime.kernel.tool_registry).run(
            [
                ToolCall(
                    "call-invalid-model-route",
                    "agent",
                    {
                        "agent": "verification",
                        "prompt": "run checks",
                        "model_route": "missing-route",
                    },
                )
            ],
            context,
        )
    )[0]

    assert result.status == ToolCallStatus.ERROR
    assert result.error == "Unknown model route: missing-route"
    assert model_client.requests == []


def test_skill_tool_executes_dynamic_overlay_skill_from_session_view(tmp_path: Path) -> None:
    nested_skill_dir = tmp_path / "packages" / "app" / ".claude" / "skills" / "review"
    observed = tmp_path / "packages" / "app" / "src" / "main.py"
    nested_skill_dir.mkdir(parents=True)
    observed.parent.mkdir(parents=True)
    observed.write_text("print('ok')", encoding="utf-8")
    (nested_skill_dir / "SKILL.md").write_text(
        """
---
description: nested review
---
review body
""".strip(),
        encoding="utf-8",
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient([]),
            discovery_sources=(
                DefinitionSourcePaths(DefinitionSource.PROJECT, tmp_path / ".claude"),
            ),
            builtins=BuiltinPackConfig(
                skills_enabled=False,
                extra_agents=[
                    AgentDefinition(name="main-router", description="router", prompt="route", tools=("*",))
                ],
            ),
        )
    )
    runtime.services.permissions = AllowingPermissionService()
    catalog = runtime.resolve_invocations(
        session_id="session-overlay-skill",
        cwd=tmp_path,
        messages=(
            RuntimeMessage(
                message_id="observed",
                role=MessageRole.USER,
                content="{}",
                metadata={"observed_paths": [str(observed)]},
            ),
        ),
    )
    assert runtime.kernel.skill_registry.get("review") is None
    context = ToolContext(
        session_id="session-overlay-skill",
        turn_id="turn-overlay-skill",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=runtime.kernel.tool_registry,
        skill_registry=runtime.kernel.skill_registry,
        skill_pool=catalog.visible_skill_definitions(user_invocable=True),
        skill_runner=runtime.run_skill_tool,
        runtime_services=runtime.services,
    )

    result = asyncio.run(
        ToolScheduler(runtime.kernel.tool_registry).run(
            [ToolCall("call-overlay-skill", "skill", {"skill": "review"})],
            context,
        )
    )[0]

    assert result.status == ToolCallStatus.SUCCESS
    assert result.output["skill"] == "review"
    assert result.output["mode"] == SkillExecutionContext.INLINE.value
    assert result.output["injected_messages"][0]["content"][0]["text"] == "review body"


def test_session_stream_surfaces_child_run_events(tmp_path: Path) -> None:
    async def scenario():
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-child-main-1"}),
                    ModelStreamEvent(
                        ModelStreamEventType.TOOL_CALL,
                        {
                            "tool_name": "agent",
                            "tool_input": {"agent": "verification", "prompt": "run checks"},
                            "call_id": "call-child-agent",
                        },
                    ),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
                ],
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-child-sub"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "subagent answer"}),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ],
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-child-main-2"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
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
                        AgentDefinition(name="verification", description="verify", prompt="verify")
                    ]
                ),
            )
        )
        return [event async for event in runtime.stream_prompt("Run agent tool", session_id="session-child-events")]

    events = asyncio.run(scenario())

    child_events = [event for event in events if event.event_type == TurnStreamEventType.CHILD_RUN]
    assert len(child_events) == 1
    assert child_events[0].child_run is not None
    assert child_events[0].child_run.agent_name == "verification"
    assert child_events[0].child_run.status.value == "completed"
    assert child_events[0].child_run.messages[-1].text == "subagent answer"


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


def test_inline_skill_request_override_shapes_next_request_and_is_consumed_once(
    tmp_path: Path,
) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-override-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "config-request"},
                        "call_id": "call-config-request",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-override-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "override applied"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-override-3"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "baseline restored"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                agent_replacements={
                    "main-router": AgentDefinition(
                        name="main-router",
                        description="router",
                        prompt="route",
                        model="baseline-model",
                        effort="low",
                    )
                },
                skills_enabled=False,
                extra_skills=[
                    SkillDefinition(
                        name="config-request",
                        description="configure the next request",
                        content="Use the configured request shape.",
                        model="override-model",
                        effort="high",
                    )
                ],
            ),
        )
    )

    first_turn = asyncio.run(runtime.run_prompt("Use the config skill", session_id="session-override"))
    second_turn = asyncio.run(runtime.run_prompt("No skill this time", session_id="session-override"))

    assert model_client.requests[0].model == "baseline-model"
    assert model_client.requests[0].effort == "low"
    assert model_client.requests[1].model == "override-model"
    assert model_client.requests[1].effort == "high"
    assert model_client.requests[1].metadata["skill_request_override"] == {
        "requested_model": "override-model",
        "requested_effort": "high",
        "source_skill": "config-request",
    }
    assert model_client.requests[2].model == "baseline-model"
    assert model_client.requests[2].effort == "low"
    assert any(
        message.role == MessageRole.SYSTEM and message.metadata.get("skill") == "config-request"
        for message in first_turn
    )
    assert second_turn[-1].text == "baseline restored"


def test_multiple_inline_skills_merge_request_override_fields(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-merge-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "set-model-a"},
                        "call_id": "call-set-model-a",
                    },
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "set-effort"},
                        "call_id": "call-set-effort",
                    },
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "set-model-b"},
                        "call_id": "call-set-model-b",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-merge-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "merged"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                agent_replacements={
                    "main-router": AgentDefinition(
                        name="main-router",
                        description="router",
                        prompt="route",
                        model="baseline-model",
                        effort="low",
                    )
                },
                skills_enabled=False,
                extra_skills=[
                    SkillDefinition(
                        name="set-model-a",
                        description="set model a",
                        content="model a",
                        model="alpha-model",
                    ),
                    SkillDefinition(
                        name="set-effort",
                        description="set effort",
                        content="effort",
                        effort="high",
                    ),
                    SkillDefinition(
                        name="set-model-b",
                        description="set model b",
                        content="model b",
                        model="beta-model",
                    ),
                ],
            ),
        )
    )

    asyncio.run(runtime.run_prompt("Merge request shaping", session_id="session-merge"))

    assert model_client.requests[1].model == "beta-model"
    assert model_client.requests[1].effort == "high"
    assert model_client.requests[1].metadata["skill_request_override"]["source_skill"] == "set-model-b"


def test_forked_skill_propagates_requested_effort_to_child_request(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-fork-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "fork-config"},
                        "call_id": "call-fork-config",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-fork-child"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "child done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-fork-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "parent done"}),
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
                        name="general-purpose",
                        description="general",
                        prompt="general",
                        tools=("*",),
                    )
                ],
                extra_skills=[
                    SkillDefinition(
                        name="fork-config",
                        description="fork with request override",
                        content="Forked request override",
                        execution_context=SkillExecutionContext.FORK,
                        agent="general-purpose",
                        model="fork-model",
                        effort="high",
                    )
                ],
            ),
        )
    )

    messages = asyncio.run(runtime.run_prompt("Fork with request override", session_id="session-fork"))

    assert model_client.requests[1].model == "fork-model"
    assert model_client.requests[1].effort == "high"
    skill_tool_result_message = next(
        message
        for message in messages
        if message.role == MessageRole.USER and any(isinstance(block, ToolResultBlock) for block in message.content)
    )
    skill_tool_result = next(
        block for block in skill_tool_result_message.content if isinstance(block, ToolResultBlock)
    )
    assert skill_tool_result.content["agent_result"]["requested_model"] == "fork-model"
    assert skill_tool_result.content["agent_result"]["requested_effort"] == "high"


def test_local_skill_shell_expansion_uses_shell_tool_output(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient([]),
            builtins=BuiltinPackConfig(skills_enabled=False),
        )
    )
    runtime.services.permissions = AllowingPermissionService()
    skill_dir = tmp_path / "local-skills" / "shell-inline"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("placeholder", encoding="utf-8")
    runtime.kernel.skill_registry.register(
        SkillDefinition(
            name="shell-inline",
            description="shell inline",
            content="Before\n!printf 'hello'\nAfter",
            origin=DefinitionOrigin(
                DefinitionSource.USER,
                path=skill_path,
                root=skill_dir.parent,
            ),
        )
    )

    result = asyncio.run(
        runtime.skill_executor.execute(
            "shell-inline",
            arguments=(),
            session_id="session-shell",
            cwd=tmp_path,
        )
    )

    assert result.injected_messages[0].text == "Before\nhello\nAfter"


def test_skill_shell_expansion_fails_closed_when_shell_tool_is_denied(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient([]),
            builtins=BuiltinPackConfig(skills_enabled=False),
        )
    )
    runtime.services.permissions = DenyingToolPermissionService()
    skill_dir = tmp_path / "local-skills" / "shell-denied"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("placeholder", encoding="utf-8")
    runtime.kernel.skill_registry.register(
        SkillDefinition(
            name="shell-denied",
            description="shell denied",
            content="!printf 'blocked'",
            origin=DefinitionOrigin(
                DefinitionSource.USER,
                path=skill_path,
                root=skill_dir.parent,
            ),
        )
    )

    with pytest.raises(RuntimeError, match="shell denied"):
        asyncio.run(
            runtime.skill_executor.execute(
                "shell-denied",
                arguments=(),
                session_id="session-shell-denied",
                cwd=tmp_path,
            )
        )


def test_skill_shell_expansion_rejects_non_local_skills(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient([]),
            builtins=BuiltinPackConfig(skills_enabled=False),
        )
    )
    runtime.services.permissions = AllowingPermissionService()
    runtime.kernel.skill_registry.register(
        SkillDefinition(
            name="bundled-shell",
            description="bundled shell",
            content="!printf 'hello'",
            origin=DefinitionOrigin(
                DefinitionSource.BUNDLED,
                path=tmp_path / "bundled-shell" / "SKILL.md",
            ),
        )
    )

    with pytest.raises(RuntimeError, match="local file-backed"):
        asyncio.run(
            runtime.skill_executor.execute(
                "bundled-shell",
                arguments=(),
                session_id="session-bundled-shell",
                cwd=tmp_path,
            )
        )


def test_user_originated_skill_route_rejects_non_user_invocable_and_inactive_path(
    tmp_path: Path,
) -> None:
    agent_registry = AgentRegistry()
    agent_registry.register(AgentDefinition(name="main-router", description="router", prompt="route"))
    skill_registry = SkillRegistry()
    skill_registry.register(
        SkillDefinition(
            name="host-hidden",
            description="not user invocable",
            content="hidden",
            user_invocable=False,
        )
    )
    skill_registry.register(
        SkillDefinition(
            name="python-only",
            description="needs a python path",
            content="python",
            paths=("src/**/*.py",),
        )
    )
    runtime = AgentRuntime(
        turn_engine=TurnEngine(
            model_client=FakeModelClient([]),
            tool_registry=ToolRegistry(),
            agent_registry=agent_registry,
            skill_registry=skill_registry,
            task_manager=TaskManager(),
        ),
        agent_registry=agent_registry,
        tool_registry=ToolRegistry(),
        skill_registry=skill_registry,
        task_manager=TaskManager(),
    )

    with pytest.raises(PermissionError, match="not user-invocable"):
        asyncio.run(
            runtime.invoke(
                AgentInvocation(
                    agent_name="main-router",
                    prompt="/skill host-hidden",
                    session_id="session-user-hidden",
                    cwd=tmp_path,
                )
            )
        )

    with pytest.raises(PermissionError, match="not active"):
        asyncio.run(
            runtime.invoke(
                AgentInvocation(
                    agent_name="main-router",
                    prompt="/skill python-only",
                    session_id="session-user-path",
                    cwd=tmp_path,
                )
            )
        )


def test_inline_skill_narrows_tools_and_records_policy_trace(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-lock-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "lockdown"},
                        "call_id": "call-lockdown",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-lock-2"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "write-note",
                        "tool_input": {"value": "blocked"},
                        "call_id": "call-write",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-lock-3"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                extra_tools=[
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
                    ),
                    ToolDefinition(
                        name="write-note",
                        description="write a note",
                        input_schema={
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        execute=lambda tool_input, _: {"written": tool_input["value"]},
                    ),
                ],
                extra_skills=[
                    SkillDefinition(
                        name="lockdown",
                        description="narrow tools",
                        content="Only use echo.",
                        allowed_tools=("echo",),
                    )
                ],
            ),
        )
    )

    messages = asyncio.run(runtime.run_prompt("Use the lockdown skill", session_id="session-lock"))

    assert model_client.requests[1].turn_context.available_tools == ("echo",)
    assert model_client.requests[1].metadata["policy"]["history"][-1]["source"] == "skill"
    denied_result_message = next(
        message
        for message in messages
        if message.role == MessageRole.USER
        and any(
            isinstance(block, ToolResultBlock) and block.tool_use_id == "call-write"
            for block in message.content
        )
    )
    denied_block = next(
        block
        for block in denied_result_message.content
        if isinstance(block, ToolResultBlock) and block.tool_use_id == "call-write"
    )
    assert denied_block.is_error is True
    assert "not available in the current execution policy" in denied_block.content


def test_inline_skill_hooks_are_released_after_turn(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-hook-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "rewrite"},
                        "call_id": "call-skill",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-hook-2"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "echo",
                        "tool_input": {"value": "original"},
                        "call_id": "call-echo-rewritten",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-hook-3"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-hook-4"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "echo",
                        "tool_input": {"value": "original"},
                        "call_id": "call-echo-original",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-hook-5"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done again"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                extra_tools=[
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
                ],
                extra_skills=[
                    SkillDefinition(
                        name="rewrite",
                        description="rewrite echo inputs",
                        content="Rewrite the next tool use.",
                        hooks={
                            "PreToolUse": {
                                "matcher": "echo",
                                "effect": {"updated_input": {"value": "rewritten"}},
                            }
                        },
                    )
                ],
            ),
        )
    )

    first_turn = asyncio.run(runtime.run_prompt("Use the rewrite skill", session_id="hook-session"))
    second_turn = asyncio.run(runtime.run_prompt("Echo directly", session_id="hook-session"))

    first_result_message = next(
        message
        for message in first_turn
        if message.role == MessageRole.USER
        and any(
            isinstance(block, ToolResultBlock) and block.tool_use_id == "call-echo-rewritten"
            for block in message.content
        )
    )
    first_block = next(
        block
        for block in first_result_message.content
        if isinstance(block, ToolResultBlock) and block.tool_use_id == "call-echo-rewritten"
    )
    second_result_message = next(
        message
        for message in second_turn
        if message.role == MessageRole.USER
        and any(
            isinstance(block, ToolResultBlock) and block.tool_use_id == "call-echo-original"
            for block in message.content
        )
    )
    second_block = next(
        block
        for block in second_result_message.content
        if isinstance(block, ToolResultBlock) and block.tool_use_id == "call-echo-original"
    )

    assert first_block.content == {"echo": "rewritten"}
    assert second_block.content == {"echo": "original"}


def test_forked_skill_subagent_stop_hook_observes_denied_child(tmp_path: Path) -> None:
    async def scenario():
        hits: list[tuple[str, str]] = []

        async def on_subagent_stop(payload):
            hits.append((payload.agent_name, payload.status))

        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(name="general-purpose", description="general", prompt="general")
        )
        skill_registry = SkillRegistry()
        skill_registry.register(
            SkillDefinition(
                name="fork-skill",
                description="fork",
                content="Forked skill",
                execution_context=SkillExecutionContext.FORK,
                agent="general-purpose",
                hooks={RuntimeHookPhase.SUBAGENT_STOP.value: {"handler": on_subagent_stop}},
            )
        )
        services = RuntimeServices(permissions=SkillAllowedAgentDeniedPermissionService())
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=FakeModelClient([]),
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=skill_registry,
                task_manager=TaskManager(),
                runtime_services=services,
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=skill_registry,
            task_manager=TaskManager(),
            runtime_services=services,
        )
        skill_executor = SkillExecutor(
            skill_registry=skill_registry,
            agent_runtime=runtime,
            runtime_services=services,
        )
        runtime.bind_skill_executor(skill_executor)
        result = await skill_executor.execute(
            "fork-skill",
            arguments=(),
            session_id="session-hook-denied",
            cwd=tmp_path,
        )
        return result, hits

    result, hits = asyncio.run(scenario())

    assert result.agent_result is not None
    assert result.agent_result.status == "denied"
    assert hits == [("general-purpose", "denied")]


def test_forked_skill_subagent_stop_hook_observes_failed_child(tmp_path: Path) -> None:
    async def scenario():
        hits: list[tuple[str, str]] = []

        async def on_subagent_stop(payload):
            hits.append((payload.agent_name, payload.status))

        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(name="general-purpose", description="general", prompt="general")
        )
        skill_registry = SkillRegistry()
        skill_registry.register(
            SkillDefinition(
                name="fork-skill",
                description="fork",
                content="Forked skill",
                execution_context=SkillExecutionContext.FORK,
                agent="general-purpose",
                hooks={RuntimeHookPhase.SUBAGENT_STOP.value: {"handler": on_subagent_stop}},
            )
        )
        services = RuntimeServices(
            permissions=AllowingPermissionService(),
            isolation=FailingIsolationService(),
        )
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=FakeModelClient([]),
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=skill_registry,
                task_manager=TaskManager(),
                runtime_services=services,
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=skill_registry,
            task_manager=TaskManager(),
            runtime_services=services,
        )
        skill_executor = SkillExecutor(
            skill_registry=skill_registry,
            agent_runtime=runtime,
            runtime_services=services,
        )
        runtime.bind_skill_executor(skill_executor)
        error = None
        try:
            await skill_executor.execute(
                "fork-skill",
                arguments=(),
                session_id="session-hook-failed",
                cwd=tmp_path,
            )
        except RuntimeError as exc:
            error = str(exc)
        return error, hits

    error, hits = asyncio.run(scenario())

    assert error == "isolation prepare failed"
    assert hits == [("general-purpose", "failed")]


def test_forked_skill_and_subagent_preserve_policy_and_isolation_ceilings(
    tmp_path: Path,
) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-parent-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "delegated-check"},
                        "call_id": "call-skill-delegated",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "restricted",
                        "tool_input": {"value": "secret"},
                        "call_id": "call-restricted",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "worker done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-parent-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "parent done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
            builtins=BuiltinPackConfig(
                agent_replacements={
                    "main-router": AgentDefinition(
                        name="main-router",
                        description="router",
                        prompt="route",
                        tools=("*",),
                        permission_mode=PermissionMode.DONT_ASK,
                        isolation=IsolationMode.WORKTREE,
                    )
                },
                extra_tools=[
                    ToolDefinition(
                        name="restricted",
                        description="restricted",
                        input_schema={
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        check_permissions=lambda _tool_input, _context: PermissionDecision(
                            PermissionBehavior.ASK,
                            "approval required",
                        ),
                        execute=lambda tool_input, _: {"value": tool_input["value"]},
                    )
                ],
                extra_agents=[
                    AgentDefinition(
                        name="worker",
                        description="worker",
                        prompt="work",
                        tools=("restricted",),
                        permission_mode=PermissionMode.BYPASS_PERMISSIONS,
                        isolation=IsolationMode.NONE,
                    )
                ],
                extra_skills=[
                    SkillDefinition(
                        name="delegated-check",
                        description="delegate to a worker",
                        content="Run the delegated check.",
                        execution_context=SkillExecutionContext.FORK,
                        agent="worker",
                        allowed_tools=("restricted",),
                    )
                ],
            ),
        )
    )

    messages = asyncio.run(runtime.run_prompt("Run the delegated check", session_id="session-ceilings"))

    worker_request = model_client.requests[1]
    assert worker_request.metadata["policy"]["effective"]["permission_mode"] == PermissionMode.DONT_ASK.value
    assert worker_request.metadata["isolation"]["mode"] == IsolationMode.WORKTREE.value

    skill_tool_result_message = next(
        message
        for message in messages
        if message.role == MessageRole.USER and any(isinstance(block, ToolResultBlock) for block in message.content)
    )
    skill_tool_result = next(
        block for block in skill_tool_result_message.content if isinstance(block, ToolResultBlock)
    )
    worker_tool_result_message = next(
        message
        for message in skill_tool_result.content["agent_result"]["messages"]
        if any(block["type"] == "tool_result" for block in message["content"])
    )
    worker_tool_result = next(
        block for block in worker_tool_result_message["content"] if block["type"] == "tool_result"
    )
    assert worker_tool_result["is_error"] is True
    assert "approval required" in worker_tool_result["content"]


def test_remote_isolation_uses_adapter_contract_and_emits_trace(tmp_path: Path) -> None:
    class RecordingIsolationAdapter(BaseIsolationAdapter):
        def __init__(self, mode: IsolationMode) -> None:
            self.mode = mode
            self.prepared: list[IsolationRequest] = []
            self.cleaned: list[dict[str, object]] = []

        async def prepare(self, request: IsolationRequest):
            self.prepared.append(request)
            lease = await BaseIsolationAdapter.prepare(self, request)
            lease.metadata["recorded"] = True
            return lease

        async def cleanup(self, lease) -> None:
            self.cleaned.append(dict(lease.metadata))
            await BaseIsolationAdapter.cleanup(self, lease)

    tool_registry = ToolRegistry()
    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentDefinition(
            name="remote-worker",
            description="remote",
            prompt="remote",
            isolation=IsolationMode.REMOTE,
        )
    )
    skill_registry = SkillRegistry()
    remote_adapter = RecordingIsolationAdapter(IsolationMode.REMOTE)
    services = RuntimeServices(
        isolation=IsolationManager(
            adapters={
                IsolationMode.NONE: BaseIsolationAdapter(),
                IsolationMode.WORKTREE: BaseIsolationAdapter(mode=IsolationMode.WORKTREE),
                IsolationMode.REMOTE: remote_adapter,
            }
        )
    )
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-remote"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "remote done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        runtime_services=services,
    )
    runtime = AgentRuntime(
        turn_engine=engine,
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        runtime_services=services,
    )

    result = asyncio.run(
        runtime.invoke(
            AgentInvocation(
                agent_name="remote-worker",
                prompt="run remotely",
                session_id="session-remote",
                cwd=tmp_path,
            )
        )
    )

    assert result.isolation_mode == IsolationMode.REMOTE
    assert len(remote_adapter.prepared) == 1
    assert len(remote_adapter.cleaned) == 1
    assert model_client.requests[0].metadata["isolation"]["mode"] == IsolationMode.REMOTE.value
    assert model_client.requests[0].metadata["isolation"]["adapter"] == "RecordingIsolationAdapter"
