import asyncio
import time
from pathlib import Path

from runtime.context_window import (
    MinimalRecoveryClassificationHints,
    RecoveryClassificationRule,
    ResolvedContextWindowSnapshot,
)
from runtime.contracts import (
    MessageAttachment,
    MessageRole,
    PromptContextEnvelope,
    RequestOverrideState,
    RuntimeMessage,
    RuntimePrivateContext,
    ToolResultBlock,
    ToolUseBlock,
    merge_request_override_state,
)
from runtime.compaction import CompactionManager
from runtime.definitions import AgentDefinition
from runtime.hooks import HookBus, HookStopDisposition, RuntimeHookPhase
from runtime.registries import ToolRegistry
from runtime.runtime_services import NoopCompactionService, RuntimeServices
from runtime.session_runtime import (
    FileTranscriptStore,
    InMemoryTranscriptStore,
    InboundEvent,
    InboundEventType,
    SessionController,
)
from runtime.turn_engine import (
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    TranscriptEntry,
    TurnEngine,
)
from runtime.turn_engine.control_plane import (
    BudgetAction,
    BudgetDecision,
    BudgetPlan,
    ContextWindowHookFailureMode,
    ContextWindowRequest,
    ContextBudgetHookFailureMode,
    ContextBudgetRequest,
    DefaultContextControlPlane,
    DefaultRecoveryPolicy,
    FailureClassification,
    MaterialCompactionPass,
    PreparedContext,
    RecoveryAction,
    RecoveryState,
    apply_budget_plan,
    apply_projection_pass,
    check_projection_invariants,
    collect_budget_candidates,
    invoke_context_window_hook,
    invoke_budget_hook,
    normalize_attempt_outcome,
)
from runtime.turn_engine.engine import AttemptFinished


class SequencedModelClient:
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


class CaptureCompactionService:
    def __init__(self) -> None:
        self.private_contexts = []

    async def prepare_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent,
        cwd: str,
        messages,
        prompt_context=None,
        private_context=None,
        runtime_context=None,
    ):
        _ = session_id, turn_id, agent, cwd, messages, prompt_context, runtime_context
        self.private_contexts.append(private_context)
        return await NoopCompactionService().prepare_turn(
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=runtime_context,
        )


def test_normalize_attempt_outcome_prefers_provider_neutral_failure_metadata() -> None:
    attempt = AttemptFinished(
        iteration=1,
        attempt_stop_reason="provider_specific_stop",
        metadata={
            "failure_class": "context_limit",
            "retryable": True,
            "provider_error_code": "413",
        },
    )
    normalized = normalize_attempt_outcome(attempt)

    assert normalized.failure_class == FailureClassification.CONTEXT_LIMIT
    assert normalized.retryable is True
    assert normalized.provider_error_code == "413"

    drifted = AttemptFinished(
        iteration=1,
        attempt_stop_reason="provider_specific_stop",
        error="context length exceeded by backend",
    )
    drifted_normalized = normalize_attempt_outcome(drifted)

    assert drifted_normalized.failure_class != FailureClassification.CONTEXT_LIMIT


def test_default_recovery_policy_covers_failure_matrix() -> None:
    policy = DefaultRecoveryPolicy()
    prepared = PreparedContext(active_messages=(), prompt_context=PromptContextEnvelope())

    context_limit = normalize_attempt_outcome(
        AttemptFinished(
            iteration=1,
            attempt_stop_reason="context_limit",
            metadata={"failure_class": "context_limit", "retryable": True},
        )
    )
    first = policy.evaluate(context_limit, recovery_state=RecoveryState(), prepared_context=prepared)
    after_first = RecoveryState().after_decision(context_limit, first)
    second = policy.evaluate(context_limit, recovery_state=after_first, prepared_context=prepared)

    output_limit = normalize_attempt_outcome(
        AttemptFinished(
            iteration=1,
            attempt_stop_reason="output_limit",
            metadata={"failure_class": "output_limit", "retryable": True, "max_output_tokens": 128},
        )
    )
    output_decision = policy.evaluate(output_limit, recovery_state=RecoveryState(), prepared_context=prepared)

    interrupted = normalize_attempt_outcome(
        AttemptFinished(iteration=1, attempt_stop_reason="interrupted", abort_reason="interrupt")
    )
    interrupted_decision = policy.evaluate(interrupted, recovery_state=RecoveryState(), prepared_context=prepared)

    unavailable = normalize_attempt_outcome(
        AttemptFinished(iteration=1, attempt_stop_reason="tool_use", produced_tool_calls=True),
        tool_executor_unavailable=True,
    )
    unavailable_decision = policy.evaluate(unavailable, recovery_state=RecoveryState(), prepared_context=prepared)

    auth_error = normalize_attempt_outcome(
        AttemptFinished(
            iteration=1,
            attempt_stop_reason="error",
            metadata={"failure_class": "auth_error", "retryable": False},
        )
    )
    auth_decision = policy.evaluate(auth_error, recovery_state=RecoveryState(), prepared_context=prepared)

    assert first.action == RecoveryAction.COMPACT_AND_RETRY
    assert second.action == RecoveryAction.HALT
    assert second.terminal_reason == "prompt_too_long"
    assert output_decision.action == RecoveryAction.RETRY_WITH_OVERRIDE
    assert output_decision.request_override is not None
    assert output_decision.request_override.max_output_tokens_override == 256
    assert interrupted_decision.action == RecoveryAction.HALT
    assert interrupted_decision.terminal_reason == "interrupted"
    assert unavailable_decision.action == RecoveryAction.HALT
    assert unavailable_decision.terminal_reason == "blocked"
    assert auth_decision.action == RecoveryAction.HALT


