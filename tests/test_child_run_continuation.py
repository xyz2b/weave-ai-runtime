import asyncio
from pathlib import Path

from runtime.agent_execution import AgentExecutionSpec, AgentRunStatus, InMemoryChildRunStore, SpawnMode
from runtime.agent_execution_service import AgentExecutionService
from runtime.agent_runtime import AgentInvocation
from runtime.contracts import MessageRole, RuntimeMessage
from runtime.definitions import AgentDefinition, IsolationMode
from runtime.isolation import IsolationLease
from runtime.registries import AgentRegistry, SkillRegistry, ToolRegistry
from runtime.runtime_services import RuntimeServices
from runtime.session_runtime import FileTranscriptStore, SessionController
from runtime.session_runtime.models import SessionStatus
from runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, TurnEngine, TurnStreamEventType


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


def test_terminal_child_run_wakes_waiting_session_and_preserves_child_run_event(tmp_path: Path) -> None:
    observed_events: list[tuple[str, object]] = []
    services = RuntimeServices()
    services.configure_compat(turn_event_sink=lambda session_id, event: observed_events.append((session_id, event)))
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-child-wakeup"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Coordinator resumed"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    turn_engine, execution_service = _build_execution_service(tmp_path, services=services, model_client=model_client)
    controller = _build_controller(
        tmp_path,
        services=services,
        turn_engine=turn_engine,
        session_id="session-child-wakeup",
    )

    asyncio.run(controller.start())
    controller.state.status = SessionStatus.WAITING

    invocation, spec = _child_invocation(tmp_path, session_id=controller.state.session_id)
    asyncio.run(
        execution_service.write_terminal_record(
            invocation,
            spec,
            status=AgentRunStatus.COMPLETED,
        )
    )

    child_events = [
        event
        for _, event in observed_events
        if getattr(event, "event_type", None) == TurnStreamEventType.CHILD_RUN
    ]

    assert len(child_events) == 1
    assert child_events[0].child_run is not None
    assert child_events[0].child_run.status == AgentRunStatus.COMPLETED
    assert controller.state.status == SessionStatus.READY
    assert controller.state.queued_commands == []
    assert model_client.requests[0].query_source == "task_notification"
    assert model_client.requests[0].private_context.extensions["child_run_continuation"]["summary"] == (
        "Child run 'verification' completed without a textual assistant summary."
    )
    assert any(
        message.role == MessageRole.NOTIFICATION
        and message.text == "Child run 'verification' completed without a textual assistant summary."
        for message in controller.messages
    )
    assert controller.messages[-1].text == "Coordinator resumed"


def test_terminal_child_run_queues_ready_session_by_default(tmp_path: Path) -> None:
    services = RuntimeServices()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-child-ready"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Queued continuation"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    turn_engine, execution_service = _build_execution_service(tmp_path, services=services, model_client=model_client)
    controller = _build_controller(
        tmp_path,
        services=services,
        turn_engine=turn_engine,
        session_id="session-child-ready",
    )

    asyncio.run(controller.start())

    invocation, spec = _child_invocation(tmp_path, session_id=controller.state.session_id)
    asyncio.run(
        execution_service.write_terminal_record(
            invocation,
            spec,
            status=AgentRunStatus.COMPLETED,
        )
    )

    assert controller.state.status == SessionStatus.READY
    assert len(controller.state.queued_commands) == 1
    assert (
        controller.state.queued_commands[0].payload["metadata"]["private_updates"]["child_run_continuation"][
            "summary"
        ]
        == "Child run 'verification' completed without a textual assistant summary."
    )
    assert model_client.requests == []

    produced = asyncio.run(controller.run_until_idle())

    assert produced[-1].text == "Queued continuation"
    assert controller.state.status == SessionStatus.READY


def test_terminal_child_run_completing_during_parent_turn_is_queued_for_later_drain(tmp_path: Path) -> None:
    services = RuntimeServices()
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-child-running-parent"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Queued after parent turn"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    turn_engine, execution_service = _build_execution_service(tmp_path, services=services, model_client=model_client)
    controller = _build_controller(
        tmp_path,
        services=services,
        turn_engine=turn_engine,
        session_id="session-child-running-parent",
    )

    asyncio.run(controller.start())

    invocation, spec = _child_invocation(
        tmp_path,
        session_id=controller.state.session_id,
        run_id="child-run-running-parent",
        parent_turn_id="parent-turn-active",
    )
    controller.state.status = SessionStatus.RUNNING
    controller.state.active_turn_id = spec.parent_turn_id

    asyncio.run(
        execution_service.write_terminal_record(
            invocation,
            spec,
            status=AgentRunStatus.COMPLETED,
        )
    )

    assert controller.state.status == SessionStatus.RUNNING
    assert controller.state.active_turn_id == "parent-turn-active"
    assert model_client.requests == []
    assert len(controller.state.queued_commands) == 1
    assert (
        controller.state.queued_commands[0].payload["metadata"]["private_updates"]["child_run_continuation"][
            "summary"
        ]
        == "Child run 'verification' completed without a textual assistant summary."
    )
    controller.state.status = SessionStatus.READY
    controller.state.active_turn_id = None

    produced = asyncio.run(controller.run_until_idle())

    assert model_client.requests[0].query_source == "task_notification"
    assert produced[-1].text == "Queued after parent turn"
    assert controller.state.status == SessionStatus.READY


