from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, AsyncIterator, Mapping, Sequence
from uuid import uuid4

from ..agent_execution import AgentRunRecord
from ..compaction import (
    CompactionPolicy,
    CompactionResult,
    evaluate_context_pressure,
    serialize_compaction_boundary,
    serialize_compaction_continuation,
    serialize_compaction_result,
    serialize_compaction_summary,
)
from ..context_window import (
    serialize_model_context_window_profile,
    serialize_resolved_context_window_snapshot,
    serialize_route_context_window_policy,
)
from ..contracts import (
    ContentBlock,
    ContentBlockType,
    MessageAttachment,
    MessageRole,
    PromptContextEnvelope,
    RedactedThinkingBlock,
    RequestOverrideState,
    RuntimeMessage,
    RuntimePrivateContext,
    SkillRequestOverrideState,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    compatibility_runtime_context_snapshot,
    coerce_request_override_state,
    coerce_skill_request_override_state,
    deserialize_content_blocks,
    merge_runtime_private_context,
    merge_request_override_state,
    merge_skill_request_override_state,
    private_context_from_legacy_runtime_context,
    prompt_context_from_legacy_runtime_context,
    request_override_from_skill_request_override,
    serialize_content_blocks,
    serialize_resumable_request_override,
    skill_request_override_from_request_override,
)
from ..definitions import AgentDefinition, PermissionMode, ResolvedInvocationCatalog
from ..execution_policy import (
    EXECUTION_POLICY_STATE_KEY,
    ExecutionPolicyState,
    build_root_execution_policy,
    policy_state_from_metadata,
    resolve_skill_pool,
    serialize_runtime_metadata,
)
from ..hooks import (
    PostCompactPayload,
    PostContextAssemblePayload,
    PostModelResponsePayload,
    PreCompactPayload,
    PreContextAssemblePayload,
    PreModelRequestPayload,
    RecoveryDecisionPayload,
    StopPayload,
    UserPromptSubmitPayload,
)
from ..invocation_catalog import SkillInvocationProvider, build_invocation_resolution_context
from ..jobs import DefaultJobService
from ..permissions import PermissionContext
from ..registries import AgentRegistry, InvocationRegistry, SkillRegistry, ToolRegistry
from ..runtime_services import RuntimeServices, SidecarContributionResult
from ..runtime_package_protocols import (
    ContextContributorExecutionEntry,
    ContextContributorPromptChannel,
)
from ..runtime_kernel.config import (
    ModelProviderBinding,
    ModelRouteBinding,
    ResolvedModelRouteBinding,
    resolve_model_route_binding,
)
from ..tool_executors import model_capabilities_for, select_tool_executor
from ..tool_lifecycle import ToolLifecycleEvent
from ..tasking import TaskManager
from ..tool_runtime import (
    SessionScope,
    ToolCall,
    ToolContext,
    ToolRefreshCallback,
    ToolScheduler,
    assemble_main_thread_tool_pool,
    maybe_await,
)
from .composer import ContextAssembler, PromptComposer
from .control_plane import (
    ContextPreparationEffectKind,
    ContextControlPlaneConfig,
    DefaultContextControlPlane,
    DefaultRecoveryPolicy,
    FailureClassification,
    NormalizedRecoveryInput,
    PreparedContext,
    RecoveryAction,
    RecoveryDecision,
    RecoveryState,
    StopDisposition,
    StopPhaseOutcome,
    build_prompt_envelope,
    next_context_generation,
    normalize_attempt_outcome,
)
from .message_protocol import normalize_messages_for_api
from .models import (
    ModelAbortSignal,
    ModelClient,
    ModelInvocationMode,
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    ModelTerminalMetadata,
    NormalizedModelCapabilities,
)


class TurnStreamEventType(StrEnum):
    ATTEMPT_FINISHED = "attempt_finished"
    CHILD_RUN = "child_run"
    COMPACTION = "compaction"
    REQUEST_START = "request_start"
    STREAM_PROGRESS = "stream_progress"
    TOOL_LIFECYCLE = "tool_lifecycle"
    MESSAGE = "message"
    MESSAGE_DISCARDED = "message_discarded"
    TERMINAL = "terminal"


class TurnPhase(StrEnum):
    PREPARE = "prepare"
    PREFETCH_SIDECARS = "prefetch_sidecars"
    COMPACT_OR_REBUILD = "compact_or_rebuild"
    BUILD_REQUEST = "build_request"
    STREAM_ATTEMPT = "stream_attempt"
    REPLAY_TOOLS = "replay_tools"
    STOP_PHASE = "stop_phase"
    RECOVERY_DECISION = "recovery_decision"
    ADVANCE_OR_FINISH = "advance_or_finish"
    TERMINAL = "terminal"


class TurnRecoveryAction(StrEnum):
    CONTINUE_SAME_TURN = "continue_same_turn"
    REBUILD_REQUEST = "rebuild_request"
    COMPACT_AND_RETRY = "compact_and_retry"
    RETRY_WITH_OVERRIDE = "retry_with_override"
    HALT = "halt"


class TurnTransitionReason(StrEnum):
    NEXT_TURN = "next_turn"
    STOP_HOOK_BLOCKING = "stop_hook_blocking"
    MAX_TURNS_EXHAUSTED = "max_turns_exhausted"
    ATTEMPT_COMPLETED = "attempt_completed"
    ATTEMPT_INTERRUPTED = "attempt_interrupted"
    ATTEMPT_ERROR = "attempt_error"
    TOOL_EXECUTOR_UNAVAILABLE = "tool_executor_unavailable"


class TurnTerminalReason(StrEnum):
    END_TURN = "end_turn"
    MESSAGE_STOP = "message_stop"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    MAX_TURNS = "max_turns"
    PROMPT_TOO_LONG = "prompt_too_long"
    IMAGE_ERROR = "image_error"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class TurnTransition:
    reason: TurnTransitionReason
    recovery_action: TurnRecoveryAction
    next_phase: TurnPhase
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnPostEffects:
    persist_memory: bool = False
    schedule_background_extraction: bool = False
    refresh_session_state: bool = False
    session_status_hint: str | None = None
    matched_stop_hooks: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AttemptFinished:
    iteration: int
    request_id: str | None = None
    attempt_stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    ttft_ms: float | None = None
    error: str | None = None
    abort_reason: str | None = None
    produced_tool_calls: bool = False
    tool_call_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def stop_reason(self) -> str | None:
        return self.attempt_stop_reason


@dataclass(frozen=True, slots=True)
class TurnTerminal:
    reason: TurnTerminalReason
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    ttft_ms: float | None = None
    error: str | None = None
    abort_reason: str | None = None
    provider_stop_reason: str | None = None
    transition: TurnTransition | None = None
    post_effects: TurnPostEffects = field(default_factory=TurnPostEffects)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def stop_reason(self) -> str:
        return self.reason.value

    @property
    def completed(self) -> bool:
        return _terminal_reason_is_completed(self.reason)


@dataclass(slots=True)
class TurnLoopState:
    phase: TurnPhase = TurnPhase.PREPARE
    iteration: int = 0
    working_messages: tuple[RuntimeMessage, ...] = ()
    policy_state: ExecutionPolicyState | None = None
    sidecar_generation: int = 0
    prepared_context: PreparedContext | None = None
    recovery_state: RecoveryState = field(default_factory=RecoveryState)
    consumed_request_override: RequestOverrideState | None = None
    transition: TurnTransition | None = None
    terminal: TurnTerminal | None = None
    post_effects: TurnPostEffects = field(default_factory=TurnPostEffects)
    attempts: tuple[AttemptFinished, ...] = ()
    phase_history: tuple[TurnPhase, ...] = field(default_factory=lambda: (TurnPhase.PREPARE,))


