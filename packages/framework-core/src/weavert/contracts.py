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
    delegation_depth: int | None = None
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
        if self.delegation_depth is not None:
            metadata["delegation_depth"] = self.delegation_depth
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

    def readonly_view(self) -> "RuntimePrivateContextView":
        return RuntimePrivateContextView(
            run_id=self.run_id,
            parent_run_id=self.parent_run_id,
            delegation_depth=self.delegation_depth,
            requested_model_route=self.requested_model_route,
            resolved_model_route=self.resolved_model_route,
            provider_name=self.provider_name,
            invocation_mode=self.invocation_mode,
            diagnostics=self.diagnostics,
            extensions=self.extensions,
        )


@dataclass(frozen=True, slots=True)
class RuntimePrivateContextView:
    run_id: str | None = None
    parent_run_id: str | None = None
    delegation_depth: int | None = None
    requested_model_route: str | None = None
    resolved_model_route: str | None = None
    provider_name: str | None = None
    invocation_mode: Any = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))
        object.__setattr__(self, "extensions", dict(self.extensions))


REQUEST_OVERRIDE_EXTENSION_KEY = "request_override"
RESUMABLE_REQUEST_OVERRIDE_METADATA_KEY = "resumable_request_override"
RECOVERY_STATE_METADATA_KEY = "recovery_state"


