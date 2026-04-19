from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol


class DefinitionSource(StrEnum):
    BUNDLED = "bundled"
    USER = "user"
    PROJECT = "project"


SOURCE_PRIORITY: dict[DefinitionSource, int] = {
    DefinitionSource.PROJECT: 100,
    DefinitionSource.USER: 200,
    DefinitionSource.BUNDLED: 300,
}


class PermissionMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS_PERMISSIONS = "bypassPermissions"
    DONT_ASK = "dontAsk"
    AUTO = "auto"
    BUBBLE = "bubble"


class MemoryScope(StrEnum):
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


class IsolationMode(StrEnum):
    NONE = "none"
    WORKTREE = "worktree"
    REMOTE = "remote"


class InterruptBehavior(StrEnum):
    CANCEL = "cancel"
    BLOCK = "block"


class SkillExecutionContext(StrEnum):
    INLINE = "inline"
    FORK = "fork"


class SkillShell(StrEnum):
    BASH = "bash"
    POWERSHELL = "powershell"


class InvocationSourceKind(StrEnum):
    BUILTIN_SKILL = "builtin_skill"
    SKILL_DIR = "skill_dir"
    SLASH_COMMAND = "slash_command"
    PLUGIN_COMMAND = "plugin_command"
    MCP_PROMPT = "mcp_prompt"


class InvocationTargetKind(StrEnum):
    SKILL = "skill"
    SLASH_COMMAND = "slash_command"
    PLUGIN_COMMAND = "plugin_command"
    MCP_PROMPT = "mcp_prompt"