@dataclass(frozen=True, slots=True)
class TurnStreamEvent:
    event_type: TurnStreamEventType
    iteration: int
    phase: TurnPhase | None = None
    request: ModelRequest | None = None
    model_event: ModelStreamEvent | None = None
    tool_event: ToolLifecycleEvent | None = None
    child_run: AgentRunRecord | None = None
    attempt: AttemptFinished | None = None
    transition: TurnTransition | None = None
    post_effects: TurnPostEffects | None = None
    message: RuntimeMessage | None = None
    compacted_messages: tuple[RuntimeMessage, ...] = ()
    terminal: TurnTerminal | None = None
    discarded_content: tuple[ContentBlock, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TurnResult:
    messages: list[RuntimeMessage] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    attempts: list[AttemptFinished] = field(default_factory=list)
    iterations: int = 0
    completed: bool = False
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    ttft_ms: float | None = None
    abort_reason: str | None = None
    error: str | None = None
    terminal: TurnTerminal | None = None
    transition: TurnTransition | None = None
    post_effects: TurnPostEffects | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _PendingBlock:
    block_type: ContentBlockType
    block_id: str | None = None
    text: str = ""
    tool_name: str | None = None
    tool_input: dict[str, Any] = field(default_factory=dict)

    def to_block(self) -> ContentBlock:
        if self.block_type == ContentBlockType.TEXT:
            return TextBlock(text=self.text)
        if self.block_type == ContentBlockType.THINKING:
            return ThinkingBlock(thinking=self.text)
        if self.block_type == ContentBlockType.REDACTED_THINKING:
            return RedactedThinkingBlock(data=self.text or None)
        if self.block_type == ContentBlockType.TOOL_USE:
            return ToolUseBlock(
                tool_use_id=self.block_id or uuid4().hex,
                name=self.tool_name or "",
                input=dict(self.tool_input),
            )
        raise ValueError(f"Unsupported content block type: {self.block_type!r}")


@dataclass(slots=True)
class _StreamAttemptState:
    blocks: list[ContentBlock] = field(default_factory=list)
    pending_block: _PendingBlock | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    new_tool_calls: list[ToolCall] = field(default_factory=list)
    message_stopped: bool = False
    pending_tool_use_closed_at_message_stop: bool = False
    request_id: str | None = None
    ttft_ms: float | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None
    error: str | None = None
    abort_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def observe(self, event: ModelStreamEvent) -> None:
        self._merge_terminal_fields(event)
        if event.event_type == ModelStreamEventType.MESSAGE_START:
            return
        if event.event_type == ModelStreamEventType.CONTENT_BLOCK_START:
            self._start_block(event)
            return
        if event.event_type == ModelStreamEventType.CONTENT_BLOCK_DELTA:
            self._apply_block_delta(event)
            return
        if event.event_type == ModelStreamEventType.CONTENT_BLOCK_STOP:
            self._finalize_pending_block()
            return
        if event.event_type == ModelStreamEventType.CONTENT_DELTA:
            self._append_legacy_text(event)
            return
        if event.event_type == ModelStreamEventType.TOOL_CALL:
            self._append_legacy_tool_call(event)
            return
        if event.event_type == ModelStreamEventType.MESSAGE_STOP:
            self.message_stopped = True
            if (
                self.pending_block is not None
                and self.pending_block.block_type == ContentBlockType.TOOL_USE
            ):
                self.pending_tool_use_closed_at_message_stop = True
            self._finalize_pending_block()
            return
        if event.event_type == ModelStreamEventType.ERROR:
            self.error = _string_value(event.payload.get("error")) or self.error or "Model stream error"

    def finalize(
        self,
        *,
        abort_reason: str | None,
        preserve_observed_tool_uses: bool = False,
    ) -> tuple[tuple[ContentBlock, ...], tuple[ContentBlock, ...], tuple[ToolCall, ...], ModelTerminalMetadata]:
        if self.message_stopped:
            committed_blocks = tuple(self.blocks)
            discarded_blocks = ()
            tool_calls = tuple(self.tool_calls)
        elif preserve_observed_tool_uses and self.tool_calls:
            committed_blocks = tuple(self.blocks)
            discarded_blocks = self._discard_pending_block()
            tool_calls = tuple(self.tool_calls)
        else:
            committed_blocks = ()
            discarded_blocks = tuple(self.blocks) + self._discard_pending_block()
            tool_calls = ()

        terminal = ModelTerminalMetadata(
            stop_reason=self.stop_reason or _synthesized_stop_reason(abort_reason, self.message_stopped, self.error),
            usage=dict(self.usage),
            request_id=self.request_id,
            ttft_ms=self.ttft_ms,
            error=self.error,
            abort_reason=self.abort_reason or abort_reason,
            metadata=dict(self.metadata),
        )
        return committed_blocks, discarded_blocks, tool_calls, terminal

    def drain_new_tool_calls(self) -> tuple[ToolCall, ...]:
        drained = tuple(self.new_tool_calls)
        self.new_tool_calls.clear()
        return drained

    def _merge_terminal_fields(self, event: ModelStreamEvent) -> None:
        terminal = event.terminal
        if terminal is not None:
            self.request_id = terminal.request_id or self.request_id
            self.ttft_ms = terminal.ttft_ms if terminal.ttft_ms is not None else self.ttft_ms
            if terminal.usage:
                self.usage = dict(terminal.usage)
            self.stop_reason = terminal.stop_reason or self.stop_reason
            self.error = terminal.error or self.error
            self.abort_reason = terminal.abort_reason or self.abort_reason
            self.metadata.update(terminal.metadata)

        payload = event.payload
        request_id = _string_value(payload.get("request_id"))
        if request_id is not None:
            self.request_id = request_id
        ttft_ms = _float_value(payload.get("ttft_ms"))
        if ttft_ms is not None:
            self.ttft_ms = ttft_ms
        usage = _mapping_value(payload.get("usage"))
        if usage:
            self.usage = usage
        stop_reason = _string_value(payload.get("stop_reason"))
        if stop_reason is not None:
            self.stop_reason = stop_reason
        error = _string_value(payload.get("error"))
        if error is not None:
            self.error = error
        abort_reason = _string_value(payload.get("abort_reason"))
        if abort_reason is not None:
            self.abort_reason = abort_reason
        metadata = _mapping_value(payload.get("metadata"))
        if metadata:
            self.metadata.update(metadata)

    def _start_block(self, event: ModelStreamEvent) -> None:
        self._finalize_pending_block()
        payload = event.payload
        block_type = _coerce_block_type(event.block_type or payload.get("block_type") or payload.get("type"))
        text = (
            _string_value(payload.get("text"))
            or _string_value(payload.get("delta"))
            or _string_value(payload.get("thinking"))
            or _string_value(payload.get("data"))
            or ""
        )
        self.pending_block = _PendingBlock(
            block_type=block_type,
            block_id=event.block_id
            or _string_value(payload.get("block_id"))
            or _string_value(payload.get("tool_use_id"))
            or _string_value(payload.get("call_id")),
            text=text,
            tool_name=_string_value(payload.get("tool_name")) or _string_value(payload.get("name")),
            tool_input=_mapping_value(payload.get("tool_input")) or _mapping_value(payload.get("input")),
        )

    def _apply_block_delta(self, event: ModelStreamEvent) -> None:
        payload = event.payload
        block_type = _coerce_block_type(event.block_type or payload.get("block_type") or payload.get("type"))
        if self.pending_block is None or self.pending_block.block_type != block_type:
            self._start_block(event)
            return
        if block_type in {
            ContentBlockType.TEXT,
            ContentBlockType.THINKING,
            ContentBlockType.REDACTED_THINKING,
        }:
            self.pending_block.text += (
                _string_value(payload.get("text"))
                or _string_value(payload.get("delta"))
                or _string_value(payload.get("thinking"))
                or _string_value(payload.get("data"))
                or ""
            )
            return
        if block_type == ContentBlockType.TOOL_USE:
            tool_name = _string_value(payload.get("tool_name")) or _string_value(payload.get("name"))
            if tool_name is not None:
                self.pending_block.tool_name = tool_name
            tool_input = _mapping_value(payload.get("tool_input")) or _mapping_value(payload.get("input"))
            if tool_input:
                self.pending_block.tool_input.update(tool_input)

    def _append_legacy_text(self, event: ModelStreamEvent) -> None:
        text = _string_value(event.payload.get("text")) or ""
        if not text:
            return
        if self.pending_block is None or self.pending_block.block_type != ContentBlockType.TEXT:
            self._finalize_pending_block()
            self.pending_block = _PendingBlock(block_type=ContentBlockType.TEXT)
        self.pending_block.text += text

    def _append_legacy_tool_call(self, event: ModelStreamEvent) -> None:
        self._finalize_pending_block()
        tool_name = _string_value(event.payload.get("tool_name"))
        if tool_name is None:
            return
        tool_input = _mapping_value(event.payload.get("tool_input")) or _mapping_value(event.payload.get("input")) or {}
        call_id = (
            _string_value(event.payload.get("call_id"))
            or _string_value(event.payload.get("tool_use_id"))
            or uuid4().hex
        )
        block = ToolUseBlock(tool_use_id=call_id, name=tool_name, input=tool_input)
        self.blocks.append(block)
        tool_call = ToolCall(call_id=call_id, tool_name=tool_name, tool_input=tool_input)
        self.tool_calls.append(tool_call)
        self.new_tool_calls.append(tool_call)

    def _finalize_pending_block(self) -> None:
        if self.pending_block is None:
            return
        block = self.pending_block.to_block()
        self.blocks.append(block)
        if isinstance(block, ToolUseBlock):
            tool_call = ToolCall(
                call_id=block.tool_use_id,
                tool_name=block.name,
                tool_input=dict(block.input),
            )
            self.tool_calls.append(tool_call)
            self.new_tool_calls.append(tool_call)
        self.pending_block = None

    def _discard_pending_block(self) -> tuple[ContentBlock, ...]:
        if self.pending_block is None:
            return ()
        discarded = (self.pending_block.to_block(),)
        self.pending_block = None
        return discarded


@dataclass(frozen=True, slots=True)
class _SidecarJoinResult:
    prompt_fragments: tuple[str, ...] = ()
    private_updates: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _RegisteredContributorJoinResult:
    memory_fragments: tuple[str, ...] = ()
    hook_fragments: tuple[str, ...] = ()
    private_updates: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


class _InvalidContextContributorOutput(TypeError):
    def __init__(self, value: Any) -> None:
        self.returned_type = type(value).__name__
        super().__init__(
            "context contributor collect() must return SidecarContributionResult or a sequence "
            "of prompt fragments"
        )


class _InvalidContextContributorBinding(TypeError):
    def __init__(self, value: Any) -> None:
        self.returned_type = type(value).__name__
        super().__init__(
            "context contributor binding must expose a callable collect() method"
        )


_SIDECAR_DIAGNOSTIC_KEYS = frozenset({"memory_retrieval", "memory_diagnostics"})
_SIDECAR_PROMPT_ONLY_KEYS = frozenset({"prompt_updates"})


class _PreTurnSidecarSupervisor:
    def __init__(
        self,
        engine: "TurnEngine",
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
    ) -> None:
        self._engine = engine
        self._session_id = session_id
        self._turn_id = turn_id
        self._agent = agent
        self._cwd = cwd
        self.generation = 0
        self._registry_task: asyncio.Task[_RegisteredContributorJoinResult] | None = None
        self._memory_task: asyncio.Task[_SidecarJoinResult] | None = None
        self._hook_task: asyncio.Task[_SidecarJoinResult] | None = None
        self._task_discipline_task: asyncio.Task[_SidecarJoinResult] | None = None

    def start(
        self,
        *,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope,
        private_context: RuntimePrivateContext,
        runtime_context: Mapping[str, object] | None,
    ) -> None:
        self.cancel()
        self.generation += 1
        task_kwargs = {
            "session_id": self._session_id,
            "turn_id": self._turn_id,
            "agent": self._agent,
            "cwd": self._cwd,
            "messages": tuple(messages),
            "prompt_context": prompt_context,
            "private_context": private_context,
            "runtime_context": dict(runtime_context or {}),
        }
        execution_plan = self._engine._runtime_services.context_contributor_execution_plan()
        if execution_plan and any(
            not bool(entry.binding.metadata.get("compatibility_only"))
            for entry in execution_plan
        ):
            self._registry_task = asyncio.create_task(
                self._engine._collect_registered_context_contributors(
                    execution_plan=execution_plan,
                    **task_kwargs,
                )
            )
            return
        self._memory_task = asyncio.create_task(
            self._engine._collect_control_plane_fragments_with_context(
                self._engine._runtime_services.memory,
                **task_kwargs,
            )
        )
        self._hook_task = asyncio.create_task(
            self._engine._collect_control_plane_fragments_with_context(
                self._engine._runtime_services.hooks,
                **task_kwargs,
            )
        )
        self._task_discipline_task = asyncio.create_task(
            self._engine._collect_control_plane_fragments_with_context(
                self._engine._runtime_services.task_discipline,
                **task_kwargs,
            )
        )

    async def restart(
        self,
        *,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope,
        private_context: RuntimePrivateContext,
        runtime_context: Mapping[str, object] | None,
    ) -> None:
        self.start(
            messages=messages,
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=runtime_context,
        )

    async def join(
        self,
    ) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, Any], dict[str, Any]]:
        if self._registry_task is not None:
            result = await self._resolve_registered(self._registry_task)
            return (
                result.memory_fragments,
                result.hook_fragments,
                result.private_updates,
                result.diagnostics,
            )
        memory_result = await self._resolve(self._memory_task)
        hook_result = await self._resolve(self._hook_task)
        task_discipline_result = await self._resolve(self._task_discipline_task)
        merged_private_updates = dict(memory_result.private_updates)
        merged_private_updates.update(hook_result.private_updates)
        merged_private_updates.update(task_discipline_result.private_updates)
        merged_diagnostics = dict(memory_result.diagnostics)
        merged_diagnostics.update(hook_result.diagnostics)
        merged_diagnostics.update(task_discipline_result.diagnostics)
        return (
            memory_result.prompt_fragments,
            hook_result.prompt_fragments + task_discipline_result.prompt_fragments,
            merged_private_updates,
            merged_diagnostics,
        )

    async def close(self) -> None:
        tasks = tuple(
            task
            for task in (
                self._registry_task,
                self._memory_task,
                self._hook_task,
                self._task_discipline_task,
            )
            if task is not None
        )
        self.cancel()
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)

    def cancel(self) -> None:
        for task in (
            self._registry_task,
            self._memory_task,
            self._hook_task,
            self._task_discipline_task,
        ):
            if task is not None and not task.done():
                task.cancel()

    async def _resolve(self, task: asyncio.Task[_SidecarJoinResult] | None) -> _SidecarJoinResult:
        if task is None:
            return _SidecarJoinResult()
        try:
            return await task
        except asyncio.CancelledError:
            return _SidecarJoinResult()

    async def _resolve_registered(
        self,
        task: asyncio.Task[_RegisteredContributorJoinResult] | None,
    ) -> _RegisteredContributorJoinResult:
        if task is None:
            return _RegisteredContributorJoinResult()
        try:
            return await task
        except asyncio.CancelledError:
            return _RegisteredContributorJoinResult()


