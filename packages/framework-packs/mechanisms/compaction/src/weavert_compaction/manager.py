from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, Protocol, Sequence
from uuid import uuid4

from weavert.contracts import (
    MessageRole,
    PromptContextEnvelope,
    RuntimeMessage,
    RuntimePrivateContext,
    ToolResultBlock,
    ToolUseBlock,
)
from .models import (
    CompactionBoundary,
    CompactionContinuation,
    CompactionPolicy,
    CompactionRequest,
    CompactionResult,
    CompactionStepResult,
    CompactionSummary,
    ContextPressure,
    serialize_compaction_boundary,
    serialize_compaction_continuation,
    serialize_compaction_summary,
)


class OrderedCompactionStrategy(Protocol):
    name: str
    order: int

    async def apply(
        self,
        request: CompactionRequest,
        *,
        policy: CompactionPolicy,
        pressure: ContextPressure,
        prior_steps: Sequence[CompactionStepResult] = (),
    ) -> CompactionStepResult | None: ...


class CompactionManager:
    def __init__(
        self,
        strategies: Sequence[OrderedCompactionStrategy] | None = None,
        *,
        default_policy: CompactionPolicy | None = None,
    ) -> None:
        self._strategies = tuple(
            sorted(
                strategies or (ThresholdSummaryCompactionStrategy(),),
                key=lambda strategy: (strategy.order, strategy.name),
            )
        )
        self._default_policy = default_policy or CompactionPolicy()

    async def prepare_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: Any,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> CompactionResult:
        policy = CompactionPolicy.from_private_context(
            private_context,
            legacy_runtime_context=runtime_context,
            default=self._default_policy,
        )
        current_messages = tuple(messages)
        initial_pressure = evaluate_context_pressure(current_messages, policy)
        request = CompactionRequest(
            session_id=session_id,
            turn_id=turn_id,
            agent=agent,
            cwd=cwd,
            messages=current_messages,
            prompt_context=prompt_context or PromptContextEnvelope(),
            private_context=private_context or RuntimePrivateContext(),
            runtime_context=runtime_context,
        )
        steps: list[CompactionStepResult] = []
        current_pressure = initial_pressure

        for strategy in self._strategies:
            step_request = replace(request, messages=current_messages)
            step = await _maybe_await(
                strategy.apply(
                    step_request,
                    policy=policy,
                    pressure=current_pressure,
                    prior_steps=tuple(steps),
                )
            )
            if step is None or not step.applied:
                continue
            current_messages = tuple(step.messages)
            steps.append(step)
            current_pressure = evaluate_context_pressure(current_messages, policy)

        metadata: dict[str, Any] = {}
        if current_pressure != initial_pressure:
            metadata["final_pressure"] = {
                "message_count": current_pressure.message_count,
                "character_count": current_pressure.character_count,
                "max_message_count": current_pressure.max_message_count,
                "max_characters": current_pressure.max_characters,
                "message_limit_exceeded": current_pressure.message_limit_exceeded,
                "character_limit_exceeded": current_pressure.character_limit_exceeded,
                "triggered": current_pressure.triggered,
            }

        return CompactionResult(
            messages=current_messages,
            policy=policy,
            pressure=initial_pressure,
            applied=bool(steps),
            steps=tuple(steps),
            fragments=tuple(fragment for step in steps for fragment in step.fragments),
            metadata=metadata,
        )

    async def collect(self, **kwargs: Any) -> tuple[str, ...]:
        _ = kwargs
        return ()