def test_hook_bus_aggregates_stop_effects_in_registration_order_and_precedence() -> None:
    bus = HookBus()
    bus.register(
        session_id="session",
        owner="first",
        phase=RuntimeHookPhase.STOP,
        handler=lambda _payload: {
            "stop_disposition": "continue_same_turn",
            "additional_context": ("first-context",),
            "notifications": ("first-note",),
            "request_override": {"requested_model": "model-a", "source": "stop:first"},
        },
    )
    bus.register(
        session_id="session",
        owner="second",
        phase=RuntimeHookPhase.STOP,
        handler=lambda _payload: {
            "stop_disposition": "block_session",
            "additional_context": ("second-context",),
            "notifications": ("second-note",),
            "request_override": {"requested_effort": "high", "source": "stop:second"},
        },
    )

    result = asyncio.run(
        bus.dispatch(
            "session",
            type("Payload", (), {"phase": RuntimeHookPhase.STOP, "reason": "completed", "turn_id": "turn"})(),
        )
    )

    assert result.additional_context == ("first-context", "second-context")
    assert result.notifications == ("first-note", "second-note")
    assert result.stop_disposition == HookStopDisposition.BLOCK_SESSION
    assert result.request_override is not None
    assert result.request_override.requested_model == "model-a"
    assert result.request_override.requested_effort == "high"
    assert result.request_override.field_sources["requested_model"] == "stop:first"
    assert result.request_override.field_sources["requested_effort"] == "stop:second"


def test_request_override_merge_respects_skill_stop_recovery_precedence() -> None:
    skill = RequestOverrideState(
        requested_model="skill-model",
        requested_effort="low",
        source="skill:config",
        field_sources={
            "requested_model": "skill:config",
            "requested_effort": "skill:config",
        },
        metadata={"sources": ["skill:config"]},
    )
    stop = RequestOverrideState(
        requested_model_route="stop-route",
        requested_effort="medium",
        source="stop:hook",
        field_sources={
            "requested_model_route": "stop:hook",
            "requested_effort": "stop:hook",
        },
        metadata={"sources": ["stop:hook"]},
    )
    recovery = RequestOverrideState(
        max_output_tokens_override=512,
        requested_effort="high",
        source="recovery:output_limit",
        field_sources={
            "max_output_tokens_override": "recovery:output_limit",
            "requested_effort": "recovery:output_limit",
        },
        metadata={"sources": ["recovery:output_limit"]},
    )

    merged = merge_request_override_state(
        merge_request_override_state(
            merge_request_override_state(None, skill),
            stop,
        ),
        recovery,
    )

    assert merged is not None
    assert merged.requested_model == "skill-model"
    assert merged.requested_model_route == "stop-route"
    assert merged.requested_effort == "high"
    assert merged.max_output_tokens_override == 512
    assert merged.field_sources["requested_model"] == "skill:config"
    assert merged.field_sources["requested_model_route"] == "stop:hook"
    assert merged.field_sources["requested_effort"] == "recovery:output_limit"