class TurnEngine:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        invocation_registry: InvocationRegistry | None = None,
        prompt_composer: PromptComposer | None = None,
        permission_handler=None,
        ask_user_handler=None,
        agent_runner=None,
        skill_runner=None,
        notification_provider=None,
        notification_sink=None,
        tool_refresh_callback: ToolRefreshCallback | None = None,
        task_manager: TaskManager | None = None,
        job_service: DefaultJobService | None = None,
        runtime_services: RuntimeServices | None = None,
        context_control_plane: Any | None = None,
        recovery_policy: Any | None = None,
        model_providers: Mapping[str, ModelProviderBinding] | None = None,
        model_routes: Mapping[str, ModelRouteBinding] | None = None,
        default_model_route: str | None = None,
    ) -> None:
        self._model_client = model_client
        self._model_providers = dict(model_providers or {})
        self._model_routes = dict(model_routes or {})
        self._default_model_route = default_model_route
        self._tool_registry = tool_registry
        self._agent_registry = agent_registry
        self._skill_registry = skill_registry
        self._invocation_registry = invocation_registry or _default_invocation_registry(skill_registry)
        self._runtime_services = runtime_services or RuntimeServices(jobs=job_service)
        if self._runtime_services.context_assembler is None:
            self._runtime_services.context_assembler = prompt_composer or ContextAssembler()
        elif prompt_composer is not None:
            self._runtime_services.context_assembler = prompt_composer
        if task_manager is not None:
            self._runtime_services.bind_task_manager(task_manager)
        elif job_service is not None and self._runtime_services.job_service is not job_service:
            self._runtime_services.bind_job_service(job_service)
        if any(
            value is not None
            for value in (
                permission_handler,
                ask_user_handler,
                notification_provider,
                notification_sink,
                tool_refresh_callback,
            )
        ):
            self._runtime_services.configure_compat(
                permission_handler=permission_handler,
                ask_user_handler=ask_user_handler,
                notification_provider=notification_provider,
                notification_sink=notification_sink,
                tool_refresh_callback=tool_refresh_callback,
            )
        if agent_runner is not None or skill_runner is not None:
            self._runtime_services.bind_execution(
                agent_runner=agent_runner,
                skill_runner=skill_runner,
            )
        self._active_scheduler: ToolScheduler | None = None
        self._active_tool_context: ToolContext | None = None
        self._active_tool_executor: Any = None
        self._active_abort_signal: ModelAbortSignal | None = None
        self._child_run_events: dict[tuple[str, str], list[AgentRunRecord]] = {}
        self._context_control_plane = context_control_plane or DefaultContextControlPlane(
            compaction_service=self._runtime_services.compaction,
            default_config=self._runtime_services.metadata.get("context_control"),
        )
        self._recovery_policy = recovery_policy or DefaultRecoveryPolicy()

    @property
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

    def _resolve_route_runtime_metadata(
        self,
        *,
        agent: AgentDefinition,
        runtime_metadata: Mapping[str, object] | None,
    ) -> tuple[ResolvedModelRouteBinding | None, dict[str, object]]:
        if not self._model_routes and self._default_model_route is None:
            return None, {}
        resolved_route_name, binding = resolve_model_route_binding(
            requested_model_route=_string_value(runtime_metadata.get("requested_model_route"))
            if isinstance(runtime_metadata, Mapping)
            else None,
            agent_model_route=agent.model_route,
            inherited_route=_string_value(runtime_metadata.get("resolved_model_route"))
            if isinstance(runtime_metadata, Mapping)
            else None,
            default_model_route=self._default_model_route,
            model_providers=self._model_providers,
            model_routes=self._model_routes,
        )
        if binding is None:
            return None, {}
        return binding, {
            "resolved_model_route": resolved_route_name,
            "provider_name": binding.provider_name,
            "resolved_capabilities": _serialize_model_capabilities(binding.capabilities),
            "provider_context_window_profiles": [
                serialize_model_context_window_profile(profile)
                for profile in binding.context_window_profiles
            ],
            "route_context_window_policy": serialize_route_context_window_policy(
                binding.context_window_policy
            ),
            "route_default_model": binding.default_model,
        }

    def _apply_route_runtime_metadata(
        self,
        *,
        agent: AgentDefinition,
        runtime_context: Mapping[str, object] | None,
        prompt_context: PromptContextEnvelope,
        private_context: RuntimePrivateContext,
        effective_private_context: RuntimePrivateContext,
        runtime_metadata: dict[str, object],
    ) -> tuple[
        RuntimePrivateContext,
        RuntimePrivateContext,
        dict[str, object],
        ResolvedModelRouteBinding | None,
    ]:
        resolved_route_binding, route_runtime_updates = self._resolve_route_runtime_metadata(
            agent=agent,
            runtime_metadata=runtime_metadata,
        )
        if not route_runtime_updates:
            return private_context, effective_private_context, runtime_metadata, resolved_route_binding
        requested_model_route = (
            effective_private_context.requested_model_route
            or _string_value(runtime_metadata.get("requested_model_route"))
            or agent.model_route
        )
        resolved_model_route = _string_value(route_runtime_updates.get("resolved_model_route"))
        provider_name = (
            _string_value(route_runtime_updates.get("provider_name"))
            or effective_private_context.provider_name
        )
        private_context = replace(
            private_context,
            requested_model_route=requested_model_route,
            resolved_model_route=resolved_model_route,
            provider_name=provider_name,
        )
        effective_private_context = replace(
            effective_private_context,
            requested_model_route=requested_model_route,
            resolved_model_route=resolved_model_route,
            provider_name=provider_name,
        )
        merged_runtime_metadata = self._merge_runtime_context(
            runtime_context,
            private_context=effective_private_context,
            prompt_context=prompt_context,
        )
        merged_runtime_metadata.update(route_runtime_updates)
        return (
            private_context,
            effective_private_context,
            merged_runtime_metadata,
            resolved_route_binding,
        )

    def configure_runtime(
        self,
        *,
        permission_handler=None,
        ask_user_handler=None,
        agent_runner=None,
        skill_runner=None,
        notification_provider=None,
        notification_sink=None,
        tool_refresh_callback: ToolRefreshCallback | None = None,
    ) -> None:
        self._runtime_services.configure_compat(
            permission_handler=permission_handler,
            ask_user_handler=ask_user_handler,
            notification_provider=notification_provider,
            notification_sink=notification_sink,
            tool_refresh_callback=tool_refresh_callback,
        )
        self._runtime_services.bind_execution(
            agent_runner=agent_runner,
            skill_runner=skill_runner,
        )

    async def emit_child_run(self, record: AgentRunRecord) -> None:
        if record.parent_turn_id is not None:
            key = (record.session_id, record.parent_turn_id)
            queue = self._child_run_events.get(key)
            if queue is not None:
                queue.append(record)
                return
        await maybe_await(
            self._runtime_services.host.emit_turn_event(
                record.session_id,
                TurnStreamEvent(
                    event_type=TurnStreamEventType.CHILD_RUN,
                    iteration=0,
                    child_run=record,
                ),
            )
        )

    def interrupt(self, reason: str = "interrupt") -> None:
        if self._active_abort_signal is not None:
            self._active_abort_signal.abort(reason)
        if self._active_tool_context is not None:
            self._active_tool_context.request_interrupt(reason)
        if self._active_tool_executor is not None and hasattr(self._active_tool_executor, "interrupt"):
            self._active_tool_executor.interrupt(reason)
        if self._active_scheduler is not None:
            self._active_scheduler.interrupt(reason)

    def create_tool_context(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent_name: str,
        cwd: Path,
        messages: list[RuntimeMessage] | tuple[RuntimeMessage, ...] = (),
        tool_pool=(),
        skill_pool=(),
        abort_signal: ModelAbortSignal | None = None,
        metadata: dict[str, Any] | None = None,
        session_scope: SessionScope | None = None,
    ) -> ToolContext:
        notifications = ()
        if self._runtime_services.notification_provider is not None:
            notifications = tuple(self._runtime_services.notification_provider())
        permission_context = _coerce_permission_context(session_id, metadata)
        private_context = private_context_from_legacy_runtime_context(metadata)
        if private_context.permission_context is None and permission_context is not None:
            private_context = replace(private_context, permission_context=permission_context)
        owner_scope = session_scope or SessionScope(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            private_context=private_context,
            task_manager=self._runtime_services.tasks.manager,
        )
        return ToolContext(
            session_id=session_id,
            turn_id=turn_id,
            agent_name=agent_name,
            cwd=cwd,
            tool_registry=self._tool_registry,
            agent_registry=self._agent_registry,
            skill_registry=self._skill_registry,
            messages=tuple(messages),
            tool_pool=tuple(tool_pool),
            skill_pool=tuple(skill_pool),
            permission_handler=self._runtime_services.permission_handler,
            ask_user_handler=self._runtime_services.ask_user_handler,
            agent_runner=self._runtime_services.agent_runner,
            skill_runner=self._runtime_services.skill_runner,
            task_manager=self._runtime_services.tasks.manager,
            abort_signal=abort_signal,
            notifications=notifications,
            notification_sink=self._runtime_services.notification_sink,
            tool_refresh_callback=self._runtime_services.tool_refresh_callback,
            runtime_services=self._runtime_services,
            permission_context=permission_context,
            private_context=private_context,
            session_state=owner_scope.session_state,
            memory_access=owner_scope.memory_access,
            session_scope=owner_scope,
            metadata=dict(metadata or {}),
        )

    def resolve_invocation_catalog(
        self,
        *,
        session_id: str,
        turn_id: str | None,
        cwd: str | Path,
        messages: tuple[RuntimeMessage, ...] | list[RuntimeMessage],
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | Mapping[str, object] | None = None,
        runtime_context: Mapping[str, object] | None = None,
    ):
        registry = self._invocation_registry
        if registry is None:
            return _empty_invocation_catalog()
        context = build_invocation_resolution_context(
            session_id=session_id,
            turn_id=turn_id,
            cwd=cwd,
            messages=tuple(messages),
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=runtime_context,
        )
        return registry.resolve(context)

    async def run_turn_stream(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: list[RuntimeMessage],
        base_system_prompt: str,
        memory_fragments: list[str] | None = None,
        hook_context: list[str] | None = None,
        compaction_fragments: list[str] | None = None,
        attachments: list[MessageAttachment] | None = None,
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | Mapping[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
        model_client_override: ModelClient | None = None,
        session_scope: SessionScope | None = None,
    ) -> AsyncIterator[TurnStreamEvent]:
        async for event in self._run_turn_stream_impl(
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
            base_system_prompt=base_system_prompt,
            memory_fragments=memory_fragments,
            hook_context=hook_context,
            compaction_fragments=compaction_fragments,
            attachments=attachments,
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=runtime_context,
            model_client_override=model_client_override,
            session_scope=session_scope,
        ):
            yield event

    async def run_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: list[RuntimeMessage],
        base_system_prompt: str,
        memory_fragments: list[str] | None = None,
        hook_context: list[str] | None = None,
        compaction_fragments: list[str] | None = None,
        attachments: list[MessageAttachment] | None = None,
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | Mapping[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
        model_client_override: ModelClient | None = None,
        session_scope: SessionScope | None = None,
    ) -> TurnResult:
        result = TurnResult()
        async for event in self.run_turn_stream(
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
            base_system_prompt=base_system_prompt,
            memory_fragments=memory_fragments,
            hook_context=hook_context,
            compaction_fragments=compaction_fragments,
            attachments=attachments,
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=runtime_context,
            model_client_override=model_client_override,
            session_scope=session_scope,
        ):
            if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
                result.messages.append(event.message)
                if event.message.role == MessageRole.ASSISTANT:
                    result.tool_calls.extend(_tool_calls_from_message(event.message))
            elif event.event_type == TurnStreamEventType.ATTEMPT_FINISHED and event.attempt is not None:
                result.attempts.append(event.attempt)
                result.iterations = max(result.iterations, event.iteration)
            elif event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
                result.iterations = max(result.iterations, event.iteration)
                result.terminal = event.terminal
                result.transition = event.transition or event.terminal.transition
                result.post_effects = event.post_effects or event.terminal.post_effects
                result.stop_reason = event.terminal.stop_reason
                result.usage = dict(event.terminal.usage)
                result.request_id = event.terminal.request_id
                result.ttft_ms = event.terminal.ttft_ms
                result.abort_reason = event.terminal.abort_reason
                result.error = event.terminal.error
                result.completed = event.terminal.completed
                result.metadata = dict(event.terminal.metadata)
        return result

    async def _run_turn_stream_impl(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: list[RuntimeMessage],
        base_system_prompt: str,
        memory_fragments: list[str] | None = None,
        hook_context: list[str] | None = None,
        compaction_fragments: list[str] | None = None,
        attachments: list[MessageAttachment] | None = None,
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | Mapping[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
        model_client_override: ModelClient | None = None,
        session_scope: SessionScope | None = None,
    ) -> AsyncIterator[TurnStreamEvent]:
        max_iterations = agent.max_turns or 4
        state = TurnLoopState(working_messages=tuple(messages))
        # Raw runtime_context is a compatibility input only; authoritative writes stay on the
        # structured prompt/private carriers for the rest of the primary path.
        runtime_context = dict(runtime_context or {})
        prompt_context = _merge_prompt_context(
            prompt_context_from_legacy_runtime_context(runtime_context),
            prompt_context,
        )
        private_context = _merge_runtime_private_context(
            private_context_from_legacy_runtime_context(runtime_context),
            private_context,
        )
        if private_context.permission_context is None:
            private_context = replace(
                private_context,
                permission_context=PermissionContext(
                    session_id=session_id,
                    mode=agent.permission_mode or PermissionMode.DEFAULT,
                ),
            )
        child_run_key = (session_id, turn_id)
        self._child_run_events[child_run_key] = []
        sidecars = _PreTurnSidecarSupervisor(
            self,
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
        )
        incoming_policy_state = private_context.policy_state or policy_state_from_metadata(runtime_context)
        policy_state = incoming_policy_state
        local_root_policy = policy_state is None
        if policy_state is None:
            root_tool_pool = assemble_main_thread_tool_pool(
                self._tool_registry,
                allowed_tools=agent.tools or None,
                disallowed_tools=agent.disallowed_tools or None,
            )
            active_skills = self._skill_registry.resolve_active() if self._skill_registry is not None else ()
            root_skill_pool = resolve_skill_pool(active_skills, agent.skills)
            root_policy = build_root_execution_policy(
                agent,
                tool_pool=root_tool_pool,
                skill_pool=root_skill_pool,
                permission_context=private_context.permission_context,
                memory_scope=self._resolve_memory_scope(session_id=session_id, agent=agent, cwd=cwd),
                isolation_mode=agent.isolation,
            )
            policy_state = ExecutionPolicyState(root_policy)
        private_context = replace(
            private_context,
            permission_context=policy_state.effective.permission_context,
            policy_state=policy_state,
        )
        state.policy_state = policy_state
        last_request: ModelRequest | None = None
        last_attempt: AttemptFinished | None = None
        resolved_context_control = ContextControlPlaneConfig.resolve(
            runtime_default=_mapping_or_none(self._runtime_services.metadata.get("context_control")),
            agent_config=_mapping_or_none(agent.metadata.get("context_control")),
            turn_override=_mapping_or_none(runtime_context.get("context_control")),
        )

        try:
            while True:
                working_messages = list(state.working_messages)
                iteration_index = state.iteration + 1
                state.iteration = iteration_index
                private_context = replace(
                    private_context,
                    permission_context=policy_state.effective.permission_context,
                    policy_state=policy_state,
                )
                effective_private_context = _merge_private_context_updates(
                    private_context,
                    private_updates=self._runtime_services.metadata,
                )
                runtime_metadata = self._merge_runtime_context(
                    runtime_context,
                    private_context=effective_private_context,
                    prompt_context=prompt_context,
                )
                (
                    private_context,
                    effective_private_context,
                    runtime_metadata,
                    resolved_route_binding,
                ) = self._apply_route_runtime_metadata(
                    agent=agent,
                    runtime_context=runtime_context,
                    prompt_context=prompt_context,
                    private_context=private_context,
                    effective_private_context=effective_private_context,
                    runtime_metadata=runtime_metadata,
                )
                model_client = (
                    model_client_override
                    or (resolved_route_binding.client if resolved_route_binding is not None else None)
                    or self._model_client
                )
                tool_pool = policy_state.effective.tool_pool
                sanitized_runtime_context = serialize_runtime_metadata(runtime_metadata)
                sidecar_prompt_context = _prompt_context_from_sidecar_metadata(runtime_metadata)
                state.sidecar_generation += 1
                _set_turn_phase(state, TurnPhase.PREFETCH_SIDECARS)
                sidecars.start(
                    messages=tuple(working_messages),
                    prompt_context=sidecar_prompt_context,
                    private_context=effective_private_context,
                    runtime_context=sanitized_runtime_context,
                )
                _set_turn_phase(state, TurnPhase.COMPACT_OR_REBUILD)
                await self._dispatch_hook(
                    session_id,
                    PreCompactPayload(
                        session_id=session_id,
                        token_count=sum(len(message.text) for message in working_messages),
                    ),
                    dispatch_context=sanitized_runtime_context,
                )
                prepared_context = await self._context_control_plane.prepare(
                    session_id=session_id,
                    turn_id=turn_id,
                    attempt_index=iteration_index,
                    agent=agent,
                    cwd=cwd,
                    messages=tuple(working_messages),
                    prompt_context=sidecar_prompt_context,
                    private_context=effective_private_context,
                    runtime_context=sanitized_runtime_context,
                    prior_prepared=state.prepared_context,
                    resolved_config=resolved_context_control,
                    transcript_store=(
                        self._runtime_services.transcript.store
                        if self._runtime_services.transcript is not None
                        else None
                    ),
                )
                compaction_payload = _prepared_compaction_payload(prepared_context)
                if prepared_context.transcript_messages is not None:
                    working_messages = list(prepared_context.transcript_messages)
                    state.working_messages = tuple(working_messages)
                    await sidecars.restart(
                        messages=prepared_context.active_messages,
                        prompt_context=prepared_context.prompt_context,
                        private_context=effective_private_context,
                        runtime_context=sanitized_runtime_context,
                    )
                    summary_id = _prepared_compaction_summary_id(prepared_context)
                    if summary_id is not None:
                        await self._dispatch_hook(
                            session_id,
                            PostCompactPayload(
                                session_id=session_id,
                                summary_id=summary_id,
                            ),
                            dispatch_context=sanitized_runtime_context,
                        )
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.COMPACTION,
                        iteration=iteration_index,
                        phase=state.phase,
                        compacted_messages=tuple(working_messages),
                        metadata=_prepared_context_event_metadata(
                            prepared_context,
                            extra={"compaction": compaction_payload} if compaction_payload is not None else None,
                        ),
                    )
                elif prepared_context.requires_sidecar_restart:
                    await sidecars.restart(
                        messages=prepared_context.active_messages,
                        prompt_context=prepared_context.prompt_context,
                        private_context=effective_private_context,
                        runtime_context=sanitized_runtime_context,
                    )
                state.prepared_context = prepared_context
                private_context = _clear_transient_recovery_flags(private_context)
                (
                    shared_memory_fragments,
                    shared_hook_context,
                    sidecar_private_updates,
                    sidecar_diagnostics,
                ) = await sidecars.join()
                if sidecar_private_updates or sidecar_diagnostics:
                    private_context = _merge_private_context_updates(
                        private_context,
                        private_updates=sidecar_private_updates,
                        diagnostics=sidecar_diagnostics,
                    )
                    effective_private_context = _merge_private_context_updates(
                        private_context,
                        private_updates=self._runtime_services.metadata,
                    )
                    runtime_metadata = self._merge_runtime_context(
                        runtime_context,
                        private_context=effective_private_context,
                        prompt_context=prompt_context,
                    )
                (
                    private_context,
                    effective_private_context,
                    runtime_metadata,
                    resolved_route_binding,
                ) = self._apply_route_runtime_metadata(
                    agent=agent,
                    runtime_context=runtime_context,
                    prompt_context=prompt_context,
                    private_context=private_context,
                    effective_private_context=effective_private_context,
                    runtime_metadata=runtime_metadata,
                )
                model_client = (
                    model_client_override
                    or (resolved_route_binding.client if resolved_route_binding is not None else None)
                    or self._model_client
                )
                sanitized_runtime_context = serialize_runtime_metadata(runtime_metadata)

                resolved_invocations = self.resolve_invocation_catalog(
                    session_id=session_id,
                    turn_id=turn_id,
                    cwd=cwd,
                    messages=tuple(working_messages),
                    prompt_context=sidecar_prompt_context,
                    private_context=effective_private_context,
                    runtime_context=runtime_metadata,
                )
                active_skills = _resolve_iteration_skill_pool(
                    catalog=resolved_invocations,
                    agent=agent,
                    policy_state=policy_state,
                    local_root_policy=local_root_policy,
                )
                if active_skills != policy_state.effective.skill_pool:
                    policy_state.apply(
                        replace(
                            policy_state.effective,
                            skill_pool=active_skills,
                            trace={
                                "source": "invocation_catalog",
                                "visible_invocations": [
                                    capability.name
                                    for capability in resolved_invocations.visible_capabilities()
                                ],
                                "model_invocable_skills": [skill.name for skill in active_skills],
                            },
                        )
                )
                tool_pool = policy_state.effective.tool_pool

                user_prompt_hook = await self._dispatch_hook(
                    session_id,
                    UserPromptSubmitPayload(
                        session_id=session_id,
                        prompt=_latest_user_prompt_text(working_messages),
                        turn_id=turn_id,
                        attachments=tuple(attachment.name for attachment in attachments or ()),
                    ),
                    dispatch_context=sanitized_runtime_context,
                )
                pre_context_hook = await self._dispatch_hook(
                    session_id,
                    PreContextAssemblePayload(
                        session_id=session_id,
                        turn_id=turn_id,
                        active_messages=tuple(prepared_context.active_messages),
                        attachment_descriptors=tuple(
                            {
                                "name": attachment.name,
                                "path": attachment.path,
                                "mime_type": attachment.mime_type,
                                "metadata": dict(attachment.metadata),
                            }
                            for attachment in attachments or ()
                        ),
                        runtime_metadata_view=dict(sanitized_runtime_context),
                    ),
                    dispatch_context=sanitized_runtime_context,
                )

                _set_turn_phase(state, TurnPhase.BUILD_REQUEST)
                prompt_context = build_prompt_envelope(
                    prompt_context_from_legacy_runtime_context(
                        sanitized_runtime_context,
                        memory_fragments=prepared_context.prompt_context.memory_fragments
                        + shared_memory_fragments
                        + tuple(memory_fragments or ()),
                        hook_fragments=prepared_context.prompt_context.hook_fragments
                        + shared_hook_context
                        + pre_context_hook.additional_context
                        + user_prompt_hook.additional_context
                        + tuple(hook_context or ()),
                        compaction_fragments=prepared_context.prompt_context.compaction_fragments
                        + tuple(compaction_fragments or ()),
                        compaction_summary=prepared_context.prompt_context.compaction_summary,
                        compaction_boundary=prepared_context.prompt_context.compaction_boundary,
                        compaction_continuation=prepared_context.prompt_context.compaction_continuation,
                        attachments=attachments or (),
                    ),
                    effects=prepared_context.effects,
                    plan=None,
                    diagnostics=tuple(prepared_context.metadata.get("diagnostics", ()) or ()),
                )
                prepared_context = replace(
                    prepared_context,
                    prompt_context=prompt_context,
                    generation=next_context_generation(
                        state.prepared_context,
                        active_messages=prepared_context.active_messages,
                        prompt_context=prompt_context,
                    ),
                    metadata={
                        **prepared_context.metadata,
                        "context_generation": next_context_generation(
                            state.prepared_context,
                            active_messages=prepared_context.active_messages,
                            prompt_context=prompt_context,
                        ),
                    },
                )
                state.prepared_context = prepared_context
                post_context_hook = await self._dispatch_hook(
                    session_id,
                    PostContextAssemblePayload(
                        session_id=session_id,
                        turn_id=turn_id,
                        prompt_context_envelope=prompt_context,
                        context_generation=prepared_context.generation,
                        request_input_view={
                            "tool_count": len(tool_pool),
                            "skill_count": len(active_skills),
                            "message_count": len(prepared_context.active_messages),
                        },
                    ),
                    dispatch_context=sanitized_runtime_context,
                )
                if post_context_hook.additional_context:
                    prompt_context = build_prompt_envelope(
                        replace(
                            prompt_context,
                            hook_fragments=prompt_context.hook_fragments
                            + post_context_hook.additional_context,
                        ),
                        effects=prepared_context.effects,
                        plan=None,
                        diagnostics=tuple(prepared_context.metadata.get("diagnostics", ()) or ()),
                    )
                    prepared_context = replace(
                        prepared_context,
                        prompt_context=prompt_context,
                        generation=next_context_generation(
                            state.prepared_context,
                            active_messages=prepared_context.active_messages,
                            prompt_context=prompt_context,
                        ),
                        metadata={
                            **prepared_context.metadata,
                            "context_generation": next_context_generation(
                                state.prepared_context,
                                active_messages=prepared_context.active_messages,
                                prompt_context=prompt_context,
                            ),
                        },
                    )
                    state.prepared_context = prepared_context
                api_messages = normalize_messages_for_api(prepared_context.active_messages)
                composition = self._compose_context(
                    session_id=session_id,
                    turn_id=turn_id,
                    agent=agent,
                    cwd=cwd,
                    messages=api_messages,
                    available_tools=[tool.name for tool in tool_pool],
                    available_skills=[skill.name for skill in active_skills],
                    available_agents=self._available_agents_for_request(
                        current_agent=agent,
                        private_context=effective_private_context,
                    ),
                    available_invocations=resolved_invocations.visible_capabilities(),
                    base_system_prompt=base_system_prompt,
                    memory_fragments=prompt_context.memory_fragments,
                    hook_context=prompt_context.hook_fragments,
                    compaction_fragments=prompt_context.compaction_fragments,
                    compaction_summary=prompt_context.compaction_summary,
                    compaction_boundary=prompt_context.compaction_boundary,
                    compaction_continuation=prompt_context.compaction_continuation,
                    attachments=prompt_context.attachments,
                    prompt_context=prompt_context,
                )
                abort_signal = ModelAbortSignal()
                assistant_message_id = uuid4().hex
                tool_context = self.create_tool_context(
                    session_id=session_id,
                    turn_id=turn_id,
                    agent_name=agent.name,
                    cwd=Path(composition.turn_context.cwd),
                    messages=tuple(working_messages),
                    tool_pool=tool_pool,
                    skill_pool=active_skills,
                    abort_signal=abort_signal,
                    metadata=runtime_metadata,
                    session_scope=session_scope,
                )
                pending_tool_turn_events: list[TurnStreamEvent] = []
                request_metadata = dict(sanitized_runtime_context)
                if compaction_payload is not None:
                    request_metadata["compaction"] = compaction_payload
                request_metadata.update(_prepared_context_event_metadata(prepared_context))
                if prepared_context.context_window is not None:
                    request_metadata["context_window"] = serialize_resolved_context_window_snapshot(
                        prepared_context.context_window
                    )
                if prepared_context.context_window_policy_tag is not None:
                    request_metadata["context_window_policy_tag"] = (
                        prepared_context.context_window_policy_tag
                    )
                    request_metadata["budget_policy_tag"] = prepared_context.context_window_policy_tag
                pending_request_override = merge_request_override_state(
                    _request_override_from_private_context(effective_private_context),
                    coerce_request_override_state(post_context_hook.request_override),
                )
                if pending_request_override is not None:
                    request_metadata["request_override"] = pending_request_override.serialize()
                    compat_skill_override = skill_request_override_from_request_override(
                        pending_request_override
                    )
                    if compat_skill_override is not None:
                        request_metadata["skill_request_override"] = compat_skill_override.serialize()
                requested_capabilities = _coerce_model_capabilities(
                    runtime_metadata.get("resolved_capabilities")
                )
                resolved_capabilities = requested_capabilities or model_capabilities_for(model_client)
                invocation_mode = (
                    (
                        _coerce_invocation_mode(pending_request_override.invocation_mode_override)
                        if pending_request_override is not None
                        else None
                    )
                    or _coerce_invocation_mode(runtime_metadata.get("invocation_mode"))
                    or _select_invocation_mode(resolved_capabilities)
                )
                request = ModelRequest(
                    system_prompt=composition.system_prompt,
                    turn_context=composition.turn_context,
                    messages=composition.messages,
                    tools=tool_pool,
                    skills=active_skills,
                    agent=agent,
                        model=(
                            pending_request_override.requested_model
                            if pending_request_override is not None
                            and pending_request_override.requested_model is not None
                            else agent.model
                            or _string_value(runtime_metadata.get("route_default_model"))
                        ),
                    effort=(
                        pending_request_override.requested_effort
                        if pending_request_override is not None
                        and pending_request_override.requested_effort is not None
                        else agent.effort
                    ),
                    max_output_tokens=(
                        pending_request_override.max_output_tokens_override
                        if pending_request_override is not None
                        and pending_request_override.max_output_tokens_override is not None
                        else None
                    ),
                    abort_signal=abort_signal,
                    query_source=_query_source(request_metadata),
                    requested_model_route=(
                        pending_request_override.requested_model_route
                        if pending_request_override is not None
                        and pending_request_override.requested_model_route is not None
                        else _string_value(runtime_metadata.get("requested_model_route"))
                        or agent.model_route
                    ),
                    resolved_model_route=_string_value(runtime_metadata.get("resolved_model_route")),
                    provider_name=_string_value(runtime_metadata.get("provider_name")),
                    resolved_capabilities=resolved_capabilities,
                    invocation_mode=invocation_mode,
                    context_window=prepared_context.context_window,
                    context_window_policy_tag=prepared_context.context_window_policy_tag,
                    private_context=effective_private_context,
                    metadata=request_metadata,
                )
                pre_model_hook = await self._dispatch_hook(
                    session_id,
                    PreModelRequestPayload(
                        session_id=session_id,
                        turn_id=turn_id,
                        context_generation=prepared_context.generation,
                        request_envelope=_serialize_model_request_envelope(request),
                        request_metadata=request_metadata,
                    ),
                    dispatch_context=sanitized_runtime_context,
                )
                pending_request_override = merge_request_override_state(
                    pending_request_override,
                    pre_model_hook.request_override,
                )
                if pending_request_override is not None:
                    request_metadata["request_override"] = pending_request_override.serialize()
                    compat_skill_override = skill_request_override_from_request_override(
                        pending_request_override
                    )
                    if compat_skill_override is not None:
                        request_metadata["skill_request_override"] = compat_skill_override.serialize()
                    else:
                        request_metadata.pop("skill_request_override", None)
                    request = replace(
                        request,
                        model=(
                            pending_request_override.requested_model
                            if pending_request_override.requested_model is not None
                            else request.model
                        ),
                        effort=(
                            pending_request_override.requested_effort
                            if pending_request_override.requested_effort is not None
                            else request.effort
                        ),
                        max_output_tokens=(
                            pending_request_override.max_output_tokens_override
                            if pending_request_override.max_output_tokens_override is not None
                            else request.max_output_tokens
                        ),
                        requested_model_route=(
                            pending_request_override.requested_model_route
                            if pending_request_override.requested_model_route is not None
                            else request.requested_model_route
                        ),
                        invocation_mode=(
                            _coerce_invocation_mode(pending_request_override.invocation_mode_override)
                            if pending_request_override.invocation_mode_override is not None
                            else request.invocation_mode
                        ),
                        metadata=request_metadata,
                    )
                last_request = request
                state.consumed_request_override = pending_request_override
                tool_executor = select_tool_executor(
                    model_client,
                    context=tool_context,
                    lifecycle_sink=lambda tool_event: pending_tool_turn_events.append(
                        TurnStreamEvent(
                            event_type=TurnStreamEventType.TOOL_LIFECYCLE,
                            iteration=iteration_index,
                            request=request,
                            tool_event=tool_event,
                            metadata={"tool_executor": _tool_executor_metadata(tool_executor)},
                        )
                    ),
                    request=request,
                )
                self._active_tool_context = tool_context
                self._active_tool_executor = tool_executor
                if tool_executor is not None:
                    request_metadata = {
                        **request_metadata,
                        "tool_executor": _tool_executor_metadata(tool_executor),
                        "model_capabilities": _serialize_model_capabilities(
                            tool_executor.model_capabilities
                        ),
                    }
                    request = replace(request, metadata=request_metadata)
                    tool_context.selected_executor_tier = tool_executor.initial_tier.value
                    tool_context.model_capabilities = tool_executor.model_capabilities
                    if tool_context.query_context is not None:
                        tool_context.query_context = replace(
                            tool_context.query_context,
                            selected_executor_tier=tool_executor.initial_tier.value,
                            model_capabilities=tool_executor.model_capabilities,
                        )
                yield TurnStreamEvent(
                    event_type=TurnStreamEventType.REQUEST_START,
                    iteration=iteration_index,
                    phase=state.phase,
                    request=request,
                )
                if pending_request_override is not None:
                    private_context = _clear_request_override(private_context)
                    state.recovery_state = state.recovery_state.clear_pending_override()

                attempt_state = _StreamAttemptState()
                pending_tool_use_closed_at_message_stop = False
                self._active_abort_signal = abort_signal
                _set_turn_phase(state, TurnPhase.STREAM_ATTEMPT)
                try:
                    if request.invocation_mode == ModelInvocationMode.BUFFERED_COMPLETION:
                        assistant_blocks, tool_calls, terminal, response_events, assistant_message_id = (
                            await self._complete_buffered_attempt(
                                model_client=model_client,
                                request=request,
                                assistant_message_id=assistant_message_id,
                                abort_reason=abort_signal.reason,
                            )
                        )
                        for event in response_events:
                            yield TurnStreamEvent(
                                event_type=TurnStreamEventType.STREAM_PROGRESS,
                                iteration=iteration_index,
                                phase=state.phase,
                                request=request,
                                model_event=event,
                            )
                    else:
                        async for event in model_client.stream(request):
                            attempt_state.observe(event)
                            yield TurnStreamEvent(
                                event_type=TurnStreamEventType.STREAM_PROGRESS,
                                iteration=iteration_index,
                                phase=state.phase,
                                request=request,
                                model_event=event,
                            )
                            if tool_executor is not None:
                                new_tool_calls = attempt_state.drain_new_tool_calls()
                                if new_tool_calls and not (
                                    event.event_type == ModelStreamEventType.MESSAGE_STOP
                                    and attempt_state.pending_tool_use_closed_at_message_stop
                                ):
                                    await tool_executor.observe_stream_calls(
                                        new_tool_calls,
                                        assistant_message_id=assistant_message_id,
                                        provider_request_id=attempt_state.request_id,
                                        block_offset=len(attempt_state.tool_calls) - len(new_tool_calls),
                                    )
                            while pending_tool_turn_events:
                                yield pending_tool_turn_events.pop(0)
                        pending_tool_use_closed_at_message_stop = (
                            attempt_state.pending_tool_use_closed_at_message_stop
                        )
                except Exception as exc:
                    if request.invocation_mode == ModelInvocationMode.BUFFERED_COMPLETION:
                        error_event = ModelStreamEvent(
                            event_type=ModelStreamEventType.ERROR,
                            payload={"error": str(exc)},
                            terminal=ModelTerminalMetadata(
                                stop_reason="error",
                                error=str(exc),
                                abort_reason=abort_signal.reason,
                            ),
                        )
                        assistant_blocks = ()
                        tool_calls = ()
                        terminal = error_event.terminal or ModelTerminalMetadata(
                            stop_reason="error",
                            error=str(exc),
                            abort_reason=abort_signal.reason,
                        )
                        yield TurnStreamEvent(
                            event_type=TurnStreamEventType.STREAM_PROGRESS,
                            iteration=iteration_index,
                            phase=state.phase,
                            request=request,
                            model_event=error_event,
                        )
                    else:
                        error_event = ModelStreamEvent(
                            event_type=ModelStreamEventType.ERROR,
                            payload={"error": str(exc)},
                            terminal=ModelTerminalMetadata(
                                stop_reason="error",
                                error=str(exc),
                                abort_reason=abort_signal.reason,
                            ),
                        )
                        attempt_state.observe(error_event)
                        yield TurnStreamEvent(
                            event_type=TurnStreamEventType.STREAM_PROGRESS,
                            iteration=iteration_index,
                            phase=state.phase,
                            request=request,
                            model_event=error_event,
                        )
                finally:
                    self._active_abort_signal = None

                if request.invocation_mode == ModelInvocationMode.BUFFERED_COMPLETION:
                    discarded_blocks = ()
                else:
                    assistant_blocks, discarded_blocks, tool_calls, terminal = attempt_state.finalize(
                        abort_reason=abort_signal.reason,
                        preserve_observed_tool_uses=_abort_reason_allows_tool_finalize(
                            abort_signal.reason
                        ),
                    )
                attempt = _attempt_finished_from_terminal(
                    iteration=iteration_index,
                    terminal=terminal,
                    tool_calls=tool_calls,
                )
                state.attempts = state.attempts + (attempt,)
                last_attempt = attempt
                if assistant_blocks:
                    assistant_message = RuntimeMessage(
                        message_id=assistant_message_id,
                        role=MessageRole.ASSISTANT,
                        content=assistant_blocks,
                        metadata=_assistant_message_metadata(terminal),
                    )
                    working_messages.append(assistant_message)
                    state.working_messages = tuple(working_messages)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.MESSAGE,
                        iteration=iteration_index,
                        phase=state.phase,
                        request=request,
                        message=assistant_message,
                    )
                    tool_context.messages = tuple(working_messages)
                    if tool_context.query_context is not None:
                        tool_context.query_context = replace(
                            tool_context.query_context,
                            messages=tuple(working_messages),
                        )
                while pending_tool_turn_events:
                    yield pending_tool_turn_events.pop(0)
                for child_event in self._drain_child_run_events(
                    session_id=session_id,
                    turn_id=turn_id,
                    iteration=iteration_index,
                ):
                    yield child_event
                if discarded_blocks:
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.MESSAGE_DISCARDED,
                        iteration=iteration_index,
                        phase=state.phase,
                        request=request,
                        discarded_content=discarded_blocks,
                        metadata={"reason": terminal.abort_reason or terminal.stop_reason},
                    )
                yield TurnStreamEvent(
                    event_type=TurnStreamEventType.ATTEMPT_FINISHED,
                    iteration=iteration_index,
                    phase=state.phase,
                    request=request,
                    attempt=attempt,
                )
                post_model_hook = await self._dispatch_hook(
                    session_id,
                    PostModelResponsePayload(
                        session_id=session_id,
                        turn_id=turn_id,
                        request_id=attempt.request_id,
                        provider_stop_reason=attempt.attempt_stop_reason,
                        usage=dict(attempt.usage),
                        response_envelope=_serialize_attempt_response_envelope(
                            assistant_blocks=assistant_blocks,
                            tool_calls=tool_calls,
                            attempt=attempt,
                        ),
                    ),
                    dispatch_context=sanitized_runtime_context,
                )
                if post_model_hook.request_override is not None:
                    private_context = _apply_request_override(
                        private_context,
                        post_model_hook.request_override,
                    )
                if post_model_hook.injected_messages:
                    for injected_message in post_model_hook.injected_messages:
                        working_messages.append(injected_message)
                        state.working_messages = tuple(working_messages)
                        yield TurnStreamEvent(
                            event_type=TurnStreamEventType.MESSAGE,
                            iteration=iteration_index,
                            phase=state.phase,
                            request=request,
                            message=injected_message,
                            metadata={"source": "post_model_response_hook"},
                        )

                if not tool_calls:
                    _set_turn_phase(state, TurnPhase.STOP_PHASE)
                    stop_hook = await self._dispatch_hook(
                        session_id,
                        StopPayload(
                            session_id=session_id,
                            reason=attempt.attempt_stop_reason or "completed",
                            turn_id=turn_id,
                        ),
                        dispatch_context=sanitized_runtime_context,
                    )
                    stop_outcome = _stop_phase_outcome_from_hook_result(stop_hook)
                    _set_turn_phase(state, TurnPhase.RECOVERY_DECISION)
                    recovery_input = normalize_attempt_outcome(
                        attempt,
                        prepared_context=prepared_context,
                    )
                    decision = self._recovery_policy.evaluate(
                        recovery_input,
                        stop_outcome=stop_outcome,
                        recovery_state=state.recovery_state,
                        prepared_context=prepared_context,
                    )
                    recovery_hook = await self._dispatch_hook(
                        session_id,
                        RecoveryDecisionPayload(
                            session_id=session_id,
                            turn_id=turn_id,
                            attempt_index=iteration_index,
                            recovery_input=_serialize_recovery_input(recovery_input),
                            candidate_action=decision.action.value,
                            failure_class=recovery_input.failure_class.value,
                        ),
                        dispatch_context=sanitized_runtime_context,
                    )
                    decision = _apply_recovery_hook_result(
                        decision,
                        recovery_hook,
                        recovery_input=recovery_input,
                    )
                    state.recovery_state = state.recovery_state.after_decision(
                        recovery_input,
                        decision,
                    )
                    transition = _turn_transition_from_recovery(
                        decision,
                        recovery_input,
                        stop_outcome=stop_outcome,
                        prepared_context=prepared_context,
                    )
                    if decision.action != RecoveryAction.HALT:
                        private_context = _apply_recovery_decision_to_private_context(
                            private_context,
                            decision,
                        )
                        for injected_message in decision.injected_messages:
                            working_messages.append(injected_message)
                            state.working_messages = tuple(working_messages)
                            yield TurnStreamEvent(
                                event_type=TurnStreamEventType.MESSAGE,
                                iteration=iteration_index,
                                phase=state.phase,
                                request=request,
                                message=injected_message,
                                transition=transition,
                                metadata=_prepared_context_event_metadata(prepared_context),
                            )
                        state.transition = transition
                        _set_turn_phase(state, TurnPhase.ADVANCE_OR_FINISH)
                        state.working_messages = tuple(working_messages)
                        _set_turn_phase(state, TurnPhase.PREPARE)
                        continue
                    terminal_reason = _turn_terminal_reason_from_recovery(decision)
                    post_effects = _turn_post_effects_for_terminal(
                        terminal_reason,
                        matched_stop_hooks=stop_outcome.matched_hook_owners,
                    )
                    terminal_event = _turn_terminal_from_attempt(
                        attempt,
                        reason=terminal_reason,
                        transition=transition,
                        post_effects=post_effects,
                        metadata={
                            **decision.metadata,
                            **_prepared_context_event_metadata(prepared_context),
                            **(
                                {
                                    "continuation_blocked": True,
                                    "matched_hooks": list(stop_outcome.matched_hook_owners),
                                }
                                if terminal_reason == TurnTerminalReason.BLOCKED
                                else {}
                            ),
                            **(
                                {
                                    "resumable_request_override": resumable_override,
                                }
                                if (
                                    resumable_override := _resumable_request_override_metadata(
                                        decision,
                                        private_context,
                                        consumed_request_override=state.consumed_request_override,
                                    )
                                )
                                is not None
                                else {}
                            ),
                        },
                    )
                    state.transition = transition
                    state.post_effects = post_effects
                    _set_turn_phase(state, TurnPhase.ADVANCE_OR_FINISH)
                    state.terminal = terminal_event
                    self._active_tool_context = None
                    self._active_tool_executor = None
                    _set_turn_phase(state, TurnPhase.TERMINAL)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.TERMINAL,
                        iteration=iteration_index,
                        phase=state.phase,
                        request=request,
                        terminal=terminal_event,
                        transition=transition,
                        post_effects=post_effects,
                    )
                    return

                _set_turn_phase(state, TurnPhase.REPLAY_TOOLS)
                if abort_signal.aborted and not (
                    _abort_reason_allows_tool_finalize(abort_signal.reason) and tool_calls
                ):
                    _set_turn_phase(state, TurnPhase.RECOVERY_DECISION)
                    recovery_input = normalize_attempt_outcome(
                        attempt,
                        prepared_context=prepared_context,
                    )
                    decision = self._recovery_policy.evaluate(
                        recovery_input,
                        recovery_state=state.recovery_state,
                        prepared_context=prepared_context,
                    )
                    state.recovery_state = state.recovery_state.after_decision(
                        recovery_input,
                        decision,
                    )
                    transition = _turn_transition_from_recovery(
                        decision,
                        recovery_input,
                        prepared_context=prepared_context,
                    )
                    post_effects = _turn_post_effects_for_terminal(
                        _turn_terminal_reason_from_recovery(decision)
                    )
                    terminal_event = _turn_terminal_from_attempt(
                        attempt,
                        reason=_turn_terminal_reason_from_recovery(decision),
                        transition=transition,
                        post_effects=post_effects,
                        metadata={
                            **decision.metadata,
                            **_prepared_context_event_metadata(prepared_context),
                            **(
                                {
                                    "resumable_request_override": resumable_override,
                                }
                                if (
                                    resumable_override := _resumable_request_override_metadata(
                                        decision,
                                        private_context,
                                        consumed_request_override=state.consumed_request_override,
                                    )
                                )
                                is not None
                                else {}
                            ),
                        },
                    )
                    state.transition = transition
                    state.post_effects = post_effects
                    self._active_tool_context = None
                    self._active_tool_executor = None
                    _set_turn_phase(state, TurnPhase.ADVANCE_OR_FINISH)
                    state.terminal = terminal_event
                    _set_turn_phase(state, TurnPhase.TERMINAL)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.TERMINAL,
                        iteration=iteration_index,
                        phase=state.phase,
                        request=request,
                        terminal=terminal_event,
                        transition=transition,
                        post_effects=post_effects,
                    )
                    return

                if tool_executor is None:
                    _set_turn_phase(state, TurnPhase.RECOVERY_DECISION)
                    recovery_input = normalize_attempt_outcome(
                        attempt,
                        prepared_context=prepared_context,
                        tool_executor_unavailable=True,
                    )
                    decision = self._recovery_policy.evaluate(
                        recovery_input,
                        recovery_state=state.recovery_state,
                        prepared_context=prepared_context,
                    )
                    state.recovery_state = state.recovery_state.after_decision(
                        recovery_input,
                        decision,
                    )
                    transition = _turn_transition_from_recovery(
                        decision,
                        recovery_input,
                        prepared_context=prepared_context,
                    )
                    post_effects = _turn_post_effects_for_terminal(
                        _turn_terminal_reason_from_recovery(decision)
                    )
                    terminal_event = _turn_terminal_from_attempt(
                        attempt,
                        reason=_turn_terminal_reason_from_recovery(decision),
                        transition=transition,
                        post_effects=post_effects,
                        metadata={
                            **decision.metadata,
                            **_prepared_context_event_metadata(prepared_context),
                            "continuation_blocked": True,
                            "tool_executor_unavailable": True,
                            **(
                                {
                                    "resumable_request_override": resumable_override,
                                }
                                if (
                                    resumable_override := _resumable_request_override_metadata(
                                        decision,
                                        private_context,
                                        consumed_request_override=state.consumed_request_override,
                                    )
                                )
                                is not None
                                else {}
                            ),
                        },
                    )
                    state.transition = transition
                    state.post_effects = post_effects
                    self._active_tool_context = None
                    self._active_tool_executor = None
                    _set_turn_phase(state, TurnPhase.ADVANCE_OR_FINISH)
                    state.terminal = terminal_event
                    _set_turn_phase(state, TurnPhase.TERMINAL)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.TERMINAL,
                        iteration=iteration_index,
                        phase=state.phase,
                        request=request,
                        terminal=terminal_event,
                        transition=transition,
                        post_effects=post_effects,
                    )
                    return
                try:
                    outcomes = await tool_executor.finalize(
                        tool_calls,
                        assistant_message_id=assistant_message_id,
                        provider_request_id=terminal.request_id,
                        has_pending_tool_use=pending_tool_use_closed_at_message_stop,
                    )
                finally:
                    self._active_tool_context = None
                    self._active_tool_executor = None

                while pending_tool_turn_events:
                    yield pending_tool_turn_events.pop(0)
                for child_event in self._drain_child_run_events(
                    session_id=session_id,
                    turn_id=turn_id,
                    iteration=iteration_index,
                    request=request,
                ):
                    yield child_event

                _set_turn_phase(state, TurnPhase.RECOVERY_DECISION)
                tool_message = tool_executor.orchestrator.tool_result_message(outcomes)
                injected_skill_messages, pending_request_override = _skill_runtime_updates_from_outcomes(
                    outcomes
                )
                if pending_request_override is not None:
                    private_context = _apply_request_override(
                        private_context,
                        request_override_from_skill_request_override(pending_request_override)
                        or RequestOverrideState(),
                    )
                recovery_input = normalize_attempt_outcome(
                    attempt,
                    prepared_context=prepared_context,
                    max_turns_exhausted=iteration_index >= max_iterations,
                )
                decision = self._recovery_policy.evaluate(
                    recovery_input,
                    recovery_state=state.recovery_state,
                    prepared_context=prepared_context,
                )
                state.recovery_state = state.recovery_state.after_decision(
                    recovery_input,
                    decision,
                )
                transition = _turn_transition_from_recovery(
                    decision,
                    recovery_input,
                    prepared_context=prepared_context,
                )
                if tool_message is not None:
                    working_messages.append(tool_message)
                    state.working_messages = tuple(working_messages)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.MESSAGE,
                        iteration=iteration_index,
                        phase=state.phase,
                        request=request,
                        message=tool_message,
                        transition=transition,
                        metadata=_prepared_context_event_metadata(prepared_context),
                    )
                for injected_message in injected_skill_messages:
                    working_messages.append(injected_message)
                    state.working_messages = tuple(working_messages)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.MESSAGE,
                        iteration=iteration_index,
                        phase=state.phase,
                        request=request,
                        message=injected_message,
                        transition=transition,
                        metadata=_prepared_context_event_metadata(prepared_context),
                    )
                for child_event in self._drain_child_run_events(
                    session_id=session_id,
                    turn_id=turn_id,
                    iteration=iteration_index,
                    request=request,
                ):
                    yield child_event

                state.transition = transition
                if decision.action == RecoveryAction.HALT:
                    terminal_reason = _turn_terminal_reason_from_recovery(decision)
                    terminal_event = _turn_terminal_from_attempt(
                        attempt,
                        reason=terminal_reason,
                        transition=transition,
                        post_effects=_turn_post_effects_for_terminal(terminal_reason),
                        metadata={
                            **decision.metadata,
                            **_prepared_context_event_metadata(prepared_context),
                            **(
                                {
                                    "resumable_request_override": resumable_override,
                                }
                                if (
                                    resumable_override := _resumable_request_override_metadata(
                                        decision,
                                        private_context,
                                        consumed_request_override=state.consumed_request_override,
                                    )
                                )
                                is not None
                                else {}
                            ),
                        },
                    )
                    state.post_effects = terminal_event.post_effects
                    _set_turn_phase(state, TurnPhase.ADVANCE_OR_FINISH)
                    state.terminal = terminal_event
                    _set_turn_phase(state, TurnPhase.TERMINAL)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.TERMINAL,
                        iteration=iteration_index,
                        phase=state.phase,
                        request=request,
                        terminal=terminal_event,
                        transition=transition,
                        post_effects=terminal_event.post_effects,
                    )
                    return

                private_context = _apply_recovery_decision_to_private_context(
                    private_context,
                    decision,
                )
                for injected_message in decision.injected_messages:
                    working_messages.append(injected_message)
                    state.working_messages = tuple(working_messages)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.MESSAGE,
                        iteration=iteration_index,
                        phase=state.phase,
                        request=request,
                        message=injected_message,
                        transition=transition,
                        metadata=_prepared_context_event_metadata(prepared_context),
                    )
                _set_turn_phase(state, TurnPhase.ADVANCE_OR_FINISH)
                state.working_messages = tuple(working_messages)
                _set_turn_phase(state, TurnPhase.PREPARE)
        except Exception as exc:
            transition = TurnTransition(
                reason=TurnTransitionReason.ATTEMPT_ERROR,
                recovery_action=TurnRecoveryAction.HALT,
                next_phase=TurnPhase.TERMINAL,
                metadata={"unhandled_exception": True},
            )
            post_effects = _turn_post_effects_for_terminal(TurnTerminalReason.ERROR)
            terminal_event = TurnTerminal(
                reason=TurnTerminalReason.ERROR,
                usage=dict(last_attempt.usage) if last_attempt is not None else {},
                request_id=last_attempt.request_id if last_attempt is not None else None,
                ttft_ms=last_attempt.ttft_ms if last_attempt is not None else None,
                error=str(exc),
                abort_reason=last_attempt.abort_reason if last_attempt is not None else None,
                provider_stop_reason=last_attempt.attempt_stop_reason if last_attempt is not None else None,
                transition=transition,
                post_effects=post_effects,
                metadata={"unhandled_exception": True},
            )
            state.transition = transition
            state.terminal = terminal_event
            state.post_effects = post_effects
            self._active_abort_signal = None
            self._active_tool_context = None
            self._active_tool_executor = None
            state.phase = TurnPhase.TERMINAL
            yield TurnStreamEvent(
                event_type=TurnStreamEventType.TERMINAL,
                iteration=state.iteration or 1,
                phase=state.phase,
                request=last_request,
                terminal=terminal_event,
                transition=transition,
                post_effects=post_effects,
            )
            return
        finally:
            await sidecars.close()
            self._child_run_events.pop(child_run_key, None)
            if self._runtime_services.hook_bus is not None:
                self._runtime_services.hook_bus.release_turn(session_id, turn_id)

    def _compose_context(self, **kwargs: Any) -> Any:
        assembler = self._runtime_services.context_assembler
        if assembler is None:
            assembler = ContextAssembler()
            self._runtime_services.context_assembler = assembler
        if hasattr(assembler, "assemble"):
            return assembler.assemble(**kwargs)
        return assembler.compose(**kwargs)

    async def _collect_control_plane_fragments(
        self,
        service: Any,
        **kwargs: Any,
    ) -> tuple[str, ...]:
        result = await self._collect_control_plane_contribution(service, **kwargs)
        return result.prompt_fragments

    async def _collect_control_plane_contribution(
        self,
        service: Any,
        **kwargs: Any,
    ) -> _SidecarJoinResult:
        if service is None or not hasattr(service, "collect"):
            return _SidecarJoinResult()
        collected = await maybe_await(service.collect(**kwargs))
        if isinstance(collected, SidecarContributionResult):
            return _SidecarJoinResult(
                prompt_fragments=tuple(str(fragment) for fragment in collected.prompt_fragments),
                private_updates=dict(collected.private_updates),
                diagnostics=dict(collected.diagnostics),
            )
        if collected is None or collected == ():
            return _SidecarJoinResult()
        if isinstance(collected, Mapping) or isinstance(collected, (str, bytes, bytearray)):
            raise _InvalidContextContributorOutput(collected)
        if not isinstance(collected, Sequence):
            raise _InvalidContextContributorOutput(collected)
        return _SidecarJoinResult(
            prompt_fragments=tuple(str(fragment) for fragment in collected),
        )

    async def _collect_control_plane_fragments_with_context(
        self,
        service: Any,
        **kwargs: Any,
    ) -> _SidecarJoinResult:
        original_runtime_context = _clone_sidecar_compat_runtime_context(
            kwargs.get("runtime_context")
        )
        local_runtime_context = _clone_sidecar_compat_runtime_context(
            original_runtime_context
        )
        contribution = await self._collect_control_plane_contribution(
            service,
            **{**kwargs, "runtime_context": local_runtime_context},
        )
        runtime_context_updates = {
            key: value
            for key, value in local_runtime_context.items()
            if original_runtime_context.get(key) != value
        }
        contribution_private_updates, contribution_private_diagnostics = _split_sidecar_private_updates(
            contribution.private_updates
        )
        compat_private_updates, compat_diagnostics = _split_sidecar_private_updates(
            runtime_context_updates
        )
        private_updates = dict(compat_private_updates)
        private_updates.update(contribution_private_updates)
        diagnostics = dict(compat_diagnostics)
        diagnostics.update(contribution_private_diagnostics)
        diagnostics.update(contribution.diagnostics)
        return _SidecarJoinResult(
            prompt_fragments=contribution.prompt_fragments,
            private_updates=private_updates,
            diagnostics=diagnostics,
        )

    async def _collect_registered_context_contributors(
        self,
        *,
        execution_plan: Sequence[ContextContributorExecutionEntry],
        **kwargs: Any,
    ) -> _RegisteredContributorJoinResult:
        base_prompt_context = kwargs.get("prompt_context") or PromptContextEnvelope()
        base_private_context = kwargs.get("private_context") or RuntimePrivateContext()
        base_runtime_context = _clone_sidecar_compat_runtime_context(kwargs.get("runtime_context"))
        memory_fragments: list[str] = []
        hook_fragments: list[str] = []
        private_updates: dict[str, Any] = {}
        diagnostics: dict[str, Any] = {}
        failure_records: list[dict[str, Any]] = []

        for entry in execution_plan:
            prompt_context = replace(
                base_prompt_context,
                memory_fragments=base_prompt_context.memory_fragments + tuple(memory_fragments),
                hook_fragments=base_prompt_context.hook_fragments + tuple(hook_fragments),
            )
            private_context = _merge_private_context_updates(
                base_private_context,
                private_updates=private_updates,
                diagnostics=diagnostics,
            )
            runtime_context = self._merge_runtime_context(
                base_runtime_context,
                private_context=private_context,
                prompt_context=prompt_context,
            )
            contributor_kwargs = {
                **kwargs,
                "prompt_context": prompt_context,
                "private_context": private_context,
                "runtime_context": runtime_context,
            }
            try:
                contribution = await self._collect_registered_context_contribution(
                    entry=entry,
                    contributor_kwargs=contributor_kwargs,
                )
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                failure_records.append(
                    _context_contributor_failure_record(
                        entry,
                        code="context_contributor_timeout",
                        error="TimeoutError",
                        message=(
                            f"context contributor timed out after {entry.binding.timeout_seconds} seconds"
                        ),
                    )
                )
                continue
            except _InvalidContextContributorOutput as exc:
                failure_records.append(
                    _context_contributor_failure_record(
                        entry,
                        code="context_contributor_invalid_output",
                        error=type(exc).__name__,
                        message=str(exc),
                        returned_type=exc.returned_type,
                    )
                )
                continue
            except _InvalidContextContributorBinding as exc:
                failure_records.append(
                    _context_contributor_failure_record(
                        entry,
                        code="context_contributor_invalid_binding",
                        error=type(exc).__name__,
                        message=str(exc),
                        returned_type=exc.returned_type,
                    )
                )
                continue
            except Exception as exc:
                failure_records.append(
                    _context_contributor_failure_record(
                        entry,
                        code="context_contributor_failed",
                        error=type(exc).__name__,
                        message=str(exc),
                    )
                )
                continue

            if entry.stage.prompt_channel == ContextContributorPromptChannel.MEMORY:
                memory_fragments.extend(contribution.prompt_fragments)
            else:
                hook_fragments.extend(contribution.prompt_fragments)
            private_updates.update(contribution.private_updates)
            _merge_sidecar_diagnostics(diagnostics, contribution.diagnostics)

        if failure_records:
            _merge_sidecar_diagnostics(
                diagnostics,
                {"context_contributor_diagnostics": tuple(failure_records)},
            )
        return _RegisteredContributorJoinResult(
            memory_fragments=tuple(memory_fragments),
            hook_fragments=tuple(hook_fragments),
            private_updates=private_updates,
            diagnostics=diagnostics,
        )

    async def _collect_registered_context_contribution(
        self,
        *,
        entry: ContextContributorExecutionEntry,
        contributor_kwargs: Mapping[str, Any],
    ) -> _SidecarJoinResult:
        contributor = entry.binding.contributor
        if not callable(getattr(contributor, "collect", None)):
            raise _InvalidContextContributorBinding(contributor)
        coroutine = self._collect_control_plane_fragments_with_context(
            contributor,
            **dict(contributor_kwargs),
        )
        if entry.binding.timeout_seconds is None:
            return await coroutine
        return await asyncio.wait_for(coroutine, timeout=entry.binding.timeout_seconds)

    async def _prepare_compaction(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: tuple[RuntimeMessage, ...],
        prompt_context: PromptContextEnvelope,
        private_context: RuntimePrivateContext,
        runtime_context: Mapping[str, object] | None,
    ) -> CompactionResult:
        service = self._runtime_services.compaction
        if service is not None and hasattr(service, "prepare_turn"):
            prepared = await maybe_await(
                service.prepare_turn(
                    session_id=session_id,
                    turn_id=turn_id,
                    agent=agent,
                    cwd=cwd,
                    messages=messages,
                    prompt_context=prompt_context,
                    private_context=private_context,
                    runtime_context=runtime_context,
                )
            )
            if prepared is not None:
                return prepared

        fragments = await self._collect_control_plane_fragments(
            service,
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
            messages=messages,
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=runtime_context,
        )
        policy = CompactionPolicy.from_private_context(
            private_context,
            legacy_runtime_context=runtime_context,
        )
        return CompactionResult(
            messages=messages,
            policy=policy,
            pressure=evaluate_context_pressure(messages, policy),
            fragments=fragments,
        )

    def _merge_runtime_context(
        self,
        runtime_context: Mapping[str, object] | None,
        *,
        private_context: RuntimePrivateContext | None = None,
        prompt_context: PromptContextEnvelope | None = None,
    ) -> dict[str, object]:
        return compatibility_runtime_context_snapshot(
            runtime_context,
            prompt_context=prompt_context,
            private_context=private_context,
            base_metadata=self._runtime_services.metadata,
        )

    def _resolve_memory_scope(
        self,
        *,
        session_id: str,
        agent: AgentDefinition,
        cwd: str,
    ):
        memory_service = self._runtime_services.memory
        if memory_service is not None and hasattr(memory_service, "resolve_context"):
            resolved = memory_service.resolve_context(session_id=session_id, agent=agent, cwd=cwd)
            scope = getattr(resolved, "scope", None)
            if scope is not None:
                return scope
        return agent.memory

    async def _dispatch_hook(
        self,
        session_id: str,
        payload: Any,
        *,
        dispatch_context: Mapping[str, Any] | None = None,
    ) -> Any:
        if self._runtime_services.hook_bus is None:
            return _EmptyHookResult()
        result = await maybe_await(
            self._runtime_services.hook_bus.dispatch(
                session_id,
                payload,
                dispatch_context=dispatch_context,
            )
        )
        await self._emit_hook_notifications(session_id, result.notifications)
        return result

    async def _complete_buffered_attempt(
        self,
        *,
        model_client: ModelClient,
        request: ModelRequest,
        assistant_message_id: str,
        abort_reason: str | None,
    ) -> tuple[
        tuple[ContentBlock, ...],
        tuple[ToolCall, ...],
        ModelTerminalMetadata,
        tuple[ModelStreamEvent, ...],
        str,
    ]:
        response = await maybe_await(model_client.complete(request))
        terminal = _terminal_from_response(response, abort_reason=abort_reason)
        tool_calls = tuple(_tool_calls_from_message(response.message))
        if terminal.stop_reason == "tool_use" and not tool_calls:
            raise ValueError(
                "Buffered completion returned stop_reason 'tool_use' without ToolUseBlock content"
            )
        resolved_message_id = response.message.message_id or assistant_message_id
        return (
            tuple(response.message.content),
            tool_calls,
            terminal,
            tuple(response.events),
            resolved_message_id,
        )

    def _available_agents_for_request(
        self,
        *,
        current_agent: AgentDefinition,
        private_context: RuntimePrivateContext | None,
    ) -> tuple[AgentDefinition, ...]:
        if self._agent_registry is None:
            return ()
        if private_context is not None and (
            private_context.run_id is not None or private_context.parent_run_id is not None
        ):
            return ()
        return tuple(
            definition
            for definition in self._agent_registry.definitions()
            if definition.name != current_agent.name
        )

    async def _emit_hook_notifications(self, session_id: str, notifications: tuple[str, ...]) -> None:
        for notification in notifications:
            await maybe_await(
                self._runtime_services.host.emit_notification(
                    RuntimeMessage(
                        message_id=uuid4().hex,
                        role=MessageRole.NOTIFICATION,
                        content=notification,
                        metadata={"session_id": session_id, "source": "hook"},
                    )
                )
            )

    def _drain_child_run_events(
        self,
        *,
        session_id: str,
        turn_id: str,
        iteration: int,
        request: ModelRequest | None = None,
    ) -> tuple[TurnStreamEvent, ...]:
        queue = self._child_run_events.get((session_id, turn_id))
        if not queue:
            return ()
        drained = tuple(queue)
        queue.clear()
        return tuple(
            TurnStreamEvent(
                event_type=TurnStreamEventType.CHILD_RUN,
                iteration=iteration,
                request=request,
                child_run=record,
            )
            for record in drained
        )


