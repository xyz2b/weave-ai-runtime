from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from ..contracts import (
    MessageRole,
    RuntimeMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

_API_BOUND_ROLES = frozenset(
    {
        MessageRole.SYSTEM,
        MessageRole.USER,
        MessageRole.ASSISTANT,
    }
)


def normalize_messages_for_api(messages: Sequence[RuntimeMessage]) -> tuple[RuntimeMessage, ...]:
    normalized: list[RuntimeMessage] = []
    for message in messages:
        if message.role not in _API_BOUND_ROLES:
            continue
        candidate = _normalize_message(message)
        if not candidate.content:
            continue
        if normalized and _can_merge_messages(normalized[-1], candidate):
            normalized[-1] = _merge_messages(normalized[-1], candidate)
        else:
            normalized.append(candidate)

    repaired = ensure_tool_result_pairing(normalized)
    merged: list[RuntimeMessage] = []
    for message in repaired:
        if merged and _can_merge_messages(merged[-1], message):
            merged[-1] = _merge_messages(merged[-1], message)
        else:
            merged.append(message)
    return tuple(merged)


def ensure_tool_result_pairing(messages: Sequence[RuntimeMessage]) -> tuple[RuntimeMessage, ...]:
    pending_tool_uses: dict[str, tuple[int, int]] = {}
    matched_tool_use_ids: set[str] = set()
    valid_result_positions: set[tuple[int, int]] = set()

    for message_index, message in enumerate(messages):
        for block_index, block in enumerate(message.content):
            if isinstance(block, ToolUseBlock) and message.role == MessageRole.ASSISTANT:
                pending_tool_uses[block.tool_use_id] = (message_index, block_index)
            elif isinstance(block, ToolResultBlock) and message.role == MessageRole.USER:
                if block.tool_use_id not in pending_tool_uses:
                    continue
                if block.tool_use_id in matched_tool_use_ids:
                    continue
                matched_tool_use_ids.add(block.tool_use_id)
                valid_result_positions.add((message_index, block_index))

    repaired: list[RuntimeMessage] = []
    for message_index, message in enumerate(messages):
        blocks = []
        for block_index, block in enumerate(message.content):
            if isinstance(block, ToolUseBlock):
                if block.tool_use_id in matched_tool_use_ids:
                    blocks.append(block)
                continue
            if isinstance(block, ToolResultBlock):
                if (message_index, block_index) in valid_result_positions:
                    blocks.append(block)
                continue
            blocks.append(block)
        if blocks:
            repaired.append(replace(message, content=tuple(blocks)))
    return tuple(repaired)


def _normalize_message(message: RuntimeMessage) -> RuntimeMessage:
    return replace(message, content=_normalize_blocks(message.content))


def _normalize_blocks(blocks: Sequence[object]) -> tuple[object, ...]:
    normalized: list[object] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            if not block.text:
                continue
            if normalized and isinstance(normalized[-1], TextBlock):
                normalized[-1] = TextBlock(text=normalized[-1].text + block.text)
            else:
                normalized.append(block)
            continue
        if isinstance(block, ToolUseBlock):
            normalized.append(
                ToolUseBlock(
                    tool_use_id=block.tool_use_id,
                    name=block.name.strip(),
                    input=_normalize_payload(block.input),
                )
            )
            continue
        if isinstance(block, ToolResultBlock):
            normalized.append(
                ToolResultBlock(
                    tool_use_id=block.tool_use_id,
                    content=_normalize_payload(block.content),
                    is_error=block.is_error,
                )
            )
            continue
        if isinstance(block, ThinkingBlock) and not block.thinking:
            continue
        normalized.append(block)
    return tuple(normalized)


def _can_merge_messages(left: RuntimeMessage, right: RuntimeMessage) -> bool:
    return left.role == right.role


def _merge_messages(left: RuntimeMessage, right: RuntimeMessage) -> RuntimeMessage:
    merged_metadata = dict(left.metadata)
    merged_metadata.update(right.metadata)
    return replace(
        left,
        content=left.content + right.content,
        attachments=left.attachments + right.attachments,
        metadata=merged_metadata,
    )


def _normalize_payload(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        return {str(key): _normalize_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_normalize_payload(value) for value in payload]
    if isinstance(payload, tuple):
        return [_normalize_payload(value) for value in payload]
    return payload
