import asyncio
import time
from pathlib import Path
from typing import Any, Sequence

from claude_agent_runtime.contracts import (
    MessageRole,
    RuntimeMessage,
    ToolResultBlock,
    ToolUseBlock,
)
from claude_agent_runtime.definitions import (
    AgentDefinition,
    InterruptBehavior,
    PermissionBehavior,
    PermissionDecision,
    ResolvedToolExecutionSemantics,
    ToolCallStatus,
    ToolClassifierInput,
    ToolDefinition,
    ToolExecutionSemantics,
    ToolFailureClassifier,
    ToolFailureMode,
    ToolFailurePolicy,
    ToolPresentationEmphasis,
    ToolRiskLevel,
    ToolResultSummary,
    ToolResultSummaryStatus,
    ToolTraits,
    ToolUsePresentation,
    ValidationOutcome,
)
from claude_agent_runtime.memory.models import MemoryEntry
from claude_agent_runtime.registries import ToolRegistry
from claude_agent_runtime.tool_executors import select_tool_executor_tier
from claude_agent_runtime.tool_lifecycle import (
    AppStateSet,
    CapabilityRefreshRequested,
    ContextUpdatePhase,
    LegacyContextModifierWrapped,
    MemoryAppended,
    PermissionAllowed,
    PermissionDenied,
    ReplayCommitted,
    ToolCallEnvelope,
    ToolLaneDerivationMode,
    ToolResolutionStatus,
    ToolSchedulerLaneKind,
    TranscriptAttachmentAdded,
)
from claude_agent_runtime.tool_orchestration import StreamingToolOrchestrator
from claude_agent_runtime.tool_resolution import resolve_tool_call
from claude_agent_runtime.tool_runtime import ToolCall, ToolContext
from claude_agent_runtime.turn_engine import (
    ModelInvocationMode,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ModelTerminalMetadata,
    NormalizedModelCapabilities,
    TurnEngine,
    TurnStreamEventType,
)


class ScriptedModelClient:
    def __init__(
        self,
        event_batches: Sequence[Sequence[ModelStreamEvent]],
        *,
        capabilities: NormalizedModelCapabilities | None = None,
    ) -> None:
        self._event_batches = [list(batch) for batch in event_batches]
        self.requests: list[ModelRequest] = []
        self.normalized_model_capabilities = capabilities

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        batch = self._event_batches.pop(0)
        for event in batch:
            yield event


class EarlyStartModelClient:
    def __init__(self, started_event: asyncio.Event) -> None:
        self.requests: list[ModelRequest] = []
        self.normalized_model_capabilities = NormalizedModelCapabilities(
            structured_tool_calls=True,
            streaming_tool_call_deltas=True,
            tool_call_finalize_boundary=True,
            parseable_tool_calls_after_message=True,
            multiple_tool_calls_per_message=True,
            abort_signal_passthrough=True,
        )
        self.started_event = started_event
        self.started_before_message_stop = False
        self._turn = 0

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        if self._turn == 0:
            self._turn += 1
            yield ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-early-1"})
            yield ModelStreamEvent(
                ModelStreamEventType.CONTENT_BLOCK_START,
                {
                    "block_type": "tool_use",
                    "tool_use_id": "call-early",
                    "name": "early",
                    "input": {"value": "ping"},
                },
            )
            yield ModelStreamEvent(
                ModelStreamEventType.CONTENT_BLOCK_STOP,
                {
                    "block_type": "tool_use",
                    "tool_use_id": "call-early",
                },
            )
            for _ in range(50):
                if self.started_event.is_set():
                    self.started_before_message_stop = True
                    break
                await asyncio.sleep(0.01)
            yield ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"})
            return
        yield ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-early-2"})
        yield ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"})
        yield ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"})


class CompleteOnlyModelClient:
    def __init__(
        self,
        responses: Sequence[ModelResponse],
        *,
        capabilities: NormalizedModelCapabilities | None = None,
    ) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []
        self.normalized_model_capabilities = capabilities or NormalizedModelCapabilities(
            structured_tool_calls=True,
            streaming_tool_call_deltas=False,
            tool_call_finalize_boundary=False,
            parseable_tool_calls_after_message=True,
            multiple_tool_calls_per_message=True,
            abort_signal_passthrough=True,
            supports_streaming=False,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self._responses.pop(0)

    async def stream(self, request: ModelRequest):
        _ = request
        raise AssertionError("stream() should not be used for complete-only clients")


def _make_agent() -> AgentDefinition:
    return AgentDefinition(name="main-router", description="router", prompt="Answer", tools=("*",))


def _collect_turn_events(engine: TurnEngine, **kwargs: Any):
    async def _collect():
        return [event async for event in engine.run_turn_stream(**kwargs)]

    return asyncio.run(_collect())


def _make_context(
    tmp_path: Path,
    registry: ToolRegistry,
    *,
    tool_pool: Sequence[ToolDefinition] | None = None,
    permission_handler=None,
) -> ToolContext:
    return ToolContext(
        session_id="session",
        turn_id="turn",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=registry,
        tool_pool=tuple(tool_pool or registry.definitions()),
        permission_handler=permission_handler,
    )


def _read_semantics(
    path_key: str | None = None,
    *,
    concurrency_safe: bool = True,
) -> ToolExecutionSemantics:
    return ToolExecutionSemantics(
        is_read_only=lambda _tool_input, _context: True,
        is_concurrency_safe=lambda _tool_input, _context: concurrency_safe,
        interrupt_behavior=lambda _tool_input, _context: InterruptBehavior.BLOCK,
        failure_policy=lambda _tool_input, _context: ToolFailurePolicy(),
        to_classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation="read",
            summary="read",
            target_paths=((str(tool_input[path_key]),) if path_key and tool_input.get(path_key) else ()),
            risk_level=ToolRiskLevel.READ,
            side_effects=False,
            tags=("read",),
        )
        if path_key
        else None,
    )