_ALLOWED_PHASE_TRANSITIONS: dict[TurnPhase, tuple[TurnPhase, ...]] = {
    TurnPhase.PREPARE: (TurnPhase.PREFETCH_SIDECARS,),
    TurnPhase.PREFETCH_SIDECARS: (TurnPhase.COMPACT_OR_REBUILD,),
    TurnPhase.COMPACT_OR_REBUILD: (TurnPhase.BUILD_REQUEST, TurnPhase.RECOVERY_DECISION),
    TurnPhase.BUILD_REQUEST: (TurnPhase.STREAM_ATTEMPT,),
    TurnPhase.STREAM_ATTEMPT: (TurnPhase.REPLAY_TOOLS, TurnPhase.STOP_PHASE, TurnPhase.RECOVERY_DECISION),
    TurnPhase.REPLAY_TOOLS: (TurnPhase.RECOVERY_DECISION,),
    TurnPhase.STOP_PHASE: (TurnPhase.RECOVERY_DECISION,),
    TurnPhase.RECOVERY_DECISION: (TurnPhase.ADVANCE_OR_FINISH,),
    TurnPhase.ADVANCE_OR_FINISH: (TurnPhase.PREPARE, TurnPhase.TERMINAL),
    TurnPhase.TERMINAL: (),
}


