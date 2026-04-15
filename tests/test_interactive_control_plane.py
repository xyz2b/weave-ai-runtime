import asyncio
from pathlib import Path

from claude_agent_runtime.builtins.tool_impls import ask_user_tool
from claude_agent_runtime.contracts import MessageRole, RuntimeMessage, ToolResultBlock
from claude_agent_runtime.definitions import (
    AgentDefinition,
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    ToolDefinition,
    ToolTraits,
)
from claude_agent_runtime.elicitation import ElicitationRequest
from claude_agent_runtime.hooks import HookBus, RuntimeHookPhase
from claude_agent_runtime.hosts import SdkHostRuntime
from claude_agent_runtime.permissions import PermissionContext
from claude_agent_runtime.registries import ToolRegistry
from claude_agent_runtime.runtime_kernel import RuntimeConfig, assemble_runtime
from claude_agent_runtime.runtime_services import RuntimeServices
from claude_agent_runtime.session_runtime import FileTranscriptStore, InboundEvent, InboundEventType, SessionController
from claude_agent_runtime.tool_runtime import ToolCall, ToolContext, ToolScheduler
from claude_agent_runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, TurnEngine


class BatchedModelClient:
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


def test_hook_bus_updates_tool_input_and_scopes_ownership(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="echo",
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
    services = RuntimeServices()
    services.hook_bus.register(
        session_id="session-a",
        owner="skill:rewrite",
        phase=RuntimeHookPhase.PRE_TOOL_USE,
        matcher="echo",
        handler=lambda _payload: {"updated_input": {"value": "rewritten"}},
    )
    scheduler = ToolScheduler(registry)
    context = ToolContext(
        session_id="session-a",
        turn_id="turn-a",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=registry,
        runtime_services=services,
        permission_context=PermissionContext(session_id="session-a"),
    )

    result = asyncio.run(
        scheduler.run(
            [ToolCall(call_id="1", tool_name="echo", tool_input={"value": "original"})],
            context,
        )
    )[0]
    other = asyncio.run(
        scheduler.run(
            [ToolCall(call_id="2", tool_name="echo", tool_input={"value": "untouched"})],
            ToolContext(
                session_id="session-b",
                turn_id="turn-b",
                agent_name="main-router",
                cwd=tmp_path,
                tool_registry=registry,
                runtime_services=services,
                permission_context=PermissionContext(session_id="session-b"),
            ),
        )
    )[0]

    assert result.output == {"echo": "rewritten"}
    assert other.output == {"echo": "untouched"}


def test_stop_hook_blocks_continuation_and_session_enters_waiting(tmp_path: Path) -> None:
    services = RuntimeServices()
    services.hook_bus.register(
        session_id="session-blocked",
        owner="host:blocker",
        phase=RuntimeHookPhase.STOP,
        handler=lambda _payload: {"continue_execution": False},
    )
    controller = SessionController(
        session_id="session-blocked",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
        turn_engine=TurnEngine(
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-block"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "blocked reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
            tool_registry=ToolRegistry(),
            runtime_services=services,
        ),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System",
        runtime_services=services,
    )
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "hello"))

    async def collect():
        return [event async for event in controller.stream_until_idle()]

    events = asyncio.run(collect())
    terminal = next(event for event in events if event.event_type.value == "terminal")

    assert terminal.terminal is not None
    assert terminal.terminal.stop_reason == "blocked"
    assert terminal.terminal.metadata["continuation_blocked"] is True
    assert controller.state.status.value == "waiting"


def test_permission_modes_and_elicitation_flow_use_shared_control_plane(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
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
    )
    scheduler = ToolScheduler(registry)
    bypass_services = RuntimeServices()
    bypass_result = asyncio.run(
        scheduler.run(
            [ToolCall(call_id="1", tool_name="restricted", tool_input={"value": "ok"})],
            ToolContext(
                session_id="bypass",
                turn_id="turn-bypass",
                agent_name="main-router",
                cwd=tmp_path,
                tool_registry=registry,
                runtime_services=bypass_services,
                permission_context=PermissionContext(
                    session_id="bypass",
                    mode=PermissionMode.BYPASS_PERMISSIONS,
                ),
            ),
        )
    )[0]
    dont_ask_result = asyncio.run(
        scheduler.run(
            [ToolCall(call_id="2", tool_name="restricted", tool_input={"value": "no"})],
            ToolContext(
                session_id="dont-ask",
                turn_id="turn-dont-ask",
                agent_name="main-router",
                cwd=tmp_path,
                tool_registry=registry,
                runtime_services=RuntimeServices(),
                permission_context=PermissionContext(
                    session_id="dont-ask",
                    mode=PermissionMode.DONT_ASK,
                ),
            ),
        )
    )[0]

    hook_services = RuntimeServices()
    hook_services.hook_bus.register(
        session_id="hook-elicit",
        owner="hook:auto-answer",
        phase=RuntimeHookPhase.ELICITATION,
        handler=lambda _payload: {"elicitation_result": {"response": "hooked"}},
    )
    hook_response = asyncio.run(
        ask_user_tool(
            {"question": "continue?"},
            ToolContext(
                session_id="hook-elicit",
                turn_id="turn-hook-elicit",
                agent_name="main-router",
                cwd=tmp_path,
                runtime_services=hook_services,
            ),
        )
    )

    host = SdkHostRuntime(name="sdk", ask_user_handler=lambda question, options=None: "hosted")
    host_services = RuntimeServices()
    host_services.bind_host(host)
    host_response = asyncio.run(
        ask_user_tool(
            {"question": "continue?", "options": ["yes", "no"]},
            ToolContext(
                session_id="host-elicit",
                turn_id="turn-host-elicit",
                agent_name="main-router",
                cwd=tmp_path,
                runtime_services=host_services,
            ),
        )
    )

    assert bypass_result.output == {"value": "ok"}
    assert dont_ask_result.error == "approval required"
    assert hook_response["response"] == {"response": "hooked"}
    assert host_response["response"] == "hosted"


def test_bound_host_runtime_emits_lifecycle_and_turn_events(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-host"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "host reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
        )
    )
    bound = runtime.bind_host(host)

    produced = asyncio.run(bound.run_prompt("hello host", session_id="host-session"))
    asyncio.run(bound.shutdown())

    assert produced[-1].text == "host reply"
    assert host.lifecycle == ["startup", "ready", "shutdown"]
    assert any(event.event_type.value == "terminal" for _, event in host.turn_events)