def test_t1_resolution_allow_updated_input(tmp_path: Path) -> None:
    async def validate(tool_input: dict[str, str], _: ToolContext) -> ValidationOutcome:
        return ValidationOutcome(True, updated_input={"mode": tool_input["mode"].strip()})

    async def check_permissions(_: dict[str, str], __: ToolContext) -> PermissionDecision:
        return PermissionDecision(PermissionBehavior.ASK, updated_input={"mode": "write"})

    async def permission_handler(
        _: ToolDefinition,
        __: dict[str, str],
        ___: PermissionDecision,
        ____: ToolContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            PermissionBehavior.ALLOW,
            updated_input={"mode": "read", "file_path": "final.txt"},
        )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="resolver",
            description="resolver",
            input_schema={
                "type": "object",
                "properties": {"mode": {"type": "string"}},
                "required": ["mode"],
                "additionalProperties": False,
            },
            semantics=ToolExecutionSemantics(
                is_read_only=lambda tool_input, _context: tool_input["mode"] == "read",
                is_concurrency_safe=lambda tool_input, _context: tool_input["mode"] == "read",
                interrupt_behavior=lambda _tool_input, _context: InterruptBehavior.BLOCK,
                failure_policy=lambda _tool_input, _context: ToolFailurePolicy(),
                to_classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="resolver",
                    summary=tool_input["mode"],
                    target_paths=((tool_input["file_path"],) if "file_path" in tool_input else ()),
                    risk_level=ToolRiskLevel.READ,
                    side_effects=False,
                    tags=("resolver", tool_input["mode"]),
                ),
            ),
            validate_input=validate,
            check_permissions=check_permissions,
            execute=lambda _tool_input, _context: None,
        )
    )
    context = _make_context(tmp_path, registry, permission_handler=permission_handler)
    resolved = asyncio.run(
        resolve_tool_call(
            ToolCallEnvelope(
                envelope_id="env-1",
                tool_use_id="call-1",
                sequence_index=0,
                raw_tool_name="resolver",
                raw_input={"mode": " write "},
                assistant_message_id="assistant-1",
                query_snapshot=context.query_context,
            ),
            context,
            executor_tier="buffered",
        )
    )

    assert resolved.resolution_status == ToolResolutionStatus.EXECUTABLE
    assert dict(resolved.execution_input or {}) == {"mode": "read", "file_path": "final.txt"}
    assert resolved.resolved_semantics is not None
    assert resolved.resolved_semantics.read_only is True
    assert isinstance(resolved.permission_decision, PermissionAllowed)


def test_t2_resolution_denied_non_executable(tmp_path: Path) -> None:
    async def check_permissions(_: dict[str, str], __: ToolContext) -> PermissionDecision:
        return PermissionDecision(PermissionBehavior.DENY, "blocked")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="deny-tool",
            description="deny",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            check_permissions=check_permissions,
            execute=lambda _tool_input, _context: {"ok": True},
        )
    )
    context = _make_context(tmp_path, registry)
    lifecycle = []
    orchestrator = StreamingToolOrchestrator(
        context=context,
        executor_tier="buffered",
        lifecycle_sink=lifecycle.append,
    )
    resolved = asyncio.run(
        orchestrator.observe_tool_call(
            ToolCall("call-denied", "deny-tool", {}),
            assistant_message_id="assistant-1",
        )
    )
    outcomes = asyncio.run(orchestrator.finalize())

    assert resolved.resolution_status == ToolResolutionStatus.DENIED
    assert isinstance(resolved.permission_decision, PermissionDenied)
    assert not any(event.kind == "execution_started" for event in lifecycle)
    assert outcomes[0].status == ToolCallStatus.DENIED


