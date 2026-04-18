import asyncio

from claude_agent_runtime.contracts import MessageRole, TextBlock, ToolResultBlock
from claude_agent_runtime.definitions import AgentDefinition, ToolDefinition, ToolTraits
from claude_agent_runtime.registries import ToolRegistry
from claude_agent_runtime.runtime_services import RuntimeServices
from claude_agent_runtime.turn_engine import (
    ContextAssembler,
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    TurnPhase,
    TurnEngine,
    TurnStreamEventType,
)


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


class InterruptibleModelClient:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        yield ModelStreamEvent(
            ModelStreamEventType.MESSAGE_START,
            {"request_id": "req-interrupt", "ttft_ms": 3.0},
        )
        yield ModelStreamEvent(
            ModelStreamEventType.CONTENT_BLOCK_START,
            {"block_type": "text", "text": "partial output"},
        )
        while request.abort_signal is not None and not request.abort_signal.aborted:
            await asyncio.sleep(0.01)


def test_run_turn_stream_emits_request_message_and_terminal_metadata() -> None:
    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-1", "ttft_ms": 12.5},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_BLOCK_START,
                    {"block_type": "text"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_BLOCK_DELTA,
                    {"block_type": "text", "text": "hello stream"},
                ),
                ModelStreamEvent(ModelStreamEventType.CONTENT_BLOCK_STOP, {"block_type": "text"}),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn", "usage": {"output_tokens": 5}},
                ),
            ]
        ]
    )
    engine = TurnEngine(model_client=model_client, tool_registry=ToolRegistry())
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    async def collect_events():
        events = []
        async for event in engine.run_turn_stream(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
            runtime_context={"query_source": "unit_test"},
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert [event.event_type for event in events] == [
        TurnStreamEventType.REQUEST_START,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.STREAM_PROGRESS,
        TurnStreamEventType.MESSAGE,
        TurnStreamEventType.ATTEMPT_FINISHED,
        TurnStreamEventType.TERMINAL,
    ]
    assert events[0].request is not None
    assert events[0].request.abort_signal is not None
    assert events[0].request.query_source == "unit_test"
    assert events[-3].message is not None
    assert events[-3].message.role == MessageRole.ASSISTANT
    assert events[-3].message.text == "hello stream"
    assert events[-2].attempt is not None
    assert events[-2].attempt.stop_reason == "end_turn"
    assert events[-2].attempt.request_id == "req-1"
    assert events[-2].attempt.produced_tool_calls is False
    assert events[-2].phase == TurnPhase.STREAM_ATTEMPT
    assert events[-1].terminal is not None
    assert events[-1].terminal.request_id == "req-1"
    assert events[-1].terminal.stop_reason == "end_turn"
    assert events[-1].terminal.ttft_ms == 12.5
    assert events[-1].terminal.usage == {"output_tokens": 5}
    assert events[-1].phase == TurnPhase.TERMINAL

    result = asyncio.run(
        TurnEngine(
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(
                            ModelStreamEventType.MESSAGE_START,
                            {"request_id": "req-2", "ttft_ms": 9.0},
                        ),
                        ModelStreamEvent(
                            ModelStreamEventType.CONTENT_DELTA,
                            {"text": "aggregated"},
                        ),
                        ModelStreamEvent(
                            ModelStreamEventType.MESSAGE_STOP,
                            {"stop_reason": "end_turn", "usage": {"output_tokens": 2}},
                        ),
                    ]
                ]
            ),
            tool_registry=ToolRegistry(),
        ).run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )
    assert result.completed is True
    assert result.messages[-1].text == "aggregated"
    assert result.stop_reason == "end_turn"
    assert result.request_id == "req-2"
    assert result.ttft_ms == 9.0
    assert result.usage == {"output_tokens": 2}
    assert result.attempts[0].request_id == "req-2"


def test_tool_continuation_emits_attempt_finished_before_unique_final_terminal() -> None:
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
    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-tool-1"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "echo", "tool_input": {"value": "ping"}, "call_id": "call-1"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "tool_use"},
                ),
            ],
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-tool-2"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_DELTA,
                    {"text": "done"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn"},
                ),
            ],
        ]
    )
    engine = TurnEngine(model_client=model_client, tool_registry=tool_registry)
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer", tools=("*",))

    async def collect_events():
        return [
            event
            async for event in engine.run_turn_stream(
                session_id="session",
                turn_id="turn",
                agent=agent,
                cwd=".",
                messages=[],
                base_system_prompt="System",
            )
        ]

    events = asyncio.run(collect_events())

    attempt_events = [event for event in events if event.event_type == TurnStreamEventType.ATTEMPT_FINISHED]
    terminal_events = [event for event in events if event.event_type == TurnStreamEventType.TERMINAL]

    assert len(attempt_events) == 2
    assert [event.attempt.stop_reason for event in attempt_events if event.attempt is not None] == [
        "tool_use",
        "end_turn",
    ]
    assert attempt_events[0].attempt is not None
    assert attempt_events[0].attempt.produced_tool_calls is True
    assert terminal_events[-1].terminal is not None
    assert terminal_events[-1].terminal.stop_reason == "end_turn"
    assert len(terminal_events) == 1
    assert events.index(attempt_events[0]) < events.index(terminal_events[0])
    tool_result_event = next(
        event
        for event in events
        if event.event_type == TurnStreamEventType.MESSAGE
        and event.message is not None
        and event.message.role == MessageRole.USER
    )
    assert tool_result_event.transition is not None
    assert tool_result_event.transition.reason.value == "next_turn"


