from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RuntimeHookPhase(StrEnum):
    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    STOP = "Stop"
    SUBAGENT_STOP = "SubagentStop"
    SESSION_END = "SessionEnd"
    NOTIFICATION = "Notification"
    ELICITATION = "Elicitation"
    ELICITATION_RESULT = "ElicitationResult"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"


class HostLifecyclePhase(StrEnum):
    STARTUP = "startup"
    READY = "ready"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True, slots=True)
class HookCommandDefinition:
    command: str
    once: bool = False
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HookMatcherDefinition:
    matcher: str | None = None
    hooks: tuple[HookCommandDefinition, ...] = ()
    plugin_name: str | None = None


@dataclass(frozen=True, slots=True)
class HookEffect:
    additional_context: tuple[str, ...] = ()
    updated_input: dict[str, Any] | None = None
    continue_execution: bool = True
    notifications: tuple[str, ...] = ()
    elicitation_result: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SessionStartPayload:
    session_id: str
    phase: RuntimeHookPhase = RuntimeHookPhase.SESSION_START
    config_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UserPromptSubmitPayload:
    session_id: str
    prompt: str
    turn_id: str | None = None
    attachments: tuple[str, ...] = ()
    phase: RuntimeHookPhase = RuntimeHookPhase.USER_PROMPT_SUBMIT


@dataclass(frozen=True, slots=True)
class PreToolUsePayload:
    session_id: str
    tool_name: str
    tool_input: dict[str, Any]
    turn_id: str | None = None
    phase: RuntimeHookPhase = RuntimeHookPhase.PRE_TOOL_USE


@dataclass(frozen=True, slots=True)
class PostToolUsePayload:
    session_id: str
    tool_name: str
    tool_input: dict[str, Any]
    tool_result: Any
    turn_id: str | None = None
    phase: RuntimeHookPhase = RuntimeHookPhase.POST_TOOL_USE


@dataclass(frozen=True, slots=True)
class PostToolUseFailurePayload:
    session_id: str
    tool_name: str
    tool_input: dict[str, Any]
    error_message: str
    turn_id: str | None = None
    phase: RuntimeHookPhase = RuntimeHookPhase.POST_TOOL_USE_FAILURE


@dataclass(frozen=True, slots=True)
class StopPayload:
    session_id: str
    reason: str
    turn_id: str | None = None
    phase: RuntimeHookPhase = RuntimeHookPhase.STOP


@dataclass(frozen=True, slots=True)
class SubagentStopPayload:
    session_id: str
    agent_name: str
    status: str
    turn_id: str | None = None
    phase: RuntimeHookPhase = RuntimeHookPhase.SUBAGENT_STOP


@dataclass(frozen=True, slots=True)
class SessionEndPayload:
    session_id: str
    final_status: str
    phase: RuntimeHookPhase = RuntimeHookPhase.SESSION_END


@dataclass(frozen=True, slots=True)
class NotificationPayload:
    session_id: str
    message: str
    level: str = "info"
    phase: RuntimeHookPhase = RuntimeHookPhase.NOTIFICATION


@dataclass(frozen=True, slots=True)
class ElicitationPayload:
    session_id: str
    prompt: str
    kind: str = "text"
    phase: RuntimeHookPhase = RuntimeHookPhase.ELICITATION


@dataclass(frozen=True, slots=True)
class ElicitationResultPayload:
    session_id: str
    prompt: str
    response: dict[str, Any]
    phase: RuntimeHookPhase = RuntimeHookPhase.ELICITATION_RESULT


@dataclass(frozen=True, slots=True)
class PreCompactPayload:
    session_id: str
    token_count: int
    phase: RuntimeHookPhase = RuntimeHookPhase.PRE_COMPACT


@dataclass(frozen=True, slots=True)
class PostCompactPayload:
    session_id: str
    summary_id: str
    phase: RuntimeHookPhase = RuntimeHookPhase.POST_COMPACT


@dataclass(frozen=True, slots=True)
class HostLifecyclePayload:
    host_name: str
    phase: HostLifecyclePhase
    metadata: dict[str, Any] = field(default_factory=dict)