def test_t3_batch_replay_ordering(tmp_path: Path) -> None:
    async def slow(_: dict[str, str], __: ToolContext) -> dict[str, str]:
        await asyncio.sleep(0.05)
        return {"name": "slow"}

    async def fast(_: dict[str, str], __: ToolContext) -> dict[str, str]:
        await asyncio.sleep(0.01)
        return {"name": "fast"}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="slow",
            description="slow",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            semantics=_read_semantics(),
            execute=slow,
        )
    )
    registry.register(
        ToolDefinition(
            name="fast",
            description="fast",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            semantics=_read_semantics(),
            execute=fast,
        )
    )
    client = ScriptedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                    ModelStreamEvent(
                        ModelStreamEventType.TOOL_CALL,
                        {"tool_name": "slow", "tool_input": {}, "call_id": "call-slow"},
                    ),
                    ModelStreamEvent(
                        ModelStreamEventType.TOOL_CALL,
                        {"tool_name": "fast", "tool_input": {}, "call_id": "call-fast"},
                    ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    engine = TurnEngine(model_client=client, tool_registry=registry)
    events = _collect_turn_events(
        engine,
        session_id="session",
        turn_id="turn",
        agent=_make_agent(),
        cwd=str(tmp_path),
        messages=[],
        base_system_prompt="System",
    )

    outcome_events = [
        event.tool_event
        for event in events
        if event.event_type == TurnStreamEventType.TOOL_LIFECYCLE
        and event.tool_event is not None
        and event.tool_event.kind == "outcome_recorded"
    ]
    replay_events = [
        event.tool_event
        for event in events
        if event.event_type == TurnStreamEventType.TOOL_LIFECYCLE
        and event.tool_event is not None
        and event.tool_event.kind == "replay_committed"
    ]
    assert [event.tool_use_id for event in outcome_events] == ["call-fast", "call-slow"]
    assert [event.tool_use_id for event in replay_events] == ["call-slow", "call-fast"]

    tool_message = next(
        event.message
        for event in events
        if event.event_type == TurnStreamEventType.MESSAGE
        and event.message is not None
        and event.message.role == MessageRole.USER
    )
    blocks = [block for block in tool_message.content if isinstance(block, ToolResultBlock)]
    assert [block.tool_use_id for block in blocks] == ["call-slow", "call-fast"]


def test_t4_lane_conservative_downgrade(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="coarse",
            description="coarse",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                semantics=ToolExecutionSemantics(
                    is_read_only=lambda _tool_input, _context: False,
                    is_concurrency_safe=lambda _tool_input, _context: True,
                    interrupt_behavior=lambda _tool_input, _context: InterruptBehavior.BLOCK,
                    failure_policy=lambda _tool_input, _context: ToolFailurePolicy(),
                ),
            execute=lambda _tool_input, _context: {"ok": True},
        )
    )
    context = _make_context(tmp_path, registry)
    orchestrator = StreamingToolOrchestrator(context=context, executor_tier="buffered")
    resolved = asyncio.run(
        orchestrator.observe_tool_call(
            ToolCall("call-coarse", "coarse", {}),
            assistant_message_id="assistant-1",
        )
    )

    assert resolved.scheduler_lane is not None
    assert resolved.scheduler_lane.lane_kind == ToolSchedulerLaneKind.EXCLUSIVE
    assert resolved.scheduler_lane.derivation_mode == ToolLaneDerivationMode.COARSE


def test_t4b_disjoint_conflict_lanes_run_in_parallel(tmp_path: Path) -> None:
    started_paths: list[str] = []
    barrier = asyncio.Event()
    start_lock = asyncio.Lock()

    async def execute(tool_input: dict[str, str], _: ToolContext) -> dict[str, str]:
        async with start_lock:
            started_paths.append(tool_input["path"])
            if len(started_paths) == 2:
                barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=0.2)
        return {"path": tool_input["path"]}

    semantics = ToolExecutionSemantics(
        is_read_only=lambda _tool_input, _context: False,
        is_concurrency_safe=lambda _tool_input, _context: True,
        interrupt_behavior=lambda _tool_input, _context: InterruptBehavior.BLOCK,
        failure_policy=lambda _tool_input, _context: ToolFailurePolicy(),
        to_classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation="write",
            summary=f"write {tool_input['path']}",
            target_paths=(tool_input["path"],),
            risk_level=ToolRiskLevel.WRITE,
            side_effects=True,
            tags=("write",),
        ),
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="writer-a",
            description="writer a",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            semantics=semantics,
            execute=execute,
        )
    )
    registry.register(
        ToolDefinition(
            name="writer-b",
            description="writer b",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            semantics=semantics,
            execute=execute,
        )
    )
    context = _make_context(tmp_path, registry)
    orchestrator = StreamingToolOrchestrator(context=context, executor_tier="buffered")

    async def run_case():
        started = time.perf_counter()
        await orchestrator.observe_tool_call(
            ToolCall("call-a", "writer-a", {"path": "a.txt"}),
            assistant_message_id="assistant-1",
        )
        await orchestrator.observe_tool_call(
            ToolCall("call-b", "writer-b", {"path": "b.txt"}),
            assistant_message_id="assistant-1",
        )
        outcomes = await orchestrator.finalize()
        return outcomes, time.perf_counter() - started

    outcomes, elapsed = asyncio.run(run_case())

    assert [outcome.status for outcome in outcomes] == [
        ToolCallStatus.SUCCESS,
        ToolCallStatus.SUCCESS,
    ]
    assert started_paths == ["a.txt", "b.txt"]
    assert elapsed < 0.3


