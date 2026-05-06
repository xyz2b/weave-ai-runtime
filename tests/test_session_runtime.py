import asyncio
from pathlib import Path

import pytest

from weavert.contracts import (
    MessageAttachment,
    MessageRole,
    RuntimeMessage,
    ToolResultBlock,
    ToolUseBlock,
)
from weavert.definitions import AgentDefinition, ToolDefinition, ToolTraits
from weavert.hooks import RuntimeHookPhase
from weavert.registries import ToolRegistry
from weavert.package_system.protocols import (
    IngressReceiptHandlerBinding,
    PackageLifecycleParticipant,
    PackageLifecyclePhase,
    PackageOwnership,
)
from weavert.runtime_services import RuntimeServices
from weavert.session_runtime import (
    FileTranscriptStore,
    InboundEvent,
    InboundEventType,
    SessionController,
)
from weavert.session_runtime.models import SessionStatus
from weavert.turn_engine import (
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    PromptComposer,
    TurnEngine,
    TurnPostEffects,
    TurnStreamEvent,
    TurnStreamEventType,
    TurnTerminal,
    TurnTerminalReason,
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


def test_session_controller_resume_then_start_dispatches_session_open_once(tmp_path: Path) -> None:
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    services = RuntimeServices()
    observed: list[tuple[str, str]] = []
    owner = PackageOwnership(
        package_name="runtime-test",
        package_role="capability",
        surface="lifecycle",
    )

    def record_session_open(*, phase, session, **_kwargs) -> None:
        observed.append((phase.value, session.state.session_id))

    services.register_lifecycle_participant(
        PackageLifecycleParticipant(
            phase=PackageLifecyclePhase.SESSION_OPEN,
            name="record-session-open",
            handler=record_session_open,
            owner=owner,
        )
    )
    controller = SessionController(
        session_id="session-resume-start",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=FakeModelClient([]), tool_registry=ToolRegistry(), runtime_services=services),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
        runtime_services=services,
    )

    asyncio.run(controller.resume())
    asyncio.run(controller.start())

    assert observed == [(PackageLifecyclePhase.SESSION_OPEN.value, "session-resume-start")]
    assert controller.state.status == SessionStatus.READY


def test_session_controller_uses_canonical_memory_resolver_for_session_start(tmp_path: Path) -> None:
    class BrokenMemorySlot:
        pass

    class RecordingMemoryService:
        def __init__(self) -> None:
            self.started: list[dict[str, object]] = []
            self.artifacts: list[dict[str, object]] = []

        async def start_session(self, **kwargs):
            self.started.append(dict(kwargs))

        def ensure_session_artifacts(self, **kwargs) -> None:
            self.artifacts.append(dict(kwargs))

    class ResolverOnlyRuntimeServices(RuntimeServices):
        def __init__(self, canonical_memory: RecordingMemoryService) -> None:
            super().__init__(memory=BrokenMemorySlot())
            self._canonical_memory = canonical_memory

        def resolve_memory_service(self):
            return getattr(self, "_canonical_memory", object.__getattribute__(self, "memory"))

    canonical_memory = RecordingMemoryService()
    services = ResolverOnlyRuntimeServices(canonical_memory)
    agent = AgentDefinition(name="main-router", description="router", prompt="Route the turn")
    controller = SessionController(
        session_id="session-resolver",
        agent=agent,
        turn_engine=TurnEngine(
            model_client=FakeModelClient([]),
            tool_registry=ToolRegistry(),
            runtime_services=services,
        ),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System prompt",
        runtime_services=services,
    )

    asyncio.run(controller._ensure_session_runtime_started())

    assert len(canonical_memory.started) == 1
    assert canonical_memory.started[0]["session_id"] == "session-resolver"
    assert canonical_memory.started[0]["agent"] == agent
    assert canonical_memory.started[0]["cwd"] == str(tmp_path)
    assert canonical_memory.started[0]["set_default"] is True
    assert canonical_memory.artifacts == [
        {
            "session_id": "session-resolver",
            "agent": agent,
            "cwd": str(tmp_path),
            "status": "active",
        }
    ]


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


