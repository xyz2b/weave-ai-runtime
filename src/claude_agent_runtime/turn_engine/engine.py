from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

from ..contracts import (
    ContentBlock,
    ContentBlockType,
    MessageAttachment,
    MessageRole,
    RedactedThinkingBlock,
    RuntimeMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from ..definitions import AgentDefinition
from ..registries import AgentRegistry, SkillRegistry, ToolRegistry
from ..tasking import TaskManager
from ..tool_runtime import (
    ToolCall,
    ToolCallResult,
    ToolCallStatus,
    ToolContext,
    ToolRefreshCallback,
    ToolScheduler,
    assemble_main_thread_tool_pool,
)
from .composer import PromptComposer
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
    REQUEST_START = "request_start"
    STREAM_PROGRESS = "stream_progress"
    MESSAGE = "message"
    MESSAGE_DISCARDED = "message_discarded"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class TurnStreamEvent:
    event_type: TurnStreamEventType
    iteration: int
    request: ModelRequest | None = None
    model_event: ModelStreamEvent | None = None
    message: RuntimeMessage | None = None
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
    message_stopped: bool = False
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
        self.tool_calls.append(ToolCall(call_id=call_id, tool_name=tool_name, tool_input=tool_input))

    def _finalize_pending_block(self) -> None:
        if self.pending_block is None:
            return
        block = self.pending_block.to_block()
        self.blocks.append(block)
        if isinstance(block, ToolUseBlock):
            self.tool_calls.append(
                ToolCall(
                    call_id=block.tool_use_id,
                    tool_name=block.name,
                    tool_input=dict(block.input),
                )
            )
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
    ) -> None:
        self._model_client = model_client
        self._tool_registry = tool_registry
        self._agent_registry = agent_registry
        self._skill_registry = skill_registry
        self._prompt_composer = prompt_composer or PromptComposer()
        self._permission_handler = permission_handler
        self._ask_user_handler = ask_user_handler
        self._agent_runner = agent_runner
        self._skill_runner = skill_runner
        self._notification_provider = notification_provider
        self._notification_sink = notification_sink
        self._tool_refresh_callback = tool_refresh_callback
        self._task_manager = task_manager or TaskManager()
        self._active_scheduler: ToolScheduler | None = None
        self._active_tool_context: ToolContext | None = None
        self._active_abort_signal: ModelAbortSignal | None = None

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
        self._permission_handler = permission_handler
        self._ask_user_handler = ask_user_handler
        self._agent_runner = agent_runner
        self._skill_runner = skill_runner
        self._notification_provider = notification_provider
        self._notification_sink = notification_sink
        self._tool_refresh_callback = tool_refresh_callback

    def interrupt(self, reason: str = "interrupt") -> None:
        if self._active_abort_signal is not None:
            self._active_abort_signal.abort(reason)
        if self._active_tool_context is not None:
            self._active_tool_context.request_interrupt(reason)
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
        if self._notification_provider is not None:
            notifications = tuple(self._notification_provider())
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
            permission_handler=self._permission_handler,
            ask_user_handler=self._ask_user_handler,
            agent_runner=self._agent_runner,
            skill_runner=self._skill_runner,
            task_manager=self._task_manager,
            abort_signal=abort_signal,
            notifications=notifications,
            notification_sink=self._notification_sink,
            tool_refresh_callback=self._tool_refresh_callback,
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
        attachments: list[MessageAttachment] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> AsyncIterator[TurnStreamEvent]:
        max_iterations = agent.max_turns or 4
        working_messages = list(messages)
        iteration = 0

        while iteration < max_iterations:
            iteration_index = iteration + 1
            state.iterations = iteration_index
            api_messages = normalize_messages_for_api(working_messages)
            tool_pool = assemble_main_thread_tool_pool(
                self._tool_registry,
                allowed_tools=agent.tools or None,
                disallowed_tools=agent.disallowed_tools or None,
            )
            active_skills = self._skill_registry.resolve_active() if self._skill_registry is not None else ()

            composition = self._prompt_composer.compose(
                session_id=session_id,
                turn_id=turn_id,
                agent=agent,
                cwd=cwd,
                messages=api_messages,
                available_tools=[tool.name for tool in tool_pool],
                available_skills=[skill.name for skill in active_skills],
                base_system_prompt=base_system_prompt,
                memory_fragments=memory_fragments or (),
                hook_context=hook_context or (),
                attachments=attachments or (),
                runtime_context=runtime_context or {},
            )
            abort_signal = ModelAbortSignal()
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
                query_source=_query_source(runtime_context),
                metadata=dict(runtime_context or {}),
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
                    message_id=uuid4().hex,
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
            if discarded_blocks:
                yield TurnStreamEvent(
                    event_type=TurnStreamEventType.MESSAGE_DISCARDED,
                    iteration=iteration_index,
                    request=request,
                    terminal=terminal,
                    discarded_content=discarded_blocks,
                    metadata={"reason": terminal.abort_reason or terminal.stop_reason},
                )
            yield TurnStreamEvent(
                event_type=TurnStreamEventType.TERMINAL,
                iteration=iteration_index,
                request=request,
                terminal=terminal,
            )

            if not tool_calls:
                state.completed = terminal.error is None and terminal.stop_reason not in {"interrupted", "error"}
                return

            if abort_signal.aborted:
                state.completed = False
                return

            tool_context = self.create_tool_context(
                session_id=session_id,
                turn_id=turn_id,
                agent_name=agent.name,
                cwd=Path(composition.turn_context.cwd),
                messages=tuple(working_messages),
                tool_pool=tool_pool,
                skill_pool=active_skills,
                abort_signal=abort_signal,
                metadata=runtime_context,
            )
            self._active_tool_context = tool_context
            self._active_scheduler = ToolScheduler(self._tool_registry)
            try:
                tool_results = await self._active_scheduler.run(tool_calls, tool_context)
            finally:
                self._active_scheduler = None
                self._active_tool_context = None

            tool_result_blocks = tuple(_tool_result_block(tool_result) for tool_result in tool_results)
            if tool_result_blocks:
                tool_message = RuntimeMessage(
                    message_id=uuid4().hex,
                    role=MessageRole.USER,
                    content=tool_result_blocks,
                    metadata={
                        "tool_results": [
                            {
                                "tool_use_id": tool_result.call_id,
                                "tool_name": tool_result.tool_name,
                                "status": tool_result.status.value,
                            }
                            for tool_result in tool_results
                        ]
                    },
                )
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


def _tool_result_block(tool_result: ToolCallResult) -> ToolResultBlock:
    if tool_result.status == ToolCallStatus.SUCCESS:
        content = tool_result.output
    else:
        content = tool_result.error or ""
    return ToolResultBlock(
        tool_use_id=tool_result.call_id,
        content=content,
        is_error=tool_result.status != ToolCallStatus.SUCCESS,
    )