def test_t5_fatal_sibling_cascade(tmp_path: Path) -> None:
    async def fatal(_: dict[str, str], __: ToolContext) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"exit_code": 1, "stderr": "boom"}

    async def sibling(_: dict[str, str], __: ToolContext) -> dict[str, Any]:
        await asyncio.sleep(0.2)
        return {"ok": True}

    async def queued(_: dict[str, str], __: ToolContext) -> dict[str, Any]:
        await asyncio.sleep(0.1)
        return {"queued": True}

    fatal_semantics = ToolExecutionSemantics(
        is_read_only=lambda _tool_input, _context: True,
        is_concurrency_safe=lambda _tool_input, _context: True,
        interrupt_behavior=lambda _tool_input, _context: InterruptBehavior.CANCEL,
        failure_policy=lambda _tool_input, _context: ToolFailurePolicy(
            failure_mode=ToolFailureMode.FATAL,
            result_classifier=ToolFailureClassifier.NONZERO_EXIT_OR_EXCEPTION,
            cancel_running_siblings=True,
            block_queued_siblings=True,
            abort_model_stream=True,
            surfaced_status=ToolCallStatus.ERROR,
        ),
        to_classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation="fatal",
            summary="fatal",
            risk_level=ToolRiskLevel.EXEC,
            side_effects=True,
            tags=("fatal",),
        ),
    )
    read_semantics = _read_semantics()
    write_semantics = ToolExecutionSemantics(
        is_read_only=lambda _tool_input, _context: False,
        is_concurrency_safe=lambda _tool_input, _context: False,
        interrupt_behavior=lambda _tool_input, _context: InterruptBehavior.CANCEL,
        failure_policy=lambda _tool_input, _context: ToolFailurePolicy(),
        to_classifier_input=lambda tool_input, _context: ToolClassifierInput(
            operation="write",
            summary="write",
            target_paths=(tool_input["path"],),
            risk_level=ToolRiskLevel.WRITE,
            side_effects=True,
            tags=("write",),
        ),
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="fatal",
            description="fatal",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            semantics=fatal_semantics,
            execute=fatal,
        )
    )
    registry.register(
        ToolDefinition(
            name="sibling",
            description="sibling",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            semantics=read_semantics,
            execute=sibling,
        )
    )
    registry.register(
        ToolDefinition(
            name="queued",
            description="queued",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            semantics=write_semantics,
            execute=queued,
        )
    )
    client = ScriptedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "fatal", "tool_input": {"path": "a.txt"}, "call_id": "call-fatal"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "sibling", "tool_input": {"path": "b.txt"}, "call_id": "call-sibling"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "queued", "tool_input": {"path": "c.txt"}, "call_id": "call-queued"},
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    engine = TurnEngine(model_client=client, tool_registry=registry)
    result = asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=_make_agent(),
            cwd=str(tmp_path),
            messages=[],
            base_system_prompt="System",
        )
    )

    tool_result_message = next(
        message for message in result.messages if message.role == MessageRole.USER
    )
    statuses = [entry["status"] for entry in tool_result_message.metadata["tool_results"]]
    assert statuses == ["error", "cancelled", "cancelled"]


def test_t6_context_update_apply_phases(tmp_path: Path) -> None:
    phase_markers: list[str] = []

    async def execute(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        context.call_updates.append(AppStateSet(namespace="phase", key="before", value="yes"))
        context.call_updates.append(
            TranscriptAttachmentAdded(attachment_type="artifact", payload={"label": "artifact"})
        )
        context.call_updates.append(
            MemoryAppended(scope="session", entry=MemoryEntry(title="memo", content="stored"))
        )
        context.call_updates.append(
            LegacyContextModifierWrapped(
                adapter_label="after",
                summary="after replay",
                modifier=lambda _ctx: phase_markers.append("after"),
            )
        )
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="updates",
            description="updates",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            execute=execute,
        )
    )
    context = _make_context(tmp_path, registry)
    orchestrator = StreamingToolOrchestrator(context=context, executor_tier="buffered")
    asyncio.run(
        orchestrator.observe_tool_call(
            ToolCall("call-updates", "updates", {}),
            assistant_message_id="assistant-1",
        )
    )
    outcomes = asyncio.run(orchestrator.finalize())

    assert context.app_state.get("phase", "before") == "yes"
    assert context.metadata["tool_attachments"] == [{"label": "artifact"}]
    assert context.memory_access.read("session")[0].title == "memo"
    assert phase_markers == ["after"]