def test_session_controller_passes_explicit_context_carriers_to_turn_engine(tmp_path: Path) -> None:
    class RecordingTurnEngine:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def run_turn_stream(self, **kwargs):
            self.calls.append(kwargs)
            yield TurnStreamEvent(
                event_type=TurnStreamEventType.TERMINAL,
                iteration=1,
                terminal=TurnTerminal(
                    reason=TurnTerminalReason.END_TURN,
                    post_effects=TurnPostEffects(session_status_hint="ready"),
                ),
            )

    engine = RecordingTurnEngine()
    controller = SessionController(
        session_id="session-explicit-context",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=engine,  # type: ignore[arg-type]
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System prompt",
    )
    controller.enqueue_event(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "Use explicit carriers",
            metadata={
                "prompt_updates": {"topic": "ops"},
                "private_updates": {"host_hint": "keep-private"},
            },
        )
    )

    asyncio.run(controller.run_until_idle())

    call = engine.calls[0]
    assert call["runtime_context"] == {
        "command_type": "user_prompt",
        "query_source": "user_prompt",
    }
    assert call["prompt_context"].session_hints == {"topic": "ops"}
    assert call["private_context"].extensions["host_hint"] == "keep-private"
    assert call["private_context"].permission_context is not None
    assert controller.current_private_context().extensions["host_hint"] == "keep-private"


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
    assert controller.current_private_context().extensions["host_hint"] == "persist-me"
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


def test_session_controller_executes_completion_receipts_after_ingress_commit(tmp_path: Path) -> None:
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    services = RuntimeServices()
    observations: list[dict[str, object]] = []

    async def record_receipt(*, receipt, services, session, **_kwargs):
        transcript = await transcript_store.load(session.state.session_id)
        session_metadata = await transcript_store.load_session_metadata(session.state.session_id)
        observations.append(
            {
                "receipt_id": receipt.receipt_id,
                "messages": [entry.message.text for entry in transcript.entries],
                "notifications": [message.text for message in services.host.current_notifications()],
                "private_updates": dict(session_metadata or {}),
            }
        )

    owner = PackageOwnership(
        package_name="runtime-test",
        package_role="capability",
        surface="ingress_receipt",
    )
    services.register_ingress_receipt_handler(
        IngressReceiptHandlerBinding(
            kind="runtime.test.inspect",
            handler=record_receipt,
            owner=owner,
        )
    )
    controller = SessionController(
        session_id="session-receipt-order",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=FakeModelClient([]), tool_registry=ToolRegistry(), runtime_services=services),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
        runtime_services=services,
    )
    controller.enqueue_event(
        InboundEvent(
            InboundEventType.HOST_EVENT,
            "Transcript before receipts",
            metadata={
                "admission_kind": "transcript_only",
                "role": "notification",
                "private_updates": {"team_id": "team-1"},
                "replay_outputs": [
                    {
                        "output_id": "replay-1",
                        "role": "notification",
                        "content": "Replay before receipts",
                    }
                ],
                "completion_receipts": [
                    {"receipt_id": "receipt-1", "kind": "runtime.test.inspect", "payload": {"step": 1}},
                    {"receipt_id": "receipt-2", "kind": "runtime.test.inspect", "payload": {"step": 2}},
                ],
            },
        )
    )

    asyncio.run(controller.run_until_idle())

    assert observations == [
        {
            "receipt_id": "receipt-1",
            "messages": ["Transcript before receipts"],
            "notifications": ["Replay before receipts"],
            "private_updates": {"team_id": "team-1"},
        },
        {
            "receipt_id": "receipt-2",
            "messages": ["Transcript before receipts"],
            "notifications": ["Replay before receipts"],
            "private_updates": {"team_id": "team-1"},
        },
    ]


