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
    PRE_CONTEXT_ASSEMBLE = "PreContextAssemble"
    POST_CONTEXT_ASSEMBLE = "PostContextAssemble"
    PRE_MODEL_REQUEST = "PreModelRequest"
    POST_MODEL_RESPONSE = "PostModelResponse"
    RECOVERY_DECISION = "RecoveryDecision"


class HookStopDisposition(StrEnum):
    HALT_FAILURE = "halt_failure"
    BLOCK_SESSION = "block_session"
    CONTINUE_SAME_TURN = "continue_same_turn"
    ALLOW_TERMINAL = "allow_terminal"


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
    stop_disposition: HookStopDisposition | str | None = None
    injected_messages: tuple[Any, ...] = ()
    request_override: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


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
class PreContextAssemblePayload:
    session_id: str
    turn_id: str
    active_messages: tuple[Any, ...] = ()
    attachment_descriptors: tuple[dict[str, Any], ...] = ()
    runtime_metadata_view: dict[str, Any] = field(default_factory=dict)
    phase: RuntimeHookPhase = RuntimeHookPhase.PRE_CONTEXT_ASSEMBLE

    def __post_init__(self) -> None:
        object.__setattr__(self, "active_messages", tuple(self.active_messages))
        object.__setattr__(
            self,
            "attachment_descriptors",
            tuple(dict(item) for item in self.attachment_descriptors),
        )
        object.__setattr__(self, "runtime_metadata_view", dict(self.runtime_metadata_view))


@dataclass(frozen=True, slots=True)
class PostContextAssemblePayload:
    session_id: str
    turn_id: str
    prompt_context_envelope: Any
    context_generation: int
    request_input_view: dict[str, Any] = field(default_factory=dict)
    phase: RuntimeHookPhase = RuntimeHookPhase.POST_CONTEXT_ASSEMBLE

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_input_view", dict(self.request_input_view))


@dataclass(frozen=True, slots=True)
class PreModelRequestPayload:
    session_id: str
    turn_id: str
    context_generation: int
    request_envelope: dict[str, Any] = field(default_factory=dict)
    request_metadata: dict[str, Any] = field(default_factory=dict)
    phase: RuntimeHookPhase = RuntimeHookPhase.PRE_MODEL_REQUEST

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_envelope", dict(self.request_envelope))
        object.__setattr__(self, "request_metadata", dict(self.request_metadata))


@dataclass(frozen=True, slots=True)
class PostModelResponsePayload:
    session_id: str
    turn_id: str
    request_id: str | None = None
    provider_stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    response_envelope: dict[str, Any] = field(default_factory=dict)
    phase: RuntimeHookPhase = RuntimeHookPhase.POST_MODEL_RESPONSE

    def __post_init__(self) -> None:
        object.__setattr__(self, "usage", dict(self.usage))
        object.__setattr__(self, "response_envelope", dict(self.response_envelope))


@dataclass(frozen=True, slots=True)
class RecoveryDecisionPayload:
    session_id: str
    turn_id: str
    attempt_index: int
    recovery_input: dict[str, Any] = field(default_factory=dict)
    candidate_action: str = ""
    failure_class: str = ""
    phase: RuntimeHookPhase = RuntimeHookPhase.RECOVERY_DECISION

    def __post_init__(self) -> None:
        object.__setattr__(self, "recovery_input", dict(self.recovery_input))


@dataclass(frozen=True, slots=True)
class HostLifecyclePayload:
    host_name: str
    phase: HostLifecyclePhase
    metadata: dict[str, Any] = field(default_factory=dict)