def test_t7_lifecycle_event_ordering(tmp_path: Path) -> None:
    async def execute(_: dict[str, str], context: ToolContext) -> dict[str, str]:
        await context.emit_progress("progress-tool", "working", progress=0.5)
        return {"ok": "done"}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="progress-tool",
            description="progress",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            semantics=_read_semantics("path"),
            execute=execute,
        )
    )
    client = ScriptedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "progress-tool", "tool_input": {"path": "p.txt"}, "call_id": "call-progress"},
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    events = _collect_turn_events(
        TurnEngine(model_client=client, tool_registry=registry),
        session_id="session",
        turn_id="turn",
        agent=_make_agent(),
        cwd=str(tmp_path),
        messages=[],
        base_system_prompt="System",
    )
    kinds = [
        event.tool_event.kind
        for event in events
        if event.event_type == TurnStreamEventType.TOOL_LIFECYCLE and event.tool_event is not None
    ]
    assert kinds == [
        "envelope_observed",
        "resolution_started",
        "resolution_completed",
        "execution_queued",
        "execution_started",
        "progress_emitted",
        "outcome_recorded",
        "replay_committed",
    ]


def test_t8_executor_downgrade_selection(tmp_path: Path) -> None:
    assert (
        select_tool_executor_tier(
            NormalizedModelCapabilities(
                structured_tool_calls=True,
                streaming_tool_call_deltas=True,
                tool_call_finalize_boundary=True,
                parseable_tool_calls_after_message=True,
                multiple_tool_calls_per_message=True,
                abort_signal_passthrough=True,
            )
        ).value
        == "full_streaming"
    )
    assert (
        select_tool_executor_tier(
            NormalizedModelCapabilities(
                structured_tool_calls=True,
                streaming_tool_call_deltas=False,
                tool_call_finalize_boundary=False,
                parseable_tool_calls_after_message=True,
                multiple_tool_calls_per_message=True,
                abort_signal_passthrough=True,
            )
        ).value
        == "buffered"
    )
    assert (
        select_tool_executor_tier(
            NormalizedModelCapabilities(
                structured_tool_calls=False,
                streaming_tool_call_deltas=False,
                tool_call_finalize_boundary=False,
                parseable_tool_calls_after_message=True,
                multiple_tool_calls_per_message=True,
                abort_signal_passthrough=True,
            )
        ).value
        == "batch"
    )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="downgrade",
            description="downgrade",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            semantics=_read_semantics("value"),
            execute=lambda tool_input, _context: {"value": tool_input["value"]},
        )
    )
    client = ScriptedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.CONTENT_BLOCK_START,
                    {
                        "block_type": "tool_use",
                        "tool_use_id": "call-downgrade",
                        "name": "downgrade",
                        "input": {"value": "x"},
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ],
        capabilities=NormalizedModelCapabilities(
            structured_tool_calls=True,
            streaming_tool_call_deltas=True,
            tool_call_finalize_boundary=True,
            parseable_tool_calls_after_message=True,
            multiple_tool_calls_per_message=True,
            abort_signal_passthrough=True,
        ),
    )
    events = _collect_turn_events(
        TurnEngine(model_client=client, tool_registry=registry),
        session_id="session",
        turn_id="turn",
        agent=_make_agent(),
        cwd=str(tmp_path),
        messages=[],
        base_system_prompt="System",
    )
    assert client.requests[0].metadata["tool_executor"]["initial_tier"] == "full_streaming"
    downgrade_events = [
        event
        for event in events
        if event.event_type == TurnStreamEventType.TOOL_LIFECYCLE
        and event.metadata.get("tool_executor", {}).get("effective_tier") == "buffered"
    ]
    assert downgrade_events
    assert downgrade_events[-1].metadata["tool_executor"]["downgrade_reason"]


def test_t9_legacy_trait_tool_compat(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="legacy",
            description="legacy",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            execute=lambda _tool_input, _context: {"legacy": True},
        )
    )
    context = _make_context(tmp_path, registry)
    lifecycle = []
    orchestrator = StreamingToolOrchestrator(
        context=context,
        executor_tier="buffered",
        lifecycle_sink=lifecycle.append,
    )
    resolved = asyncio.run(
        orchestrator.observe_tool_call(
            ToolCall("call-legacy", "legacy", {}),
            assistant_message_id="assistant-1",
        )
    )
    outcomes = asyncio.run(orchestrator.finalize())

    assert resolved.resolution_status == ToolResolutionStatus.EXECUTABLE
    assert isinstance(resolved.resolved_semantics, ResolvedToolExecutionSemantics)
    assert resolved.resolved_semantics.read_only is True
    assert resolved.resolved_semantics.concurrency_safe is True
    assert outcomes[0].status == ToolCallStatus.SUCCESS
    assert [event.kind for event in lifecycle][-1] == "replay_committed"


