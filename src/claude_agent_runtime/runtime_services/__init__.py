from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from ..contracts import RuntimeMessage
from ..definitions import AgentDefinition, PermissionBehavior, PermissionDecision, ToolDefinition
from ..tasking import TaskManager


class ContextContributionService(Protocol):
    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        runtime_context: Mapping[str, Any] | None = None,
    ) -> Sequence[str]: ...


class PermissionService(Protocol):
    async def authorize(
        self,
        definition: ToolDefinition,
        tool_input: dict[str, Any],
        decision: PermissionDecision,
        context: Any,
    ) -> PermissionDecision: ...


class ElicitationService(Protocol):
    async def ask(
        self,
        question: str,
        options: Sequence[str] | None = None,
    ) -> Any: ...


class HostRuntimeService(Protocol):
    def current_notifications(self) -> Sequence[RuntimeMessage]: ...

    async def emit_notification(self, message: RuntimeMessage) -> None: ...


class ToolCatalogService(Protocol):
    async def refresh_tools(self, context: Any) -> Sequence[ToolDefinition] | None: ...


@dataclass(slots=True)
class NoopHookService:
    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        runtime_context: Mapping[str, Any] | None = None,
    ) -> tuple[str, ...]:
        _ = session_id, turn_id, agent, cwd, messages, runtime_context
        return ()


@dataclass(slots=True)
class NoopMemoryService:
    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        runtime_context: Mapping[str, Any] | None = None,
    ) -> tuple[str, ...]:
        _ = session_id, turn_id, agent, cwd, messages, runtime_context
        return ()


@dataclass(slots=True)
class NoopCompactionService:
    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        runtime_context: Mapping[str, Any] | None = None,
    ) -> tuple[str, ...]:
        _ = session_id, turn_id, agent, cwd, messages, runtime_context
        return ()


@dataclass(slots=True)
class CallbackPermissionService:
    handler: Any = None

    async def authorize(
        self,
        definition: ToolDefinition,
        tool_input: dict[str, Any],
        decision: PermissionDecision,
        context: Any,
    ) -> PermissionDecision:
        if self.handler is None:
            return PermissionDecision(
                PermissionBehavior.DENY,
                message=decision.message or "Permission required",
                details=dict(decision.details),
            )
        return await _maybe_await(self.handler(definition, tool_input, decision, context))


@dataclass(slots=True)
class CallbackElicitationService:
    handler: Any = None

    async def ask(
        self,
        question: str,
        options: Sequence[str] | None = None,
    ) -> Any:
        if self.handler is None:
            raise RuntimeError("No ask_user handler is configured")
        return await _maybe_await(self.handler(question, options))


@dataclass(slots=True)
class DefaultHostService:
    notification_provider: Callable[[], Sequence[RuntimeMessage]] | None = None
    notification_sink: Callable[[RuntimeMessage], Any] | None = None

    def current_notifications(self) -> tuple[RuntimeMessage, ...]:
        if self.notification_provider is None:
            return ()
        return tuple(self.notification_provider())

    async def emit_notification(self, message: RuntimeMessage) -> None:
        if self.notification_sink is None:
            return None
        await _maybe_await(self.notification_sink(message))


@dataclass(slots=True)
class CallbackToolCatalogService:
    refresh_callback: Any = None

    async def refresh_tools(self, context: Any) -> tuple[ToolDefinition, ...] | None:
        if self.refresh_callback is None:
            return None
        refreshed = await _maybe_await(self.refresh_callback(context))
        if refreshed is None:
            return None
        return tuple(refreshed)


@dataclass(slots=True)
class DefaultTaskService:
    manager: TaskManager = field(default_factory=TaskManager)


@dataclass(slots=True)
class DefaultTranscriptService:
    store: Any


@dataclass(slots=True)
class RuntimeServices:
    hooks: ContextContributionService = field(default_factory=NoopHookService)
    permissions: PermissionService = field(default_factory=CallbackPermissionService)
    elicitation: ElicitationService = field(default_factory=CallbackElicitationService)
    memory: ContextContributionService = field(default_factory=NoopMemoryService)
    compaction: ContextContributionService = field(default_factory=NoopCompactionService)
    host: HostRuntimeService = field(default_factory=DefaultHostService)
    tasks: DefaultTaskService = field(default_factory=DefaultTaskService)
    transcript: DefaultTranscriptService | None = None
    tool_catalog: ToolCatalogService = field(default_factory=CallbackToolCatalogService)
    context_assembler: Any = None
    agent_runner: Any = None
    skill_runner: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def task_manager(self) -> TaskManager:
        return self.tasks.manager

    @property
    def transcript_store(self) -> Any:
        if self.transcript is None:
            raise RuntimeError("Runtime transcript service is not configured")
        return self.transcript.store

    @property
    def permission_handler(self) -> Any:
        if isinstance(self.permissions, CallbackPermissionService) and self.permissions.handler is None:
            return None
        return self.permissions.authorize

    @property
    def ask_user_handler(self) -> Any:
        if isinstance(self.elicitation, CallbackElicitationService) and self.elicitation.handler is None:
            return None
        return self.elicitation.ask

    @property
    def tool_refresh_callback(self) -> Any:
        if isinstance(self.tool_catalog, CallbackToolCatalogService) and self.tool_catalog.refresh_callback is None:
            return None
        return self.tool_catalog.refresh_tools

    @property
    def notification_provider(self) -> Any:
        if isinstance(self.host, DefaultHostService) and self.host.notification_provider is None:
            return None
        return self.host.current_notifications

    @property
    def notification_sink(self) -> Any:
        if isinstance(self.host, DefaultHostService) and self.host.notification_sink is None:
            return None
        return self.host.emit_notification

    def bind_execution(
        self,
        *,
        agent_runner: Any = None,
        skill_runner: Any = None,
    ) -> None:
        self.agent_runner = agent_runner
        self.skill_runner = skill_runner

    def configure_compat(
        self,
        *,
        permission_handler: Any = None,
        ask_user_handler: Any = None,
        tool_refresh_callback: Any = None,
        notification_provider: Callable[[], Sequence[RuntimeMessage]] | None = None,
        notification_sink: Callable[[RuntimeMessage], Any] | None = None,
    ) -> None:
        self.permissions = CallbackPermissionService(permission_handler)
        self.elicitation = CallbackElicitationService(ask_user_handler)
        self.tool_catalog = CallbackToolCatalogService(tool_refresh_callback)
        self.host = DefaultHostService(
            notification_provider=notification_provider,
            notification_sink=notification_sink,
        )


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


__all__ = [
    "CallbackElicitationService",
    "CallbackPermissionService",
    "CallbackToolCatalogService",
    "ContextContributionService",
    "DefaultHostService",
    "DefaultTaskService",
    "DefaultTranscriptService",
    "ElicitationService",
    "HostRuntimeService",
    "NoopCompactionService",
    "NoopHookService",
    "NoopMemoryService",
    "PermissionService",
    "RuntimeServices",
    "ToolCatalogService",
]
