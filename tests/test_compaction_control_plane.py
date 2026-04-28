import asyncio
from pathlib import Path

from weavert.agent_runtime import AgentInvocation, AgentRuntime
from weavert.compaction import (
    CompactionManager,
    CompactionStepResult,
    ContextPressure,
)
from weavert.contracts import MessageRole, RuntimeMessage, RuntimePrivateContext
from weavert.definitions import AgentDefinition
from weavert.registries import AgentRegistry, SkillRegistry, ToolRegistry
from weavert.runtime_services import RuntimeServices
from weavert.session_runtime import InMemoryTranscriptStore, InboundEvent, InboundEventType, SessionController
from weavert.tasking import TaskManager
from weavert.turn_engine import (
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    TurnEngine,
    TurnStreamEventType,
)


class CaptureModelClient:
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


class RecordingStrategy:
    def __init__(self, name: str, order: int) -> None:
        self.name = name
        self.order = order

    async def apply(
        self,
        request,
        *,
        policy,
        pressure: ContextPressure,
        prior_steps=(),
    ):
        _ = policy, pressure
        return CompactionStepResult(
            strategy_name=self.name,
            applied=True,
            messages=request.messages,
            fragments=(self.name,),
            metadata={"prior": [step.strategy_name for step in prior_steps]},
        )


def test_compaction_manager_applies_ordered_strategies() -> None:
    manager = CompactionManager(
        strategies=(
            RecordingStrategy("late", 20),
            RecordingStrategy("early", 10),
        )
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Route")

    result = asyncio.run(
        manager.prepare_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=(RuntimeMessage(message_id="m1", role=MessageRole.USER, content="hello"),),
        )
    )

    assert result.applied is True
    assert [step.strategy_name for step in result.steps] == ["early", "late"]
    assert result.steps[1].metadata["prior"] == ["early"]
    assert result.fragments == ("early", "late")


def test_compaction_manager_reads_policy_from_private_context_extensions() -> None:
    manager = CompactionManager()
    agent = AgentDefinition(name="main-router", description="router", prompt="Route")

    result = asyncio.run(
        manager.prepare_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=(
                RuntimeMessage(message_id="u1", role=MessageRole.USER, content="older prompt one"),
                RuntimeMessage(message_id="a1", role=MessageRole.ASSISTANT, content="older answer one"),
                RuntimeMessage(message_id="u2", role=MessageRole.USER, content="older prompt two"),
                RuntimeMessage(message_id="a2", role=MessageRole.ASSISTANT, content="older answer two"),
                RuntimeMessage(message_id="u3", role=MessageRole.USER, content="latest prompt"),
            ),
            private_context=RuntimePrivateContext(
                extensions={"compaction_policy": {"max_message_count": 3, "keep_recent_messages": 2}}
            ),
        )
    )

    assert result.applied is True
    assert result.summary is not None
    assert result.policy.max_message_count == 3


def test_turn_engine_emits_structured_compaction_request_context() -> None:
    model_client = CaptureModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-compact"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices(
        compaction=CompactionManager(),
        metadata={"compaction_policy": {"max_message_count": 3, "keep_recent_messages": 2}},
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Route")

    async def collect_events():
        return tuple(
            [
                event
                async for event in engine.run_turn_stream(
                    session_id="session",
                    turn_id="turn",
                    agent=agent,
                    cwd=".",
                    messages=[
                        RuntimeMessage(message_id="u1", role=MessageRole.USER, content="older prompt one"),
                        RuntimeMessage(message_id="a1", role=MessageRole.ASSISTANT, content="older answer one"),
                        RuntimeMessage(message_id="u2", role=MessageRole.USER, content="older prompt two"),
                        RuntimeMessage(message_id="a2", role=MessageRole.ASSISTANT, content="older answer two"),
                        RuntimeMessage(message_id="u3", role=MessageRole.USER, content="latest prompt"),
                    ],
                    base_system_prompt="System",
                )
            ]
        )

    events = asyncio.run(collect_events())

    assert events[0].event_type == TurnStreamEventType.COMPACTION
    request = next(event.request for event in events if event.event_type == TurnStreamEventType.REQUEST_START)
    assert request is not None
    assert request.turn_context.compaction_summary is not None
    assert request.turn_context.compaction_boundary is not None
    assert request.turn_context.compaction_continuation is not None
    assert request.turn_context.compaction_summary["message_count"] == 3
    assert request.turn_context.compaction_boundary["message_count_before"] == 5
    assert request.turn_context.compaction_boundary["message_count_after"] == 3
    assert request.metadata["compaction"]["summary"]["message_count"] == 3
    assert request.messages[0].role == MessageRole.SYSTEM
    assert request.messages[0].text.startswith("Compacted conversation summary:")