def _set_turn_phase(state: TurnLoopState, phase: TurnPhase) -> None:
    if state.phase == phase:
        return
    allowed = _ALLOWED_PHASE_TRANSITIONS.get(state.phase, ())
    if phase not in allowed:
        raise ValueError(f"Illegal turn phase transition: {state.phase.value} -> {phase.value}")
    state.phase = phase
    state.phase_history = state.phase_history + (phase,)


def _attempt_finished_from_terminal(
    *,
    iteration: int,
    terminal: ModelTerminalMetadata,
    tool_calls: Sequence[ToolCall],
) -> AttemptFinished:
    return AttemptFinished(
        iteration=iteration,
        request_id=terminal.request_id,
        attempt_stop_reason=terminal.stop_reason,
        usage=dict(terminal.usage),
        ttft_ms=terminal.ttft_ms,
        error=terminal.error,
        abort_reason=terminal.abort_reason,
        produced_tool_calls=bool(tool_calls),
        tool_call_count=len(tool_calls),
        metadata=dict(terminal.metadata),
    )


def _terminal_reason_from_attempt(attempt: AttemptFinished) -> TurnTerminalReason:
    raw_reason = attempt.attempt_stop_reason
    if raw_reason is None:
        if attempt.error is not None:
            return TurnTerminalReason.ERROR
        return TurnTerminalReason.INCOMPLETE
    try:
        return TurnTerminalReason(raw_reason)
    except ValueError:
        if attempt.error is not None:
            return TurnTerminalReason.ERROR
        return TurnTerminalReason.INCOMPLETE