def test_t10_full_streaming_early_start(tmp_path: Path) -> None:
    started_event = asyncio.Event()

    async def execute(_: dict[str, str], __: ToolContext) -> dict[str, str]:
        started_event.set()
        return {"ok": "started"}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="early",
            description="early",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            semantics=_read_semantics("value"),
            execute=execute,
        )
    )
    client = EarlyStartModelClient(started_event)
    result = asyncio.run(
        TurnEngine(model_client=client, tool_registry=registry).run_turn(
            session_id="session",
            turn_id="turn",
            agent=_make_agent(),
            cwd=str(tmp_path),
            messages=[],
            base_system_prompt="System",
        )
    )

    assert result.completed is True
    assert client.started_before_message_stop is True


def test_t11_progress_and_refresh_affect_subsequent_requests(tmp_path: Path) -> None:
    async def refresher(_: dict[str, Any], context: ToolContext) -> dict[str, bool]:
        await context.emit_progress("refresher", "refreshing", progress=0.25)
        context.refresh_capabilities.request("tool_pool", "unlock extra tool")
        return {"refreshed": True}

    registry = ToolRegistry()
    refresher_tool = ToolDefinition(
        name="refresher",
        description="refresh",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        semantics=_read_semantics("path"),
        execute=refresher,
    )
    extra_tool = ToolDefinition(
        name="new-tool",
        description="new",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        execute=lambda _tool_input, _context: {"new": True},
    )
    registry.register(refresher_tool)
    client = ScriptedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "refresher", "tool_input": {}, "call_id": "call-refresh"},
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    engine = TurnEngine(model_client=client, tool_registry=registry)

    async def refresh_tools(context: ToolContext):
        return (*context.tool_pool, extra_tool)

    engine.configure_runtime(tool_refresh_callback=refresh_tools)
    events = _collect_turn_events(
        engine,
        session_id="session",
        turn_id="turn",
        agent=_make_agent(),
        cwd=str(tmp_path),
        messages=[],
        base_system_prompt="System",
    )

    assert {tool.name for tool in client.requests[1].tools} == {"new-tool", "refresher"}
    progress_events = [
        event.tool_event.kind
        for event in events
        if event.event_type == TurnStreamEventType.TOOL_LIFECYCLE and event.tool_event is not None
    ]
    assert "progress_emitted" in progress_events


def test_t11b_unsupported_refresh_scope_is_rejected(tmp_path: Path) -> None:
    context = ToolContext(
        session_id="session",
        turn_id="turn",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=ToolRegistry(),
    )

    receipt = context.refresh_capabilities.request("skill_pool", "refresh skills")

    assert receipt.accepted is False
    assert context.refresh_capabilities.receipts == [receipt]
    assert context.call_updates == []


def test_t12_legacy_trait_tool_compat_multiple_aliases(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="legacy-a",
            aliases=("LegacyA",),
            description="legacy a",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            execute=lambda _tool_input, _context: {"tool": "a"},
        )
    )
    registry.register(
        ToolDefinition(
            name="legacy-b",
            aliases=("LegacyB",),
            description="legacy b",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            execute=lambda _tool_input, _context: {"tool": "b"},
        )
    )
    client = ScriptedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "LegacyA", "tool_input": {}, "call_id": "call-a"},
                ),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {"tool_name": "legacy-b", "tool_input": {}, "call_id": "call-b"},
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    result = asyncio.run(
        TurnEngine(model_client=client, tool_registry=registry).run_turn(
            session_id="session",
            turn_id="turn",
            agent=_make_agent(),
            cwd=str(tmp_path),
            messages=[],
            base_system_prompt="System",
        )
    )

    tool_message = next(message for message in result.messages if message.role == MessageRole.USER)
    blocks = [block for block in tool_message.content if isinstance(block, ToolResultBlock)]
    assert [block.tool_use_id for block in blocks] == ["call-a", "call-b"]
    assert tool_message.metadata["tool_results"] == [
        {"tool_use_id": "call-a", "tool_name": "legacy-a", "status": "success"},
        {"tool_use_id": "call-b", "tool_name": "legacy-b", "status": "success"},
    ]