def test_child_execution_uses_canonical_isolation_resolver(tmp_path: Path) -> None:
    class BrokenIsolationSlot:
        async def prepare(self, **_kwargs):
            raise AssertionError("raw isolation slot should not be used")

        async def cleanup(self, _lease):
            raise AssertionError("raw isolation slot should not be used")

    class RecordingIsolationService:
        def __init__(self) -> None:
            self.prepared: list[dict[str, object]] = []
            self.cleaned: list[dict[str, object]] = []

        async def prepare(self, **kwargs):
            self.prepared.append(dict(kwargs))
            return IsolationLease(
                session_id=kwargs["session_id"],
                agent_name=kwargs["agent_name"],
                mode=kwargs["mode"],
                working_directory=kwargs["cwd"],
                adapter_name="RecordingIsolationService",
            )

        async def cleanup(self, lease) -> None:
            self.cleaned.append(
                {
                    "session_id": lease.session_id,
                    "agent_name": lease.agent_name,
                    "mode": lease.mode,
                    "working_directory": lease.working_directory,
                }
            )

    class ResolverOnlyRuntimeServices(RuntimeServices):
        def __init__(self, canonical_isolation: RecordingIsolationService) -> None:
            super().__init__(isolation=BrokenIsolationSlot())
            self._canonical_isolation = canonical_isolation

        def resolve_isolation_service(self):
            return getattr(self, "_canonical_isolation", object.__getattribute__(self, "isolation"))

    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-isolation-resolver"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    canonical_isolation = RecordingIsolationService()
    services = ResolverOnlyRuntimeServices(canonical_isolation)
    _turn_engine, execution_service = _build_execution_service(tmp_path, services=services, model_client=model_client)
    invocation, spec = _child_invocation(
        tmp_path,
        session_id="session-isolation-resolver",
        run_id="child-run-isolation-resolver",
    )

    result = asyncio.run(execution_service.run(invocation, spec))

    assert result.status == AgentRunStatus.COMPLETED.value
    assert len(canonical_isolation.prepared) == 1
    assert canonical_isolation.prepared[0]["session_id"] == "session-isolation-resolver"
    assert canonical_isolation.prepared[0]["agent_name"] == "verification"
    assert canonical_isolation.prepared[0]["mode"] == IsolationMode.NONE
    assert canonical_isolation.prepared[0]["cwd"] == tmp_path
    assert len(canonical_isolation.cleaned) == 1
    assert canonical_isolation.cleaned[0] == {
        "session_id": "session-isolation-resolver",
        "agent_name": "verification",
        "mode": IsolationMode.NONE,
        "working_directory": tmp_path,
    }


def test_child_run_continuation_dedupes_session_delivery_but_not_child_run_observability(tmp_path: Path) -> None:
    observed_events: list[tuple[str, object]] = []
    services = RuntimeServices()
    services.configure_compat(turn_event_sink=lambda session_id, event: observed_events.append((session_id, event)))
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-child-dedupe"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "Resumed once"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    turn_engine, execution_service = _build_execution_service(tmp_path, services=services, model_client=model_client)
    controller = _build_controller(
        tmp_path,
        services=services,
        turn_engine=turn_engine,
        session_id="session-child-dedupe",
    )

    asyncio.run(controller.start())
    controller.state.status = SessionStatus.WAITING

    invocation, spec = _child_invocation(tmp_path, session_id=controller.state.session_id, run_id="child-run-dedupe")
    asyncio.run(
        execution_service.write_terminal_record(
            invocation,
            spec,
            status=AgentRunStatus.COMPLETED,
        )
    )
    asyncio.run(
        execution_service.write_terminal_record(
            invocation,
            spec,
            status=AgentRunStatus.COMPLETED,
        )
    )

    child_events = [
        event
        for _, event in observed_events
        if getattr(event, "event_type", None) == TurnStreamEventType.CHILD_RUN
    ]

    assert len(child_events) == 2
    assert len(model_client.requests) == 1
    assert controller.state.queued_commands == []
    assert controller.state.status == SessionStatus.READY
    assert controller.messages[-1].text == "Resumed once"


def _build_execution_service(
    tmp_path: Path,
    *,
    services: RuntimeServices,
    model_client: FakeModelClient,
) -> tuple[TurnEngine, AgentExecutionService]:
    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentDefinition(name="verification", description="verify", prompt="verify")
    )
    turn_engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        runtime_services=services,
    )
    execution_service = AgentExecutionService(
        turn_engine=turn_engine,
        agent_registry=agent_registry,
        tool_registry=ToolRegistry(),
        skill_registry=SkillRegistry(),
        runtime_services=services,
        run_store=InMemoryChildRunStore(),
    )
    return turn_engine, execution_service


def _build_controller(
    tmp_path: Path,
    *,
    services: RuntimeServices,
    turn_engine: TurnEngine,
    session_id: str,
) -> SessionController:
    return SessionController(
        session_id=session_id,
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
        turn_engine=turn_engine,
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System prompt",
        runtime_services=services,
    )


def _child_invocation(
    tmp_path: Path,
    *,
    session_id: str,
    run_id: str = "child-run-1",
    parent_turn_id: str = "parent-turn",
) -> tuple[AgentInvocation, AgentExecutionSpec]:
    invocation = AgentInvocation(
        agent_name="verification",
        prompt="run child checks",
        session_id=session_id,
        cwd=tmp_path,
        background=True,
        query_source="background_agent",
        parent_run_id="parent-run",
        parent_turn_id=parent_turn_id,
    )
    spec = AgentExecutionSpec(
        run_id=run_id,
        parent_run_id="parent-run",
        session_id=session_id,
        parent_turn_id=parent_turn_id,
        turn_id=f"{run_id}-turn",
        agent_name="verification",
        spawn_mode=SpawnMode.BACKGROUND,
        query_source="background_agent",
        prompt_messages=(
            RuntimeMessage(
                message_id=f"{run_id}-message",
                role=MessageRole.USER,
                content="run child checks",
            ),
        ),
        cwd=tmp_path,
        background=True,
    )
    return invocation, spec
