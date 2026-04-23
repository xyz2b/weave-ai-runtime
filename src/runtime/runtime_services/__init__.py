from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from ..compaction import CompactionManager, CompactionPolicy, CompactionResult, evaluate_context_pressure
from ..contracts import PromptContextEnvelope, RuntimeMessage, RuntimePrivateContext
from ..definitions import AgentDefinition, ToolDefinition
from ..elicitation import SharedElicitationService
from ..hooks import HookBus
from ..hosts.base import CallbackHostAdapter, HostRuntime, NullHostAdapter
from ..isolation import IsolationManager
from ..jobs import DefaultJobService
from ..permissions import PermissionEngine
from ..tasking import TaskManager
from ..task_lists import DefaultTaskListService


@dataclass(frozen=True, slots=True)
class SidecarContributionResult:
    prompt_fragments: tuple[str, ...] = ()
    private_updates: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "prompt_fragments", tuple(self.prompt_fragments))
        object.__setattr__(self, "private_updates", dict(self.private_updates))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))


class ContextContributionService(Protocol):
    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> Sequence[str] | SidecarContributionResult: ...


class CompactionService(Protocol):
    async def prepare_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> CompactionResult: ...

    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> Sequence[str]: ...


class PermissionService(Protocol):
    async def evaluate(
        self,
        request: Any,
        *,
        initial_decision: Any = None,
        hook_result: Any = None,
        runtime_context: Any = None,
    ) -> Any: ...

    async def authorize(
        self,
        definition: ToolDefinition,
        tool_input: dict[str, Any],
        decision: Any,
        context: Any,
    ) -> Any: ...