def test_t13_fatal_failure_aborts_stream_and_preserves_observed_tool_use(tmp_path: Path) -> None:
    class FatalAbortModelClient:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []
            self.normalized_model_capabilities = NormalizedModelCapabilities(
                structured_tool_calls=True,
                streaming_tool_call_deltas=True,
                tool_call_finalize_boundary=True,
                parseable_tool_calls_after_message=True,
                multiple_tool_calls_per_message=True,
                abort_signal_passthrough=True,
            )
            self.saw_abort = False
            self._turn = 0

        async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
            raise NotImplementedError

        async def stream(self, request: ModelRequest):
            self.requests.append(request)
            if self._turn == 0:
                self._turn += 1
                yield ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-fatal-1"})
                yield ModelStreamEvent(
                    ModelStreamEventType.CONTENT_BLOCK_START,
                    {
                        "block_type": "tool_use",
                        "tool_use_id": "call-fatal-abort",
                        "name": "fatal",
                        "input": {},
                    },
                )
                yield ModelStreamEvent(
                    ModelStreamEventType.CONTENT_BLOCK_STOP,
                    {
                        "block_type": "tool_use",
                        "tool_use_id": "call-fatal-abort",
                    },
                )
                while True:
                    await asyncio.sleep(0.01)
                    if request.abort_signal is not None and request.abort_signal.aborted:
                        self.saw_abort = True
                        return
                    yield ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "partial"})
            yield ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-fatal-2"})
            yield ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"})
            yield ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"})

    async def fatal(_: dict[str, Any], __: ToolContext) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return {"exit_code": 1, "stderr": "boom"}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="fatal",
            description="fatal",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            semantics=ToolExecutionSemantics(
                is_read_only=lambda _tool_input, _context: True,
                is_concurrency_safe=lambda _tool_input, _context: True,
                interrupt_behavior=lambda _tool_input, _context: InterruptBehavior.CANCEL,
                failure_policy=lambda _tool_input, _context: ToolFailurePolicy(
                    failure_mode=ToolFailureMode.FATAL,
                    result_classifier=ToolFailureClassifier.NONZERO_EXIT_OR_EXCEPTION,
                    cancel_running_siblings=True,
                    block_queued_siblings=True,
                    abort_model_stream=True,
                    surfaced_status=ToolCallStatus.ERROR,
                ),
            ),
            execute=fatal,
        )
    )
    client = FatalAbortModelClient()
    result = asyncio.run(
        TurnEngine(model_client=client, tool_registry=registry).run_turn(
            session_id="session",
            turn_id="turn",
            agent=_make_agent(),
            cwd=str(tmp_path),
            messages=[],
            base_system_prompt="System",
        )
    )

    assert client.saw_abort is True
    assert result.completed is True
    assistant_messages = [message for message in result.messages if message.role == MessageRole.ASSISTANT]
    assert isinstance(assistant_messages[0].content[0], ToolUseBlock)
    assert assistant_messages[0].text == ""
    tool_message = next(message for message in result.messages if message.role == MessageRole.USER)
    assert tool_message.metadata["tool_results"][0]["status"] == "error"


def test_t14_lifecycle_events_surface_presentation_and_summary(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="presented",
            description="presented",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            semantics=ToolExecutionSemantics(
                is_read_only=lambda _tool_input, _context: True,
                is_concurrency_safe=lambda _tool_input, _context: True,
                interrupt_behavior=lambda _tool_input, _context: InterruptBehavior.BLOCK,
                failure_policy=lambda _tool_input, _context: ToolFailurePolicy(),
                render_tool_use_message=lambda tool_input, _context: ToolUsePresentation(
                    title="Read artifact",
                    subtitle=tool_input["path"],
                    emphasis=ToolPresentationEmphasis.LOW,
                ),
                render_tool_result_summary=lambda tool_input, _context: ToolResultSummary(
                    title="Artifact loaded",
                    summary=tool_input["path"],
                    status=ToolResultSummaryStatus.SUCCESS,
                    detail_lines=("cached",),
                ),
                to_classifier_input=lambda tool_input, _context: ToolClassifierInput(
                    operation="presented",
                    summary=tool_input["path"],
                    target_paths=(tool_input["path"],),
                    risk_level=ToolRiskLevel.READ,
                    side_effects=False,
                    tags=("read",),
                ),
            ),
            execute=lambda tool_input, _context: {"path": tool_input["path"]},
        )
    )
    client = ScriptedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-presented-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "presented",
                        "tool_input": {"path": "artifact.txt"},
                        "call_id": "call-presented",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-presented-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    events = _collect_turn_events(
        TurnEngine(model_client=client, tool_registry=registry),
        session_id="session",
        turn_id="turn",
        agent=_make_agent(),
        cwd=str(tmp_path),
        messages=[],
        base_system_prompt="System",
    )

    resolution_event = next(
        event.tool_event
        for event in events
        if event.event_type == TurnStreamEventType.TOOL_LIFECYCLE
        and event.tool_event is not None
        and event.tool_event.kind == "resolution_completed"
    )
    outcome_event = next(
        event.tool_event
        for event in events
        if event.event_type == TurnStreamEventType.TOOL_LIFECYCLE
        and event.tool_event is not None
        and event.tool_event.kind == "outcome_recorded"
    )
    replay_event = next(
        event.tool_event
        for event in events
        if event.event_type == TurnStreamEventType.TOOL_LIFECYCLE
        and event.tool_event is not None
        and event.tool_event.kind == "replay_committed"
    )
    tool_message = next(
        event.message
        for event in events
        if event.event_type == TurnStreamEventType.MESSAGE
        and event.message is not None
        and event.message.role == MessageRole.USER
    )

    assert resolution_event.tool_use_presentation is not None
    assert resolution_event.tool_use_presentation.title == "Read artifact"
    assert outcome_event.result_summary is not None
    assert outcome_event.result_summary.summary == "artifact.txt"
    assert replay_event.result_summary is not None
    assert replay_event.result_summary.detail_lines == ("cached",)
    assert tool_message.metadata["tool_results"][0]["result_summary"] == {
        "title": "Artifact loaded",
        "summary": "artifact.txt",
        "status": "success",
        "detail_lines": ["cached"],
    }