def test_tool_context_exposes_turn_scoped_runtime_state() -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="inspect_context",
            description="inspect current tool context",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            execute=lambda _tool_input, context: {
                "roles": [message.role.value for message in context.messages],
                "message_count": len(context.messages),
                "has_abort_signal": context.abort_signal is not None,
                "tool_names": [definition.name for definition in context.tool_pool],
                "has_refresh_callback": context.tool_refresh_callback is not None,
                "has_runtime_services": context.runtime_services is not None,
            },
        )
    )
    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-ctx-1"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "inspect_context", "tool_input": {}, "call_id": "call-ctx-1"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "tool_use"},
                ),
            ],
            [
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_START,
                    {"request_id": "req-ctx-2"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_DELTA,
                    {"text": "context captured"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {"stop_reason": "end_turn"},
                ),
            ],
        ]
    )
    engine = TurnEngine(model_client=model_client, tool_registry=tool_registry)

    async def refresh_tools(context):
        return context.tool_pool

    engine.configure_runtime(tool_refresh_callback=refresh_tools)
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer", tools=("*",))

    result = asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    tool_result_message = next(
        message
        for message in result.messages
        if message.role == MessageRole.USER and any(isinstance(block, ToolResultBlock) for block in message.content)
    )
    tool_result = next(block for block in tool_result_message.content if isinstance(block, ToolResultBlock))

    assert tool_result.content["roles"] == ["assistant"]
    assert tool_result.content["message_count"] == 1
    assert tool_result.content["has_abort_signal"] is True
    assert tool_result.content["tool_names"] == ["inspect_context"]
    assert tool_result.content["has_refresh_callback"] is True
    assert tool_result.content["has_runtime_services"] is True
    assert result.messages[-1].text == "context captured"


def test_runtime_services_contribute_context_during_request_assembly() -> None:
    class StaticContributionService:
        def __init__(self, *lines: str) -> None:
            self._lines = lines

        async def collect(self, **kwargs):
            _ = kwargs
            return self._lines

    model_client = BatchedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-services"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(
        memory=StaticContributionService("Memory line"),
        hooks=StaticContributionService("Hook line"),
        compaction=StaticContributionService("Compaction line"),
        context_assembler=ContextAssembler(),
        metadata={"runtime_id": "unit-test"},
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert request.turn_context.memory_fragments == ("Memory line",)
    assert request.turn_context.hook_context == ("Hook line",)
    assert request.turn_context.compaction_fragments == ("Compaction line",)
    assert request.turn_context.prompt_context.memory_fragments == ("Memory line",)
    assert request.metadata["runtime_id"] == "unit-test"
    assert request.private_context.extensions["runtime_id"] == "unit-test"
    assert "runtime_id" not in request.system_prompt
    assert "Memory line" in request.system_prompt
    assert "Hook line" in request.system_prompt
    assert "Compaction line" in request.system_prompt


def test_interrupt_aborts_model_stream_and_discards_partial_output() -> None:
    model_client = InterruptibleModelClient()
    engine = TurnEngine(model_client=model_client, tool_registry=ToolRegistry())
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")

    async def collect_events():
        events = []
        async for event in engine.run_turn_stream(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
        ):
            events.append(event)
        return events

    async def scenario():
        task = asyncio.create_task(collect_events())
        while not model_client.requests:
            await asyncio.sleep(0)
        engine.interrupt("user_cancel")
        return await task

    events = asyncio.run(scenario())

    assert model_client.requests[0].abort_signal is not None
    assert model_client.requests[0].abort_signal.aborted is True
    assert model_client.requests[0].abort_signal.reason == "user_cancel"
    assert not any(event.event_type == TurnStreamEventType.MESSAGE for event in events)
    discard_event = next(event for event in events if event.event_type == TurnStreamEventType.MESSAGE_DISCARDED)
    assert discard_event.metadata["reason"] == "user_cancel"
    assert len(discard_event.discarded_content) == 1
    assert isinstance(discard_event.discarded_content[0], TextBlock)
    assert discard_event.discarded_content[0].text == "partial output"
    terminal_event = next(event for event in events if event.event_type == TurnStreamEventType.TERMINAL)
    assert terminal_event.terminal is not None
    assert terminal_event.terminal.stop_reason == "interrupted"
    assert terminal_event.terminal.abort_reason == "user_cancel"
    assert terminal_event.terminal.request_id == "req-interrupt"

    async def run_turn_with_interrupt():
        interrupting_client = InterruptibleModelClient()
        interrupting_engine = TurnEngine(model_client=interrupting_client, tool_registry=ToolRegistry())
        task = asyncio.create_task(
            interrupting_engine.run_turn(
                session_id="session",
                turn_id="turn-2",
                agent=agent,
                cwd=".",
                messages=[],
                base_system_prompt="System",
            )
        )
        while not interrupting_client.requests:
            await asyncio.sleep(0)
        interrupting_engine.interrupt("user_cancel")
        return await task

    result = asyncio.run(run_turn_with_interrupt())
    assert result.completed is False
    assert result.messages == []
    assert result.tool_calls == []
    assert result.stop_reason == "interrupted"
    assert result.abort_reason == "user_cancel"
