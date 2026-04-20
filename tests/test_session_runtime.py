import asyncio
from pathlib import Path

from runtime.contracts import (
    MessageAttachment,
    MessageRole,
    RuntimeMessage,
    ToolResultBlock,
    ToolUseBlock,
)
from runtime.definitions import AgentDefinition, ToolDefinition, ToolTraits
from runtime.hooks import RuntimeHookPhase
from runtime.registries import ToolRegistry
from runtime.runtime_services import RuntimeServices
from runtime.session_runtime import (
    FileTranscriptStore,
    InboundEvent,
    InboundEventType,
    SessionController,
)
from runtime.session_runtime.models import SessionStatus
from runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, PromptComposer, TurnEngine


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
        runtime_context={"prompt_updates": {"mode": "test"}},
    )

    assert "Base prompt" in composition.system_prompt
    assert "Route the turn" in composition.system_prompt
    assert "Remember this" in composition.system_prompt
    assert "Hook says hi" in composition.system_prompt
    assert "note.txt" in composition.system_prompt
    assert "mode: test" in composition.system_prompt
    assert composition.turn_context.available_tools == ("read",)
    assert composition.turn_context.available_skills == ("verify",)
    assert composition.turn_context.prompt_context.session_hints == {"mode": "test"}


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
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-1", "ttft_ms": 4.5},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "echo", "tool_input": {"value": "ping"}, "call_id": "call-1"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "tool_use", "usage": {"output_tokens": 7}},
                ),
            ],
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-2", "ttft_ms": 7.0},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn", "usage": {"output_tokens": 3}},
                ),
            ],
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
    assert produced[-1].text == "done"
    assert not any(message.role == MessageRole.TOOL for message in produced)
    assert any(
        message.role == MessageRole.USER
        and any(isinstance(block, ToolResultBlock) for block in message.content)
        for message in produced
    )
    loaded = asyncio.run(transcript_store.load("session-1"))
    assert len(loaded.entries) == len(controller.messages)
    assert len(model_client.requests) == 2
    assert model_client.requests[0].abort_signal is not None
    assert model_client.requests[0].query_source == "user_prompt"
    second_request = model_client.requests[1]
    assert all(message.role != MessageRole.TOOL for message in second_request.messages)
    assert second_request.abort_signal is not None
    assistant_tool_use = next(
        message
        for message in second_request.messages
        if message.role == MessageRole.ASSISTANT
        and any(isinstance(block, ToolUseBlock) for block in message.content)
    )
    tool_use_block = next(block for block in assistant_tool_use.content if isinstance(block, ToolUseBlock))
    assert tool_use_block.tool_use_id == "call-1"
    tool_result_message = next(
        message
        for message in second_request.messages
        if message.role == MessageRole.USER
        and any(isinstance(block, ToolResultBlock) for block in message.content)
    )
    tool_result_block = next(
        block for block in tool_result_message.content if isinstance(block, ToolResultBlock)
    )
    assert tool_result_block.tool_use_id == "call-1"
    assert tool_result_block.content == {"echo": "ping"}
    assert produced[-1].metadata["request_id"] == "req-2"
    assert produced[-1].metadata["stop_reason"] == "end_turn"
    assert produced[-1].metadata["ttft_ms"] == 7.0
    assert produced[-1].metadata["usage"] == {"output_tokens": 3}

    controller.interrupt()
    assert controller.state.status == SessionStatus.INTERRUPTED
    asyncio.run(controller.resume())
    assert controller.state.status == SessionStatus.READY
    assert len(controller.messages) == len(loaded.entries)
    assert all(entry.turn_id is not None for entry in loaded.entries)


def test_session_controller_close_is_idempotent(tmp_path: Path) -> None:
    services = RuntimeServices()
    session_end_statuses: list[str] = []
    services.hook_bus.register(
        session_id="session-close",
        owner="test",
        phase=RuntimeHookPhase.SESSION_END,
        handler=lambda payload: session_end_statuses.append(payload.final_status),
    )
    controller = SessionController(
        session_id="session-close",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=FakeModelClient([]), tool_registry=ToolRegistry(), runtime_services=services),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System prompt",
        runtime_services=services,
    )

    asyncio.run(controller.start())
    asyncio.run(controller.close())
    asyncio.run(controller.close(final_status="failed"))

    assert session_end_statuses == ["completed"]
    assert controller.state.status == SessionStatus.COMPLETED