@dataclass(frozen=True, slots=True)
class RequestOverrideState:
    requested_model: str | None = None
    requested_effort: Any = None
    requested_model_route: str | None = None
    invocation_mode_override: Any = None
    max_output_tokens_override: int | None = None
    source: str | None = None
    field_sources: dict[str, str] = field(default_factory=dict)
    resumable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_sources", dict(self.field_sources))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def __bool__(self) -> bool:
        return any(
            value is not None
            for value in (
                self.requested_model,
                self.requested_effort,
                self.requested_model_route,
                self.invocation_mode_override,
                self.max_output_tokens_override,
            )
        )

    def serialize(self) -> dict[str, Any]:
        return {
            "requested_model": self.requested_model,
            "requested_effort": self.requested_effort,
            "requested_model_route": self.requested_model_route,
            "invocation_mode_override": self.invocation_mode_override,
            "max_output_tokens_override": self.max_output_tokens_override,
            "source": self.source,
            "field_sources": dict(self.field_sources),
            "resumable": self.resumable,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class SkillRequestOverrideState:
    requested_model: str | None = None
    requested_effort: Any = None
    source_skill: str | None = None

    def __bool__(self) -> bool:
        return (
            self.requested_model is not None
            or self.requested_effort is not None
            or self.source_skill is not None
        )

    def serialize(self) -> dict[str, Any]:
        return {
            "requested_model": self.requested_model,
            "requested_effort": self.requested_effort,
            "source_skill": self.source_skill,
        }


_PRIVATE_CONTEXT_DIAGNOSTIC_KEYS = frozenset(
    {
        "memory_retrieval",
        "memory_diagnostics",
        "legacy_runtime_context_write_blocked",
    }
)


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
    diagnostic_keys = [
        key
        for key in tuple(raw_context)
        if key in _PRIVATE_CONTEXT_DIAGNOSTIC_KEYS or key.endswith("_diagnostics")
    ]
    for key in diagnostic_keys:
        diagnostics[key] = raw_context.pop(key)
    raw_context.pop("prompt_updates", None)
    raw_context.pop("compaction_summary", None)
    raw_context.pop("compaction_boundary", None)
    raw_context.pop("compaction_continuation", None)
    return RuntimePrivateContext(
        permission_context=raw_context.pop("permission_context", None),
        policy_state=raw_context.pop("execution_policy_state", None),
        run_id=_coerce_optional_string(raw_context.pop("run_id", None)),
        parent_run_id=_coerce_optional_string(raw_context.pop("parent_run_id", None)),
        delegation_depth=_coerce_optional_int(raw_context.pop("delegation_depth", None)),
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


def coerce_runtime_private_context(
    value: RuntimePrivateContext | Mapping[str, Any] | None,
) -> RuntimePrivateContext:
    if isinstance(value, RuntimePrivateContext):
        return value
    if isinstance(value, Mapping):
        return private_context_from_legacy_runtime_context(value)
    return RuntimePrivateContext()


def merge_runtime_private_context(
    private_context: RuntimePrivateContext | Mapping[str, Any] | None = None,
    runtime_context: Mapping[str, Any] | None = None,
    *,
    private_updates: Mapping[str, Any] | None = None,
    diagnostics: Mapping[str, Any] | None = None,
) -> RuntimePrivateContext:
    merged: dict[str, Any] = {}
    if runtime_context:
        merged.update({str(key): value for key, value in runtime_context.items()})
    merged.update(coerce_runtime_private_context(private_context).compat_metadata())
    if private_updates:
        merged.update({str(key): value for key, value in private_updates.items()})
    if diagnostics:
        merged.update({str(key): value for key, value in diagnostics.items()})
    return private_context_from_legacy_runtime_context(merged)


def compatibility_runtime_context_snapshot(
    runtime_context: Mapping[str, Any] | None = None,
    *,
    prompt_context: PromptContextEnvelope | None = None,
    private_context: RuntimePrivateContext | Mapping[str, Any] | None = None,
    base_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if base_metadata:
        merged.update({str(key): value for key, value in base_metadata.items()})
    if runtime_context:
        merged.update({str(key): value for key, value in runtime_context.items()})
    if prompt_context is not None:
        merged["prompt_updates"] = dict(prompt_context.session_hints)
        if prompt_context.compaction_summary is not None:
            merged["compaction_summary"] = dict(prompt_context.compaction_summary)
        if prompt_context.compaction_boundary is not None:
            merged["compaction_boundary"] = dict(prompt_context.compaction_boundary)
        if prompt_context.compaction_continuation is not None:
            merged["compaction_continuation"] = dict(prompt_context.compaction_continuation)
    if private_context is not None:
        merged.update(coerce_runtime_private_context(private_context).compat_metadata())
    return merged


def _coerce_optional_string(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _coerce_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def request_override_from_skill_request_override(
    value: SkillRequestOverrideState | None,
) -> RequestOverrideState | None:
    if value is None or not value:
        return None
    source = value.source_skill or "skill"
    field_sources: dict[str, str] = {}
    if value.requested_model is not None:
        field_sources["requested_model"] = source
    if value.requested_effort is not None:
        field_sources["requested_effort"] = source
    state = RequestOverrideState(
        requested_model=value.requested_model,
        requested_effort=value.requested_effort,
        source=source,
        field_sources=field_sources,
        metadata={"sources": [source], "source_kind": "skill"},
    )
    return state if state else None


def skill_request_override_from_request_override(
    value: RequestOverrideState | None,
) -> SkillRequestOverrideState | None:
    if value is None:
        return None
    state = SkillRequestOverrideState(
        requested_model=value.requested_model,
        requested_effort=value.requested_effort,
        source_skill=_coerce_optional_string(value.metadata.get("source_skill"))
        or value.source,
    )
    return state if state else None


def coerce_request_override_state(value: object) -> RequestOverrideState | None:
    if isinstance(value, RequestOverrideState):
        return value if value else None
    if isinstance(value, SkillRequestOverrideState):
        return request_override_from_skill_request_override(value)
    if not isinstance(value, Mapping):
        return None
    metadata = _coerce_mapping(value.get("metadata"))
    field_sources = {
        str(key): str(source)
        for key, source in _coerce_mapping(value.get("field_sources")).items()
        if source is not None
    }
    state = RequestOverrideState(
        requested_model=_coerce_optional_string(
            value.get("requested_model") or value.get("model")
        ),
        requested_effort=value.get("requested_effort", value.get("effort")),
        requested_model_route=_coerce_optional_string(
            value.get("requested_model_route") or value.get("model_route")
        ),
        invocation_mode_override=value.get(
            "invocation_mode_override",
            value.get("invocation_mode"),
        ),
        max_output_tokens_override=_coerce_optional_int(
            value.get("max_output_tokens_override", value.get("max_output_tokens"))
        ),
        source=_coerce_optional_string(value.get("source"))
        or _coerce_optional_string(value.get("source_skill")),
        field_sources=field_sources,
        resumable=bool(value.get("resumable", False)),
        metadata=metadata,
    )
    if state.source and not state.metadata.get("sources"):
        state = RequestOverrideState(
            requested_model=state.requested_model,
            requested_effort=state.requested_effort,
            requested_model_route=state.requested_model_route,
            invocation_mode_override=state.invocation_mode_override,
            max_output_tokens_override=state.max_output_tokens_override,
            source=state.source,
            field_sources=state.field_sources,
            resumable=state.resumable,
            metadata={**state.metadata, "sources": [state.source]},
        )
    return state if state else None


def merge_request_override_state(
    current: RequestOverrideState | None,
    incoming: RequestOverrideState | None,
) -> RequestOverrideState | None:
    if incoming is None:
        return current
    if current is None:
        return incoming

    def _resolved_field_source(field_name: str) -> str | None:
        if getattr(incoming, field_name) is not None:
            return incoming.field_sources.get(field_name) or incoming.source
        return current.field_sources.get(field_name) or current.source

    requested_model = (
        incoming.requested_model
        if incoming.requested_model is not None
        else current.requested_model
    )
    requested_effort = (
        incoming.requested_effort
        if incoming.requested_effort is not None
        else current.requested_effort
    )
    requested_model_route = (
        incoming.requested_model_route
        if incoming.requested_model_route is not None
        else current.requested_model_route
    )
    invocation_mode_override = (
        incoming.invocation_mode_override
        if incoming.invocation_mode_override is not None
        else current.invocation_mode_override
    )
    max_output_tokens_override = (
        incoming.max_output_tokens_override
        if incoming.max_output_tokens_override is not None
        else current.max_output_tokens_override
    )
    sources: list[str] = []
    for candidate in (
        *tuple(current.metadata.get("sources", ())),
        *tuple(incoming.metadata.get("sources", ())),
        current.source,
        incoming.source,
    ):
        normalized = _coerce_optional_string(candidate)
        if normalized is None or normalized in sources:
            continue
        sources.append(normalized)
    metadata = dict(current.metadata)
    metadata.update(incoming.metadata)
    if sources:
        metadata["sources"] = sources
    if incoming.source and incoming.source.startswith("skill:"):
        metadata.setdefault("source_skill", incoming.source.partition(":")[2])
    field_sources = {
        field_name: source
        for field_name in (
            "requested_model",
            "requested_effort",
            "requested_model_route",
            "invocation_mode_override",
            "max_output_tokens_override",
        )
        if (source := _resolved_field_source(field_name)) is not None
    }
    merged = RequestOverrideState(
        requested_model=requested_model,
        requested_effort=requested_effort,
        requested_model_route=requested_model_route,
        invocation_mode_override=invocation_mode_override,
        max_output_tokens_override=max_output_tokens_override,
        source=incoming.source or current.source,
        field_sources=field_sources,
        resumable=incoming.resumable or current.resumable,
        metadata=metadata,
    )
    return merged if merged else None


def select_resumable_request_override(
    value: object,
) -> RequestOverrideState | None:
    state = coerce_request_override_state(value)
    if state is None or not state.resumable:
        return None
    return state


def serialize_resumable_request_override(
    value: RequestOverrideState | None,
) -> dict[str, Any] | None:
    if value is None or not value.resumable:
        return None
    return value.serialize()


def coerce_skill_request_override_state(value: object) -> SkillRequestOverrideState | None:
    if isinstance(value, RequestOverrideState):
        return skill_request_override_from_request_override(value)
    if isinstance(value, SkillRequestOverrideState):
        return value if value else None
    if not isinstance(value, Mapping):
        return None
    state = SkillRequestOverrideState(
        requested_model=_coerce_optional_string(value.get("requested_model")),
        requested_effort=value.get("requested_effort"),
        source_skill=_coerce_optional_string(value.get("source_skill")),
    )
    return state if state else None


def merge_skill_request_override_state(
    current: SkillRequestOverrideState | None,
    incoming: SkillRequestOverrideState | None,
) -> SkillRequestOverrideState | None:
    merged = merge_request_override_state(
        request_override_from_skill_request_override(current),
        request_override_from_skill_request_override(incoming),
    )
    return skill_request_override_from_request_override(merged)


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