def test_sidecars_restart_after_compaction_rewrites_request_inputs() -> None:
    class RestartAwareService:
        def __init__(self, prefix: str) -> None:
            self.prefix = prefix
            self.calls: list[tuple[str, ...]] = []
            self.cancelled = 0

        async def collect(self, **kwargs):
            messages = tuple(kwargs["messages"])
            message_ids = tuple(message.message_id for message in messages)
            self.calls.append(message_ids)
            if len(self.calls) == 1:
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            return (f"{self.prefix}:{','.join(message_ids)}",)

    class YieldingCompactionManager:
        def __init__(self) -> None:
            self._manager = CompactionManager()

        async def prepare_turn(self, **kwargs):
            await asyncio.sleep(0)
            return await self._manager.prepare_turn(**kwargs)

        async def collect(self, **kwargs):
            _ = kwargs
            return ()

    model_client = CaptureModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-sidecars"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    memory_service = RestartAwareService("memory")
    hook_service = RestartAwareService("hook")
    services = RuntimeServices(
        memory=memory_service,
        hooks=hook_service,
        compaction=YieldingCompactionManager(),
        metadata={"compaction_policy": {"max_message_count": 3, "keep_recent_messages": 2}},
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="Route")

    asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=agent,
            cwd=".",
            messages=[
                RuntimeMessage(message_id="u1", role=MessageRole.USER, content="older prompt one"),
                RuntimeMessage(message_id="a1", role=MessageRole.ASSISTANT, content="older answer one"),
                RuntimeMessage(message_id="u2", role=MessageRole.USER, content="older prompt two"),
                RuntimeMessage(message_id="a2", role=MessageRole.ASSISTANT, content="older answer two"),
                RuntimeMessage(message_id="u3", role=MessageRole.USER, content="latest prompt"),
            ],
            base_system_prompt="System",
        )
    )

    request = model_client.requests[0]
    assert memory_service.cancelled == 1
    assert hook_service.cancelled == 1
    assert len(memory_service.calls) == 2
    assert len(hook_service.calls) == 2
    assert memory_service.calls[0] != memory_service.calls[1]
    assert hook_service.calls[0] != hook_service.calls[1]
    assert request.turn_context.memory_fragments == (
        f"memory:{','.join(memory_service.calls[-1])}",
    )
    assert request.turn_context.hook_context == (
        f"hook:{','.join(hook_service.calls[-1])}",
    )


def test_session_resume_uses_rewritten_compacted_transcript() -> None:
    transcript_store = InMemoryTranscriptStore()
    agent = AgentDefinition(name="main-router", description="router", prompt="Route")
    seed_messages = (
        RuntimeMessage(message_id="u1", role=MessageRole.USER, content="older prompt one"),
        RuntimeMessage(message_id="a1", role=MessageRole.ASSISTANT, content="older answer one"),
        RuntimeMessage(message_id="u2", role=MessageRole.USER, content="older prompt two"),
        RuntimeMessage(message_id="a2", role=MessageRole.ASSISTANT, content="older answer two"),
    )

    async def seed() -> None:
        from weavert.turn_engine import TranscriptEntry

        for message in seed_messages:
            await transcript_store.append(
                TranscriptEntry(session_id="session", turn_id="seed-turn", message=message)
            )

    asyncio.run(seed())

    model_client = CaptureModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "after compaction"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "after resume"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    services = RuntimeServices(
        compaction=CompactionManager(),
        metadata={"compaction_policy": {"max_message_count": 3, "keep_recent_messages": 2}},
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    controller = SessionController(
        session_id="session",
        agent=agent,
        turn_engine=engine,
        transcript_store=transcript_store,
        cwd=".",
        system_prompt="System",
        runtime_services=services,
    )

    asyncio.run(controller.resume())
    asyncio.run(controller.start())
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "fresh prompt"))
    produced = asyncio.run(controller.run_until_idle())

    assert produced[-1].text == "after compaction"
    loaded = asyncio.run(transcript_store.load("session"))
    assert len(loaded.entries) == 4
    summary_entry = next(entry for entry in loaded.entries if entry.message.metadata.get("compaction_summary"))
    assert summary_entry.message.metadata["compaction"]["boundary"]["message_count_before"] == 5
    assert controller.state.metadata["compaction_continuation"]["summary_id"] == summary_entry.message.message_id

    resumed = SessionController(
        session_id="session",
        agent=agent,
        turn_engine=engine,
        transcript_store=transcript_store,
        cwd=".",
        system_prompt="System",
        runtime_services=services,
    )
    asyncio.run(resumed.resume())
    asyncio.run(resumed.start())
    resumed.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "continue"))
    resumed_messages = asyncio.run(resumed.run_until_idle())

    assert resumed_messages[-1].text == "after resume"
    second_request = model_client.requests[1]
    assert second_request.metadata["compaction_continuation"]["summary_id"] == summary_entry.message.message_id
    assert second_request.messages[0].metadata["compaction_summary"] is True
    assert all(message.message_id not in {"u1", "a1", "u2"} for message in second_request.messages)


def test_background_agent_inherits_compaction_continuation_metadata(tmp_path: Path) -> None:
    model_client = CaptureModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-bg"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "background answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentDefinition(name="verification", description="verify", prompt="verify", tools=("*",))
    )
    engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        agent_registry=agent_registry,
        skill_registry=SkillRegistry(),
        task_manager=TaskManager(),
    )
    runtime = AgentRuntime(
        turn_engine=engine,
        agent_registry=agent_registry,
        tool_registry=ToolRegistry(),
        skill_registry=SkillRegistry(),
        task_manager=TaskManager(),
    )

    background = asyncio.run(
        runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="background run",
                session_id="session",
                cwd=tmp_path,
                background=True,
                metadata={
                    "compaction_continuation": {
                        "mode": "summary_replay",
                        "summary_id": "summary-123",
                    }
                },
            )
        )
    )
    asyncio.run(runtime.wait_for_background(background.task_id))

    assert model_client.requests[0].metadata["compaction_continuation"]["summary_id"] == "summary-123"
