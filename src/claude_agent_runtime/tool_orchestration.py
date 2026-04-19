from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, Callable, Sequence
from uuid import uuid4

from .contracts import MessageRole, RuntimeMessage, ToolResultBlock, utc_now
from .definitions import ToolCallStatus, ToolFailureClassifier, ToolFailureMode
from .execution_policy import EXECUTION_POLICY_STATE_KEY
from .tool_lifecycle import (
    AppStateSet,
    CapabilityRefreshRequested,
    ContextUpdate,
    ContextUpdatePhase,
    EnvelopeObserved,
    ExecutionQueued,
    ExecutionStarted,
    FileObservationRecorded,
    LegacyContextModifierWrapped,
    LifecycleTransitionError,
    MemoryAppended,
    NotificationEmitted,
    OutcomeRecorded,
    ProgressEmitted,
    ReplayCommitted,
    ResolvedToolCall,
    ResolutionCompleted,
    ResolutionStarted,
    ToolCallEnvelope,
    ToolLifecycleEvent,
    ToolLifecycleStage,
    ToolLaneDerivationMode,
    ToolOutcome,
    ToolResolutionStatus,
    ToolSchedulerLane,
    ToolSchedulerLaneKind,
    TranscriptAttachmentAdded,
    project_lifecycle_stage,
)
from .tool_resolution import resolve_tool_call, with_scheduler_lane
from .tool_runtime import (
    ExecutedToolCall,
    ToolCall,
    ToolContext,
    _build_tool_execution_classifications,
    _tool_catalog_view,
    execute_resolved_tool_call,
    maybe_await,
)

LifecycleSink = Callable[[ToolLifecycleEvent], None]