class ElicitationService(Protocol):
    async def request(self, request: Any, *, runtime_context: Any = None) -> Any: ...

    async def ask(
        self,
        question: str,
        options: Sequence[str] | None = None,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        runtime_context: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...


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
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> SidecarContributionResult:
        _ = session_id, turn_id, agent, cwd, messages, prompt_context, private_context, runtime_context
        return SidecarContributionResult()


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
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> SidecarContributionResult:
        _ = session_id, turn_id, agent, cwd, messages, prompt_context, private_context, runtime_context
        return SidecarContributionResult()


@dataclass(slots=True)
class NoopCompactionService:
    async def prepare_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> CompactionResult:
        _ = session_id, turn_id, agent, cwd, prompt_context, private_context, runtime_context
        policy = CompactionPolicy(enabled=False)
        return CompactionResult(
            messages=tuple(messages),
            policy=policy,
            pressure=evaluate_context_pressure(messages, policy),
        )

    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> SidecarContributionResult:
        _ = session_id, turn_id, agent, cwd, messages, prompt_context, private_context, runtime_context
        return SidecarContributionResult()


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
    manager: TaskManager | None = None


@dataclass(slots=True)
class DefaultTranscriptService:
    store: Any


@dataclass(slots=True)
class LiveSessionRegistry:
    _sessions: dict[str, Any] = field(default_factory=dict)

    def register(self, session: Any) -> None:
        session_id = getattr(getattr(session, "state", None), "session_id", None)
        if session_id is None:
            return
        self._sessions[str(session_id)] = session

    def unregister(self, session_id: str, *, session: Any | None = None) -> None:
        key = str(session_id)
        current = self._sessions.get(key)
        if session is not None and current is not session:
            return
        self._sessions.pop(key, None)

    def get(self, session_id: str) -> Any | None:
        return self._sessions.get(str(session_id))


@dataclass(slots=True)
class RuntimeServices:
    hooks: ContextContributionService = field(default_factory=NoopHookService)
    hook_bus: HookBus = field(default_factory=HookBus)
    permissions: PermissionService = field(default_factory=PermissionEngine)
    elicitation: ElicitationService = field(default_factory=SharedElicitationService)
    isolation: IsolationManager = field(default_factory=IsolationManager)
    memory: ContextContributionService = field(default_factory=NoopMemoryService)
    compaction: CompactionService | ContextContributionService = field(default_factory=CompactionManager)
    host: HostRuntime = field(default_factory=NullHostAdapter)
    jobs: DefaultJobService | None = None
    tasks: DefaultTaskService = field(default_factory=DefaultTaskService)
    task_lists: DefaultTaskListService = field(default_factory=DefaultTaskListService)
    task_discipline: ContextContributionService = field(default_factory=NoopHookService)
    sessions: LiveSessionRegistry = field(default_factory=LiveSessionRegistry)
    transcript: DefaultTranscriptService | None = None
    tool_catalog: ToolCatalogService = field(default_factory=CallbackToolCatalogService)
    context_assembler: Any = None
    agent_runner: Any = None
    skill_runner: Any = None
    teammates: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        manager = self.tasks.manager
        if manager is not None:
            self.jobs = manager.job_service if self.jobs is None else manager.job_service
        elif self.jobs is None:
            self.jobs = DefaultJobService()
        if self.jobs is None:  # pragma: no cover - defensive boundary
            self.jobs = DefaultJobService()
        if self.tasks.manager is None:
            self.tasks = DefaultTaskService(TaskManager(job_service=self.jobs))
        self.jobs.bind_runtime(
            runtime_id=str(self.metadata.get("runtime_id") or "default"),
            services=self,
        )

    @property
    def task_manager(self) -> TaskManager:
        if self.tasks.manager is None:  # pragma: no cover - defensive boundary
            self.tasks = DefaultTaskService(TaskManager(job_service=self.job_service))
        return self.tasks.manager

    @property
    def job_service(self) -> DefaultJobService:
        if self.jobs is None:  # pragma: no cover - defensive boundary
            self.jobs = DefaultJobService()
            self.jobs.bind_runtime(
                runtime_id=str(self.metadata.get("runtime_id") or "default"),
                services=self,
            )
        return self.jobs

    @property
    def task_list_service(self) -> DefaultTaskListService:
        return self.task_lists

    @property
    def session_registry(self) -> LiveSessionRegistry:
        return self.sessions

    @property
    def transcript_store(self) -> Any:
        if self.transcript is None:
            raise RuntimeError("Runtime transcript service is not configured")
        return self.transcript.store

    @property
    def permission_handler(self) -> Any:
        return self.permissions.authorize

    @property
    def ask_user_handler(self) -> Any:
        return self.elicitation.ask

    @property
    def tool_refresh_callback(self) -> Any:
        if isinstance(self.tool_catalog, CallbackToolCatalogService) and self.tool_catalog.refresh_callback is None:
            return None
        return self.tool_catalog.refresh_tools

    @property
    def notification_provider(self) -> Any:
        return self.host.current_notifications

    @property
    def notification_sink(self) -> Any:
        return self.host.emit_notification

    def bind_execution(
        self,
        *,
        agent_runner: Any = None,
        skill_runner: Any = None,
    ) -> None:
        self.agent_runner = agent_runner
        self.skill_runner = skill_runner

    def bind_host(self, host: HostRuntime) -> None:
        if self.teammates is not None and hasattr(self.teammates, "bind_host"):
            self.host = self.teammates.bind_host(host)
            return
        self.host = host

    def bind_teammates(self, teammates: Any) -> None:
        self.teammates = teammates
        if self.host is not None and hasattr(teammates, "bind_host"):
            self.host = teammates.bind_host(self.host)

    def configure_compat(
        self,
        *,
        permission_handler: Any = None,
        ask_user_handler: Any = None,
        tool_refresh_callback: Any = None,
        notification_provider: Callable[[], Sequence[RuntimeMessage]] | None = None,
        notification_sink: Callable[[RuntimeMessage], Any] | None = None,
        turn_event_sink: Callable[[str, Any], Any] | None = None,
    ) -> None:
        if tool_refresh_callback is not None or isinstance(self.tool_catalog, CallbackToolCatalogService):
            self.tool_catalog = CallbackToolCatalogService(tool_refresh_callback)
        if any(
            value is not None
            for value in (
                permission_handler,
                ask_user_handler,
                notification_provider,
                notification_sink,
                turn_event_sink,
            )
        ):
            self.host = CallbackHostAdapter(
                permission_handler=permission_handler,
                ask_user_handler=ask_user_handler,
                notification_provider=notification_provider,
                notification_sink=notification_sink,
                turn_event_sink=turn_event_sink,
            )


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


__all__ = [
    "CallbackToolCatalogService",
    "CompactionService",
    "ContextContributionService",
    "DefaultTaskService",
    "DefaultTranscriptService",
    "ElicitationService",
    "NoopCompactionService",
    "NoopHookService",
    "NoopMemoryService",
    "PermissionService",
    "RuntimeServices",
    "ToolCatalogService",
]