def test_budget_plan_validation_ignores_invalid_entries_with_diagnostics() -> None:
    messages = (
        RuntimeMessage(
            message_id="assistant-msg",
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(
                    tool_use_id="tool-1",
                    name="echo",
                    input={"value": "full"},
                ),
            ),
        ),
        RuntimeMessage(
            message_id="tool-msg",
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="tool-1",
                    content={"value": "full"},
                ),
            ),
            metadata={"tool_results": [{"tool_use_id": "tool-1", "tool_name": "echo"}]},
        ),
    )
    plan = BudgetPlan(
        decisions=(
            BudgetDecision(candidate_id="missing", action=BudgetAction.SUMMARIZE, summary_text="drop"),
            BudgetDecision(
                candidate_id="tool-msg:0:tool-1",
                action=BudgetAction.SUMMARIZE,
                summary_text="summary",
                reason="budget",
            ),
            BudgetDecision(candidate_id="tool-msg:0:tool-1", action=BudgetAction.INLINE),
        ),
        policy_tag="policy-a",
    )

    updated, effects, diagnostics = asyncio.run(
        apply_budget_plan(
            messages,
            plan,
            session_id="session",
            turn_id="turn",
        )
    )

    assert updated[1].content[0].content == "summary"
    assert len(effects) == 1
    assert "unknown_candidate:missing" in diagnostics
    assert "duplicate_candidate:tool-msg:0:tool-1" in diagnostics


def test_apply_budget_plan_preserves_replay_order_for_summary_and_externalize() -> None:
    store = InMemoryTranscriptStore()
    messages = (
        RuntimeMessage(
            message_id="assistant-msg",
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(tool_use_id="tool-1", name="first", input={"value": "a"}),
                ToolUseBlock(tool_use_id="tool-2", name="second", input={"value": "b"}),
            ),
        ),
        RuntimeMessage(
            message_id="tool-msg",
            role=MessageRole.USER,
            content=(
                ToolResultBlock(tool_use_id="tool-1", content={"value": "payload-a"}),
                ToolResultBlock(tool_use_id="tool-2", content={"value": "payload-b"}),
            ),
            metadata={
                "tool_results": [
                    {"tool_use_id": "tool-1", "tool_name": "first"},
                    {"tool_use_id": "tool-2", "tool_name": "second"},
                ]
            },
        ),
    )
    plan = BudgetPlan(
        decisions=(
            BudgetDecision(
                candidate_id="tool-msg:1:tool-2",
                action=BudgetAction.EXTERNALIZE,
                summary_text="payload b",
                reason="budget",
            ),
            BudgetDecision(
                candidate_id="tool-msg:0:tool-1",
                action=BudgetAction.SUMMARIZE,
                summary_text="payload a",
                reason="budget",
            ),
        ),
        policy_tag="policy-spillover",
    )

    updated, effects, diagnostics = asyncio.run(
        apply_budget_plan(
            messages,
            plan,
            session_id="session",
            turn_id="turn-1",
            transcript_store=store,
        )
    )

    tool_message = updated[1]
    assert [block.tool_use_id for block in tool_message.content] == ["tool-1", "tool-2"]
    assert tool_message.content[0].content == "payload a"
    assert tool_message.content[1].content["artifact_ref"].startswith("tool_result_spillover-")
    tool_results = tool_message.metadata["tool_results"]
    assert tool_results[0]["summarized"] is True
    assert tool_results[0]["artifact_ref"].startswith("tool_result_spillover-")
    assert tool_results[1]["externalized"] is True
    assert tool_results[1]["artifact_ref"].startswith("tool_result_spillover-")
    assert any(effect.kind.value == "spillover" for effect in effects)
    assert diagnostics == []


def test_in_memory_transcript_store_retains_referenced_artifacts_during_gc() -> None:
    async def scenario() -> None:
        store = InMemoryTranscriptStore()
        retained = await store.persist_artifact(
            "session",
            turn_id="turn-1",
            kind="tool_result_spillover",
            payload={"value": "keep"},
            metadata={"policy_tag": "retain"},
            retention_class="referenced",
        )
        dropped = await store.persist_artifact(
            "session",
            turn_id="turn-1",
            kind="tool_result_spillover",
            payload={"value": "drop"},
            metadata={"policy_tag": "drop"},
            retention_class="referenced",
        )
        await store.append(
            TranscriptEntry(
                session_id="session",
                turn_id="turn-1",
                message=RuntimeMessage(
                    message_id="tool-msg",
                    role=MessageRole.USER,
                    content=(
                        ToolResultBlock(
                            tool_use_id="tool-1",
                            content={"artifact_ref": retained.artifact_ref, "summary": "keep"},
                        ),
                    ),
                    metadata={
                        "tool_results": [
                            {
                                "tool_use_id": "tool-1",
                                "artifact_ref": retained.artifact_ref,
                                "externalized": True,
                            }
                        ]
                    },
                ),
            )
        )
        await store.save_session_metadata(
            "session",
            {"control_plane": {"spillover_artifact_refs": [retained.artifact_ref]}},
        )

        removed = await store.purge_unreferenced_artifacts("session")
        kept_payload = await store.load_artifact("session", retained.artifact_ref)
        dropped_payload = await store.load_artifact("session", dropped.artifact_ref)

        assert removed == (dropped.artifact_ref,)
        assert kept_payload is not None
        assert kept_payload.entry.digest == retained.digest
        assert dropped_payload is None

    asyncio.run(scenario())


