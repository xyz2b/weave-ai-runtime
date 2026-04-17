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
from ..contracts import (
    ContentBlock,
    ContentBlockType,
    MessageAttachment,
    MessageRole,
    RedactedThinkingBlock,
    RuntimeMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
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
from ..hooks import PostCompactPayload, PreCompactPayload, StopPayload, UserPromptSubmitPayload
from ..invocation_catalog import SkillInvocationProvider, build_invocation_resolution_context
from ..permissions import PermissionContext
from ..registries import AgentRegistry, InvocationRegistry, SkillRegistry, ToolRegistry
from ..runtime_services import DefaultTaskService, RuntimeServices
from ..tool_executors import model_capabilities_for, select_tool_executor
from ..tool_lifecycle import ToolLifecycleEvent
from ..tasking import TaskManager
from ..tool_runtime import (
    ToolCall,
    ToolContext,
    ToolRefreshCallback,
    ToolScheduler,
    assemble_main_thread_tool_pool,
    maybe_await,
)
from .composer import ContextAssembler, PromptComposer
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
    fragments: tuple[str, ...] = ()
    runtime_context_updates: dict[str, Any] = field(default_factory=dict)


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
        self._memory_task: asyncio.Task[_SidecarJoinResult] | None = None
        self._hook_task: asyncio.Task[_SidecarJoinResult] | None = None

    def start(
        self,
        *,
        messages: Sequence[RuntimeMessage],
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
            "runtime_context": dict(runtime_context or {}),
        }
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

    async def restart(
        self,
        *,
        messages: Sequence[RuntimeMessage],
        runtime_context: Mapping[str, object] | None,
    ) -> None:
        self.start(messages=messages, runtime_context=runtime_context)

    async def join(self) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, Any]]:
        memory_result = await self._resolve(self._memory_task)
        hook_result = await self._resolve(self._hook_task)
        merged_updates = dict(memory_result.runtime_context_updates)
        merged_updates.update(hook_result.runtime_context_updates)
        return memory_result.fragments, hook_result.fragments, merged_updates

    async def close(self) -> None:
        tasks = tuple(task for task in (self._memory_task, self._hook_task) if task is not None)
        self.cancel()
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)

    def cancel(self) -> None:
        for task in (self._memory_task, self._hook_task):
            if task is not None and not task.done():
                task.cancel()

    async def _resolve(self, task: asyncio.Task[_SidecarJoinResult] | None) -> _SidecarJoinResult:
        if task is None:
            return _SidecarJoinResult()
        try:
            return await task
        except asyncio.CancelledError:
            return _SidecarJoinResult()


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
        runtime_services: RuntimeServices | None = None,
    ) -> None:
        self._model_client = model_client
        self._tool_registry = tool_registry
        self._agent_registry = agent_registry
        self._skill_registry = skill_registry
        self._invocation_registry = invocation_registry or _default_invocation_registry(skill_registry)
        self._runtime_services = runtime_services or RuntimeServices(
            tasks=DefaultTaskService(task_manager or TaskManager())
        )
        if self._runtime_services.context_assembler is None:
            self._runtime_services.context_assembler = prompt_composer or ContextAssembler()
        elif prompt_composer is not None:
            self._runtime_services.context_assembler = prompt_composer
        if task_manager is not None and self._runtime_services.task_manager is not task_manager:
            self._runtime_services.tasks = DefaultTaskService(task_manager)
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

    @property
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

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
    ) -> ToolContext:
        notifications = ()
        if self._runtime_services.notification_provider is not None:
            notifications = tuple(self._runtime_services.notification_provider())
        permission_context = _coerce_permission_context(session_id, metadata)
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
            task_manager=self._runtime_services.task_manager,
            abort_signal=abort_signal,
            notifications=notifications,
            notification_sink=self._runtime_services.notification_sink,
            tool_refresh_callback=self._runtime_services.tool_refresh_callback,
            runtime_services=self._runtime_services,
            permission_context=permission_context,
            metadata=dict(metadata or {}),
        )

    def resolve_invocation_catalog(
        self,
        *,
        session_id: str,
        turn_id: str | None,
        cwd: str | Path,
        messages: tuple[RuntimeMessage, ...] | list[RuntimeMessage],
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
        runtime_context: dict[str, object] | None = None,
        model_client_override: ModelClient | None = None,
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
            runtime_context=runtime_context,
            model_client_override=model_client_override,
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
        runtime_context: dict[str, object] | None = None,
        model_client_override: ModelClient | None = None,
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
            runtime_context=runtime_context,
            model_client_override=model_client_override,
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
                result.stop_reason = event.terminal.stop_reason
                result.usage = dict(event.terminal.usage)
                result.request_id = event.terminal.request_id
                result.ttft_ms = event.terminal.ttft_ms
                result.abort_reason = event.terminal.abort_reason
                result.error = event.terminal.error
                result.completed = event.terminal.completed
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
        runtime_context: dict[str, object] | None = None,
        model_client_override: ModelClient | None = None,
    ) -> AsyncIterator[TurnStreamEvent]:
        max_iterations = agent.max_turns or 4
        state = TurnLoopState(working_messages=tuple(messages))
        runtime_context = dict(runtime_context or {})
        child_run_key = (session_id, turn_id)
        self._child_run_events[child_run_key] = []
        sidecars = _PreTurnSidecarSupervisor(
            self,
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
        )
        runtime_context.setdefault(
            "permission_context",
            PermissionContext(
                session_id=session_id,
                mode=agent.permission_mode or PermissionMode.DEFAULT,
            ),
        )
        incoming_policy_state = policy_state_from_metadata(runtime_context)
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
                permission_context=runtime_context["permission_context"],
                memory_scope=self._resolve_memory_scope(session_id=session_id, agent=agent, cwd=cwd),
                isolation_mode=agent.isolation,
            )
            policy_state = ExecutionPolicyState(root_policy)
            runtime_context[EXECUTION_POLICY_STATE_KEY] = policy_state
        state.policy_state = policy_state
        last_request: ModelRequest | None = None
        last_attempt: AttemptFinished | None = None

        try:
            while True:
                working_messages = list(state.working_messages)
                model_client = model_client_override or self._model_client
                iteration_index = state.iteration + 1
                state.iteration = iteration_index
                runtime_metadata = self._merge_runtime_context(runtime_context)
                runtime_metadata[EXECUTION_POLICY_STATE_KEY] = policy_state
                runtime_metadata["permission_context"] = policy_state.effective.permission_context
                tool_pool = policy_state.effective.tool_pool
                sanitized_runtime_context = serialize_runtime_metadata(runtime_metadata)
                state.sidecar_generation += 1
                _set_turn_phase(state, TurnPhase.PREFETCH_SIDECARS)
                sidecars.start(
                    messages=tuple(working_messages),
                    runtime_context=sanitized_runtime_context,
                )
                _set_turn_phase(state, TurnPhase.COMPACT_OR_REBUILD)
                await self._dispatch_hook(
                    session_id,
                    PreCompactPayload(
                        session_id=session_id,
                        token_count=sum(len(message.text) for message in working_messages),
                    ),
                )
                compaction_result = await self._prepare_compaction(
                    session_id=session_id,
                    turn_id=turn_id,
                    agent=agent,
                    cwd=cwd,
                    messages=tuple(working_messages),
                    runtime_context=sanitized_runtime_context,
                )
                compaction_payload = (
                    serialize_compaction_result(compaction_result)
                    if compaction_result.applied or compaction_result.fragments
                    else None
                )
                if compaction_result.applied:
                    working_messages = list(compaction_result.messages)
                    state.working_messages = tuple(working_messages)
                    await sidecars.restart(
                        messages=state.working_messages,
                        runtime_context=sanitized_runtime_context,
                    )
                    if compaction_result.summary is not None:
                        await self._dispatch_hook(
                            session_id,
                            PostCompactPayload(
                                session_id=session_id,
                                summary_id=compaction_result.summary.summary_id,
                            ),
                        )
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.COMPACTION,
                        iteration=iteration_index,
                        phase=state.phase,
                        compacted_messages=tuple(working_messages),
                        metadata={"compaction": compaction_payload} if compaction_payload is not None else {},
                    )
                shared_memory_fragments, shared_hook_context, sidecar_updates = await sidecars.join()
                if sidecar_updates:
                    runtime_context.update(sidecar_updates)
                    runtime_metadata.update(sidecar_updates)
                    sanitized_runtime_context.update(sidecar_updates)

                resolved_invocations = self.resolve_invocation_catalog(
                    session_id=session_id,
                    turn_id=turn_id,
                    cwd=cwd,
                    messages=tuple(working_messages),
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

                api_messages = normalize_messages_for_api(working_messages)
                shared_compaction_fragments = tuple(compaction_result.fragments)

                user_prompt_hook = await self._dispatch_hook(
                    session_id,
                    UserPromptSubmitPayload(
                        session_id=session_id,
                        prompt=_latest_user_prompt_text(working_messages),
                        turn_id=turn_id,
                        attachments=tuple(attachment.name for attachment in attachments or ()),
                    ),
                )

                _set_turn_phase(state, TurnPhase.BUILD_REQUEST)
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
                        runtime_context=sanitized_runtime_context,
                    ),
                    available_invocations=resolved_invocations.visible_capabilities(),
                    base_system_prompt=base_system_prompt,
                    memory_fragments=shared_memory_fragments + tuple(memory_fragments or ()),
                    hook_context=shared_hook_context
                    + user_prompt_hook.additional_context
                    + tuple(hook_context or ()),
                    compaction_fragments=shared_compaction_fragments + tuple(compaction_fragments or ()),
                    compaction_summary=serialize_compaction_summary(compaction_result.summary),
                    compaction_boundary=serialize_compaction_boundary(compaction_result.boundary),
                    compaction_continuation=serialize_compaction_continuation(compaction_result.continuation),
                    attachments=attachments or (),
                    runtime_context=sanitized_runtime_context,
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
                )
                pending_tool_turn_events: list[TurnStreamEvent] = []
                request_metadata = dict(sanitized_runtime_context)
                if compaction_payload is not None:
                    request_metadata["compaction"] = compaction_payload
                requested_capabilities = _coerce_model_capabilities(
                    runtime_metadata.get("resolved_capabilities")
                )
                resolved_capabilities = requested_capabilities or model_capabilities_for(model_client)
                invocation_mode = (
                    _coerce_invocation_mode(runtime_metadata.get("invocation_mode"))
                    or _select_invocation_mode(resolved_capabilities)
                )
                request = ModelRequest(
                    system_prompt=composition.system_prompt,
                    turn_context=composition.turn_context,
                    messages=composition.messages,
                    tools=tool_pool,
                    skills=active_skills,
                    agent=agent,
                    model=agent.model,
                    effort=agent.effort,
                    abort_signal=abort_signal,
                    query_source=_query_source(request_metadata),
                    requested_model_route=_string_value(runtime_metadata.get("requested_model_route")),
                    resolved_model_route=_string_value(runtime_metadata.get("resolved_model_route")),
                    provider_name=_string_value(runtime_metadata.get("provider_name")),
                    resolved_capabilities=resolved_capabilities,
                    invocation_mode=invocation_mode,
                    metadata=request_metadata,
                )
                last_request = request
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

                if not tool_calls:
                    _set_turn_phase(state, TurnPhase.STOP_PHASE)
                    stop_hook = await self._dispatch_hook(
                        session_id,
                        StopPayload(
                            session_id=session_id,
                            reason=attempt.attempt_stop_reason or "completed",
                            turn_id=turn_id,
                        ),
                    )
                    _set_turn_phase(state, TurnPhase.RECOVERY_DECISION)
                    terminal_reason = _terminal_reason_from_attempt(attempt)
                    if (
                        not stop_hook.continue_execution
                        and not _terminal_reason_is_failure(terminal_reason)
                    ):
                        terminal_reason = TurnTerminalReason.BLOCKED
                        transition = TurnTransition(
                            reason=TurnTransitionReason.STOP_HOOK_BLOCKING,
                            recovery_action=TurnRecoveryAction.HALT,
                            next_phase=TurnPhase.TERMINAL,
                            metadata={"matched_hooks": list(stop_hook.matched_owners)},
                        )
                    elif terminal_reason == TurnTerminalReason.INTERRUPTED:
                        transition = TurnTransition(
                            reason=TurnTransitionReason.ATTEMPT_INTERRUPTED,
                            recovery_action=TurnRecoveryAction.HALT,
                            next_phase=TurnPhase.TERMINAL,
                        )
                    elif _terminal_reason_is_failure(terminal_reason):
                        transition = TurnTransition(
                            reason=TurnTransitionReason.ATTEMPT_ERROR,
                            recovery_action=TurnRecoveryAction.HALT,
                            next_phase=TurnPhase.TERMINAL,
                        )
                    else:
                        transition = TurnTransition(
                            reason=TurnTransitionReason.ATTEMPT_COMPLETED,
                            recovery_action=TurnRecoveryAction.HALT,
                            next_phase=TurnPhase.TERMINAL,
                        )
                    post_effects = _turn_post_effects_for_terminal(
                        terminal_reason,
                        matched_stop_hooks=stop_hook.matched_owners,
                    )
                    terminal_event = _turn_terminal_from_attempt(
                        attempt,
                        reason=terminal_reason,
                        transition=transition,
                        post_effects=post_effects,
                        metadata={
                            **(
                                {
                                    "continuation_blocked": True,
                                    "matched_hooks": list(stop_hook.matched_owners),
                                }
                                if terminal_reason == TurnTerminalReason.BLOCKED
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
                    transition = TurnTransition(
                        reason=TurnTransitionReason.ATTEMPT_INTERRUPTED,
                        recovery_action=TurnRecoveryAction.HALT,
                        next_phase=TurnPhase.TERMINAL,
                    )
                    post_effects = _turn_post_effects_for_terminal(TurnTerminalReason.INTERRUPTED)
                    terminal_event = _turn_terminal_from_attempt(
                        attempt,
                        reason=TurnTerminalReason.INTERRUPTED,
                        transition=transition,
                        post_effects=post_effects,
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
                    transition = TurnTransition(
                        reason=TurnTransitionReason.TOOL_EXECUTOR_UNAVAILABLE,
                        recovery_action=TurnRecoveryAction.HALT,
                        next_phase=TurnPhase.TERMINAL,
                        metadata={"tool_call_count": len(tool_calls)},
                    )
                    post_effects = _turn_post_effects_for_terminal(TurnTerminalReason.BLOCKED)
                    terminal_event = _turn_terminal_from_attempt(
                        attempt,
                        reason=TurnTerminalReason.BLOCKED,
                        transition=transition,
                        post_effects=post_effects,
                        metadata={
                            "continuation_blocked": True,
                            "tool_executor_unavailable": True,
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
                if iteration_index >= max_iterations:
                    transition = TurnTransition(
                        reason=TurnTransitionReason.MAX_TURNS_EXHAUSTED,
                        recovery_action=TurnRecoveryAction.HALT,
                        next_phase=TurnPhase.TERMINAL,
                        metadata={"tool_call_count": len(tool_calls)},
                    )
                    terminal_event = _turn_terminal_from_attempt(
                        attempt,
                        reason=TurnTerminalReason.MAX_TURNS,
                        transition=transition,
                        post_effects=_turn_post_effects_for_terminal(TurnTerminalReason.MAX_TURNS),
                    )
                else:
                    transition = TurnTransition(
                        reason=TurnTransitionReason.NEXT_TURN,
                        recovery_action=TurnRecoveryAction.CONTINUE_SAME_TURN,
                        next_phase=TurnPhase.PREPARE,
                        metadata={
                            "tool_call_count": len(tool_calls),
                            "tool_executor": _tool_executor_metadata(tool_executor),
                        },
                    )
                    terminal_event = None

                tool_message = tool_executor.orchestrator.tool_result_message(outcomes)
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
                    )
                for child_event in self._drain_child_run_events(
                    session_id=session_id,
                    turn_id=turn_id,
                    iteration=iteration_index,
                    request=request,
                ):
                    yield child_event

                state.transition = transition
                if terminal_event is not None:
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
        if service is None or not hasattr(service, "collect"):
            return ()
        fragments = await maybe_await(service.collect(**kwargs))
        if not fragments:
            return ()
        return tuple(str(fragment) for fragment in fragments)

    async def _collect_control_plane_fragments_with_context(
        self,
        service: Any,
        **kwargs: Any,
    ) -> _SidecarJoinResult:
        original_runtime_context = dict(kwargs.get("runtime_context") or {})
        local_runtime_context = dict(original_runtime_context)
        fragments = await self._collect_control_plane_fragments(
            service,
            **{**kwargs, "runtime_context": local_runtime_context},
        )
        runtime_context_updates = {
            key: value
            for key, value in local_runtime_context.items()
            if original_runtime_context.get(key) != value
        }
        return _SidecarJoinResult(
            fragments=fragments,
            runtime_context_updates=runtime_context_updates,
        )

    async def _prepare_compaction(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: tuple[RuntimeMessage, ...],
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
            runtime_context=runtime_context,
        )
        policy = CompactionPolicy.from_runtime_context(runtime_context)
        return CompactionResult(
            messages=messages,
            policy=policy,
            pressure=evaluate_context_pressure(messages, policy),
            fragments=fragments,
        )

    def _merge_runtime_context(
        self,
        runtime_context: Mapping[str, object] | None,
    ) -> dict[str, object]:
        merged = dict(self._runtime_services.metadata)
        if runtime_context:
            merged.update(runtime_context)
        return merged

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

    async def _dispatch_hook(self, session_id: str, payload: Any) -> Any:
        if self._runtime_services.hook_bus is None:
            return _EmptyHookResult()
        result = await maybe_await(self._runtime_services.hook_bus.dispatch(session_id, payload))
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
        runtime_context: Mapping[str, object] | None,
    ) -> tuple[AgentDefinition, ...]:
        if self._agent_registry is None:
            return ()
        if runtime_context and (
            runtime_context.get("run_id") is not None
            or runtime_context.get("parent_run_id") is not None
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