class StreamingToolOrchestrator:
    def __init__(
        self,
        *,
        context: ToolContext,
        executor_tier: str,
        model_capabilities: Any = None,
        lifecycle_sink: LifecycleSink | None = None,
    ) -> None:
        self._context = context
        self._executor_tier = executor_tier
        self._model_capabilities = model_capabilities
        self._lifecycle_sink = lifecycle_sink
        self._completion_index = 0
        self._scheduled_tasks: dict[str, asyncio.Task[ToolOutcome]] = {}
        self._scheduled_lanes: dict[str, ToolSchedulerLane] = {}
        self._resolved_calls: dict[str, ResolvedToolCall] = {}
        self._outcomes: dict[int, ToolOutcome] = {}
        self._lifecycle_stages: dict[str, ToolLifecycleStage | None] = {}
        self._started_calls: set[str] = set()
        self._observed_count = 0
        self._context.progress_callback = self._on_progress
        self._context.refresh_callback = self._on_refresh
        self._context.notification_callback = self._on_notification

    async def observe_tool_call(
        self,
        call: ToolCall,
        *,
        assistant_message_id: str,
        provider_request_id: str | None = None,
        block_index: int | None = None,
    ) -> ResolvedToolCall:
        envelope = ToolCallEnvelope(
            envelope_id=uuid4().hex,
            tool_use_id=call.call_id,
            sequence_index=self._observed_count,
            raw_tool_name=call.tool_name,
            raw_input=dict(call.tool_input),
            assistant_message_id=assistant_message_id,
            provider_request_id=provider_request_id,
            block_index=block_index,
            observed_at=utc_now(),
            query_snapshot=self._context.query_context,
        )
        self._observed_count += 1
        self._emit_lifecycle(
            EnvelopeObserved(
                tool_use_id=envelope.tool_use_id,
                replay_index=envelope.sequence_index,
                assistant_message_id=assistant_message_id,
                raw_tool_name=envelope.raw_tool_name,
            )
        )
        self._emit_lifecycle(
            ResolutionStarted(
                tool_use_id=envelope.tool_use_id,
                replay_index=envelope.sequence_index,
            )
        )
        resolved_call = await resolve_tool_call(
            envelope,
            self._context,
            executor_tier=self._executor_tier,
            model_capabilities=self._model_capabilities,
        )
        lane = self._derive_lane(resolved_call)
        resolved_call = with_scheduler_lane(resolved_call, lane)
        self._resolved_calls[resolved_call.envelope.tool_use_id] = resolved_call
        self._emit_lifecycle(
            ResolutionCompleted(
                tool_use_id=resolved_call.envelope.tool_use_id,
                replay_index=resolved_call.replay_index,
                resolution_status=resolved_call.resolution_status,
                canonical_tool_name=resolved_call.canonical_tool_name,
                tool_use_presentation=(
                    resolved_call.resolved_semantics.tool_use_presentation
                    if resolved_call.resolved_semantics is not None
                    else None
                ),
                classifier_input=(
                    resolved_call.resolved_semantics.classifier_input
                    if resolved_call.resolved_semantics is not None
                    else None
                ),
            )
        )
        if resolved_call.resolution_status != ToolResolutionStatus.EXECUTABLE:
            outcome = self._synthetic_outcome(resolved_call)
            self._record_outcome(outcome)
            return resolved_call
        self._emit_lifecycle(
            ExecutionQueued(
                tool_use_id=resolved_call.envelope.tool_use_id,
                replay_index=resolved_call.replay_index,
                lane_kind=lane.lane_kind if lane is not None else ToolSchedulerLaneKind.EXCLUSIVE,
                lane_key=lane.lane_key if lane is not None else None,
            )
        )
        wait_for = self._dependencies_for_lane(lane)
        task = asyncio.create_task(self._run_scheduled_call(resolved_call, wait_for=wait_for))
        self._scheduled_tasks[resolved_call.envelope.tool_use_id] = task
        if lane is not None:
            self._scheduled_lanes[resolved_call.envelope.tool_use_id] = lane
        return resolved_call

    async def run_batch(
        self,
        calls: Sequence[ToolCall],
        *,
        assistant_message_id: str,
        provider_request_id: str | None = None,
    ) -> tuple[ToolOutcome, ...]:
        for index, call in enumerate(calls):
            await self.observe_tool_call(
                call,
                assistant_message_id=assistant_message_id,
                provider_request_id=provider_request_id,
                block_index=index,
            )
        return await self.finalize()

    async def finalize(self) -> tuple[ToolOutcome, ...]:
        if self._scheduled_tasks:
            await asyncio.gather(*self._scheduled_tasks.values(), return_exceptions=True)
        ordered = tuple(self._outcomes[index] for index in sorted(self._outcomes))
        for outcome in ordered:
            await self._apply_context_updates(outcome, ContextUpdatePhase.BEFORE_REPLAY)
        for outcome in ordered:
            self._emit_lifecycle(
                ReplayCommitted(
                    tool_use_id=outcome.resolved_call.envelope.tool_use_id,
                    replay_index=outcome.replay_index,
                    completion_index=outcome.completion_index,
                    status=outcome.status,
                    result_summary=outcome.result_summary,
                )
            )
            await self._apply_context_updates(outcome, ContextUpdatePhase.WITH_REPLAY)
        for outcome in ordered:
            await self._apply_context_updates(outcome, ContextUpdatePhase.AFTER_REPLAY)
        return ordered

    def interrupt(self, reason: str = "interrupt") -> None:
        self._context.request_interrupt(reason)
        for task in self._scheduled_tasks.values():
            if not task.done():
                task.cancel()

    def tool_result_message(self, outcomes: Sequence[ToolOutcome]) -> RuntimeMessage | None:
        result_blocks = tuple(
            outcome.result_block
            for outcome in outcomes
            if outcome.result_block is not None
        )
        if not result_blocks:
            return None
        metadata: dict[str, Any] = {
            "tool_results": [
                _tool_result_metadata_entry(outcome)
                for outcome in outcomes
            ]
        }
        observed_paths = list(self._context.file_state.observed_paths())
        if observed_paths:
            metadata["observed_paths"] = observed_paths
        return RuntimeMessage(
            message_id=uuid4().hex,
            role=MessageRole.USER,
            content=result_blocks,
            metadata=metadata,
        )

    async def _run_scheduled_call(
        self,
        resolved_call: ResolvedToolCall,
        *,
        wait_for: Sequence[asyncio.Task[ToolOutcome]] = (),
    ) -> ToolOutcome:
        lane = resolved_call.scheduler_lane or ToolSchedulerLane(ToolSchedulerLaneKind.EXCLUSIVE)
        try:
            if wait_for is not None:
                await asyncio.gather(*wait_for, return_exceptions=True)
            self._started_calls.add(resolved_call.envelope.tool_use_id)
            self._emit_lifecycle(
                ExecutionStarted(
                    tool_use_id=resolved_call.envelope.tool_use_id,
                    replay_index=resolved_call.replay_index,
                    lane_kind=lane.lane_kind,
                )
            )
            executed = await execute_resolved_tool_call(resolved_call, self._context)
            outcome = self._build_outcome(resolved_call, executed)
        except asyncio.CancelledError:
            completion_index = self._completion_index
            self._completion_index += 1
            outcome = ToolOutcome(
                resolved_call=resolved_call,
                status=ToolCallStatus.CANCELLED,
                terminal_reason="Tool execution cancelled",
                error_message="Tool execution cancelled",
                result_block=_tool_result_block(
                    replace(
                        _empty_result(resolved_call),
                        status=ToolCallStatus.CANCELLED,
                        error="Tool execution cancelled",
                    )
                ),
                completion_index=completion_index,
                replay_index=resolved_call.replay_index,
                replay_eligible=True,
            )
        self._record_outcome(outcome)
        self._started_calls.discard(resolved_call.envelope.tool_use_id)
        await self._maybe_cascade_failure(outcome)
        return outcome

    def _build_outcome(
        self,
        resolved_call: ResolvedToolCall,
        executed: ExecutedToolCall,
    ) -> ToolOutcome:
        result = self._classify_result(executed.result, resolved_call)
        completion_index = self._completion_index
        self._completion_index += 1
        context_updates = tuple(executed.context_updates) + self._derived_context_updates(
            resolved_call,
            result,
        )
        return ToolOutcome(
            resolved_call=resolved_call,
            status=result.status,
            terminal_reason=result.error,
            raw_output=result.output,
            error_message=result.error,
            result_block=_tool_result_block(result),
            result_summary=executed.result_summary,
            context_updates=context_updates,
            completion_index=completion_index,
            replay_index=resolved_call.replay_index,
            replay_eligible=True,
        )

    def _synthetic_outcome(self, resolved_call: ResolvedToolCall) -> ToolOutcome:
        completion_index = self._completion_index
        self._completion_index += 1
        if resolved_call.resolution_status == ToolResolutionStatus.DENIED:
            permission = resolved_call.permission_decision
            status = (
                permission.denied_status
                if permission is not None and hasattr(permission, "denied_status")
                else ToolCallStatus.DENIED
            )
            error = permission.message if permission is not None and hasattr(permission, "message") else "Tool use denied"
        else:
            status = ToolCallStatus.ERROR
            error = f"Invalid tool call: {resolved_call.envelope.raw_tool_name}"
        return ToolOutcome(
            resolved_call=resolved_call,
            status=status,
            terminal_reason=error,
            error_message=error,
            result_block=_tool_result_block(
                replace(
                    _empty_result(resolved_call),
                    status=status,
                    error=error,
                )
            ),
            completion_index=completion_index,
            replay_index=resolved_call.replay_index,
            replay_eligible=True,
        )

    def _record_outcome(self, outcome: ToolOutcome) -> None:
        self._outcomes[outcome.replay_index] = outcome
        self._emit_lifecycle(
            OutcomeRecorded(
                tool_use_id=outcome.resolved_call.envelope.tool_use_id,
                replay_index=outcome.replay_index,
                completion_index=outcome.completion_index,
                status=outcome.status,
                result_summary=outcome.result_summary,
            )
        )

    def _derive_lane(self, resolved_call: ResolvedToolCall) -> ToolSchedulerLane | None:
        if resolved_call.resolution_status != ToolResolutionStatus.EXECUTABLE:
            return None
        semantics = resolved_call.resolved_semantics
        if semantics is None:
            return ToolSchedulerLane(ToolSchedulerLaneKind.EXCLUSIVE)
        if not semantics.concurrency_safe:
            return ToolSchedulerLane(
                lane_kind=ToolSchedulerLaneKind.EXCLUSIVE,
                shares_concurrency=False,
                derivation_mode=ToolLaneDerivationMode.COARSE,
            )
        classifier_input = semantics.classifier_input
        conflict_domains = ()
        if classifier_input is not None and classifier_input.target_paths:
            conflict_domains = tuple(
                resolved_call.capability_context.file_state.conflict_key(path)
                for path in classifier_input.target_paths
            )
        if semantics.read_only and not conflict_domains:
            return ToolSchedulerLane(
                lane_kind=ToolSchedulerLaneKind.CONCURRENT,
                shares_concurrency=True,
                derivation_mode=ToolLaneDerivationMode.PRECISE,
            )
        if conflict_domains:
            return ToolSchedulerLane(
                lane_kind=ToolSchedulerLaneKind.CONFLICT,
                lane_key="|".join(conflict_domains),
                conflict_domains=conflict_domains,
                shares_concurrency=False,
                derivation_mode=ToolLaneDerivationMode.PRECISE,
            )
        return ToolSchedulerLane(
            lane_kind=ToolSchedulerLaneKind.EXCLUSIVE,
            shares_concurrency=False,
            derivation_mode=ToolLaneDerivationMode.COARSE,
        )

    def _dependencies_for_lane(
        self,
        lane: ToolSchedulerLane | None,
    ) -> tuple[asyncio.Task[ToolOutcome], ...]:
        if lane is None:
            return ()
        dependencies: list[asyncio.Task[ToolOutcome]] = []
        seen: set[int] = set()
        for tool_use_id, task in self._scheduled_tasks.items():
            if task.done():
                continue
            prior_lane = self._scheduled_lanes.get(tool_use_id)
            if prior_lane is None or not _lanes_overlap(prior_lane, lane):
                continue
            marker = id(task)
            if marker in seen:
                continue
            seen.add(marker)
            dependencies.append(task)
        return tuple(dependencies)

    def _classify_result(
        self,
        result: Any,
        resolved_call: ResolvedToolCall,
    ) -> Any:
        semantics = resolved_call.resolved_semantics
        if semantics is None:
            return result
        policy = semantics.failure_policy
        if result.status != ToolCallStatus.SUCCESS:
            return result
        if policy.result_classifier == ToolFailureClassifier.NONZERO_EXIT_OR_EXCEPTION:
            output = result.output
            if isinstance(output, dict) and int(output.get("exit_code", 0)) != 0:
                return replace(
                    result,
                    status=policy.surfaced_status,
                    error=output.get("stderr") or output.get("stdout") or "Tool execution failed",
                )
        return result

    def _derived_context_updates(
        self,
        resolved_call: ResolvedToolCall,
        result: Any,
    ) -> tuple[ContextUpdate, ...]:
        if result.status != ToolCallStatus.SUCCESS:
            return ()
        semantics = resolved_call.resolved_semantics
        if semantics is None or semantics.classifier_input is None:
            return ()
        updates: list[ContextUpdate] = []
        observation_kind = "read" if semantics.read_only else "write_commit"
        for path in semantics.classifier_input.target_paths:
            updates.append(
                FileObservationRecorded(
                    observation_kind=observation_kind,
                    path=path,
                    conflict_key=resolved_call.capability_context.file_state.conflict_key(path),
                )
            )
        return tuple(updates)

    async def _maybe_cascade_failure(self, outcome: ToolOutcome) -> None:
        semantics = outcome.resolved_call.resolved_semantics
        if semantics is None:
            return
        policy = semantics.failure_policy
        if policy.failure_mode != ToolFailureMode.FATAL:
            return
        if outcome.status == ToolCallStatus.SUCCESS:
            return
        if policy.abort_model_stream:
            self._context.request_interrupt(
                reason=f"tool_failure:{outcome.resolved_call.envelope.tool_use_id}"
            )
        current_id = outcome.resolved_call.envelope.tool_use_id
        for tool_use_id, task in tuple(self._scheduled_tasks.items()):
            if tool_use_id == current_id or task.done():
                continue
            started = tool_use_id in self._started_calls
            if started and not policy.cancel_running_siblings:
                continue
            if not started and not policy.block_queued_siblings:
                continue
            task.cancel()

    async def _apply_context_updates(
        self,
        outcome: ToolOutcome,
        phase: ContextUpdatePhase,
    ) -> None:
        for update in outcome.context_updates:
            if update.apply_phase != phase:
                continue
            await self._apply_context_update(update)

    async def _apply_context_update(self, update: ContextUpdate) -> None:
        if isinstance(update, AppStateSet):
            if self._context.turn_state is not None:
                self._context.turn_state.set(update.namespace, update.key, update.value)
            else:
                self._context.app_state.set(update.namespace, update.key, update.value)
            return
        if isinstance(update, FileObservationRecorded):
            if update.observation_kind == "read":
                self._context.file_state.record_read(update.path, update.digest)
            elif update.observation_kind == "write_intent":
                self._context.file_state.record_write_intent(update.path)
            else:
                self._context.file_state.record_write_commit(update.path, update.digest)
            return
        if isinstance(update, CapabilityRefreshRequested):
            await self._refresh_capabilities(update.scope, update.reason)
            return
        if isinstance(update, NotificationEmitted):
            await self._context.emit_notification(
                RuntimeMessage(
                    message_id=uuid4().hex,
                    role=MessageRole.NOTIFICATION,
                    content=update.message,
                    metadata={
                        "level": update.level,
                        "skip_runtime_notification": True,
                    },
                )
            )
            return
        if isinstance(update, MemoryAppended):
            self._context.memory_access.append(update.scope, update.entry)
            return
        if isinstance(update, TranscriptAttachmentAdded):
            attachments = self._context.metadata.setdefault("tool_attachments", [])
            if isinstance(attachments, list):
                attachments.append(dict(update.payload))
            return
        if isinstance(update, LegacyContextModifierWrapped) and update.modifier is not None:
            await maybe_await(update.modifier(self._context))

    async def _refresh_capabilities(self, scope: str, reason: str) -> None:
        if scope != "tool_pool":
            return
        if self._context.runtime_services is None:
            return
        callback = self._context.runtime_services.tool_refresh_callback
        if callback is None:
            return
        refreshed = await maybe_await(callback(self._context))
        if refreshed is None:
            return
        self._context.tool_pool = tuple(refreshed)
        self._context.tool_catalog = _tool_catalog_view(self._context.tool_pool)
        if self._context.turn_scope is not None:
            self._context.turn_scope.tool_pool = self._context.tool_pool
            self._context.turn_scope.tool_catalog = self._context.tool_catalog
        self._context.tool_execution_classifications = _build_tool_execution_classifications(
            self._context.tool_pool
        )
        if self._context.internal_context is not None:
            self._context.internal_context.execution_classifications = dict(
                self._context.tool_execution_classifications
            )
        policy_state = self._context.metadata.get(EXECUTION_POLICY_STATE_KEY)
        if policy_state is not None and hasattr(policy_state, "effective"):
            policy_state.effective = replace(
                policy_state.effective,
                tool_pool=self._context.tool_pool,
                trace={
                    "source": "capability_refresh",
                    "scope": scope,
                    "reason": reason,
                    "effective_tools": [tool.name for tool in self._context.tool_pool],
                },
            )

    def _emit_lifecycle(self, event: ToolLifecycleEvent) -> None:
        current = self._lifecycle_stages.get(event.tool_use_id)
        try:
            stage = project_lifecycle_stage(current, event)
        except LifecycleTransitionError:
            raise
        self._lifecycle_stages[event.tool_use_id] = stage
        if self._lifecycle_sink is not None:
            self._lifecycle_sink(event)

    def _on_progress(
        self,
        progress_id: str,
        message: str,
        percent: float | None,
        context: ToolContext,
    ) -> None:
        if context.tool_use_id is None or context.replay_index is None:
            return
        self._emit_lifecycle(
            ProgressEmitted(
                tool_use_id=context.tool_use_id,
                replay_index=context.replay_index,
                progress_id=progress_id,
                message=message,
                percent=percent,
            )
        )

    def _on_refresh(self, scope: str, reason: str, context: ToolContext) -> None:
        _ = scope, reason, context
        return None

    def _on_notification(self, message: str, level: str, context: ToolContext) -> None:
        _ = message, level, context
        return None


