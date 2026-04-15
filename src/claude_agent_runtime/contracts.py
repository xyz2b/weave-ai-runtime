from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Generic, TypeAlias, TypeVar


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    HOOK = "hook"
    NOTIFICATION = "notification"


class ContentBlockType(StrEnum):
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    REDACTED_THINKING = "redacted_thinking"


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    type: ContentBlockType = field(default=ContentBlockType.TEXT, init=False)


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    tool_use_id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    type: ContentBlockType = field(default=ContentBlockType.TOOL_USE, init=False)


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    tool_use_id: str
    content: Any
    is_error: bool = False
    type: ContentBlockType = field(default=ContentBlockType.TOOL_RESULT, init=False)


@dataclass(frozen=True, slots=True)
class ThinkingBlock:
    thinking: str
    signature: str | None = None
    type: ContentBlockType = field(default=ContentBlockType.THINKING, init=False)


@dataclass(frozen=True, slots=True)
class RedactedThinkingBlock:
    data: str | None = None
    type: ContentBlockType = field(default=ContentBlockType.REDACTED_THINKING, init=False)


ContentBlock: TypeAlias = (
    TextBlock
    | ToolUseBlock
    | ToolResultBlock
    | ThinkingBlock
    | RedactedThinkingBlock
)


@dataclass(frozen=True, slots=True)
class MessageAttachment:
    name: str
    path: str
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeMessage:
    message_id: str
    role: MessageRole
    content: tuple[ContentBlock, ...]
    created_at: datetime = field(default_factory=utc_now)
    attachments: tuple[MessageAttachment, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", coerce_content_blocks(self.content))

    @property
    def text(self) -> str:
        return content_blocks_to_text(self.content)


class SessionCommandType(StrEnum):
    USER_PROMPT = "user_prompt"
    SYSTEM_MESSAGE = "system_message"
    TASK_NOTIFICATION = "task_notification"
    HOST_EVENT = "host_event"
    INTERRUPT = "interrupt"
    RESUME = "resume"


@dataclass(frozen=True, slots=True)
class SessionCommand:
    command_id: str
    command_type: SessionCommandType
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=utc_now)
    priority: int = 0


class SessionStatus(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(slots=True)
class SessionState:
    session_id: str
    status: SessionStatus = SessionStatus.IDLE
    current_agent: str = "main-router"
    active_turn_id: str | None = None
    queued_commands: list[SessionCommand] = field(default_factory=list)
    started_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnContext:
    session_id: str
    turn_id: str
    agent_name: str
    cwd: str
    messages: tuple[RuntimeMessage, ...]
    available_tools: tuple[str, ...] = ()
    available_skills: tuple[str, ...] = ()
    memory_fragments: tuple[str, ...] = ()
    hook_context: tuple[str, ...] = ()
    compaction_fragments: tuple[str, ...] = ()
    attachments: tuple[MessageAttachment, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


T = TypeVar("T")


@dataclass(slots=True)
class ExecutionResult(Generic[T]):
    status: ExecutionStatus
    value: T | None = None
    messages: list[RuntimeMessage] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def coerce_content_blocks(value: object) -> tuple[ContentBlock, ...]:
    if isinstance(value, str):
        return () if value == "" else (TextBlock(text=value),)
    if isinstance(value, (TextBlock, ToolUseBlock, ToolResultBlock, ThinkingBlock, RedactedThinkingBlock)):
        return (value,)
    if isinstance(value, tuple):
        blocks = value
    elif isinstance(value, list):
        blocks = tuple(value)
    else:
        raise TypeError(f"Unsupported runtime message content: {type(value)!r}")
    normalized: list[ContentBlock] = []
    for block in blocks:
        if not isinstance(block, (TextBlock, ToolUseBlock, ToolResultBlock, ThinkingBlock, RedactedThinkingBlock)):
            raise TypeError(f"Unsupported content block: {type(block)!r}")
        normalized.append(block)
    return tuple(normalized)


def content_blocks_to_text(blocks: tuple[ContentBlock, ...]) -> str:
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        elif isinstance(block, ToolResultBlock):
            if isinstance(block.content, str):
                parts.append(block.content)
            elif block.content is not None:
                parts.append(json.dumps(block.content, ensure_ascii=True, sort_keys=True))
        elif isinstance(block, ThinkingBlock):
            parts.append(block.thinking)
        elif isinstance(block, RedactedThinkingBlock) and block.data:
            parts.append(block.data)
    return "".join(parts)


def serialize_content_blocks(blocks: tuple[ContentBlock, ...]) -> list[dict[str, Any]]:
    return [serialize_content_block(block) for block in blocks]


def serialize_content_block(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": block.type.value, "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": block.type.value,
            "tool_use_id": block.tool_use_id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": block.type.value,
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    if isinstance(block, ThinkingBlock):
        return {
            "type": block.type.value,
            "thinking": block.thinking,
            "signature": block.signature,
        }
    return {
        "type": block.type.value,
        "data": block.data,
    }


def deserialize_content_blocks(payload: object) -> tuple[ContentBlock, ...]:
    if isinstance(payload, str):
        return coerce_content_blocks(payload)
    if not isinstance(payload, list):
        raise TypeError(f"Unsupported serialized content payload: {type(payload)!r}")
    return tuple(deserialize_content_block(block_payload) for block_payload in payload)


def deserialize_content_block(payload: object) -> ContentBlock:
    if not isinstance(payload, dict):
        raise TypeError(f"Unsupported serialized content block: {type(payload)!r}")
    block_type = ContentBlockType(str(payload["type"]))
    if block_type == ContentBlockType.TEXT:
        return TextBlock(text=str(payload.get("text", "")))
    if block_type == ContentBlockType.TOOL_USE:
        return ToolUseBlock(
            tool_use_id=str(payload["tool_use_id"]),
            name=str(payload["name"]),
            input=dict(payload.get("input", {})),
        )
    if block_type == ContentBlockType.TOOL_RESULT:
        return ToolResultBlock(
            tool_use_id=str(payload["tool_use_id"]),
            content=payload.get("content"),
            is_error=bool(payload.get("is_error", False)),
        )
    if block_type == ContentBlockType.THINKING:
        return ThinkingBlock(
            thinking=str(payload.get("thinking", "")),
            signature=str(payload["signature"]) if payload.get("signature") is not None else None,
        )
    return RedactedThinkingBlock(data=str(payload["data"]) if payload.get("data") is not None else None)