def test_file_transcript_store_round_trips_artifact_manifest_and_payload(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = FileTranscriptStore(tmp_path / "transcripts")
        persisted = await store.persist_artifact(
            "session",
            turn_id="turn-1",
            kind="tool_result_spillover",
            payload={"value": "payload"},
            metadata={"tool_use_id": "tool-1"},
            retention_class="referenced",
        )

        reloaded = FileTranscriptStore(tmp_path / "transcripts")
        listed = await reloaded.list_artifacts("session")
        loaded = await reloaded.load_artifact("session", persisted.artifact_ref)

        assert listed[0].artifact_ref == persisted.artifact_ref
        assert listed[0].retention_class == "referenced"
        assert loaded is not None
        assert loaded.entry.digest == persisted.digest
        assert loaded.payload == {"value": "payload"}

    asyncio.run(scenario())


def test_context_control_plane_degrades_missing_artifact_without_dropping_replay_slot() -> None:
    plane = DefaultContextControlPlane(compaction_service=NoopCompactionService())
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    store = InMemoryTranscriptStore()
    messages = (
        RuntimeMessage(
            message_id="assistant-msg",
            role=MessageRole.ASSISTANT,
            content=(ToolUseBlock(tool_use_id="tool-1", name="echo", input={"value": "x"}),),
        ),
        RuntimeMessage(
            message_id="tool-msg",
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="tool-1",
                    content={"artifact_ref": "missing-ref", "summary": "fallback"},
                ),
            ),
            metadata={
                "tool_results": [
                    {
                        "tool_use_id": "tool-1",
                        "artifact_ref": "missing-ref",
                        "externalized": True,
                        "summary_text": "fallback",
                    }
                ]
            },
        ),
    )

    prepared = asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=1,
            agent=agent,
            cwd=".",
            messages=messages,
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(),
            runtime_context={},
            transcript_store=store,
        )
    )

    assert prepared.transcript_messages is not None
    degraded = prepared.active_messages[1].content[0]
    assert isinstance(degraded, ToolResultBlock)
    assert degraded.content == "fallback"
    assert "missing_artifact:missing-ref" in prepared.metadata["diagnostics"]
    assert any(effect.kind.value == "spillover" for effect in prepared.effects)


