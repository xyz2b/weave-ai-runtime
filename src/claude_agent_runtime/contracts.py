from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Generic, TypeVar


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    HOOK = "hook"
    NOTIFICATION = "notification"


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
    content: str
    created_at: datetime = field(default_factory=utc_now)
    attachments: tuple[MessageAttachment, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


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

