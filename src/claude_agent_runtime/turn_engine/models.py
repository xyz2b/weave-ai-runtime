from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, AsyncIterator, Protocol, Sequence

from ..contracts import RuntimeMessage, TurnContext, utc_now
from ..definitions import AgentDefinition, EffortValue, SkillDefinition, ToolDefinition


class ModelStreamEventType(StrEnum):
    MESSAGE_START = "message_start"
    CONTENT_DELTA = "content_delta"
    TOOL_CALL = "tool_call"
    MESSAGE_STOP = "message_stop"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    event_type: ModelStreamEventType
    payload: dict[str, Any] = field(default_factory=dict)


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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    message: RuntimeMessage
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
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