class InvocationPathMatchState(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    INDETERMINATE = "indeterminate"


class InvocationHiddenReason(StrEnum):
    PATH_MISMATCH = "path_mismatch"
    PATH_INDETERMINATE = "path_indeterminate"
    INACTIVE = "inactive"
    POLICY_NARROWED = "policy_narrowed"


class PermissionBehavior(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    DENIED = "denied"


class ToolFailureMode(StrEnum):
    REPORT_ONLY = "report_only"
    ERROR_RESULT = "error_result"
    FATAL = "fatal"


class ToolFailureClassifier(StrEnum):
    EXCEPTION_ONLY = "exception_only"
    NONZERO_EXIT_OR_EXCEPTION = "nonzero_exit_or_exception"
    CUSTOM = "custom"


class ToolPresentationEmphasis(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ToolResultSummaryStatus(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    CANCELLED = "cancelled"
    ERROR = "error"


class ToolRiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    EXEC = "exec"
    NETWORK = "network"
    DELEGATE = "delegate"


EffortValue = str | int
ToolInput = Mapping[str, Any]


ToolInputResolver = Callable[[ToolInput, Any], Awaitable[Any] | Any]


def _return(value: Any) -> Callable[[ToolInput, Any], Any]:
    def _resolver(_: ToolInput, __: Any) -> Any:
        return value

    return _resolver


@dataclass(frozen=True, slots=True)
class DefinitionOrigin:
    source: DefinitionSource
    path: Path | None = None
    root: Path | None = None

    @property
    def priority(self) -> int:
        return SOURCE_PRIORITY[self.source]

    @property
    def label(self) -> str:
        if self.path is not None:
            return str(self.path)
        return self.source.value


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    valid: bool
    message: str | None = None
    updated_input: dict[str, Any] | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    behavior: PermissionBehavior
    message: str | None = None
    updated_input: dict[str, Any] | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolTraits:
    read_only: bool = False
    concurrency_safe: bool = False
    destructive: bool = False
    interrupt_behavior: InterruptBehavior = InterruptBehavior.BLOCK


@dataclass(frozen=True, slots=True)
class ToolFailurePolicy:
    failure_mode: ToolFailureMode = ToolFailureMode.REPORT_ONLY
    result_classifier: ToolFailureClassifier = ToolFailureClassifier.EXCEPTION_ONLY
    cancel_running_siblings: bool = False
    block_queued_siblings: bool = False
    abort_model_stream: bool = False
    surfaced_status: ToolCallStatus = ToolCallStatus.ERROR


@dataclass(frozen=True, slots=True)
class ToolUsePresentation:
    title: str
    subtitle: str | None = None
    icon_hint: str | None = None
    emphasis: ToolPresentationEmphasis = ToolPresentationEmphasis.NORMAL


@dataclass(frozen=True, slots=True)
class ToolResultSummary:
    title: str
    summary: str
    status: ToolResultSummaryStatus
    detail_lines: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolClassifierInput:
    operation: str
    summary: str
    target_paths: tuple[str, ...] = ()
    target_urls: tuple[str, ...] = ()
    risk_level: ToolRiskLevel = ToolRiskLevel.READ
    side_effects: bool = False
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolExecutionSemantics:
    is_read_only: ToolInputResolver = field(default_factory=lambda: _return(False))
    is_concurrency_safe: ToolInputResolver = field(default_factory=lambda: _return(False))
    interrupt_behavior: ToolInputResolver = field(
        default_factory=lambda: _return(InterruptBehavior.BLOCK)
    )
    failure_policy: ToolInputResolver = field(
        default_factory=lambda: _return(ToolFailurePolicy())
    )
    render_tool_use_message: ToolInputResolver = field(default_factory=lambda: _return(None))
    render_tool_result_summary: ToolInputResolver = field(default_factory=lambda: _return(None))
    to_classifier_input: ToolInputResolver = field(default_factory=lambda: _return(None))

    @classmethod
    def from_traits(cls, traits: ToolTraits) -> "ToolExecutionSemantics":
        failure_mode = ToolFailureMode.FATAL if traits.destructive else ToolFailureMode.REPORT_ONLY
        failure_policy = ToolFailurePolicy(
            failure_mode=failure_mode,
            result_classifier=ToolFailureClassifier.EXCEPTION_ONLY,
            cancel_running_siblings=traits.destructive,
            block_queued_siblings=traits.destructive,
            abort_model_stream=traits.destructive,
            surfaced_status=ToolCallStatus.ERROR,
        )
        return cls(
            is_read_only=_return(traits.read_only),
            is_concurrency_safe=_return(traits.read_only and traits.concurrency_safe),
            interrupt_behavior=_return(traits.interrupt_behavior),
            failure_policy=_return(failure_policy),
        )


@dataclass(frozen=True, slots=True)
class ResolvedToolExecutionSemantics:
    read_only: bool
    concurrency_safe: bool
    interrupt_behavior: InterruptBehavior
    failure_policy: ToolFailurePolicy
    tool_use_presentation: ToolUsePresentation | None = None
    tool_result_summary: ToolResultSummary | None = None
    classifier_input: ToolClassifierInput | None = None


class ToolValidator(Protocol):
    def __call__(
        self,
        tool_input: ToolInput,
        context: Any,
    ) -> Awaitable[ValidationOutcome] | ValidationOutcome: ...


class ToolPermissionChecker(Protocol):
    def __call__(
        self,
        tool_input: ToolInput,
        context: Any,
    ) -> Awaitable[PermissionDecision] | PermissionDecision: ...


class ToolExecutor(Protocol):
    def __call__(
        self,
        tool_input: ToolInput,
        context: Any,
    ) -> Awaitable[Any] | Any: ...


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    search_hint: str | None = None
    prompt: str | None = None
    traits: ToolTraits = field(default_factory=ToolTraits)
    semantics: ToolExecutionSemantics | None = None
    validate_input: ToolValidator | None = None
    check_permissions: ToolPermissionChecker | None = None
    execute: ToolExecutor | None = None
    runtime_execution_class: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    origin: DefinitionOrigin = field(
        default_factory=lambda: DefinitionOrigin(DefinitionSource.BUNDLED)
    )

    def matches(self, name: str) -> bool:
        return name == self.name or name in self.aliases

    @property
    def execution_semantics(self) -> ToolExecutionSemantics:
        return self.semantics or ToolExecutionSemantics.from_traits(self.traits)


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    name: str
    description: str
    prompt: str
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    model: str | None = None
    model_route: str | None = None
    effort: EffortValue | None = None
    permission_mode: PermissionMode | None = None
    max_turns: int | None = None
    background: bool = False
    memory: MemoryScope | None = None
    isolation: IsolationMode | None = None
    skills: tuple[str, ...] = ()
    mcp_servers: tuple[Any, ...] = ()
    hooks: Mapping[str, Any] = field(default_factory=dict)
    initial_prompt: str | None = None
    critical_system_reminder: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    origin: DefinitionOrigin = field(
        default_factory=lambda: DefinitionOrigin(DefinitionSource.BUNDLED)
    )


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    description: str
    content: str
    display_name: str | None = None
    when_to_use: str | None = None
    version: str | None = None
    user_invocable: bool = True
    disable_model_invocation: bool = False
    argument_hint: str | None = None
    argument_names: tuple[str, ...] = ()
    execution_context: SkillExecutionContext = SkillExecutionContext.INLINE
    agent: str | None = None
    model: str | None = None
    effort: EffortValue | None = None
    allowed_tools: tuple[str, ...] = ()
    shell: SkillShell | None = None
    hooks: Mapping[str, Any] = field(default_factory=dict)
    paths: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    origin: DefinitionOrigin = field(
        default_factory=lambda: DefinitionOrigin(DefinitionSource.BUNDLED)
    )


@dataclass(frozen=True, slots=True)
class InvocationVisibilityPolicy:
    user_invocable: bool = True
    model_invocable: bool = True
    paths: tuple[str, ...] = ()
    surface_hints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvocationExecutionPolicy:
    target_kind: InvocationTargetKind
    target_name: str
    context: str | None = None
    allowed_tools: tuple[str, ...] = ()
    agent: str | None = None
    model: str | None = None
    effort: EffortValue | None = None
    hooks: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvocationDefinition:
    name: str
    source_kind: InvocationSourceKind
    description: str
    display_name: str | None = None
    argument_hint: str | None = None
    aliases: tuple[str, ...] = ()
    visibility_policy: InvocationVisibilityPolicy = field(
        default_factory=InvocationVisibilityPolicy
    )
    execution_policy: InvocationExecutionPolicy | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    origin: DefinitionOrigin = field(
        default_factory=lambda: DefinitionOrigin(DefinitionSource.BUNDLED)
    )


@dataclass(frozen=True, slots=True)
class InvocationResolutionContext:
    session_id: str
    turn_id: str | None
    cwd: Path
    prompt_paths: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    workspace_roots: tuple[Path, ...] = ()
    observed_paths: tuple[str, ...] = ()
    working_set: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvocationCapabilityView:
    name: str
    source_kind: InvocationSourceKind
    description: str
    display_name: str | None = None
    argument_hint: str | None = None
    user_invocable: bool = True
    model_invocable: bool = True
    source_label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvocationDiagnostics:
    name: str
    source_kind: InvocationSourceKind
    visible: bool
    user_invocable: bool
    model_invocable: bool
    hidden_reason: InvocationHiddenReason | None = None
    matched_paths: tuple[str, ...] = ()
    path_match_state: InvocationPathMatchState = InvocationPathMatchState.MATCHED
    narrowed_by_policy: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResolvedInvocation:
    definition: InvocationDefinition
    capability: InvocationCapabilityView
    diagnostics: InvocationDiagnostics


@dataclass(frozen=True, slots=True)
class ResolvedInvocationCatalog:
    visible: tuple[ResolvedInvocation, ...] = ()
    hidden: tuple[ResolvedInvocation, ...] = ()

    @property
    def diagnostics(self) -> tuple[InvocationDiagnostics, ...]:
        return tuple(entry.diagnostics for entry in (*self.visible, *self.hidden))

    def diagnostics_for(self, name: str) -> InvocationDiagnostics | None:
        for entry in (*self.visible, *self.hidden):
            if entry.definition.name == name:
                return entry.diagnostics
        return None

    def visible_capabilities(
        self,
        *,
        user_invocable: bool | None = None,
        model_invocable: bool | None = None,
    ) -> tuple[InvocationCapabilityView, ...]:
        selected: list[InvocationCapabilityView] = []
        for entry in self.visible:
            if user_invocable is not None and entry.diagnostics.user_invocable != user_invocable:
                continue
            if model_invocable is not None and entry.diagnostics.model_invocable != model_invocable:
                continue
            selected.append(entry.capability)
        return tuple(selected)

    def visible_skill_definitions(
        self,
        *,
        user_invocable: bool | None = None,
        model_invocable: bool | None = None,
    ) -> tuple[SkillDefinition, ...]:
        selected: list[SkillDefinition] = []
        for entry in self.visible:
            if user_invocable is not None and entry.diagnostics.user_invocable != user_invocable:
                continue
            if model_invocable is not None and entry.diagnostics.model_invocable != model_invocable:
                continue
            candidate = entry.definition.metadata.get("skill_definition")
            if isinstance(candidate, SkillDefinition):
                selected.append(candidate)
        return tuple(selected)


class InvocationProvider(Protocol):
    name: str

    def list_invocations(self) -> tuple[InvocationDefinition, ...]: ...
