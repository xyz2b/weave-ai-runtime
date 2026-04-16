from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, AsyncIterator, Mapping
from uuid import uuid4

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
from ..definitions import AgentDefinition, PermissionMode
from ..execution_policy import (
    EXECUTION_POLICY_STATE_KEY,
    ExecutionPolicyState,
    build_root_execution_policy,
    policy_state_from_metadata,
    resolve_skill_pool,
    serialize_runtime_metadata,
)
from ..hooks import StopPayload, UserPromptSubmitPayload
from ..permissions import PermissionContext
from ..registries import AgentRegistry, SkillRegistry, ToolRegistry
from ..runtime_services import DefaultTaskService, RuntimeServices
from ..tool_executors import select_tool_executor
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
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    ModelTerminalMetadata,
)


class TurnStreamEventType(StrEnum):
    COMPACTION = "compaction"
    REQUEST_START = "request_start"
    STREAM_PROGRESS = "stream_progress"
    TOOL_LIFECYCLE = "tool_lifecycle"
    MESSAGE = "message"
    MESSAGE_DISCARDED = "message_discarded"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class TurnStreamEvent:
    event_type: TurnStreamEventType
    iteration: int
    request: ModelRequest | None = None
    model_event: ModelStreamEvent | None = None
    tool_event: ToolLifecycleEvent | None = None
    message: RuntimeMessage | None = None
    compacted_messages: tuple[RuntimeMessage, ...] = ()
    terminal: ModelTerminalMetadata | None = None
    discarded_content: tuple[ContentBlock, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TurnResult:
    messages: list[RuntimeMessage] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    attempts: list[ModelTerminalMetadata] = field(default_factory=list)
    iterations: int = 0
    completed: bool = False
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    ttft_ms: float | None = None
    abort_reason: str | None = None
    error: str | None = None


@dataclass(slots=True)
class _TurnRunState:
    iterations: int = 0
    completed: bool = False


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
    ) -> tuple[tuple[ContentBlock, ...], tuple[ContentBlock, ...], tuple[ToolCall, ...], ModelTerminalMetadata]:
        discarded_blocks = tuple(self.blocks) + self._discard_pending_block()
        if self.message_stopped:
            committed_blocks = tuple(self.blocks)
            discarded_blocks = ()
            tool_calls = tuple(self.tool_calls)
        else:
            committed_blocks = ()
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