def test_budget_hook_failure_mode_supports_pass_through_and_fail_prepare() -> None:
    class RaisingHook:
        def plan(self, request):  # pragma: no cover - exercised via invoke_budget_hook
            _ = request
            raise RuntimeError("boom")

    request = ContextBudgetRequest(turn_id="turn", attempt_index=1)
    plan, diagnostics = asyncio.run(
        invoke_budget_hook(
            RaisingHook(),
            request,
            failure_mode=ContextBudgetHookFailureMode.PASS_THROUGH,
            timeout_seconds=None,
        )
    )

    assert plan is None
    assert diagnostics == ["context_budget_hook_error:RuntimeError"]

    try:
        asyncio.run(
            invoke_budget_hook(
                RaisingHook(),
                request,
                failure_mode=ContextBudgetHookFailureMode.FAIL_PREPARE,
                timeout_seconds=None,
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("FAIL_PREPARE should surface the hook error")


def test_sync_budget_hook_timeout_surfaces_timeout_without_blocking_main_loop() -> None:
    class SlowHook:
        def plan(self, request):  # pragma: no cover - exercised via invoke_budget_hook
            _ = request
            time.sleep(0.2)
            return None

    request = ContextBudgetRequest(turn_id="turn", attempt_index=1)

    async def scenario() -> tuple[object, list[str], float]:
        started_at = time.perf_counter()
        plan, diagnostics = await invoke_budget_hook(
            SlowHook(),
            request,
            failure_mode=ContextBudgetHookFailureMode.PASS_THROUGH,
            timeout_seconds=0.01,
        )
        return plan, diagnostics, time.perf_counter() - started_at

    plan, diagnostics, elapsed = asyncio.run(scenario())

    assert plan is None
    assert diagnostics == ["context_budget_hook_error:TimeoutError"]
    assert elapsed < 0.15


def test_context_budget_hook_receives_structured_request() -> None:
    class CapturingHook:
        def __init__(self) -> None:
            self.requests: list[ContextBudgetRequest] = []

        def plan(self, request: ContextBudgetRequest):
            self.requests.append(request)
            return None

    hook = CapturingHook()
    plane = DefaultContextControlPlane(
        compaction_service=NoopCompactionService(),
        default_config={"budget_hook": hook},
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    messages = (
        RuntimeMessage(
            message_id="assistant-msg",
            role=MessageRole.ASSISTANT,
            content=(ToolUseBlock(tool_use_id="tool-1", name="echo", input={"value": "x"}),),
        ),
        RuntimeMessage(
            message_id="tool-msg",
            role=MessageRole.USER,
            content=(ToolResultBlock(tool_use_id="tool-1", content={"value": "payload"}),),
            metadata={"tool_results": [{"tool_use_id": "tool-1", "tool_name": "echo"}]},
        ),
    )

    asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=1,
            agent=agent,
            cwd=".",
            messages=messages,
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(
                provider_name="provider-a",
                requested_model_route="route-a",
                invocation_mode="stream",
                extensions={"marker": "private"},
            ),
            runtime_context={"requested_model": "model-a"},
        )
    )

    request = hook.requests[0]
    assert request.candidates[0].tool_use_id == "tool-1"
    assert request.provider_hints is not None
    assert request.provider_hints.provider_name == "provider-a"
    assert request.provider_hints.model_name == "model-a"
    assert request.provider_hints.requested_model_route == "route-a"
    assert request.private_context.extensions["marker"] == "private"


def test_context_window_hook_emits_canonical_diagnostics() -> None:
    class RaisingHook:
        def plan(self, request):  # pragma: no cover - exercised via invoke_context_window_hook
            _ = request
            raise RuntimeError("boom")

    request = ContextWindowRequest(turn_id="turn", attempt_index=1)
    plan, diagnostics = asyncio.run(
        invoke_context_window_hook(
            RaisingHook(),
            request,
            failure_mode=ContextWindowHookFailureMode.PASS_THROUGH,
            timeout_seconds=None,
        )
    )

    assert plan is None
    assert diagnostics == ["context_window_hook_error:RuntimeError"]


def test_context_window_prepare_derives_proactive_snapshot_and_policy() -> None:
    compaction = CaptureCompactionService()
    plane = DefaultContextControlPlane(compaction_service=compaction)
    agent = AgentDefinition(
        name="main-router",
        description="router",
        prompt="route",
        model="model-a",
    )
    messages = (
        RuntimeMessage(message_id="u1", role=MessageRole.USER, content="012345678901234567890123456789"),
    )

    prepared = asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=1,
            agent=agent,
            cwd=".",
            messages=messages,
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(provider_name="provider-a"),
            runtime_context={
                "provider_name": "provider-a",
                "resolved_model_route": "route-a",
                "provider_context_window_profiles": [
                    {
                        "provider_name": "provider-a",
                        "model_selector": "model-a",
                        "max_input_tokens": 40,
                        "reserved_output_tokens": 10,
                        "token_estimation_hint": {"chars_per_token": 1.0},
                    }
                ],
                "route_context_window_policy": {
                    "trigger_buffer_tokens": 5,
                    "policy_tag": "route-a-policy",
                },
            },
        )
    )

    assert prepared.context_window is not None
    assert prepared.context_window.max_input_tokens == 40
    assert prepared.context_window.remaining_input_tokens == 0
    assert prepared.context_window.fallback_mode == "proactive_and_reactive"
    assert prepared.metadata["context_window_policy_tag"] == "route-a-policy"
    applied_private_context = compaction.private_contexts[0]
    assert applied_private_context.extensions["compaction_policy"]["max_characters"] == 25
    assert applied_private_context.extensions["compaction_policy"]["force"] is True


def test_unknown_context_window_stays_reactive_only() -> None:
    compaction = CaptureCompactionService()
    plane = DefaultContextControlPlane(compaction_service=compaction)
    agent = AgentDefinition(
        name="main-router",
        description="router",
        prompt="route",
        model="model-a",
    )

    prepared = asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=1,
            agent=agent,
            cwd=".",
            messages=(RuntimeMessage(message_id="u1", role=MessageRole.USER, content="hello"),),
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(provider_name="provider-a"),
            runtime_context={
                "provider_name": "provider-a",
                "resolved_model_route": "route-a",
            },
        )
    )

    assert prepared.context_window is not None
    assert prepared.context_window.known is False
    assert prepared.context_window.fallback_mode == "reactive_only"
    assert "compaction_policy" not in compaction.private_contexts[0].extensions


