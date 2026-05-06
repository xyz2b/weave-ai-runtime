import asyncio
from pathlib import Path

from weavert.agent_execution import AgentExecutionSpec, AgentRunRecord, AgentRunStatus, InMemoryChildRunStore, SpawnMode
from weavert.agent_execution_service import AgentExecutionService
from weavert.agent_runtime import AgentInvocation
from weavert.child_result_projection import project_child_run_record
from weavert.definitions import AgentDefinition
from weavert_hosts_reference import SdkHostRuntime
from weavert.registries import AgentRegistry, SkillRegistry, ToolRegistry
from weavert.result_projections import child_summary, terminal_failure
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.runtime_services import RuntimeServices
from weavert.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, TurnEngine, TurnStreamEventType
from weavert.workflow_observability import (
    WORKFLOW_EXTENSION_EVENT_NAMESPACE,
    WorkflowDiagnosticSeverity,
    WorkflowLifecycleStatus,
    WorkflowOutcome,
    resolve_workflow_run_observability,
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


async def _collect_turn_events(model_batches: list[list[ModelStreamEvent]]):
    engine = TurnEngine(model_client=FakeModelClient(model_batches), tool_registry=ToolRegistry())
    agent = AgentDefinition(name="main-router", description="router", prompt="Answer")
    return [
        event
        async for event in engine.run_turn_stream(
            session_id="session-root",
            turn_id="turn-root",
            agent=agent,
            cwd=".",
            messages=[],
            base_system_prompt="System",
            runtime_context={"query_source": "unit_test"},
        )
    ]


def test_turn_stream_events_expose_unified_workflow_observation() -> None:
    events = asyncio.run(
        _collect_turn_events(
            [
                [
                    ModelStreamEvent(
                        ModelStreamEventType.MESSAGE_START,
                        {"request_id": "req-root", "ttft_ms": 5.0},
                    ),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "observed"}),
                    ModelStreamEvent(
                        ModelStreamEventType.MESSAGE_STOP,
                        {"stop_reason": "end_turn", "usage": {"output_tokens": 1}},
                    ),
                ]
            ]
        )
    )

    request_event = next(event for event in events if event.event_type == TurnStreamEventType.REQUEST_START)
    terminal_event = next(event for event in events if event.event_type == TurnStreamEventType.TERMINAL)

    assert request_event.workflow_observation is not None
    assert request_event.workflow_observation.workflow.identity.run_id == "turn-root"
    assert request_event.workflow_observation.workflow.lifecycle_status == WorkflowLifecycleStatus.RUNNING
    assert request_event.workflow_observation.workflow.outcome == WorkflowOutcome.RUNNING
    assert request_event.workflow_observation.workflow.query_source == "unit_test"
    assert request_event.metadata["workflow_observation"]["workflow"]["identity"]["run_id"] == "turn-root"

    assert terminal_event.workflow_observation is not None
    assert terminal_event.workflow_observation.workflow.lifecycle_status == WorkflowLifecycleStatus.COMPLETED
    assert terminal_event.workflow_observation.workflow.outcome == WorkflowOutcome.SUCCEEDED
    assert terminal_event.workflow_observation.workflow.diagnostics == ()


def test_blocking_and_advisory_workflow_diagnostics_are_preserved_across_surfaces() -> None:
    failed_events = asyncio.run(
        _collect_turn_events(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-failed"}),
                    ModelStreamEvent(ModelStreamEventType.ERROR, {"error": "model exploded"}),
                ]
            ]
        )
    )
    failed_terminal = next(event for event in failed_events if event.event_type == TurnStreamEventType.TERMINAL)
    failed_observation = failed_terminal.workflow_observation

    assert failed_observation is not None
    assert failed_observation.workflow.lifecycle_status == WorkflowLifecycleStatus.FAILED
    assert failed_observation.workflow.outcome == WorkflowOutcome.FAILED
    assert failed_observation.workflow.diagnostics[0].severity == WorkflowDiagnosticSeverity.BLOCKING
    assert failed_observation.workflow.diagnostics[0].message == "model exploded"

    child_record = AgentRunRecord(
        run_id="child-max-turns",
        parent_run_id="turn-root",
        session_id="session-root",
        parent_turn_id="turn-root",
        turn_id="child-turn",
        agent_name="reviewer",
        spawn_mode=SpawnMode.SYNC,
        status=AgentRunStatus.MAX_TURNS,
        terminal_metadata={"stop_reason": "max_turns"},
    )
    projection = project_child_run_record(child_record)
    resolved_projection = resolve_workflow_run_observability(projection)
    summary = child_summary((projection,), agent_name="reviewer")

    assert resolved_projection is not None
    assert resolved_projection.lifecycle_status == WorkflowLifecycleStatus.MAX_TURNS
    assert resolved_projection.outcome == WorkflowOutcome.DEGRADED
    assert resolved_projection.diagnostics[0].severity == WorkflowDiagnosticSeverity.ADVISORY
    assert summary is not None
    assert summary.workflow_observability == resolved_projection