def test_session_controller_streams_turn_events_until_idle(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-stream"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "streamed reply"}),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn"},
                ),
            ]
        ]
    )
    controller = SessionController(
        session_id="session-stream",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry()),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System prompt",
    )
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "hello"))

    async def collect():
        events = []
        async for event in controller.stream_until_idle():
            events.append(event)
        return events

    events = asyncio.run(collect())

    assert [event.event_type.value for event in events] == [
        "request_start",
        "stream_progress",
        "stream_progress",
        "stream_progress",
        "message",
        "attempt_finished",
        "terminal",
    ]
    assert controller.state.status == SessionStatus.READY
    assert controller.messages[-1].text == "streamed reply"


def test_session_controller_projects_interrupted_terminal_to_interrupted(tmp_path: Path) -> None:
    class InterruptibleModelClient:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
            raise NotImplementedError

        async def stream(self, request: ModelRequest):
            self.requests.append(request)
            yield ModelStreamEvent(
                ModelStreamEventType.MESSAGE_START,
                {"request_id": "req-interrupt"},
            )
            yield ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "partial"})
            while request.abort_signal is not None and not request.abort_signal.aborted:
                await asyncio.sleep(0)

    model_client = InterruptibleModelClient()
    controller = SessionController(
        session_id="session-interrupt",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry()),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System prompt",
    )
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "hello"))

    async def scenario():
        events_task = asyncio.create_task(collect())
        while not model_client.requests:
            await asyncio.sleep(0)
        controller.interrupt("user_cancel")
        return await events_task

    async def collect():
        return [event async for event in controller.stream_until_idle()]

    events = asyncio.run(scenario())

    terminal = next(event for event in events if event.event_type.value == "terminal")
    assert terminal.terminal is not None
    assert terminal.terminal.stop_reason == "interrupted"
    assert controller.state.status == SessionStatus.INTERRUPTED


def test_session_controller_persists_ingress_messages_before_first_request(tmp_path: Path) -> None:
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")

    class TranscriptAwareModelClient:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []
            self.transcript_snapshot: list[tuple[str, str]] = []

        async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
            raise NotImplementedError

        async def stream(self, request: ModelRequest):
            self.requests.append(request)
            transcript = await transcript_store.load("session-ordering")
            self.transcript_snapshot = [
                (entry.message.role.value, entry.message.text)
                for entry in transcript.entries
            ]
            yield ModelStreamEvent(
                ModelStreamEventType.MESSAGE_START,
                {"request_id": "req-ordering"},
            )
            yield ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "ordered"})
            yield ModelStreamEvent(
                ModelStreamEventType.MESSAGE_STOP,
                {"stop_reason": "end_turn"},
            )

    model_client = TranscriptAwareModelClient()
    controller = SessionController(
        session_id="session-ordering",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry()),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
    )
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "hello ordering"))

    produced = asyncio.run(controller.run_until_idle())

    assert model_client.transcript_snapshot == [("user", "hello ordering")]
    assert model_client.requests[0].messages[0].role == MessageRole.USER
    assert model_client.requests[0].messages[0].text == "hello ordering"
    assert produced[-1].text == "ordered"