def test_normalize_attempt_outcome_uses_context_window_recovery_hints() -> None:
    prepared = PreparedContext(
        active_messages=(),
        prompt_context=PromptContextEnvelope(),
        context_window=ResolvedContextWindowSnapshot(
            provider_name="provider-a",
            model_name="model-a",
            max_input_tokens=128000,
            reserved_output_tokens=4096,
            fallback_mode="proactive_and_reactive",
            recovery_classification_hints=MinimalRecoveryClassificationHints(
                context_limit=RecoveryClassificationRule(
                    provider_error_codes=("context_length_exceeded",),
                    message_substrings=("maximum context length",),
                    retryable=True,
                )
            ),
        ),
    )

    normalized = normalize_attempt_outcome(
        AttemptFinished(
            iteration=1,
            attempt_stop_reason="provider_error",
            error="maximum context length reached",
            metadata={"provider_error_code": "context_length_exceeded"},
        ),
        prepared_context=prepared,
    )

    assert normalized.failure_class == FailureClassification.CONTEXT_LIMIT
    assert normalized.retryable is True


def test_canonical_context_window_config_key_wins_over_legacy_alias() -> None:
    class CapturingHook:
        def __init__(self, label: str) -> None:
            self.label = label
            self.calls = 0

        def plan(self, request):
            _ = request
            self.calls += 1
            return None

    canonical = CapturingHook("canonical")
    legacy = CapturingHook("legacy")
    plane = DefaultContextControlPlane(
        compaction_service=NoopCompactionService(),
        default_config={
            "budget_hook": legacy,
            "context_window_hook": canonical,
        },
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    messages = (
        RuntimeMessage(
            message_id="assistant-msg",
            role=MessageRole.ASSISTANT,
            content=(ToolUseBlock(tool_use_id="tool-1", name="echo", input={"value": "x"}),),
        ),
        RuntimeMessage(
            message_id="tool-msg",
            role=MessageRole.USER,
            content=(ToolResultBlock(tool_use_id="tool-1", content={"value": "payload"}),),
            metadata={"tool_results": [{"tool_use_id": "tool-1", "tool_name": "echo"}]},
        ),
    )

    prepared = asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=1,
            agent=agent,
            cwd=".",
            messages=messages,
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(),
            runtime_context={},
        )
    )

    assert canonical.calls == 1
    assert legacy.calls == 0
    assert "deprecated_config_key:budget_hook" not in prepared.metadata["diagnostics"]


def test_legacy_context_window_config_key_emits_deprecation_diagnostic() -> None:
    class CapturingHook:
        def __init__(self) -> None:
            self.calls = 0

        def plan(self, request):
            _ = request
            self.calls += 1
            return None

    hook = CapturingHook()
    plane = DefaultContextControlPlane(
        compaction_service=NoopCompactionService(),
        default_config={"budget_hook": hook},
    )
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    messages = (
        RuntimeMessage(
            message_id="assistant-msg",
            role=MessageRole.ASSISTANT,
            content=(ToolUseBlock(tool_use_id="tool-1", name="echo", input={"value": "x"}),),
        ),
        RuntimeMessage(
            message_id="tool-msg",
            role=MessageRole.USER,
            content=(ToolResultBlock(tool_use_id="tool-1", content={"value": "payload"}),),
            metadata={"tool_results": [{"tool_use_id": "tool-1", "tool_name": "echo"}]},
        ),
    )

    prepared = asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=1,
            agent=agent,
            cwd=".",
            messages=messages,
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(),
            runtime_context={},
        )
    )

    assert hook.calls == 1
    assert "deprecated_config_key:budget_hook" in prepared.metadata["diagnostics"]


def test_context_control_plane_reuses_and_bumps_generation() -> None:
    plane = DefaultContextControlPlane(compaction_service=NoopCompactionService())
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    messages = (
        RuntimeMessage(message_id="u1", role=MessageRole.USER, content="hello"),
        RuntimeMessage(message_id="a1", role=MessageRole.ASSISTANT, content="answer"),
    )

    first = asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=1,
            agent=agent,
            cwd=".",
            messages=messages,
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(),
            runtime_context={},
        )
    )
    second = asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=2,
            agent=agent,
            cwd=".",
            messages=messages,
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(),
            runtime_context={},
            prior_prepared=first,
        )
    )
    third = asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=3,
            agent=agent,
            cwd=".",
            messages=messages,
            prompt_context=PromptContextEnvelope(hook_fragments=("new-fragment",)),
            private_context=RuntimePrivateContext(),
            runtime_context={},
            prior_prepared=second,
        )
    )

    projected, metadata = apply_projection_pass(messages + messages, max_active_messages=2)

    assert first.generation == 1
    assert second.generation == 1
    assert third.generation == 2
    assert third.requires_sidecar_restart is True
    assert len(projected) >= 2
    assert metadata["latest_user_message_id"] == "u1"