def test_t15_buffered_completion_without_tools(tmp_path: Path) -> None:
    client = CompleteOnlyModelClient(
        [
            ModelResponse(
                message=RuntimeMessage(
                    message_id="buffered-no-tools",
                    role=MessageRole.ASSISTANT,
                    content="buffered answer",
                ),
                stop_reason="end_turn",
                request_id="req-buffered-no-tools",
                terminal=ModelTerminalMetadata(
                    stop_reason="end_turn",
                    request_id="req-buffered-no-tools",
                    usage={"output_tokens": 3},
                ),
            )
        ]
    )

    result = asyncio.run(
        TurnEngine(model_client=client, tool_registry=ToolRegistry()).run_turn(
            session_id="session",
            turn_id="turn",
            agent=_make_agent(),
            cwd=str(tmp_path),
            messages=[],
            base_system_prompt="System",
        )
    )

    assert client.requests[0].invocation_mode == ModelInvocationMode.BUFFERED_COMPLETION
    assert result.completed is True
    assert result.messages[-1].text == "buffered answer"
    assert result.request_id == "req-buffered-no-tools"
    assert result.usage == {"output_tokens": 3}


def test_t16_buffered_completion_tool_results_preserve_order(tmp_path: Path) -> None:
    async def slow(_: dict[str, str], __: ToolContext) -> dict[str, str]:
        await asyncio.sleep(0.05)
        return {"name": "slow"}

    async def fast(_: dict[str, str], __: ToolContext) -> dict[str, str]:
        await asyncio.sleep(0.01)
        return {"name": "fast"}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="slow",
            description="slow",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            semantics=_read_semantics(),
            execute=slow,
        )
    )
    registry.register(
        ToolDefinition(
            name="fast",
            description="fast",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            semantics=_read_semantics(),
            execute=fast,
        )
    )
    client = CompleteOnlyModelClient(
        [
            ModelResponse(
                message=RuntimeMessage(
                    message_id="buffered-tools-1",
                    role=MessageRole.ASSISTANT,
                    content=(
                        ToolUseBlock(tool_use_id="call-slow", name="slow", input={}),
                        ToolUseBlock(tool_use_id="call-fast", name="fast", input={}),
                    ),
                ),
                stop_reason="tool_use",
                request_id="req-buffered-tools-1",
                terminal=ModelTerminalMetadata(
                    stop_reason="tool_use",
                    request_id="req-buffered-tools-1",
                ),
            ),
            ModelResponse(
                message=RuntimeMessage(
                    message_id="buffered-tools-2",
                    role=MessageRole.ASSISTANT,
                    content="done",
                ),
                stop_reason="end_turn",
                request_id="req-buffered-tools-2",
                terminal=ModelTerminalMetadata(
                    stop_reason="end_turn",
                    request_id="req-buffered-tools-2",
                ),
            ),
        ]
    )

    result = asyncio.run(
        TurnEngine(model_client=client, tool_registry=registry).run_turn(
            session_id="session",
            turn_id="turn",
            agent=_make_agent(),
            cwd=str(tmp_path),
            messages=[],
            base_system_prompt="System",
        )
    )

    assert client.requests[0].invocation_mode == ModelInvocationMode.BUFFERED_COMPLETION
    assert client.requests[0].metadata["tool_executor"]["initial_tier"] == "buffered"
    tool_message = next(message for message in result.messages if message.role == MessageRole.USER)
    blocks = [block for block in tool_message.content if isinstance(block, ToolResultBlock)]
    assert [block.tool_use_id for block in blocks] == ["call-slow", "call-fast"]
    assert result.attempts[0].stop_reason == "tool_use"
    assert result.attempts[0].request_id == "req-buffered-tools-1"
    assert result.attempts[-1].stop_reason == "end_turn"
    assert result.attempts[-1].request_id == "req-buffered-tools-2"
