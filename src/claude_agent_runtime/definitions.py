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


class PermissionBehavior(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


EffortValue = str | int
ToolInput = Mapping[str, Any]


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
    validate_input: ToolValidator | None = None
    check_permissions: ToolPermissionChecker | None = None
    execute: ToolExecutor | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    origin: DefinitionOrigin = field(
        default_factory=lambda: DefinitionOrigin(DefinitionSource.BUNDLED)
    )

    def matches(self, name: str) -> bool:
        return name == self.name or name in self.aliases


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    name: str
    description: str
    prompt: str
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    model: str | None = None
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