def test_projection_invariants_preserve_latest_user_and_attachment_handles() -> None:
    attachment = MessageAttachment(name="note.txt", path="/tmp/note.txt")
    messages = (
        RuntimeMessage(message_id="sys", role=MessageRole.SYSTEM, content="system"),
        RuntimeMessage(
            message_id="assistant-msg",
            role=MessageRole.ASSISTANT,
            content=(ToolUseBlock(tool_use_id="tool-1", name="echo", input={"value": "x"}),),
        ),
        RuntimeMessage(
            message_id="tool-msg",
            role=MessageRole.USER,
            content=(ToolResultBlock(tool_use_id="tool-1", content={"value": "payload"}),),
        ),
        RuntimeMessage(
            message_id="latest-user",
            role=MessageRole.USER,
            content="latest",
            attachments=(attachment,),
        ),
    )

    projected, _ = apply_projection_pass(messages, max_active_messages=2)

    assert any(message.message_id == "sys" for message in projected)
    assert any(message.message_id == "latest-user" for message in projected)
    assert check_projection_invariants(messages, projected) == ()


def test_material_compaction_pass_feeds_prepared_context_effects() -> None:
    agent = AgentDefinition(name="main-router", description="router", prompt="route")
    plane = DefaultContextControlPlane(compaction_service=CompactionManager())
    messages = (
        RuntimeMessage(message_id="u1", role=MessageRole.USER, content="older prompt one"),
        RuntimeMessage(message_id="a1", role=MessageRole.ASSISTANT, content="older answer one"),
        RuntimeMessage(message_id="u2", role=MessageRole.USER, content="older prompt two"),
        RuntimeMessage(message_id="a2", role=MessageRole.ASSISTANT, content="older answer two"),
        RuntimeMessage(message_id="u3", role=MessageRole.USER, content="latest prompt"),
    )

    prepared = asyncio.run(
        plane.prepare(
            session_id="session",
            turn_id="turn",
            attempt_index=1,
            agent=agent,
            cwd=".",
            messages=messages,
            prompt_context=PromptContextEnvelope(),
            private_context=RuntimePrivateContext(
                extensions={"compaction_policy": {"max_message_count": 3, "keep_recent_messages": 2}}
            ),
            runtime_context={},
        )
    )

    assert any(effect.kind.value == "compaction" for effect in prepared.effects)
    assert prepared.prompt_context.compaction_summary is not None
    assert prepared.prompt_context.compaction_boundary is not None
    assert prepared.transcript_messages is not None
    assert isinstance(MaterialCompactionPass(CompactionManager()), MaterialCompactionPass)


def test_session_resume_replays_explicit_resumable_request_override(tmp_path: Path) -> None:
    model_client = SequencedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-block"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "blocked"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-resume"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "resumed"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-fresh"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "fresh"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    store = InMemoryTranscriptStore()
    services = RuntimeServices()
    services.hook_bus.register(
        session_id="session-resume-override",
        owner="resume-hook",
        phase=RuntimeHookPhase.STOP,
        handler=lambda _payload: {
            "stop_disposition": "block_session",
            "request_override": {
                "requested_model": "resume-model",
                "resumable": True,
                "source": "stop:resume",
            },
        },
    )

    async def first_session() -> SessionController:
        controller = SessionController(
            session_id="session-resume-override",
            agent=AgentDefinition(
                name="main-router",
                description="router",
                prompt="route",
                model="baseline-model",
            ),
            turn_engine=TurnEngine(
                model_client=model_client,
                tool_registry=ToolRegistry(),
                runtime_services=services,
            ),
            transcript_store=store,
            cwd=str(tmp_path),
            system_prompt="System",
            runtime_services=services,
        )
        await controller.start()
        controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "block"))
        await controller.run_until_idle()
        return controller

    blocked = asyncio.run(first_session())

    assert blocked.state.status.value == "waiting"
    assert blocked.state.metadata["resumable_request_override"]["requested_model"] == "resume-model"

    async def resumed_session() -> None:
        resumed_services = RuntimeServices()
        controller = SessionController(
            session_id="session-resume-override",
            agent=AgentDefinition(
                name="main-router",
                description="router",
                prompt="route",
                model="baseline-model",
            ),
            turn_engine=TurnEngine(
                model_client=model_client,
                tool_registry=ToolRegistry(),
                runtime_services=resumed_services,
            ),
            transcript_store=store,
            cwd=str(tmp_path),
            system_prompt="System",
            runtime_services=resumed_services,
        )
        await controller.resume()
        await controller.start()
        controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "resume"))
        await controller.run_until_idle()
        controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "fresh"))
        await controller.run_until_idle()

    asyncio.run(resumed_session())

    assert model_client.requests[1].model == "resume-model"
    assert model_client.requests[2].model == "baseline-model"