def test_host_bridge_emits_unified_workflow_extension_events_for_root_and_child_activity(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-host"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "hosted"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
        )
    )
    root_host = SdkHostRuntime(name="sdk-root")
    bound = runtime.bind_host(root_host)

    asyncio.run(bound.run_prompt("hello host", session_id="host-root-session"))

    root_events = [
        event
        for event in root_host.extension_events
        if getattr(event, "namespace", None) == WORKFLOW_EXTENSION_EVENT_NAMESPACE
    ]
    assert [event.event_type for event in root_events] == ["workflow.started", "workflow.terminal"]
    assert root_events[0].payload["workflow"]["identity"]["run_id"]
    assert root_events[-1].payload["workflow"]["outcome"] == WorkflowOutcome.SUCCEEDED.value

    child_host = SdkHostRuntime(name="sdk-child")
    services = RuntimeServices()
    services.bind_host(child_host)
    agent_registry = AgentRegistry()
    agent_registry.register(AgentDefinition(name="verification", description="verify", prompt="verify"))
    turn_engine = TurnEngine(model_client=FakeModelClient([]), tool_registry=ToolRegistry(), runtime_services=services)
    execution_service = AgentExecutionService(
        turn_engine=turn_engine,
        agent_registry=agent_registry,
        tool_registry=ToolRegistry(),
        skill_registry=SkillRegistry(),
        runtime_services=services,
        run_store=InMemoryChildRunStore(),
    )
    invocation = AgentInvocation(
        agent_name="verification",
        prompt="run checks",
        session_id="host-child-session",
        cwd=tmp_path,
        background=True,
        query_source="background_agent",
        parent_run_id="parent-run",
        parent_turn_id="parent-turn",
    )
    spec = AgentExecutionSpec(
        run_id="child-run-terminal",
        parent_run_id="parent-run",
        session_id="host-child-session",
        parent_turn_id="parent-turn",
        turn_id="child-turn",
        agent_name="verification",
        spawn_mode=SpawnMode.BACKGROUND,
        query_source="background_agent",
        prompt_messages=(),
        cwd=tmp_path,
        background=True,
    )

    asyncio.run(
        execution_service.write_terminal_record(
            invocation,
            spec,
            status=AgentRunStatus.DENIED,
            terminal_metadata={"error": "blocked by policy", "permission_denied": True},
        )
    )

    child_events = [
        event
        for event in child_host.extension_events
        if getattr(event, "namespace", None) == WORKFLOW_EXTENSION_EVENT_NAMESPACE
    ]
    assert [event.event_type for event in child_events] == ["workflow.child.updated"]
    assert child_events[0].payload["workflow"]["run_kind"] == "child"
    assert child_events[0].payload["workflow"]["diagnostics"][0]["code"] == "workflow_permission_denied"


def test_runtime_stream_prompt_preserves_explicit_query_source_across_root_events(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-stream"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "streamed"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
        )
    )

    async def _collect() -> list[object]:
        return [
            event
            async for event in runtime.stream_prompt(
                "Hello stream",
                session_id="workflow-stream-session",
                metadata={"query_source": "workflow_stream_test", "run_id": "workflow-stream-root"},
            )
        ]

    events = asyncio.run(_collect())
    request_event = next(event for event in events if event.event_type == TurnStreamEventType.REQUEST_START)
    terminal_event = next(event for event in events if event.event_type == TurnStreamEventType.TERMINAL)

    assert request_event.workflow_observation is not None
    assert request_event.workflow_observation.workflow.run_id == "workflow-stream-root"
    assert request_event.workflow_observation.workflow.query_source == "workflow_stream_test"
    assert terminal_event.workflow_observation is not None
    assert terminal_event.workflow_observation.workflow.run_id == "workflow-stream-root"
    assert terminal_event.workflow_observation.workflow.query_source == "workflow_stream_test"


def test_workflow_run_reports_and_failure_helpers_share_the_unified_model(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-report"}),
                        ModelStreamEvent(ModelStreamEventType.ERROR, {"error": "report exploded"}),
                    ]
                ]
            ),
        )
    )

    report = asyncio.run(
        runtime.run_prompt_report(
            "Hello runtime",
            session_id="workflow-report-session",
            metadata={
                "query_source": "workflow_report_test",
                "run_id": "workflow-report-root",
                "parent_run_id": "workflow-report-parent",
            },
        )
    )
    failure = terminal_failure(report)

    assert report.turn_id is not None
    assert report.run_id == "workflow-report-root"
    assert report.workflow_observability is not None
    assert report.workflow_observability.identity.turn_id == report.turn_id
    assert report.workflow_observability.linkage.parent_run_id == "workflow-report-parent"
    assert report.workflow_observability.query_source == "workflow_report_test"
    assert report.workflow_observability.lifecycle_status == WorkflowLifecycleStatus.FAILED
    assert report.workflow_observability.diagnostics[0].message == "report exploded"
    assert failure is not None
    assert failure.workflow_observability == report.workflow_observability