class ThresholdSummaryCompactionStrategy:
    name = "threshold_summary"
    order = 100

    async def apply(
        self,
        request: CompactionRequest,
        *,
        policy: CompactionPolicy,
        pressure: ContextPressure,
        prior_steps: Sequence[CompactionStepResult] = (),
    ) -> CompactionStepResult | None:
        _ = prior_steps
        if not policy.enabled:
            return None
        if not _should_compact(policy, pressure):
            return None

        pinned_prefix, remaining = _split_pinned_prefix(request.messages)
        keep_recent = min(len(remaining), max(0, policy.keep_recent_messages))
        compact_candidates = remaining[:-keep_recent] if keep_recent else remaining
        preserved_tail = remaining[-keep_recent:] if keep_recent else ()

        if not compact_candidates:
            return None

        summary_text = _summarize_messages(compact_candidates, policy)
        if not summary_text:
            return None

        summary_id = uuid4().hex
        trigger = _trigger_name(policy, pressure)
        boundary = CompactionBoundary(
            boundary_id=uuid4().hex,
            start_index=len(pinned_prefix),
            end_index=len(pinned_prefix) + len(compact_candidates),
            source_message_ids=tuple(message.message_id for message in compact_candidates),
            preserved_message_ids=tuple(message.message_id for message in pinned_prefix + preserved_tail),
            message_count_before=len(request.messages),
            message_count_after=len(pinned_prefix) + len(preserved_tail) + 1,
            trigger=trigger,
            metadata={"strategy_name": self.name},
        )
        summary = CompactionSummary(
            summary_id=summary_id,
            text=summary_text,
            source_message_ids=tuple(message.message_id for message in compact_candidates),
            message_count=len(compact_candidates),
            metadata={"strategy_name": self.name, "trigger": trigger},
        )
        continuation = CompactionContinuation(
            mode="summary_replay",
            summary_id=summary_id,
            resume_message_id=preserved_tail[-1].message_id if preserved_tail else None,
            metadata={
                "strategy_name": self.name,
                "preserved_message_ids": [message.message_id for message in preserved_tail],
            },
        )
        summary_message = RuntimeMessage(
            message_id=summary_id,
            role=MessageRole.SYSTEM,
            content=f"Compacted conversation summary:\n{summary_text}",
            metadata={
                "compaction_summary": True,
                "compaction": {
                    "applied": True,
                    "strategy_name": self.name,
                    "trigger": trigger,
                    "summary": serialize_compaction_summary(summary),
                    "boundary": serialize_compaction_boundary(boundary),
                    "continuation": serialize_compaction_continuation(continuation),
                },
            },
        )
        compacted_messages = tuple(pinned_prefix) + (summary_message,) + tuple(preserved_tail)
        return CompactionStepResult(
            strategy_name=self.name,
            applied=True,
            messages=compacted_messages,
            fragments=(
                f"Compacted {len(compact_candidates)} message(s) into summary {summary_id[:8]} via {self.name}.",
            ),
            summary=summary,
            boundary=boundary,
            continuation=continuation,
            metadata={"trigger": trigger},
        )


def evaluate_context_pressure(
    messages: Sequence[RuntimeMessage],
    policy: CompactionPolicy,
) -> ContextPressure:
    message_count = len(messages)
    character_count = sum(_message_size(message) for message in messages)
    message_limit_exceeded = (
        policy.max_message_count is not None and message_count > policy.max_message_count
    )
    character_limit_exceeded = (
        policy.max_characters is not None and character_count > policy.max_characters
    )
    return ContextPressure(
        message_count=message_count,
        character_count=character_count,
        max_message_count=policy.max_message_count,
        max_characters=policy.max_characters,
        message_limit_exceeded=message_limit_exceeded,
        character_limit_exceeded=character_limit_exceeded,
        triggered=policy.force or message_limit_exceeded or character_limit_exceeded,
    )


def _message_size(message: RuntimeMessage) -> int:
    return len(message.text) + sum(len(attachment.name) + len(attachment.path) for attachment in message.attachments)


def _should_compact(policy: CompactionPolicy, pressure: ContextPressure) -> bool:
    return policy.force or pressure.triggered


def _trigger_name(policy: CompactionPolicy, pressure: ContextPressure) -> str:
    if policy.force:
        return "forced"
    if pressure.message_limit_exceeded or pressure.character_limit_exceeded:
        return "context_pressure"
    return "policy"


def _split_pinned_prefix(
    messages: Sequence[RuntimeMessage],
) -> tuple[tuple[RuntimeMessage, ...], tuple[RuntimeMessage, ...]]:
    index = 0
    while index < len(messages) and messages[index].role == MessageRole.SYSTEM:
        index += 1
    return tuple(messages[:index]), tuple(messages[index:])


def _summarize_messages(messages: Sequence[RuntimeMessage], policy: CompactionPolicy) -> str:
    lines: list[str] = []
    for message in messages:
        lines.append(_summarize_message(message, width=policy.summary_line_width))
        if len(lines) >= policy.summary_line_limit:
            remaining = len(messages) - len(lines)
            if remaining > 0:
                lines.append(f"- ... {remaining} earlier message(s) omitted")
            break
    return "\n".join(line for line in lines if line)


def _summarize_message(message: RuntimeMessage, *, width: int) -> str:
    text = message.text.strip()
    if not text:
        tool_uses = [
            f"tool:{block.name}"
            for block in message.content
            if isinstance(block, ToolUseBlock)
        ]
        tool_results = [
            f"tool_result:{block.tool_use_id}"
            for block in message.content
            if isinstance(block, ToolResultBlock)
        ]
        text = ", ".join(tool_uses + tool_results)
    if not text:
        text = "(non-text content)"
    normalized = " ".join(text.split())
    if len(normalized) > width:
        normalized = normalized[: max(0, width - 3)].rstrip() + "..."
    return f"- {message.role.value}: {normalized}"


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
