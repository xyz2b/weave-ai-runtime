from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Generic, Mapping, TypeAlias, TypeVar

from .definitions import InvocationCapabilityView


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {str(key): inner for key, inner in value.items()}


def _coerce_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): inner for key, inner in value.items()}
    return {}


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
class PromptContextEnvelope:
    memory_fragments: tuple[str, ...] = ()
    hook_fragments: tuple[str, ...] = ()
    compaction_fragments: tuple[str, ...] = ()
    attachments: tuple[MessageAttachment, ...] = ()
    session_hints: dict[str, Any] = field(default_factory=dict)
    compaction_summary: dict[str, Any] | None = None
    compaction_boundary: dict[str, Any] | None = None
    compaction_continuation: dict[str, Any] | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_fragments", tuple(self.memory_fragments))
        object.__setattr__(self, "hook_fragments", tuple(self.hook_fragments))
        object.__setattr__(self, "compaction_fragments", tuple(self.compaction_fragments))
        object.__setattr__(self, "attachments", tuple(self.attachments))
        object.__setattr__(self, "session_hints", dict(self.session_hints))
        object.__setattr__(self, "compaction_summary", _copy_mapping(self.compaction_summary))
        object.__setattr__(self, "compaction_boundary", _copy_mapping(self.compaction_boundary))
        object.__setattr__(
            self,
            "compaction_continuation",
            _copy_mapping(self.compaction_continuation),
        )
        object.__setattr__(self, "extensions", dict(self.extensions))

    def compat_metadata(self) -> dict[str, Any]:
        metadata = dict(self.extensions)
        if self.session_hints:
            metadata["session_hints"] = dict(self.session_hints)
        return metadata


@dataclass(frozen=True, slots=True)
class RuntimePrivateContext:
    permission_context: Any = None
    policy_state: Any = None
    run_id: str | None = None
    parent_run_id: str | None = None
    requested_model_route: str | None = None
    resolved_model_route: str | None = None
    provider_name: str | None = None
    invocation_mode: Any = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))
        object.__setattr__(self, "extensions", dict(self.extensions))

    def compat_metadata(self) -> dict[str, Any]:
        metadata = dict(self.extensions)
        if self.permission_context is not None:
            metadata["permission_context"] = self.permission_context
        if self.policy_state is not None:
            metadata["execution_policy_state"] = self.policy_state
        if self.run_id is not None:
            metadata["run_id"] = self.run_id
        if self.parent_run_id is not None:
            metadata["parent_run_id"] = self.parent_run_id
        if self.requested_model_route is not None:
            metadata["requested_model_route"] = self.requested_model_route
        if self.resolved_model_route is not None:
            metadata["resolved_model_route"] = self.resolved_model_route
        if self.provider_name is not None:
            metadata["provider_name"] = self.provider_name
        if self.invocation_mode is not None:
            metadata["invocation_mode"] = self.invocation_mode
        metadata.update(self.diagnostics)
        return metadata


_PRIVATE_CONTEXT_DIAGNOSTIC_KEYS = frozenset({"memory_retrieval", "memory_diagnostics"})


def prompt_context_from_legacy_runtime_context(
    runtime_context: Mapping[str, Any] | None,
    *,
    memory_fragments: tuple[str, ...] | list[str] = (),
    hook_fragments: tuple[str, ...] | list[str] = (),
    compaction_fragments: tuple[str, ...] | list[str] = (),
    attachments: tuple[MessageAttachment, ...] | list[MessageAttachment] = (),
    compaction_summary: Mapping[str, Any] | None = None,
    compaction_boundary: Mapping[str, Any] | None = None,
    compaction_continuation: Mapping[str, Any] | None = None,
) -> PromptContextEnvelope:
    session_hints: dict[str, Any] = {}
    if runtime_context is not None:
        session_hints = _coerce_mapping(runtime_context.get("prompt_updates"))
    return PromptContextEnvelope(
        memory_fragments=tuple(memory_fragments),
        hook_fragments=tuple(hook_fragments),
        compaction_fragments=tuple(compaction_fragments),
        attachments=tuple(attachments),
        session_hints=session_hints,
        compaction_summary=_copy_mapping(compaction_summary),
        compaction_boundary=_copy_mapping(compaction_boundary),
        compaction_continuation=_copy_mapping(compaction_continuation),
    )


def private_context_from_legacy_runtime_context(
    runtime_context: Mapping[str, Any] | None,
) -> RuntimePrivateContext:
    if runtime_context is None:
        return RuntimePrivateContext()
    raw_context = dict(runtime_context)
    diagnostics = _coerce_mapping(raw_context.pop("diagnostics", None))
    for key in _PRIVATE_CONTEXT_DIAGNOSTIC_KEYS:
        if key in raw_context:
            diagnostics[key] = raw_context.pop(key)
    raw_context.pop("prompt_updates", None)
    return RuntimePrivateContext(
        permission_context=raw_context.pop("permission_context", None),
        policy_state=raw_context.pop("execution_policy_state", None),
        run_id=_coerce_optional_string(raw_context.pop("run_id", None)),
        parent_run_id=_coerce_optional_string(raw_context.pop("parent_run_id", None)),
        requested_model_route=_coerce_optional_string(
            raw_context.pop("requested_model_route", None)
        ),
        resolved_model_route=_coerce_optional_string(
            raw_context.pop("resolved_model_route", None)
        ),
        provider_name=_coerce_optional_string(raw_context.pop("provider_name", None)),
        invocation_mode=raw_context.pop("invocation_mode", None),
        diagnostics=diagnostics,
        extensions=raw_context,
    )


def _coerce_optional_string(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


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


# Session commands model inbound control-flow events, not invocation/catalog entries.
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
    available_agents: tuple[str, ...] = ()
    available_invocations: tuple[InvocationCapabilityView, ...] = ()
    memory_fragments: tuple[str, ...] = ()
    hook_context: tuple[str, ...] = ()
    compaction_fragments: tuple[str, ...] = ()
    compaction_summary: dict[str, Any] | None = None
    compaction_boundary: dict[str, Any] | None = None
    compaction_continuation: dict[str, Any] | None = None
    attachments: tuple[MessageAttachment, ...] = ()
    prompt_context: PromptContextEnvelope = field(default_factory=PromptContextEnvelope)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        prompt_context = self.prompt_context
        if prompt_context == PromptContextEnvelope():
            prompt_context = PromptContextEnvelope(
                memory_fragments=tuple(self.memory_fragments),
                hook_fragments=tuple(self.hook_context),
                compaction_fragments=tuple(self.compaction_fragments),
                attachments=tuple(self.attachments),
                compaction_summary=self.compaction_summary,
                compaction_boundary=self.compaction_boundary,
                compaction_continuation=self.compaction_continuation,
                extensions=dict(self.metadata),
            )
        object.__setattr__(self, "prompt_context", prompt_context)
        object.__setattr__(self, "memory_fragments", prompt_context.memory_fragments)
        object.__setattr__(self, "hook_context", prompt_context.hook_fragments)
        object.__setattr__(self, "compaction_fragments", prompt_context.compaction_fragments)
        object.__setattr__(self, "compaction_summary", _copy_mapping(prompt_context.compaction_summary))
        object.__setattr__(self, "compaction_boundary", _copy_mapping(prompt_context.compaction_boundary))
        object.__setattr__(
            self,
            "compaction_continuation",
            _copy_mapping(prompt_context.compaction_continuation),
        )
        object.__setattr__(self, "attachments", prompt_context.attachments)
        object.__setattr__(self, "metadata", prompt_context.compat_metadata())


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