def _turn_terminal_from_attempt(
    attempt: AttemptFinished,
    *,
    reason: TurnTerminalReason,
    transition: TurnTransition,
    post_effects: TurnPostEffects,
    metadata: Mapping[str, Any] | None = None,
) -> TurnTerminal:
    combined_metadata = dict(attempt.metadata)
    if metadata:
        combined_metadata.update({str(key): value for key, value in metadata.items()})
    if attempt.attempt_stop_reason is not None and attempt.attempt_stop_reason != reason.value:
        combined_metadata.setdefault("attempt_stop_reason", attempt.attempt_stop_reason)
    return TurnTerminal(
        reason=reason,
        usage=dict(attempt.usage),
        request_id=attempt.request_id,
        ttft_ms=attempt.ttft_ms,
        error=attempt.error,
        abort_reason=attempt.abort_reason,
        provider_stop_reason=attempt.attempt_stop_reason,
        transition=transition,
        post_effects=post_effects,
        metadata=combined_metadata,
    )


def _turn_post_effects_for_terminal(
    reason: TurnTerminalReason,
    *,
    matched_stop_hooks: Sequence[str] = (),
) -> TurnPostEffects:
    if reason in {TurnTerminalReason.END_TURN, TurnTerminalReason.MESSAGE_STOP}:
        return TurnPostEffects(
            persist_memory=True,
            schedule_background_extraction=True,
            refresh_session_state=True,
            session_status_hint="ready",
            matched_stop_hooks=tuple(matched_stop_hooks),
        )
    if reason == TurnTerminalReason.BLOCKED:
        return TurnPostEffects(
            refresh_session_state=True,
            session_status_hint="waiting",
            matched_stop_hooks=tuple(matched_stop_hooks),
        )
    if reason == TurnTerminalReason.INTERRUPTED:
        return TurnPostEffects(
            session_status_hint="interrupted",
            matched_stop_hooks=tuple(matched_stop_hooks),
        )
    return TurnPostEffects(
        session_status_hint="ready",
        matched_stop_hooks=tuple(matched_stop_hooks),
    )