def test_emitted_resumable_request_override_survives_provider_error(tmp_path: Path) -> None:
    model_client = SequencedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-error"}),
                ModelStreamEvent(ModelStreamEventType.ERROR, {"error": "transport boom"}),
            ],
        ]
    )
    store = InMemoryTranscriptStore()

    async def seed_metadata() -> None:
        await store.save_session_metadata(
            "session-error-resume-override",
            {
                "resumable_request_override": {
                    "requested_model": "resume-model",
                    "source": "stop:resume",
                    "resumable": True,
                    "metadata": {"sources": ["stop:resume"]},
                }
            },
        )

    asyncio.run(seed_metadata())

    services = RuntimeServices()
    controller = SessionController(
        session_id="session-error-resume-override",
        agent=AgentDefinition(
            name="main-router",
            description="router",
            prompt="route",
            model="baseline-model",
        ),
        turn_engine=TurnEngine(
            model_client=model_client,
            tool_registry=ToolRegistry(),
            runtime_services=services,
        ),
        transcript_store=store,
        cwd=str(tmp_path),
        system_prompt="System",
        runtime_services=services,
    )

    async def scenario() -> None:
        await controller.resume()
        await controller.start()
        controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "resume"))
        await controller.run_until_idle()

    asyncio.run(scenario())

    assert model_client.requests[0].model == "resume-model"
    assert controller.state.metadata["resumable_request_override"]["requested_model"] == "resume-model"


def test_observability_metadata_exposes_control_plane_and_recovery_fields(tmp_path: Path) -> None:
    model_client = SequencedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-observe"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    services = RuntimeServices()
    controller = SessionController(
        session_id="session-observe",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
        turn_engine=TurnEngine(
            model_client=model_client,
            tool_registry=ToolRegistry(),
            runtime_services=services,
        ),
        transcript_store=InMemoryTranscriptStore(),
        cwd=str(tmp_path),
        system_prompt="System",
        runtime_services=services,
    )
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "observe"))

    async def collect():
        return [event async for event in controller.stream_until_idle()]

    events = asyncio.run(collect())
    request_event = next(event for event in events if event.event_type.value == "request_start")
    terminal_event = next(event for event in events if event.event_type.value == "terminal")

    assert request_event.request is not None
    assert request_event.request.metadata["control_plane"]["context_generation"] >= 1
    assert "effect_kinds" in request_event.request.metadata["control_plane"]
    assert terminal_event.terminal is not None
    assert terminal_event.terminal.metadata["recovery_action"] == "halt"
    assert terminal_event.terminal.metadata["recovery_reason"] == "attempt_completed"
    assert terminal_event.terminal.metadata["policy_tag"] == "default_recovery_policy"


def test_turn_engine_retries_output_limit_with_shared_request_override(tmp_path: Path) -> None:
    model_client = SequencedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "partial"}),
                ModelStreamEvent(
                    ModelStreamEventType.MESSAGE_STOP,
                    {
                        "stop_reason": "output_limit",
                        "metadata": {
                            "failure_class": "output_limit",
                            "retryable": True,
                            "max_output_tokens": 128,
                        },
                    },
                ),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "completed"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-3"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "fresh"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    services = RuntimeServices()
    controller = SessionController(
        session_id="session-output-limit",
        agent=AgentDefinition(
            name="main-router",
            description="router",
            prompt="route",
            model="baseline-model",
        ),
        turn_engine=TurnEngine(
            model_client=model_client,
            tool_registry=ToolRegistry(),
            runtime_services=services,
        ),
        transcript_store=InMemoryTranscriptStore(),
        cwd=str(tmp_path),
        system_prompt="System",
        runtime_services=services,
    )

    async def scenario() -> None:
        await controller.start()
        controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "continue"))
        await controller.run_until_idle()
        controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "fresh"))
        await controller.run_until_idle()

    asyncio.run(scenario())

    assert len(model_client.requests) == 3
    assert model_client.requests[0].model == "baseline-model"
    assert model_client.requests[1].max_output_tokens == 256
    assert model_client.requests[1].metadata["request_override"]["field_sources"][
        "max_output_tokens_override"
    ] == "recovery:output_limit"
    assert model_client.requests[2].max_output_tokens is None
    assert "control_plane" in model_client.requests[1].metadata
