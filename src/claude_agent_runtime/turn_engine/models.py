from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, AsyncIterator, Protocol, Sequence

from ..contracts import (
    ContentBlockType,
    RuntimeMessage,
    RuntimePrivateContext,
    TurnContext,
    private_context_from_legacy_runtime_context,
    utc_now,
)
from ..definitions import AgentDefinition, EffortValue, SkillDefinition, ToolDefinition


class ModelStreamEventType(StrEnum):
    MESSAGE_START = "message_start"
    CONTENT_BLOCK_START = "content_block_start"
    CONTENT_BLOCK_DELTA = "content_block_delta"
    CONTENT_BLOCK_STOP = "content_block_stop"
    CONTENT_DELTA = "content_delta"
    TOOL_CALL = "tool_call"
    MESSAGE_STOP = "message_stop"
    ERROR = "error"


class ToolExecutorTier(StrEnum):
    FULL_STREAMING = "full_streaming"
    BUFFERED = "buffered"
    BATCH = "batch"
    NONE = "none"


class ModelInvocationMode(StrEnum):
    STREAM = "stream"
    BUFFERED_COMPLETION = "buffered_completion"


class ModelAbortSignal:
    __slots__ = ("_event", "_reason")

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason: str | None = None

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return self._reason

    def abort(self, reason: str = "interrupt") -> None:
        self._reason = reason
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()


@dataclass(frozen=True, slots=True)
class ModelTerminalMetadata:
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    ttft_ms: float | None = None
    error: str | None = None
    abort_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizedModelCapabilities:
    structured_tool_calls: bool = True
    streaming_tool_call_deltas: bool = False
    tool_call_finalize_boundary: bool = False
    parseable_tool_calls_after_message: bool = True
    multiple_tool_calls_per_message: bool = True
    abort_signal_passthrough: bool = True
    supports_streaming: bool = True


class ModelCapabilityProvider(Protocol):
    def tool_capabilities(
        self,
        request: "ModelRequest",
    ) -> NormalizedModelCapabilities: ...


@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    event_type: ModelStreamEventType
    payload: dict[str, Any] = field(default_factory=dict)
    block_id: str | None = None
    block_index: int | None = None
    block_type: ContentBlockType | str | None = None
    terminal: ModelTerminalMetadata | None = None


@dataclass(frozen=True, slots=True)
class ModelRequest:
    system_prompt: str
    turn_context: TurnContext
    messages: Sequence[RuntimeMessage]
    tools: Sequence[ToolDefinition] = ()
    skills: Sequence[SkillDefinition] = ()
    agent: AgentDefinition | None = None
    model: str | None = None
    effort: EffortValue | None = None
    abort_signal: ModelAbortSignal | None = None
    query_source: str | None = None
    requested_model_route: str | None = None
    resolved_model_route: str | None = None
    provider_name: str | None = None
    resolved_capabilities: NormalizedModelCapabilities | None = None
    invocation_mode: ModelInvocationMode | None = None
    private_context: RuntimePrivateContext = field(default_factory=RuntimePrivateContext)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        private_context = self.private_context
        if private_context == RuntimePrivateContext():
            private_context = private_context_from_legacy_runtime_context(self.metadata)
        object.__setattr__(self, "private_context", private_context)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    message: RuntimeMessage
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    ttft_ms: float | None = None
    terminal: ModelTerminalMetadata | None = None
    events: tuple[ModelStreamEvent, ...] = ()


class ModelClient(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    session_id: str
    turn_id: str | None
    message: RuntimeMessage
    created_at: Any = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class TranscriptSession:
    session_id: str
    entries: tuple[TranscriptEntry, ...]


class TranscriptStore(Protocol):
    async def append(self, entry: TranscriptEntry) -> None: ...

    async def load(self, session_id: str) -> TranscriptSession: ...

    async def replace(self, session: TranscriptSession) -> None: ...