class TurnEngine:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
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
    ) -> AsyncIterator[TurnStreamEvent]:
        state = _TurnRunState()
        async for event in self._run_turn_stream_impl(
            state=state,
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
    ) -> TurnResult:
        result = TurnResult()
        state = _TurnRunState()
        async for event in self._run_turn_stream_impl(
            state=state,
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
        ):
            if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
                result.messages.append(event.message)
                if event.message.role == MessageRole.ASSISTANT:
                    result.tool_calls.extend(_tool_calls_from_message(event.message))
            elif event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
                result.attempts.append(event.terminal)
                result.iterations = max(result.iterations, event.iteration)
                result.stop_reason = event.terminal.stop_reason
                result.usage = dict(event.terminal.usage)
                result.request_id = event.terminal.request_id
                result.ttft_ms = event.terminal.ttft_ms
                result.abort_reason = event.terminal.abort_reason
                result.error = event.terminal.error

        result.iterations = max(result.iterations, state.iterations)
        result.completed = state.completed
        return result

    async def _run_turn_stream_impl(
        self,
        *,
        state: _TurnRunState,
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
    ) -> AsyncIterator[TurnStreamEvent]:
        max_iterations = agent.max_turns or 4
        working_messages = list(messages)
        iteration = 0
        runtime_context = dict(runtime_context or {})
        runtime_context.setdefault(
            "permission_context",
            PermissionContext(
                session_id=session_id,
                mode=agent.permission_mode or PermissionMode.DEFAULT,
            ),
        )
        policy_state = policy_state_from_metadata(runtime_context)
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

        try:
            while iteration < max_iterations:
                iteration_index = iteration + 1
                state.iterations = iteration_index
                runtime_metadata = self._merge_runtime_context(runtime_context)
                runtime_metadata[EXECUTION_POLICY_STATE_KEY] = policy_state
                runtime_metadata["permission_context"] = policy_state.effective.permission_context
                tool_pool = policy_state.effective.tool_pool
                active_skills = policy_state.effective.skill_pool
                sanitized_runtime_context = serialize_runtime_metadata(runtime_metadata)
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
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.COMPACTION,
                        iteration=iteration_index,
                        compacted_messages=tuple(working_messages),
                        metadata={"compaction": compaction_payload} if compaction_payload is not None else {},
                    )

                api_messages = normalize_messages_for_api(working_messages)
                shared_memory_fragments = await self._collect_control_plane_fragments(
                    self._runtime_services.memory,
                    session_id=session_id,
                    turn_id=turn_id,
                    agent=agent,
                    cwd=cwd,
                    messages=tuple(working_messages),
                    runtime_context=sanitized_runtime_context,
                )
                shared_hook_context = await self._collect_control_plane_fragments(
                    self._runtime_services.hooks,
                    session_id=session_id,
                    turn_id=turn_id,
                    agent=agent,
                    cwd=cwd,
                    messages=tuple(working_messages),
                    runtime_context=sanitized_runtime_context,
                )
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

                composition = self._compose_context(
                    session_id=session_id,
                    turn_id=turn_id,
                    agent=agent,
                    cwd=cwd,
                    messages=api_messages,
                    available_tools=[tool.name for tool in tool_pool],
                    available_skills=[skill.name for skill in active_skills],
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
                    metadata=request_metadata,
                )
                tool_executor = select_tool_executor(
                    self._model_client,
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
                    request=request,
                )

                attempt_state = _StreamAttemptState()
                self._active_abort_signal = abort_signal
                try:
                    async for event in self._model_client.stream(request):
                        attempt_state.observe(event)
                        yield TurnStreamEvent(
                            event_type=TurnStreamEventType.STREAM_PROGRESS,
                            iteration=iteration_index,
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
                except Exception as exc:
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
                        request=request,
                        model_event=error_event,
                    )
                finally:
                    self._active_abort_signal = None

                assistant_blocks, discarded_blocks, tool_calls, terminal = attempt_state.finalize(
                    abort_reason=abort_signal.reason
                )
                if assistant_blocks:
                    assistant_message = RuntimeMessage(
                        message_id=assistant_message_id,
                        role=MessageRole.ASSISTANT,
                        content=assistant_blocks,
                        metadata=_assistant_message_metadata(terminal),
                    )
                    working_messages.append(assistant_message)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.MESSAGE,
                        iteration=iteration_index,
                        request=request,
                        message=assistant_message,
                        terminal=terminal,
                    )
                    tool_context.messages = tuple(working_messages)
                    if tool_context.query_context is not None:
                        tool_context.query_context = replace(
                            tool_context.query_context,
                            messages=tuple(working_messages),
                        )
                while pending_tool_turn_events:
                    yield pending_tool_turn_events.pop(0)
                if discarded_blocks:
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.MESSAGE_DISCARDED,
                        iteration=iteration_index,
                        request=request,
                        terminal=terminal,
                        discarded_content=discarded_blocks,
                        metadata={"reason": terminal.abort_reason or terminal.stop_reason},
                    )

                if not tool_calls:
                    stop_hook = await self._dispatch_hook(
                        session_id,
                        StopPayload(
                            session_id=session_id,
                            reason=terminal.stop_reason or "completed",
                            turn_id=turn_id,
                        ),
                    )
                    if not stop_hook.continue_execution:
                        terminal = replace(
                            terminal,
                            stop_reason="blocked",
                            metadata={
                                **terminal.metadata,
                                "continuation_blocked": True,
                                "matched_hooks": list(stop_hook.matched_owners),
                            },
                        )
                    state.completed = (
                        terminal.error is None
                        and terminal.stop_reason not in {"interrupted", "error", "blocked"}
                    )
                    self._active_tool_context = None
                    self._active_tool_executor = None
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.TERMINAL,
                        iteration=iteration_index,
                        request=request,
                        terminal=terminal,
                    )
                    return

                yield TurnStreamEvent(
                    event_type=TurnStreamEventType.TERMINAL,
                    iteration=iteration_index,
                    request=request,
                    terminal=replace(
                        terminal,
                        metadata={
                            **terminal.metadata,
                            "tool_executor": _tool_executor_metadata(tool_executor),
                        },
                    ),
                )

                if abort_signal.aborted:
                    state.completed = False
                    self._active_tool_context = None
                    self._active_tool_executor = None
                    return

                if tool_executor is None:
                    state.completed = False
                    self._active_tool_context = None
                    self._active_tool_executor = None
                    return
                try:
                    outcomes = await tool_executor.finalize(
                        tool_calls,
                        assistant_message_id=assistant_message_id,
                        provider_request_id=terminal.request_id,
                        has_pending_tool_use=attempt_state.pending_tool_use_closed_at_message_stop,
                    )
                finally:
                    self._active_tool_context = None
                    self._active_tool_executor = None

                while pending_tool_turn_events:
                    yield pending_tool_turn_events.pop(0)

                tool_message = tool_executor.orchestrator.tool_result_message(outcomes)
                if tool_message is not None:
                    working_messages.append(tool_message)
                    yield TurnStreamEvent(
                        event_type=TurnStreamEventType.MESSAGE,
                        iteration=iteration_index,
                        request=request,
                        message=tool_message,
                        terminal=terminal,
                    )

                iteration += 1

            state.completed = False
        finally:
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
