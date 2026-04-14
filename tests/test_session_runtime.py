import asyncio
from pathlib import Path

from claude_agent_runtime.contracts import MessageAttachment, MessageRole, RuntimeMessage
from claude_agent_runtime.definitions import AgentDefinition, ToolDefinition, ToolTraits
from claude_agent_runtime.registries import ToolRegistry
from claude_agent_runtime.session_runtime import (
    FileTranscriptStore,
    InboundEvent,
    InboundEventType,
    SessionController,
)
from claude_agent_runtime.session_runtime.models import SessionStatus
from claude_agent_runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, PromptComposer, TurnEngine


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


def test_prompt_composer_includes_dynamic_context() -> None:
    composer = PromptComposer()
    agent = AgentDefinition(name="main-router", description="router", prompt="Route the turn")
    composition = composer.compose(
        session_id="session",
        turn_id="turn",
        agent=agent,
        cwd="/tmp/project",
        messages=(
            RuntimeMessage(message_id="m1", role=MessageRole.USER, content="hello"),
        ),
        available_tools=("read",),
        available_skills=("verify",),
        base_system_prompt="Base prompt",
        memory_fragments=("Remember this",),
        hook_context=("Hook says hi",),
        attachments=(MessageAttachment(name="note.txt", path="/tmp/project/note.txt"),),
        runtime_context={"mode": "test"},
    )

    assert "Base prompt" in composition.system_prompt
    assert "Route the turn" in composition.system_prompt
    assert "Remember this" in composition.system_prompt
    assert "Hook says hi" in composition.system_prompt
    assert "note.txt" in composition.system_prompt
    assert "mode: test" in composition.system_prompt
    assert composition.turn_context.available_tools == ("read",)
    assert composition.turn_context.available_skills == ("verify",)


def test_session_controller_normalizes_priorities_and_resumes_from_transcript(
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

    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "echo", "tool_input": {"value": "ping"}, "call_id": "call-1"},
                )
            ],
            [ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"})],
        ]
    )
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    agent = AgentDefinition(
        name="main-router",
        description="router",
        prompt="Route the turn",
        tools=("*",),
    )
    engine = TurnEngine(model_client=model_client, tool_registry=tool_registry)
    controller = SessionController(
        session_id="session-1",
        agent=agent,
        turn_engine=engine,
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
    )

    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "Use echo"))
    controller.enqueue_event(InboundEvent(InboundEventType.SYSTEM_MESSAGE, "System override"))
    priorities = [command.priority for command in controller.state.queued_commands]
    assert priorities == sorted(priorities, reverse=True)
    controller.state.queued_commands = [
        command
        for command in controller.state.queued_commands
        if command.command_type.value == "user_prompt"
    ]

    produced = asyncio.run(controller.run_until_idle())

    assert controller.state.status == SessionStatus.READY
    assert produced[-1].content == "done"
    assert any(message.role == MessageRole.TOOL for message in produced)
    loaded = asyncio.run(transcript_store.load("session-1"))
    assert len(loaded.entries) == len(controller.messages)
    assert len(model_client.requests) == 2

    controller.interrupt()
    assert controller.state.status == SessionStatus.INTERRUPTED
    asyncio.run(controller.resume())
    assert controller.state.status == SessionStatus.READY
    assert len(controller.messages) == len(loaded.entries)