def test_session_controller_handles_local_only_host_event_without_turn_execution(tmp_path: Path) -> None:
    class UnexpectedTurnModelClient:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
            raise NotImplementedError

        async def stream(self, request: ModelRequest):
            self.requests.append(request)
            raise AssertionError("local_only ingress should not start turn execution")
            yield  # pragma: no cover - keep generator form

    model_client = UnexpectedTurnModelClient()
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    controller = SessionController(
        session_id="session-local-only",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry()),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
    )
    controller.enqueue_event(
        InboundEvent(
            InboundEventType.HOST_EVENT,
            "Refresh complete",
            metadata={"private_updates": {"refresh": True}},
        )
    )

    produced = asyncio.run(controller.run_until_idle())
    transcript = asyncio.run(transcript_store.load("session-local-only"))
    notifications = controller.runtime_services.host.current_notifications()

    assert produced == ()
    assert model_client.requests == []
    assert transcript.entries == ()
    assert [message.text for message in notifications] == ["Refresh complete"]
    assert notifications[0].metadata["ingress_replay"] is True
    assert controller.state.metadata["refresh"] is True


def test_session_controller_carries_local_only_private_updates_into_next_turn(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-carried-private"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "turn reply"}),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn"},
                ),
            ]
        ]
    )
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    controller = SessionController(
        session_id="session-carried-private",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry()),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
    )

    controller.enqueue_event(
        InboundEvent(
            InboundEventType.HOST_EVENT,
            "Refresh complete",
            metadata={"private_updates": {"host_hint": "persist-me"}},
        )
    )
    asyncio.run(controller.run_until_idle())

    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "hello"))
    produced = asyncio.run(controller.run_until_idle())

    request = model_client.requests[0]
    assert produced[-1].text == "turn reply"
    assert request.private_context.extensions["host_hint"] == "persist-me"
    assert request.turn_context.prompt_context.session_hints == {}
    assert "host_hint: persist-me" not in request.system_prompt


def test_session_controller_close_clears_session_scoped_hooks(tmp_path: Path) -> None:
    services = RuntimeServices()
    session_start_hits: list[str] = []
    services.hook_bus.register(
        session_id="session-reopen",
        owner="test",
        phase=RuntimeHookPhase.SESSION_START,
        handler=lambda payload: session_start_hits.append(payload.session_id),
    )

    first = SessionController(
        session_id="session-reopen",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=FakeModelClient([]), tool_registry=ToolRegistry(), runtime_services=services),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System prompt",
        runtime_services=services,
    )

    asyncio.run(first.start())
    asyncio.run(first.close())

    second = SessionController(
        session_id="session-reopen",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=FakeModelClient([]), tool_registry=ToolRegistry(), runtime_services=services),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System prompt",
        runtime_services=services,
    )

    asyncio.run(second.start())
    asyncio.run(second.close())

    assert session_start_hits == ["session-reopen"]


def test_session_controller_admits_host_generated_prompt_with_ingress_role_preserved(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-system"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "system reply"}),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn"},
                ),
            ]
        ]
    )
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    controller = SessionController(
        session_id="session-system",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry()),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
    )
    controller.enqueue_event(InboundEvent(InboundEventType.SYSTEM_MESSAGE, "System override"))

    asyncio.run(controller.run_until_idle())
    loaded = asyncio.run(transcript_store.load("session-system"))

    assert model_client.requests[0].query_source == "system_message"
    assert model_client.requests[0].messages[0].role == MessageRole.SYSTEM
    assert loaded.entries[0].message.role == MessageRole.SYSTEM
    assert loaded.entries[0].message.metadata["source"] == "system_message"


def test_session_controller_records_task_notifications_without_turn_execution(tmp_path: Path) -> None:
    class UnexpectedTurnModelClient:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
            raise NotImplementedError

        async def stream(self, request: ModelRequest):
            self.requests.append(request)
            raise AssertionError("transcript_only ingress should not start turn execution")
            yield  # pragma: no cover - keep generator form

    model_client = UnexpectedTurnModelClient()
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    controller = SessionController(
        session_id="session-task",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry()),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
    )
    controller.enqueue_event(InboundEvent(InboundEventType.TASK_NOTIFICATION, "Task finished"))

    produced = asyncio.run(controller.run_until_idle())
    loaded = asyncio.run(transcript_store.load("session-task"))

    assert produced == ()
    assert model_client.requests == []
    assert [entry.message.role for entry in loaded.entries] == [MessageRole.NOTIFICATION]
    assert [entry.message.text for entry in loaded.entries] == ["Task finished"]