def _empty_result(resolved_call: ResolvedToolCall):
    from .tool_runtime import ToolCallResult

    return ToolCallResult(
        call_id=resolved_call.envelope.tool_use_id,
        tool_name=resolved_call.canonical_tool_name or resolved_call.envelope.raw_tool_name,
        status=ToolCallStatus.ERROR,
    )


def _tool_result_block(result: Any) -> ToolResultBlock:
    content = result.output if result.status == ToolCallStatus.SUCCESS else (result.error or "")
    return ToolResultBlock(
        tool_use_id=result.call_id,
        content=content,
        is_error=result.status != ToolCallStatus.SUCCESS,
    )


def _lanes_overlap(left: ToolSchedulerLane, right: ToolSchedulerLane) -> bool:
    if ToolSchedulerLaneKind.EXCLUSIVE in {left.lane_kind, right.lane_kind}:
        return True
    if ToolSchedulerLaneKind.CONCURRENT in {left.lane_kind, right.lane_kind}:
        return False
    left_domains = set(left.conflict_domains or ((left.lane_key,) if left.lane_key else ()))
    right_domains = set(right.conflict_domains or ((right.lane_key,) if right.lane_key else ()))
    if not left_domains or not right_domains:
        return True
    return not left_domains.isdisjoint(right_domains)


def _tool_result_metadata_entry(outcome: ToolOutcome) -> dict[str, Any]:
    entry = {
        "tool_use_id": outcome.resolved_call.envelope.tool_use_id,
        "tool_name": outcome.resolved_call.canonical_tool_name
        or outcome.resolved_call.envelope.raw_tool_name,
        "status": outcome.status.value,
    }
    if outcome.result_summary is not None:
        entry["result_summary"] = {
            "title": outcome.result_summary.title,
            "summary": outcome.result_summary.summary,
            "status": outcome.result_summary.status.value,
            "detail_lines": list(outcome.result_summary.detail_lines),
        }
    return entry