def _stop_phase_outcome_from_hook_result(value: Any) -> StopPhaseOutcome:
    disposition = StopDisposition.ALLOW_TERMINAL
    raw_disposition = getattr(value, "stop_disposition", None)
    if raw_disposition is not None:
        try:
            disposition = StopDisposition(str(raw_disposition))
        except ValueError:
            disposition = StopDisposition.ALLOW_TERMINAL
    return StopPhaseOutcome(
        disposition=disposition,
        matched_hook_owners=tuple(getattr(value, "matched_owners", ()) or ()),
        additional_context=tuple(getattr(value, "additional_context", ()) or ()),
        notifications=tuple(getattr(value, "notifications", ()) or ()),
        injected_messages=tuple(getattr(value, "injected_messages", ()) or ()),
        request_override=coerce_request_override_state(getattr(value, "request_override", None)),
        metadata={
            **dict(getattr(value, "metadata", {}) or {}),
            "hook_dispatch_id": getattr(value, "dispatch_id", None),
            "winner_summary": dict(getattr(value, "winner_summary", {}) or {}),
        },
    )


def _serialize_model_request_envelope(request: ModelRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "effort": request.effort,
        "requested_model_route": request.requested_model_route,
        "resolved_model_route": request.resolved_model_route,
        "provider_name": request.provider_name,
        "context_window": serialize_resolved_context_window_snapshot(request.context_window),
        "context_window_policy_tag": request.context_window_policy_tag,
        "invocation_mode": request.invocation_mode.value if request.invocation_mode is not None else None,
        "max_output_tokens": request.max_output_tokens,
        "query_source": request.query_source,
        "message_count": len(request.messages),
        "tool_names": [tool.name for tool in request.tools],
        "skill_names": [skill.name for skill in request.skills],
        "agent_name": request.agent.name if request.agent is not None else None,
        "turn_context": {
            "session_id": request.turn_context.session_id,
            "turn_id": request.turn_context.turn_id,
            "cwd": request.turn_context.cwd,
            "hook_context": list(request.turn_context.hook_context),
            "memory_fragments": list(request.turn_context.memory_fragments),
        },
    }


def _serialize_attempt_response_envelope(
    *,
    assistant_blocks: Sequence[ContentBlock],
    tool_calls: Sequence[ToolCall],
    attempt: AttemptFinished,
) -> dict[str, Any]:
    return {
        "request_id": attempt.request_id,
        "provider_stop_reason": attempt.attempt_stop_reason,
        "usage": dict(attempt.usage),
        "tool_calls": [
            {
                "call_id": call.call_id,
                "tool_name": call.tool_name,
                "tool_input": dict(call.tool_input),
            }
            for call in tool_calls
        ],
        "assistant_content": serialize_content_blocks(tuple(assistant_blocks)),
        "error": attempt.error,
    }


def _serialize_recovery_input(value: NormalizedRecoveryInput) -> dict[str, Any]:
    return {
        "terminal_reason": value.terminal_reason,
        "failure_class": value.failure_class.value,
        "retryable": value.retryable,
        "provider_error_code": value.provider_error_code,
        "error": value.error,
        "abort_reason": value.abort_reason,
        "produced_tool_calls": value.produced_tool_calls,
        "tool_call_count": value.tool_call_count,
        "max_turns_exhausted": value.max_turns_exhausted,
        "tool_executor_unavailable": value.tool_executor_unavailable,
        "metadata": dict(value.metadata),
    }


def _apply_recovery_hook_result(
    decision: RecoveryDecision,
    hook_result: Any,
    *,
    recovery_input: NormalizedRecoveryInput,
) -> RecoveryDecision:
    request_override = merge_request_override_state(
        decision.request_override,
        coerce_request_override_state(getattr(hook_result, "request_override", None)),
    )
    injected_messages = tuple(decision.injected_messages) + tuple(
        getattr(hook_result, "injected_messages", ()) or ()
    )
    metadata = dict(decision.metadata)
    dispatch_id = getattr(hook_result, "dispatch_id", None)
    if dispatch_id:
        metadata["recovery_hook_dispatch_id"] = dispatch_id
    matched_hooks = tuple(getattr(hook_result, "matched_owners", ()) or ())
    if matched_hooks:
        metadata["recovery_hook_matched"] = list(matched_hooks)
    should_continue = bool(getattr(hook_result, "continue_execution", True))
    if not should_continue:
        return RecoveryDecision(
            action=RecoveryAction.HALT,
            reason="recovery_hook_blocked",
            request_override=request_override,
            injected_messages=injected_messages,
            terminal_reason="blocked",
            metadata=metadata,
        )
    if decision.action == RecoveryAction.HALT and matched_hooks:
        resumed_action = (
            RecoveryAction.RETRY_WITH_OVERRIDE
            if request_override is not None
            else (
                RecoveryAction.CONTINUE_SAME_TURN
                if recovery_input.produced_tool_calls
                else RecoveryAction.REBUILD_REQUEST
            )
        )
        return RecoveryDecision(
            action=resumed_action,
            reason="recovery_hook_continue",
            request_override=request_override,
            injected_messages=injected_messages,
            metadata=metadata,
        )
    return replace(
        decision,
        request_override=request_override,
        injected_messages=injected_messages,
        metadata=metadata,
    )


def _turn_terminal_reason_from_recovery(
    decision: RecoveryDecision,
) -> TurnTerminalReason:
    if decision.terminal_reason is None:
        return TurnTerminalReason.END_TURN
    try:
        return TurnTerminalReason(decision.terminal_reason)
    except ValueError:
        return TurnTerminalReason.ERROR


def _turn_transition_reason_from_recovery(
    decision: RecoveryDecision,
    recovery_input: NormalizedRecoveryInput,
) -> TurnTransitionReason:
    if decision.reason == "stop_hook_blocking":
        return TurnTransitionReason.STOP_HOOK_BLOCKING
    if recovery_input.max_turns_exhausted:
        return TurnTransitionReason.MAX_TURNS_EXHAUSTED
    if recovery_input.tool_executor_unavailable:
        return TurnTransitionReason.TOOL_EXECUTOR_UNAVAILABLE
    if recovery_input.interrupted:
        return TurnTransitionReason.ATTEMPT_INTERRUPTED
    if recovery_input.terminal_failure:
        return TurnTransitionReason.ATTEMPT_ERROR
    if decision.action == RecoveryAction.CONTINUE_SAME_TURN:
        return TurnTransitionReason.NEXT_TURN
    return TurnTransitionReason.ATTEMPT_COMPLETED


def _turn_transition_from_recovery(
    decision: RecoveryDecision,
    recovery_input: NormalizedRecoveryInput,
    *,
    stop_outcome: StopPhaseOutcome | None = None,
    prepared_context: PreparedContext | None = None,
) -> TurnTransition:
    metadata = dict(decision.metadata)
    if stop_outcome is not None and stop_outcome.matched_hook_owners:
        metadata.setdefault("matched_hooks", list(stop_outcome.matched_hook_owners))
    if prepared_context is not None:
        metadata.setdefault("context_generation", prepared_context.generation)
        metadata.setdefault("context_effect_kinds", list(prepared_context.effect_kinds()))
    next_phase = TurnPhase.TERMINAL if decision.action == RecoveryAction.HALT else TurnPhase.PREPARE
    return TurnTransition(
        reason=_turn_transition_reason_from_recovery(decision, recovery_input),
        recovery_action=TurnRecoveryAction(decision.action.value),
        next_phase=next_phase,
        metadata=metadata,
    )


def _apply_recovery_decision_to_private_context(
    private_context: RuntimePrivateContext,
    decision: RecoveryDecision,
) -> RuntimePrivateContext:
    updated = private_context
    if decision.request_override is not None:
        updated = _apply_request_override(updated, decision.request_override)
    if decision.action == RecoveryAction.COMPACT_AND_RETRY:
        extensions = dict(updated.extensions)
        extensions["force_compaction"] = True
        updated = replace(updated, extensions=extensions)
    return updated


def _clear_transient_recovery_flags(
    private_context: RuntimePrivateContext,
) -> RuntimePrivateContext:
    if "force_compaction" not in private_context.extensions:
        return private_context
    extensions = dict(private_context.extensions)
    extensions.pop("force_compaction", None)
    return replace(private_context, extensions=extensions)


def _prepared_compaction_payload(
    prepared_context: PreparedContext | None,
) -> dict[str, Any] | None:
    if prepared_context is None:
        return None
    for effect in prepared_context.effects:
        if effect.kind != ContextPreparationEffectKind.COMPACTION:
            continue
        payload = effect.metadata.get("compaction")
        if isinstance(payload, Mapping):
            return dict(payload)
    return None


def _prepared_compaction_summary_id(
    prepared_context: PreparedContext | None,
) -> str | None:
    payload = _prepared_compaction_payload(prepared_context)
    if not isinstance(payload, Mapping):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return None
    summary_id = summary.get("summary_id")
    return str(summary_id) if summary_id is not None else None


def _prepared_context_event_metadata(
    prepared_context: PreparedContext | None,
    *,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if prepared_context is not None:
        metadata["control_plane"] = {
            "context_generation": prepared_context.generation,
            "effect_kinds": list(prepared_context.effect_kinds()),
            "effect_summaries": list(prepared_context.metadata.get("effect_summaries", ()) or ()),
            "effects": [
                {
                    "kind": effect.kind.value,
                    "summary": effect.summary,
                    "metadata": dict(effect.metadata),
                }
                for effect in prepared_context.effects
            ],
            "requires_sidecar_restart": prepared_context.requires_sidecar_restart,
            "diagnostics": list(prepared_context.metadata.get("diagnostics", ()) or ()),
            "context_window": serialize_resolved_context_window_snapshot(prepared_context.context_window),
            "context_window_policy_tag": prepared_context.context_window_policy_tag,
            "budget_policy_tag": prepared_context.metadata.get("budget_policy_tag"),
            "spillover_artifact_refs": list(
                prepared_context.metadata.get("spillover_artifact_refs", ()) or ()
            ),
        }
    if extra:
        metadata.update({str(key): value for key, value in extra.items()})
    return metadata


def _resumable_request_override_metadata(
    decision: RecoveryDecision | None,
    private_context: RuntimePrivateContext,
    *,
    consumed_request_override: RequestOverrideState | None = None,
) -> dict[str, Any] | None:
    if decision is not None:
        serialized = serialize_resumable_request_override(decision.request_override)
        if serialized is not None:
            return serialized
        if decision.terminal_reason not in {
            TurnTerminalReason.END_TURN.value,
            TurnTerminalReason.MESSAGE_STOP.value,
        }:
            serialized = serialize_resumable_request_override(consumed_request_override)
            if serialized is not None:
                return serialized
    return serialize_resumable_request_override(_request_override_from_private_context(private_context))


def _terminal_reason_is_failure(reason: TurnTerminalReason) -> bool:
    return reason in {
        TurnTerminalReason.ERROR,
        TurnTerminalReason.PROMPT_TOO_LONG,
        TurnTerminalReason.IMAGE_ERROR,
        TurnTerminalReason.INTERRUPTED,
    }


def _terminal_reason_is_completed(reason: TurnTerminalReason) -> bool:
    return reason in {TurnTerminalReason.END_TURN, TurnTerminalReason.MESSAGE_STOP}


def _assistant_message_metadata(terminal: ModelTerminalMetadata) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if terminal.stop_reason is not None:
        metadata["stop_reason"] = terminal.stop_reason
    if terminal.request_id is not None:
        metadata["request_id"] = terminal.request_id
    if terminal.ttft_ms is not None:
        metadata["ttft_ms"] = terminal.ttft_ms
    if terminal.usage:
        metadata["usage"] = dict(terminal.usage)
    if terminal.abort_reason is not None:
        metadata["abort_reason"] = terminal.abort_reason
    if terminal.error is not None:
        metadata["error"] = terminal.error
    if terminal.metadata:
        metadata.update(dict(terminal.metadata))
    return metadata


def _terminal_from_response(
    response: Any,
    *,
    abort_reason: str | None,
) -> ModelTerminalMetadata:
    existing = response.terminal or ModelTerminalMetadata()
    usage = dict(existing.usage)
    if response.usage:
        usage = dict(response.usage)
    return ModelTerminalMetadata(
        stop_reason=response.stop_reason or existing.stop_reason or _synthesized_stop_reason(abort_reason, True, None),
        usage=usage,
        request_id=response.request_id or existing.request_id,
        ttft_ms=response.ttft_ms if response.ttft_ms is not None else existing.ttft_ms,
        error=existing.error,
        abort_reason=existing.abort_reason or abort_reason,
        metadata=dict(existing.metadata),
    )


def _default_invocation_registry(skill_registry: SkillRegistry | None) -> InvocationRegistry | None:
    if skill_registry is None:
        return None
    registry = InvocationRegistry()
    registry.register_provider(SkillInvocationProvider(skill_registry))
    return registry


def _empty_invocation_catalog() -> ResolvedInvocationCatalog:
    return ResolvedInvocationCatalog()


def _resolve_iteration_skill_pool(
    *,
    catalog: ResolvedInvocationCatalog,
    agent: AgentDefinition,
    policy_state: ExecutionPolicyState,
    local_root_policy: bool,
) -> tuple[Any, ...]:
    visible_model_skills = catalog.visible_skill_definitions(model_invocable=True)
    if local_root_policy:
        return resolve_skill_pool(visible_model_skills, agent.skills)
    visible_names = {skill.name for skill in visible_model_skills}
    return tuple(
        skill
        for skill in policy_state.effective.skill_pool
        if skill.name in visible_names
    )


def _latest_user_prompt_text(messages: list[RuntimeMessage]) -> str:
    for message in reversed(messages):
        if message.role == MessageRole.USER:
            return message.text
    return ""


def _tool_calls_from_message(message: RuntimeMessage) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    for block in message.content:
        if not isinstance(block, ToolUseBlock):
            continue
        tool_calls.append(
            ToolCall(
                call_id=block.tool_use_id,
                tool_name=block.name,
                tool_input=dict(block.input),
            )
        )
    return tool_calls


def _coerce_block_type(value: ContentBlockType | str | None) -> ContentBlockType:
    if isinstance(value, ContentBlockType):
        return value
    if value is None:
        return ContentBlockType.TEXT
    return ContentBlockType(str(value))


def _mapping_value(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): inner for key, inner in value.items()}