def test_session_controller_stops_completion_receipts_after_first_failure(tmp_path: Path) -> None:
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    services = RuntimeServices()
    attempted_receipts: list[str] = []

    async def fail_receipt(*, receipt, **_kwargs):
        attempted_receipts.append(receipt.receipt_id)
        raise RuntimeError("boom")

    async def later_receipt(*, receipt, **_kwargs):
        attempted_receipts.append(receipt.receipt_id)

    owner = PackageOwnership(
        package_name="runtime-test",
        package_role="capability",
        surface="ingress_receipt",
    )
    services.register_ingress_receipt_handler(
        IngressReceiptHandlerBinding(
            kind="runtime.test.fail",
            handler=fail_receipt,
            owner=owner,
        )
    )
    services.register_ingress_receipt_handler(
        IngressReceiptHandlerBinding(
            kind="runtime.test.later",
            handler=later_receipt,
            owner=owner,
        )
    )
    controller = SessionController(
        session_id="session-receipt-failure",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=FakeModelClient([]), tool_registry=ToolRegistry(), runtime_services=services),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
        runtime_services=services,
    )
    controller.enqueue_event(
        InboundEvent(
            InboundEventType.HOST_EVENT,
            "Failure still commits ingress",
            metadata={
                "admission_kind": "transcript_only",
                "role": "notification",
                "private_updates": {"team_id": "team-2"},
                "replay_outputs": [
                    {
                        "output_id": "replay-failure",
                        "role": "notification",
                        "content": "Replay committed",
                    }
                ],
                "completion_receipts": [
                    {"receipt_id": "receipt-fail", "kind": "runtime.test.fail"},
                    {"receipt_id": "receipt-later", "kind": "runtime.test.later"},
                ],
            },
        )
    )

    with pytest.raises(RuntimeError, match="runtime.test.fail"):
        asyncio.run(controller.run_until_idle())

    loaded = asyncio.run(transcript_store.load("session-receipt-failure"))
    persisted = asyncio.run(transcript_store.load_session_metadata("session-receipt-failure"))

    assert attempted_receipts == ["receipt-fail"]
    assert [entry.message.text for entry in loaded.entries] == ["Failure still commits ingress"]
    assert [message.text for message in services.host.current_notifications()] == ["Replay committed"]
    assert persisted is not None
    assert persisted["team_id"] == "team-2"
    assert persisted["last_ingress_completion_receipt_failure"] == {
        "receipt_id": "receipt-fail",
        "kind": "runtime.test.fail",
        "error": "boom",
    }


def test_session_controller_restores_ready_state_when_admit_turn_receipt_fails(tmp_path: Path) -> None:
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    services = RuntimeServices()
    model_client = FakeModelClient([])
    attempted_receipts: list[str] = []

    async def fail_receipt(*, receipt, **_kwargs):
        attempted_receipts.append(receipt.receipt_id)
        raise RuntimeError("boom")

    owner = PackageOwnership(
        package_name="runtime-test",
        package_role="capability",
        surface="ingress_receipt",
    )
    services.register_ingress_receipt_handler(
        IngressReceiptHandlerBinding(
            kind="runtime.test.fail",
            handler=fail_receipt,
            owner=owner,
        )
    )
    controller = SessionController(
        session_id="session-admit-turn-receipt-failure",
        agent=AgentDefinition(name="main-router", description="router", prompt="Route the turn"),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry(), runtime_services=services),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System prompt",
        runtime_services=services,
    )
    controller.enqueue_event(
        InboundEvent(
            InboundEventType.HOST_EVENT,
            "Turn blocked by receipt failure",
            metadata={
                "admission_kind": "admit_turn",
                "completion_receipts": [
                    {"receipt_id": "receipt-fail", "kind": "runtime.test.fail"},
                ],
            },
        )
    )

    with pytest.raises(RuntimeError, match="runtime.test.fail"):
        asyncio.run(controller.run_until_idle())

    loaded = asyncio.run(transcript_store.load("session-admit-turn-receipt-failure"))

    assert attempted_receipts == ["receipt-fail"]
    assert model_client.requests == []
    assert controller.state.status == SessionStatus.READY
    assert controller.state.active_turn_id is None
    assert [entry.message.text for entry in loaded.entries] == ["Turn blocked by receipt failure"]