def _string_value(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _float_value(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _query_source(runtime_context: dict[str, object] | None) -> str | None:
    if not runtime_context:
        return None
    for key in ("query_source", "command_type", "agent_name"):
        value = runtime_context.get(key)
        if value is not None:
            return str(value)
    return None


def _merge_prompt_context(
    compat_prompt_context: PromptContextEnvelope,
    explicit_prompt_context: PromptContextEnvelope | None,
) -> PromptContextEnvelope:
    if explicit_prompt_context is None:
        return compat_prompt_context
    session_hints = dict(compat_prompt_context.session_hints)
    session_hints.update(explicit_prompt_context.session_hints)
    extensions = dict(compat_prompt_context.extensions)
    extensions.update(explicit_prompt_context.extensions)
    return PromptContextEnvelope(
        memory_fragments=compat_prompt_context.memory_fragments + explicit_prompt_context.memory_fragments,
        hook_fragments=compat_prompt_context.hook_fragments + explicit_prompt_context.hook_fragments,
        compaction_fragments=(
            compat_prompt_context.compaction_fragments + explicit_prompt_context.compaction_fragments
        ),
        attachments=compat_prompt_context.attachments + explicit_prompt_context.attachments,
        session_hints=session_hints,
        compaction_summary=(
            explicit_prompt_context.compaction_summary
            if explicit_prompt_context.compaction_summary is not None
            else compat_prompt_context.compaction_summary
        ),
        compaction_boundary=(
            explicit_prompt_context.compaction_boundary
            if explicit_prompt_context.compaction_boundary is not None
            else compat_prompt_context.compaction_boundary
        ),
        compaction_continuation=(
            explicit_prompt_context.compaction_continuation
            if explicit_prompt_context.compaction_continuation is not None
            else compat_prompt_context.compaction_continuation
        ),
        extensions=extensions,
    )


def _merge_runtime_private_context(
    compat_private_context: RuntimePrivateContext,
    explicit_private_context: RuntimePrivateContext | Mapping[str, object] | None,
) -> RuntimePrivateContext:
    if explicit_private_context is None:
        return compat_private_context
    if isinstance(explicit_private_context, RuntimePrivateContext):
        resolved_explicit = explicit_private_context
    else:
        resolved_explicit = private_context_from_legacy_runtime_context(explicit_private_context)
    diagnostics = dict(compat_private_context.diagnostics)
    diagnostics.update(resolved_explicit.diagnostics)
    extensions = dict(compat_private_context.extensions)
    extensions.update(resolved_explicit.extensions)
    return RuntimePrivateContext(
        permission_context=(
            resolved_explicit.permission_context
            if resolved_explicit.permission_context is not None
            else compat_private_context.permission_context
        ),
        policy_state=(
            resolved_explicit.policy_state
            if resolved_explicit.policy_state is not None
            else compat_private_context.policy_state
        ),
        run_id=resolved_explicit.run_id or compat_private_context.run_id,
        parent_run_id=resolved_explicit.parent_run_id or compat_private_context.parent_run_id,
        delegation_depth=(
            resolved_explicit.delegation_depth
            if resolved_explicit.delegation_depth is not None
            else compat_private_context.delegation_depth
        ),
        requested_model_route=(
            resolved_explicit.requested_model_route or compat_private_context.requested_model_route
        ),
        resolved_model_route=(
            resolved_explicit.resolved_model_route or compat_private_context.resolved_model_route
        ),
        provider_name=resolved_explicit.provider_name or compat_private_context.provider_name,
        invocation_mode=(
            resolved_explicit.invocation_mode
            if resolved_explicit.invocation_mode is not None
            else compat_private_context.invocation_mode
        ),
        diagnostics=diagnostics,
        extensions=extensions,
    )


def _merge_private_context_updates(
    private_context: RuntimePrivateContext,
    *,
    private_updates: Mapping[str, Any] | None = None,
    diagnostics: Mapping[str, Any] | None = None,
) -> RuntimePrivateContext:
    return merge_runtime_private_context(
        private_context,
        private_updates=private_updates,
        diagnostics=diagnostics,
    )


def _request_override_from_private_context(
    private_context: RuntimePrivateContext,
) -> RequestOverrideState | None:
    return coerce_request_override_state(private_context.extensions.get("request_override")) or (
        request_override_from_skill_request_override(
            coerce_skill_request_override_state(private_context.extensions.get("skill_request_override"))
        )
    )


def _apply_request_override(
    private_context: RuntimePrivateContext,
    pending: RequestOverrideState,
) -> RuntimePrivateContext:
    extensions = dict(private_context.extensions)
    current = _request_override_from_private_context(private_context)
    merged = merge_request_override_state(current, pending)
    if merged is None:
        extensions.pop("request_override", None)
        extensions.pop("skill_request_override", None)
    else:
        extensions["request_override"] = merged.serialize()
        compat_skill_override = skill_request_override_from_request_override(merged)
        if compat_skill_override is not None:
            extensions["skill_request_override"] = compat_skill_override.serialize()
        else:
            extensions.pop("skill_request_override", None)
    return replace(private_context, extensions=extensions)


def _clear_request_override(
    private_context: RuntimePrivateContext,
) -> RuntimePrivateContext:
    if (
        "skill_request_override" not in private_context.extensions
        and "request_override" not in private_context.extensions
    ):
        return private_context
    extensions = dict(private_context.extensions)
    extensions.pop("request_override", None)
    extensions.pop("skill_request_override", None)
    return replace(private_context, extensions=extensions)


def _skill_request_override_from_private_context(
    private_context: RuntimePrivateContext,
) -> SkillRequestOverrideState | None:
    return skill_request_override_from_request_override(
        _request_override_from_private_context(private_context)
    )


def _apply_skill_request_override(
    private_context: RuntimePrivateContext,
    pending: SkillRequestOverrideState,
) -> RuntimePrivateContext:
    request_override = request_override_from_skill_request_override(pending)
    if request_override is None:
        return private_context
    return _apply_request_override(private_context, request_override)


def _clear_skill_request_override(
    private_context: RuntimePrivateContext,
) -> RuntimePrivateContext:
    return _clear_request_override(private_context)


def _skill_runtime_updates_from_outcomes(
    outcomes: Sequence[Any],
) -> tuple[tuple[RuntimeMessage, ...], SkillRequestOverrideState | None]:
    injected_messages: list[RuntimeMessage] = []
    pending_request_override: SkillRequestOverrideState | None = None
    for outcome in outcomes:
        raw_output = getattr(outcome, "raw_output", None)
        if not isinstance(raw_output, Mapping):
            continue
        if "skill" not in raw_output or "mode" not in raw_output:
            continue
        for payload in raw_output.get("injected_messages", ()) or ():
            message = _deserialize_runtime_message_payload(payload)
            if message is not None:
                injected_messages.append(message)
        pending_request_override = merge_skill_request_override_state(
            pending_request_override,
            coerce_skill_request_override_state(raw_output.get("request_override")),
        )
    return tuple(injected_messages), pending_request_override


def _deserialize_runtime_message_payload(payload: Any) -> RuntimeMessage | None:
    if not isinstance(payload, Mapping):
        return None
    role_value = payload.get("role")
    if role_value is None:
        return None
    attachments_payload = payload.get("attachments")
    attachments: list[MessageAttachment] = []
    if isinstance(attachments_payload, Sequence):
        for item in attachments_payload:
            if not isinstance(item, Mapping):
                continue
            attachments.append(
                MessageAttachment(
                    name=str(item.get("name", "")),
                    path=str(item.get("path", "")),
                    mime_type=str(item["mime_type"]) if item.get("mime_type") is not None else None,
                    metadata=dict(item.get("metadata", {}))
                    if isinstance(item.get("metadata"), Mapping)
                    else {},
                )
            )
    return RuntimeMessage(
        message_id=str(payload.get("message_id") or uuid4().hex),
        role=MessageRole(str(role_value)),
        content=deserialize_content_blocks(payload.get("content", [])),
        attachments=tuple(attachments),
        metadata=dict(payload.get("metadata", {}))
        if isinstance(payload.get("metadata"), Mapping)
        else {},
    )


def _split_sidecar_private_updates(
    updates: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    private_updates: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    if updates is None:
        return private_updates, diagnostics
    for key, value in updates.items():
        normalized_key = str(key)
        if normalized_key in _SIDECAR_PROMPT_ONLY_KEYS:
            continue
        if normalized_key in _SIDECAR_DIAGNOSTIC_KEYS:
            diagnostics[normalized_key] = value
            continue
        private_updates[normalized_key] = value
    return private_updates, diagnostics


def _merge_sidecar_diagnostics(
    target: dict[str, Any],
    incoming: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if incoming is None:
        return target
    for key, value in incoming.items():
        normalized_key = str(key)
        if normalized_key == "context_contributor_diagnostics" and normalized_key in target:
            existing = tuple(target.get(normalized_key, ()) or ())
            target[normalized_key] = existing + tuple(value or ())
            continue
        target[normalized_key] = value
    return target


def _context_contributor_failure_record(
    entry: ContextContributorExecutionEntry,
    *,
    code: str,
    error: str,
    message: str,
    returned_type: str | None = None,
) -> dict[str, Any]:
    record = {
        "code": code,
        "contributor": entry.binding.name,
        "stage": entry.stage.name.value,
        "owner": {
            "package_name": entry.binding.owner.package_name,
            "package_role": entry.binding.owner.package_role,
            "surface": entry.binding.owner.surface,
            "metadata": dict(entry.binding.owner.metadata),
        },
        "error": error,
        "message": message,
    }
    if returned_type is not None:
        record["returned_type"] = returned_type
    return record


def _clone_sidecar_compat_runtime_context(
    runtime_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if runtime_context is None:
        return {}
    return {
        str(key): _clone_sidecar_compat_value(value)
        for key, value in runtime_context.items()
    }


def _clone_sidecar_compat_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(inner_key): _clone_sidecar_compat_value(inner_value)
            for inner_key, inner_value in value.items()
        }
    if isinstance(value, list):
        return [_clone_sidecar_compat_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone_sidecar_compat_value(item) for item in value)
    if isinstance(value, set):
        return {_clone_sidecar_compat_value(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_clone_sidecar_compat_value(item) for item in value)
    return value


def _prompt_context_from_sidecar_metadata(
    runtime_context: Mapping[str, Any] | None,
) -> PromptContextEnvelope:
    if runtime_context is None:
        return PromptContextEnvelope()
    return prompt_context_from_legacy_runtime_context(
        runtime_context,
        compaction_summary=_mapping_or_none(runtime_context.get("compaction_summary")),
        compaction_boundary=_mapping_or_none(runtime_context.get("compaction_boundary")),
        compaction_continuation=_mapping_or_none(runtime_context.get("compaction_continuation")),
    )


def _mapping_or_none(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _synthesized_stop_reason(
    abort_reason: str | None,
    message_stopped: bool,
    error: str | None,
) -> str:
    if abort_reason is not None:
        return "interrupted"
    if error is not None:
        return "error"
    if message_stopped:
        return "message_stop"
    return "incomplete"


def _abort_reason_allows_tool_finalize(reason: str | None) -> bool:
    return bool(reason and reason.startswith("tool_failure:"))


def _tool_executor_metadata(tool_executor: Any) -> dict[str, Any] | None:
    if tool_executor is None:
        return None
    metadata = {
        "initial_tier": tool_executor.initial_tier.value,
        "effective_tier": tool_executor.effective_tier.value,
    }
    if tool_executor.downgrade_reason is not None:
        metadata["downgrade_reason"] = tool_executor.downgrade_reason
    return metadata


def _serialize_model_capabilities(capabilities: Any) -> dict[str, Any] | None:
    if capabilities is None:
        return None
    return {
        "structured_tool_calls": capabilities.structured_tool_calls,
        "streaming_tool_call_deltas": capabilities.streaming_tool_call_deltas,
        "tool_call_finalize_boundary": capabilities.tool_call_finalize_boundary,
        "parseable_tool_calls_after_message": capabilities.parseable_tool_calls_after_message,
        "multiple_tool_calls_per_message": capabilities.multiple_tool_calls_per_message,
        "abort_signal_passthrough": capabilities.abort_signal_passthrough,
        "supports_streaming": capabilities.supports_streaming,
    }


def _coerce_permission_context(
    session_id: str,
    metadata: Mapping[str, Any] | None,
) -> PermissionContext:
    if metadata is not None:
        value = metadata.get("permission_context")
        if isinstance(value, PermissionContext):
            return value
    return PermissionContext(session_id=session_id)


@dataclass(frozen=True, slots=True)
class _EmptyHookResult:
    additional_context: tuple[str, ...] = ()
    matched_owners: tuple[str, ...] = ()
    continue_execution: bool = True
    notifications: tuple[str, ...] = ()


def _coerce_model_capabilities(value: object) -> NormalizedModelCapabilities | None:
    if isinstance(value, NormalizedModelCapabilities):
        return value
    if not isinstance(value, dict):
        return None
    try:
        return NormalizedModelCapabilities(
            structured_tool_calls=bool(value.get("structured_tool_calls", True)),
            streaming_tool_call_deltas=bool(value.get("streaming_tool_call_deltas", False)),
            tool_call_finalize_boundary=bool(value.get("tool_call_finalize_boundary", False)),
            parseable_tool_calls_after_message=bool(value.get("parseable_tool_calls_after_message", True)),
            multiple_tool_calls_per_message=bool(value.get("multiple_tool_calls_per_message", True)),
            abort_signal_passthrough=bool(value.get("abort_signal_passthrough", True)),
            supports_streaming=bool(value.get("supports_streaming", True)),
        )
    except Exception:
        return None


def _coerce_invocation_mode(value: object) -> ModelInvocationMode | None:
    if isinstance(value, ModelInvocationMode):
        return value
    if value is None:
        return None
    try:
        return ModelInvocationMode(str(value))
    except ValueError:
        return None


def _select_invocation_mode(
    capabilities: NormalizedModelCapabilities | None,
) -> ModelInvocationMode:
    if capabilities is not None and not capabilities.supports_streaming:
        return ModelInvocationMode.BUFFERED_COMPLETION
    return ModelInvocationMode.STREAM
