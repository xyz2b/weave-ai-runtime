from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from uuid import uuid4

from .contracts import (
    ExecutionResult,
    ExecutionStatus,
    MessageRole,
    RuntimeMessage,
    RuntimePrivateContext,
    RuntimePrivateContextView,
    private_context_from_legacy_runtime_context,
)
from .definitions import (
    AgentDefinition,
    DefinitionSource,
    InterruptBehavior,
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    SkillDefinition,
    ToolCallStatus,
    ToolDefinition,
    ValidationOutcome,
)
from .elicitation import ElicitationRequest
from .hooks import NotificationPayload, PostToolUseFailurePayload, PostToolUsePayload, PreToolUsePayload
from .permissions import PermissionContext
from .registries import ToolRegistry
from .runtime_services import RuntimeServices
from .tasking import TaskManager
from .tool_lifecycle import (
    AgentCatalog,
    AppState,
    CapabilityRefreshHandle,
    CapabilityRefreshRequested,
    CatalogEntryView,
    FileState,
    MemoryAccess,
    NotificationEmitted,
    NotificationsHandle,
    PermissionContextView,
    PermissionRuleView,
    ProgressHandle,
    QueryAbortHandle,
    QueryContext,
    ResolvedToolCall,
    SessionStateHandle,
    SkillCatalog,
    ToolCallIdentity,
    ToolExecutionClass,
    ToolExecutionContext,
    ToolCapabilityContext,
    ToolCatalog,
    TurnStateHandle,
)


@dataclass(frozen=True, slots=True)
class ToolProgressUpdate:
    tool_name: str
    message: str
    progress: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolProgressSink(Protocol):
    async def emit(self, update: ToolProgressUpdate) -> None: ...


class PermissionHandler(Protocol):
    async def __call__(
        self,
        definition: ToolDefinition,
        tool_input: dict[str, Any],
        decision: PermissionDecision,
        context: "ToolContext",
    ) -> PermissionDecision: ...


class AskUserHandler(Protocol):
    async def __call__(
        self,
        question: str,
        options: Sequence[str] | None = None,
    ) -> Any: ...


class AgentRunner(Protocol):
    async def __call__(
        self,
        agent_name: str,
        prompt: str,
        context: "ToolContext",
        *,
        background: bool = False,
        spawn_mode: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        model_route: str | None = None,
        reason: str | None = None,
        permission_mode: str | None = None,
        isolation: str | None = None,
        max_turns: int | None = None,
    ) -> Any: ...


class SkillRunner(Protocol):
    async def __call__(
        self,
        skill_name: str,
        arguments: Sequence[str],
        context: "ToolContext",
    ) -> Any: ...


class NotificationSink(Protocol):
    async def __call__(self, message: RuntimeMessage) -> None: ...


class ToolRefreshCallback(Protocol):
    async def __call__(
        self,
        context: "ToolContext",
    ) -> Sequence[ToolDefinition] | None: ...


@dataclass(slots=True)
class SessionScope:
    session_id: str
    agent_name: str
    cwd: Path
    private_context: RuntimePrivateContext = field(default_factory=RuntimePrivateContext)
    session_state: SessionStateHandle = field(default_factory=SessionStateHandle)
    memory_access: MemoryAccess = field(default_factory=MemoryAccess)
    read_cache: Any = None
    task_manager: TaskManager | None = None


@dataclass(slots=True)
class TurnScope:
    session_id: str
    turn_id: str
    agent_name: str
    cwd: Path
    query: QueryContext
    private_context: RuntimePrivateContext = field(default_factory=RuntimePrivateContext)
    tool_pool: tuple[ToolDefinition, ...] = ()
    skill_pool: tuple[SkillDefinition, ...] = ()
    turn_state: TurnStateHandle = field(default_factory=TurnStateHandle)
    file_state: FileState = field(default_factory=FileState)
    progress: ProgressHandle | None = None
    notifications: NotificationsHandle | None = None
    refresh_capabilities: CapabilityRefreshHandle | None = None
    abort_handle: QueryAbortHandle | None = None
    tool_catalog: ToolCatalog | None = None
    agent_catalog: AgentCatalog | None = None
    skill_catalog: SkillCatalog | None = None
    permission_context_view: PermissionContextView | None = None


@dataclass(slots=True)
class InternalToolContext:
    session: SessionScope
    turn: TurnScope
    tool_registry: ToolRegistry | None = None
    agent_registry: Any = None
    skill_registry: Any = None
    progress_sink: ToolProgressSink | None = None
    permission_handler: PermissionHandler | None = None
    ask_user_handler: AskUserHandler | None = None
    agent_runner: AgentRunner | None = None
    skill_runner: SkillRunner | None = None
    task_manager: TaskManager | None = None
    notification_sink: NotificationSink | None = None
    tool_refresh_callback: ToolRefreshCallback | None = None
    runtime_services: RuntimeServices | None = None
    permission_context: PermissionContext | None = None
    pending_hook_effect: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_classifications: dict[str, ToolExecutionClass] = field(default_factory=dict)


@dataclass(slots=True)
class ToolContext:
    session_id: str
    turn_id: str
    agent_name: str
    cwd: Path
    tool_registry: ToolRegistry | None = None
    agent_registry: Any = None
    skill_registry: Any = None
    messages: tuple[RuntimeMessage, ...] = ()
    tool_pool: tuple[ToolDefinition, ...] = ()
    skill_pool: tuple[SkillDefinition, ...] = ()
    progress_sink: ToolProgressSink | None = None
    permission_handler: PermissionHandler | None = None
    ask_user_handler: AskUserHandler | None = None
    agent_runner: AgentRunner | None = None
    skill_runner: SkillRunner | None = None
    task_manager: TaskManager | None = None
    abort_signal: Any = None
    notifications: tuple[RuntimeMessage, ...] = ()
    notification_sink: NotificationSink | None = None
    tool_refresh_callback: ToolRefreshCallback | None = None
    runtime_services: RuntimeServices | None = None
    permission_context: PermissionContext | None = None
    private_context: RuntimePrivateContext = field(default_factory=RuntimePrivateContext)
    pending_hook_effect: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    query_context: QueryContext | None = None
    session_state: SessionStateHandle | None = None
    turn_state: TurnStateHandle | None = None
    app_state: AppState | None = None
    file_state: FileState | None = None
    progress: ProgressHandle | None = None
    notifications_handle: NotificationsHandle | None = None
    refresh_capabilities: CapabilityRefreshHandle | None = None
    memory_access: MemoryAccess | None = None
    tool_catalog: ToolCatalog | None = None
    agent_catalog_view: AgentCatalog | None = None
    skill_catalog_view: SkillCatalog | None = None
    permission_context_view: PermissionContextView | None = None
    private_context_view: RuntimePrivateContextView | None = None
    session_scope: SessionScope | None = None
    turn_scope: TurnScope | None = None
    internal_context: InternalToolContext | None = None
    tool_execution_classifications: dict[str, ToolExecutionClass] = field(default_factory=dict)
    capability_context: ToolCapabilityContext | None = None
    tool_use_id: str | None = None
    replay_index: int | None = None
    canonical_tool_name: str | None = None
    selected_executor_tier: str = "none"
    model_capabilities: Any = None
    progress_callback: Any = None
    notification_callback: Any = None
    refresh_callback: Any = None
    call_updates: list[Any] = field(default_factory=list)
    _interrupt_reason: str | None = None

    def __post_init__(self) -> None:
        private_context = self.private_context
        if private_context == RuntimePrivateContext():
            private_context = private_context_from_legacy_runtime_context(self.metadata)
        if private_context.permission_context is None and self.permission_context is not None:
            private_context = replace(private_context, permission_context=self.permission_context)
        self.private_context = private_context
        if self.permission_context is None and self.private_context.permission_context is not None:
            self.permission_context = self.private_context.permission_context
        if not self.metadata:
            self.metadata = self.private_context.compat_metadata()
        if self.session_scope is not None and self.session_state is None:
            self.session_state = self.session_scope.session_state
        if self.session_state is None:
            self.session_state = SessionStateHandle()
        if self.turn_state is None and self.app_state is not None:
            self.turn_state = TurnStateHandle(self.app_state._state)
        if self.turn_state is None:
            self.turn_state = TurnStateHandle()
        if self.app_state is None:
            self.app_state = AppState(self.turn_state._state)
        elif self.turn_state is None:
            self.turn_state = TurnStateHandle(self.app_state._state)
        if self.file_state is None:
            self.file_state = FileState(guarded_roots=_guarded_memory_roots(self))
        if self.session_scope is not None and self.memory_access is None:
            self.memory_access = self.session_scope.memory_access
        if self.memory_access is None:
            self.memory_access = MemoryAccess()
        if self.permission_context_view is None:
            self.permission_context_view = _coerce_permission_context_view(self.permission_context)
        if self.private_context_view is None:
            self.private_context_view = self.private_context.readonly_view()
        if self.tool_catalog is None:
            self.tool_catalog = _tool_catalog_view(self.tool_pool)
        if self.agent_catalog_view is None:
            self.agent_catalog_view = _agent_catalog_view(self.agent_registry)
        if self.skill_catalog_view is None:
            self.skill_catalog_view = _skill_catalog_view(self.skill_pool)
        if self.query_context is None:
            self.query_context = QueryContext(
                session_id=self.session_id,
                turn_id=self.turn_id,
                agent_name=self.agent_name,
                cwd=self.cwd,
                messages=tuple(self.messages),
                selected_executor_tier=self.selected_executor_tier,
                model_capabilities=self.model_capabilities,
                abort_handle=QueryAbortHandle(self.abort_signal),
                continuation_metadata=dict(self.metadata),
            )
        if self.progress is None:
            self.progress = ProgressHandle(emitter=self._emit_progress_event)
        if self.notifications_handle is None:
            self.notifications_handle = NotificationsHandle(emitter=self._record_notification)
        if self.refresh_capabilities is None:
            self.refresh_capabilities = CapabilityRefreshHandle(
                emitter=self._record_refresh,
                supported_scopes=_supported_refresh_scopes(self),
            )
        if self.session_scope is None:
            self.session_scope = SessionScope(
                session_id=self.session_id,
                agent_name=self.agent_name,
                cwd=self.cwd,
                private_context=self.private_context,
                session_state=self.session_state,
                memory_access=self.memory_access,
                read_cache=self.metadata.get("session_read_cache"),
                task_manager=self.task_manager,
            )
        else:
            self.session_scope.agent_name = self.agent_name
            self.session_scope.cwd = self.cwd
            self.session_scope.task_manager = self.task_manager
            self.memory_access = self.session_scope.memory_access
        if self.turn_scope is None:
            self.turn_scope = TurnScope(
                session_id=self.session_id,
                turn_id=self.turn_id,
                agent_name=self.agent_name,
                cwd=self.cwd,
                query=self.query_context,
                private_context=self.private_context,
                tool_pool=tuple(self.tool_pool),
                skill_pool=tuple(self.skill_pool),
                turn_state=self.turn_state,
                file_state=self.file_state,
                progress=self.progress,
                notifications=self.notifications_handle,
                refresh_capabilities=self.refresh_capabilities,
                abort_handle=self.query_context.abort_handle if self.query_context is not None else None,
                tool_catalog=self.tool_catalog,
                agent_catalog=self.agent_catalog_view,
                skill_catalog=self.skill_catalog_view,
                permission_context_view=self.permission_context_view,
            )
        else:
            self.turn_scope.query = self.query_context
            self.turn_scope.tool_pool = tuple(self.tool_pool)
            self.turn_scope.skill_pool = tuple(self.skill_pool)
            self.turn_scope.file_state = self.file_state
            self.turn_scope.turn_state = self.turn_state
            self.turn_scope.progress = self.progress
            self.turn_scope.notifications = self.notifications_handle
            self.turn_scope.refresh_capabilities = self.refresh_capabilities
            self.turn_scope.abort_handle = (
                self.query_context.abort_handle if self.query_context is not None else None
            )
            self.turn_scope.tool_catalog = self.tool_catalog
            self.turn_scope.agent_catalog = self.agent_catalog_view
            self.turn_scope.skill_catalog = self.skill_catalog_view
            self.turn_scope.permission_context_view = self.permission_context_view
        if not self.tool_execution_classifications:
            self.tool_execution_classifications = _build_tool_execution_classifications(
                self.tool_pool or (
                    tuple(self.tool_registry.definitions())
                    if self.tool_registry is not None and hasattr(self.tool_registry, "definitions")
                    else ()
                )
            )
        if self.internal_context is None:
            self.internal_context = InternalToolContext(
                session=self.session_scope,
                turn=self.turn_scope,
                tool_registry=self.tool_registry,
                agent_registry=self.agent_registry,
                skill_registry=self.skill_registry,
                progress_sink=self.progress_sink,
                permission_handler=self.permission_handler,
                ask_user_handler=self.ask_user_handler,
                agent_runner=self.agent_runner,
                skill_runner=self.skill_runner,
                task_manager=self.task_manager,
                notification_sink=self.notification_sink,
                tool_refresh_callback=self.tool_refresh_callback,
                runtime_services=self.runtime_services,
                permission_context=self.permission_context,
                pending_hook_effect=self.pending_hook_effect,
                metadata=dict(self.metadata),
                execution_classifications=dict(self.tool_execution_classifications),
            )
        elif not self.tool_execution_classifications and self.internal_context.execution_classifications:
            self.tool_execution_classifications = dict(self.internal_context.execution_classifications)

    async def emit_progress(
        self,
        tool_name: str,
        message: str,
        *,
        progress: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.progress is not None:
            self.progress.update(tool_name, message, progress)
        if self.progress_sink is None:
            return
        await self.progress_sink.emit(
            ToolProgressUpdate(
                tool_name=tool_name,
                message=message,
                progress=progress,
                metadata=metadata or {},
            )
        )

    def request_interrupt(self, reason: str = "interrupt") -> None:
        self._interrupt_reason = reason
        abort_signal = self.abort_signal
        if abort_signal is not None and hasattr(abort_signal, "abort"):
            abort_signal.abort(reason)

    def interrupted(self) -> bool:
        return self._interrupt_reason is not None

    @property
    def interrupt_reason(self) -> str | None:
        return self._interrupt_reason

    async def emit_notification(self, message: RuntimeMessage) -> None:
        if self.notifications_handle is not None and not message.metadata.get("skip_runtime_notification"):
            self.notifications_handle.emit(
                message.text,
                str(message.metadata.get("level", "info")),
            )
        self.notifications = (*self.notifications, message)
        if (
            self.runtime_services is not None
            and not message.metadata.get("skip_hook_dispatch")
            and self.runtime_services.hook_bus is not None
        ):
            hook_result = await maybe_await(
                self.runtime_services.hook_bus.dispatch(
                    self.session_id,
                    NotificationPayload(
                        session_id=self.session_id,
                        message=message.text,
                        level=str(message.metadata.get("level", "info")),
                    ),
                )
            )
            await _emit_hook_notifications(self, hook_result.notifications)
        if self.notification_sink is not None:
            await maybe_await(self.notification_sink(message))
            return
        if self.runtime_services is not None and self.runtime_services.notification_sink is not None:
            await maybe_await(self.runtime_services.notification_sink(message))

    async def refresh_tools(self) -> tuple[ToolDefinition, ...]:
        if self.refresh_capabilities is not None:
            self.refresh_capabilities.request("tool_pool", "compat_refresh_tools")
        if self.runtime_services is not None and self.runtime_services.tool_refresh_callback is not None:
            refreshed = await maybe_await(self.runtime_services.tool_refresh_callback(self))
            if refreshed is not None:
                self.tool_pool = tuple(refreshed)
                self.tool_catalog = _tool_catalog_view(self.tool_pool)
                self.tool_execution_classifications = _build_tool_execution_classifications(
                    self.tool_pool
                )
                if self.turn_scope is not None:
                    self.turn_scope.tool_pool = self.tool_pool
                    self.turn_scope.tool_catalog = self.tool_catalog
                if self.internal_context is not None:
                    self.internal_context.execution_classifications = dict(
                        self.tool_execution_classifications
                    )
            return tuple(self.tool_pool)
        if self.tool_refresh_callback is None:
            return tuple(self.tool_pool)
        refreshed = await maybe_await(self.tool_refresh_callback(self))
        if refreshed is not None:
            self.tool_pool = tuple(refreshed)
            self.tool_catalog = _tool_catalog_view(self.tool_pool)
            self.tool_execution_classifications = _build_tool_execution_classifications(self.tool_pool)
            if self.turn_scope is not None:
                self.turn_scope.tool_pool = self.tool_pool
                self.turn_scope.tool_catalog = self.tool_catalog
            if self.internal_context is not None:
                self.internal_context.execution_classifications = dict(
                    self.tool_execution_classifications
                )
        return tuple(self.tool_pool)

    def for_call(
        self,
        *,
        tool_use_id: str,
        replay_index: int,
        assistant_message_id: str,
        canonical_tool_name: str | None,
        executor_tier: str,
        model_capabilities: Any,
        execution_class: ToolExecutionClass = ToolExecutionClass.LEGACY_COMPAT,
    ) -> "ToolContext":
        call_context = replace(
            self,
            tool_use_id=tool_use_id,
            replay_index=replay_index,
            canonical_tool_name=canonical_tool_name,
            selected_executor_tier=executor_tier,
            model_capabilities=model_capabilities,
            query_context=QueryContext(
                session_id=self.session_id,
                turn_id=self.turn_id,
                agent_name=self.agent_name,
                cwd=self.cwd,
                messages=tuple(self.messages),
                selected_executor_tier=executor_tier,
                model_capabilities=model_capabilities,
                abort_handle=QueryAbortHandle(self.abort_signal),
                continuation_metadata=dict(self.metadata),
            ),
            progress=None,
            notifications_handle=None,
            refresh_capabilities=None,
            turn_scope=None,
            internal_context=None,
            capability_context=None,
            call_updates=[],
        )
        call_context.progress = ProgressHandle(emitter=call_context._emit_progress_event)
        call_context.notifications_handle = NotificationsHandle(
            emitter=call_context._record_notification
        )
        call_context.refresh_capabilities = CapabilityRefreshHandle(
            emitter=call_context._record_refresh,
            supported_scopes=_supported_refresh_scopes(call_context),
        )
        call_context.capability_context = call_context._build_execution_context(
            tool_use_id=tool_use_id,
            replay_index=replay_index,
            assistant_message_id=assistant_message_id,
            canonical_tool_name=canonical_tool_name,
            executor_tier=executor_tier,
            execution_class=execution_class,
        )
        return call_context

    def public_execution_context_for_call(
        self,
        *,
        tool_use_id: str,
        replay_index: int,
        assistant_message_id: str,
        canonical_tool_name: str | None,
        executor_tier: str,
        model_capabilities: Any,
        execution_class: ToolExecutionClass = ToolExecutionClass.PUBLIC,
    ) -> tuple[ToolExecutionContext, "ToolContext"]:
        compat_context = self.for_call(
            tool_use_id=tool_use_id,
            replay_index=replay_index,
            assistant_message_id=assistant_message_id,
            canonical_tool_name=canonical_tool_name,
            executor_tier=executor_tier,
            model_capabilities=model_capabilities,
            execution_class=execution_class,
        )
        execution_context = compat_context._build_execution_context(
            tool_use_id=tool_use_id,
            replay_index=replay_index,
            assistant_message_id=assistant_message_id,
            canonical_tool_name=canonical_tool_name,
            executor_tier=executor_tier,
            execution_class=execution_class,
        )
        compat_context.capability_context = execution_context
        return execution_context, compat_context

    def _build_execution_context(
        self,
        *,
        tool_use_id: str,
        replay_index: int,
        assistant_message_id: str,
        canonical_tool_name: str | None,
        executor_tier: str,
        execution_class: ToolExecutionClass,
    ) -> ToolExecutionContext:
        private_context_view = self.private_context_view or self.private_context.readonly_view()
        query = self.query_context or QueryContext(
            session_id=self.session_id,
            turn_id=self.turn_id,
            agent_name=self.agent_name,
            cwd=self.cwd,
            messages=tuple(self.messages),
            selected_executor_tier=executor_tier,
            model_capabilities=self.model_capabilities,
            abort_handle=QueryAbortHandle(self.abort_signal),
            continuation_metadata=dict(self.metadata),
        )
        if execution_class == ToolExecutionClass.PUBLIC:
            query = replace(
                query,
                continuation_metadata=dict(private_context_view.extensions),
            )
        return ToolExecutionContext(
            call=ToolCallIdentity(
                tool_use_id=tool_use_id,
                canonical_tool_name=canonical_tool_name,
                assistant_message_id=assistant_message_id,
                replay_index=replay_index,
                executor_tier=executor_tier,
            ),
            query=query,
            tool_catalog=self.tool_catalog or _tool_catalog_view(self.tool_pool),
            agent_catalog=self.agent_catalog_view or _agent_catalog_view(self.agent_registry),
            skill_catalog=self.skill_catalog_view or _skill_catalog_view(self.skill_pool),
            permission_context=self.permission_context_view
            or _coerce_permission_context_view(self.permission_context),
            session_state=self.session_state,
            turn_state=self.turn_state,
            file_state=self.file_state,
            progress=self.progress,
            notifications=self.notifications_handle,
            refresh_capabilities=self.refresh_capabilities,
            memory_access=self.memory_access,
            abort_handle=self.query_context.abort_handle if self.query_context is not None else None,
            private_context_view=private_context_view,
            execution_class=execution_class,
        )

    def _emit_progress_event(
        self,
        progress_id: str,
        message: str,
        percent: float | None,
    ) -> None:
        if self.progress_callback is not None:
            self.progress_callback(progress_id, message, percent, self)

    def _record_notification(self, message: str, level: str) -> None:
        self.call_updates.append(NotificationEmitted(level=level, message=message))
        if self.notification_callback is not None:
            self.notification_callback(message, level, self)

    def _record_refresh(self, scope: str, reason: str) -> None:
        self.call_updates.append(CapabilityRefreshRequested(scope=scope, reason=reason))
        if self.refresh_callback is not None:
            self.refresh_callback(scope, reason, self)


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    tool_name: str
    tool_input: dict[str, Any]


@dataclass(slots=True)
class ToolCallResult:
    call_id: str
    tool_name: str
    status: ToolCallStatus
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_execution_result(self) -> ExecutionResult[Any]:
        if self.status == ToolCallStatus.SUCCESS:
            return ExecutionResult(status=ExecutionStatus.SUCCESS, value=self.output, metadata=self.metadata)
        if self.status == ToolCallStatus.CANCELLED:
            return ExecutionResult(status=ExecutionStatus.CANCELLED, error=self.error, metadata=self.metadata)
        if self.status == ToolCallStatus.DENIED:
            return ExecutionResult(status=ExecutionStatus.FAILED, error=self.error, metadata=self.metadata)
        return ExecutionResult(status=ExecutionStatus.FAILED, error=self.error, metadata=self.metadata)


@dataclass(frozen=True, slots=True)
class ExecutedToolCall:
    result: ToolCallResult
    context_updates: tuple[Any, ...] = ()
    result_summary: Any = None


@dataclass(frozen=True, slots=True)
class PreparedToolExecution:
    execution_class: ToolExecutionClass
    api_context: ToolContext | ToolExecutionContext
    call_context: ToolContext


class ToolScheduler:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._running: dict[str, tuple[asyncio.Task[ToolCallResult], ToolDefinition]] = {}

    async def run(
        self,
        calls: Sequence[ToolCall],
        context: ToolContext,
    ) -> tuple[ToolCallResult, ...]:
        results: list[ToolCallResult] = []
        for concurrent, batch in self.partition_calls(calls):
            if concurrent:
                batch_results = await self._run_concurrent_batch(batch, context)
                results.extend(batch_results)
            else:
                for call in batch:
                    results.append(await self._run_single(call, context))
        return tuple(results)

    def interrupt(self, reason: str = "interrupt") -> None:
        for task, definition in self._running.values():
            if definition.traits.interrupt_behavior == InterruptBehavior.CANCEL:
                task.cancel()

    def partition_calls(self, calls: Sequence[ToolCall]) -> list[tuple[bool, list[ToolCall]]]:
        batches: list[tuple[bool, list[ToolCall]]] = []
        for call in calls:
            definition = self._registry.get(call.tool_name)
            concurrent = bool(
                definition is not None
                and definition.traits.read_only
                and definition.traits.concurrency_safe
            )
            if concurrent and batches and batches[-1][0]:
                batches[-1][1].append(call)
            else:
                batches.append((concurrent, [call]))
        return batches

    async def _run_concurrent_batch(
        self,
        calls: Sequence[ToolCall],
        context: ToolContext,
    ) -> tuple[ToolCallResult, ...]:
        tasks = [asyncio.create_task(self._run_single(call, context)) for call in calls]
        for call, task in zip(calls, tasks):
            definition = self._registry.get(call.tool_name)
            if definition is not None:
                self._running[call.call_id] = (task, definition)
        try:
            return tuple(await asyncio.gather(*tasks))
        finally:
            for call in calls:
                self._running.pop(call.call_id, None)

    async def _run_single(self, call: ToolCall, context: ToolContext) -> ToolCallResult:
        definition = self._registry.get(call.tool_name)
        if definition is None:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.ERROR,
                error=f"Unknown tool: {call.tool_name}",
            )
        if context.tool_pool and not _tool_available_in_pool(call.tool_name, context.tool_pool):
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.DENIED,
                error=f"Tool '{call.tool_name}' is not available in the current execution policy",
                metadata={"available_tools": [tool.name for tool in context.tool_pool]},
            )
        try:
            task = asyncio.current_task()
            if task is not None:
                self._running[call.call_id] = (task, definition)
            return await execute_tool_call(definition, call, context)
        except asyncio.CancelledError:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.CANCELLED,
                error="Tool execution cancelled",
            )
        finally:
            self._running.pop(call.call_id, None)


async def execute_tool_call(
    definition: ToolDefinition,
    call: ToolCall,
    context: ToolContext,
) -> ToolCallResult:
    prepared = _prepare_tool_execution(
        definition,
        context,
        tool_use_id=call.call_id,
        replay_index=0,
        assistant_message_id=call.call_id,
        canonical_tool_name=definition.name,
        executor_tier=context.selected_executor_tier or "direct",
        model_capabilities=context.model_capabilities,
    )
    tool_context = prepared.api_context
    call_context = prepared.call_context
    try:
        if call_context.interrupted() and definition.traits.interrupt_behavior == InterruptBehavior.CANCEL:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=definition.name,
                status=ToolCallStatus.CANCELLED,
                error=call_context.interrupt_reason or "Tool execution interrupted",
            )

        normalized_input = validate_input_schema(definition.input_schema, call.tool_input)

        if definition.validate_input is not None:
            validation = await maybe_await(definition.validate_input(normalized_input, tool_context))
            if not validation.valid:
                return ToolCallResult(
                    call_id=call.call_id,
                    tool_name=definition.name,
                    status=ToolCallStatus.ERROR,
                    error=validation.message or "Tool input validation failed",
                    metadata=validation.details,
                )
            if validation.updated_input is not None:
                normalized_input = validation.updated_input

        pre_tool_hook = await _dispatch_hook(
            call_context,
            PreToolUsePayload(
                session_id=call_context.session_id,
                tool_name=definition.name,
                tool_input=dict(normalized_input),
                turn_id=call_context.turn_id,
            ),
        )
        if pre_tool_hook.updated_input is not None:
            normalized_input = pre_tool_hook.updated_input
        call_context.pending_hook_effect = pre_tool_hook
        if not pre_tool_hook.continue_execution:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=definition.name,
                status=ToolCallStatus.DENIED,
                error="Tool use blocked by runtime hook",
                metadata={"matched_hooks": list(pre_tool_hook.matched_owners)},
            )

        permission_decision = PermissionDecision(PermissionBehavior.ALLOW)
        if definition.check_permissions is not None:
            permission_decision = await maybe_await(
                definition.check_permissions(normalized_input, tool_context)
            )
        normalized_input = permission_decision.updated_input or normalized_input

        if call_context.runtime_services is not None:
            permission_decision = await call_context.runtime_services.permissions.authorize(
                definition,
                normalized_input,
                permission_decision,
                call_context,
            )
            normalized_input = permission_decision.updated_input or normalized_input
        elif permission_decision.behavior == PermissionBehavior.ASK:
            if call_context.permission_handler is None:
                return ToolCallResult(
                    call_id=call.call_id,
                    tool_name=definition.name,
                    status=ToolCallStatus.DENIED,
                    error=permission_decision.message or "Permission required",
                    metadata=permission_decision.details,
                )
            permission_decision = await call_context.permission_handler(
                definition,
                normalized_input,
                permission_decision,
                call_context,
            )
            normalized_input = permission_decision.updated_input or normalized_input

        if permission_decision.behavior != PermissionBehavior.ALLOW:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=definition.name,
                status=ToolCallStatus.DENIED,
                error=permission_decision.message or "Tool use denied",
                metadata=permission_decision.details,
            )

        if definition.execute is None:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=definition.name,
                status=ToolCallStatus.ERROR,
                error=f"Tool '{definition.name}' has no execution handler",
            )

        raw_output = await maybe_await(definition.execute(normalized_input, tool_context))
        post_tool_hook = await _dispatch_hook(
            call_context,
            PostToolUsePayload(
                session_id=call_context.session_id,
                tool_name=definition.name,
                tool_input=dict(normalized_input),
                tool_result=raw_output,
                turn_id=call_context.turn_id,
            ),
        )
        if not post_tool_hook.continue_execution:
            return ToolCallResult(
                call_id=call.call_id,
                tool_name=definition.name,
                status=ToolCallStatus.DENIED,
                error="Tool result blocked by runtime hook",
                metadata={"matched_hooks": list(post_tool_hook.matched_owners)},
            )
        return map_tool_output(definition.name, call.call_id, raw_output)
    except Exception as exc:  # pragma: no cover - defensive boundary
        await _dispatch_hook(
            call_context,
            PostToolUseFailurePayload(
                session_id=call_context.session_id,
                tool_name=definition.name,
                tool_input=dict(call.tool_input),
                error_message=str(exc),
                turn_id=call_context.turn_id,
            ),
        )
        return ToolCallResult(
            call_id=call.call_id,
            tool_name=definition.name,
            status=ToolCallStatus.ERROR,
            error=str(exc),
        )
    finally:
        call_context.pending_hook_effect = None


async def execute_resolved_tool_call(
    resolved_call: ResolvedToolCall,
    context: ToolContext,
) -> ExecutedToolCall:
    definition = resolved_call.tool_definition_ref
    if definition is None:
        return ExecutedToolCall(
            result=ToolCallResult(
                call_id=resolved_call.envelope.tool_use_id,
                tool_name=resolved_call.canonical_tool_name or resolved_call.envelope.raw_tool_name,
                status=ToolCallStatus.ERROR,
                error="Resolved tool call is missing a definition",
            )
        )
    prepared = _prepare_tool_execution(
        definition,
        context,
        tool_use_id=resolved_call.envelope.tool_use_id,
        replay_index=resolved_call.replay_index,
        assistant_message_id=resolved_call.envelope.assistant_message_id,
        canonical_tool_name=resolved_call.canonical_tool_name,
        executor_tier=resolved_call.capability_context.executor_tier,
        model_capabilities=resolved_call.capability_context.query_context.model_capabilities,
        execution_class=resolved_call.execution_class,
    )
    tool_context = prepared.api_context
    call_context = prepared.call_context
    try:
        interrupt_behavior = (
            resolved_call.resolved_semantics.interrupt_behavior
            if resolved_call.resolved_semantics is not None
            else definition.traits.interrupt_behavior
        )
        if call_context.interrupted() and interrupt_behavior == InterruptBehavior.CANCEL:
            return ExecutedToolCall(
                result=ToolCallResult(
                    call_id=resolved_call.envelope.tool_use_id,
                    tool_name=definition.name,
                    status=ToolCallStatus.CANCELLED,
                    error=call_context.interrupt_reason or "Tool execution interrupted",
                )
            )
        if definition.execute is None:
            return ExecutedToolCall(
                result=ToolCallResult(
                    call_id=resolved_call.envelope.tool_use_id,
                    tool_name=definition.name,
                    status=ToolCallStatus.ERROR,
                    error=f"Tool '{definition.name}' has no execution handler",
                )
            )
        execution_input = dict(resolved_call.execution_input or {})
        raw_output = await maybe_await(definition.execute(execution_input, tool_context))
        post_tool_hook = await _dispatch_hook(
            call_context,
            PostToolUsePayload(
                session_id=call_context.session_id,
                tool_name=definition.name,
                tool_input=dict(execution_input),
                tool_result=raw_output,
                turn_id=call_context.turn_id,
            ),
        )
        if not post_tool_hook.continue_execution:
            return ExecutedToolCall(
                result=ToolCallResult(
                    call_id=resolved_call.envelope.tool_use_id,
                    tool_name=definition.name,
                    status=ToolCallStatus.DENIED,
                    error="Tool result blocked by runtime hook",
                    metadata={"matched_hooks": list(post_tool_hook.matched_owners)},
                ),
                context_updates=tuple(call_context.call_updates),
            )
        return ExecutedToolCall(
            result=map_tool_output(definition.name, resolved_call.envelope.tool_use_id, raw_output),
            context_updates=tuple(call_context.call_updates),
            result_summary=(
                resolved_call.resolved_semantics.tool_result_summary
                if resolved_call.resolved_semantics is not None
                else None
            ),
        )
    except asyncio.CancelledError:
        return ExecutedToolCall(
            result=ToolCallResult(
                call_id=resolved_call.envelope.tool_use_id,
                tool_name=definition.name,
                status=ToolCallStatus.CANCELLED,
                error="Tool execution cancelled",
            ),
            context_updates=tuple(call_context.call_updates),
        )
    except Exception as exc:  # pragma: no cover - defensive boundary
        await _dispatch_hook(
            call_context,
            PostToolUseFailurePayload(
                session_id=call_context.session_id,
                tool_name=definition.name,
                tool_input=dict(resolved_call.execution_input or {}),
                error_message=str(exc),
                turn_id=call_context.turn_id,
            ),
        )
        return ExecutedToolCall(
            result=ToolCallResult(
                call_id=resolved_call.envelope.tool_use_id,
                tool_name=definition.name,
                status=ToolCallStatus.ERROR,
                error=str(exc),
            ),
            context_updates=tuple(call_context.call_updates),
        )
    finally:
        call_context.pending_hook_effect = None


def _prepare_tool_execution(
    definition: ToolDefinition,
    context: ToolContext,
    *,
    tool_use_id: str,
    replay_index: int,
    assistant_message_id: str,
    canonical_tool_name: str | None,
    executor_tier: str,
    model_capabilities: Any,
    execution_class: ToolExecutionClass | None = None,
) -> PreparedToolExecution:
    resolved_class = execution_class or _tool_execution_class_for_definition(definition, context)
    if resolved_class == ToolExecutionClass.PUBLIC:
        execution_context, call_context = context.public_execution_context_for_call(
            tool_use_id=tool_use_id,
            replay_index=replay_index,
            assistant_message_id=assistant_message_id,
            canonical_tool_name=canonical_tool_name,
            executor_tier=executor_tier,
            model_capabilities=model_capabilities,
            execution_class=resolved_class,
        )
        return PreparedToolExecution(
            execution_class=resolved_class,
            api_context=execution_context,
            call_context=call_context,
        )
    call_context = context.for_call(
        tool_use_id=tool_use_id,
        replay_index=replay_index,
        assistant_message_id=assistant_message_id,
        canonical_tool_name=canonical_tool_name,
        executor_tier=executor_tier,
        model_capabilities=model_capabilities,
        execution_class=resolved_class,
    )
    return PreparedToolExecution(
        execution_class=resolved_class,
        api_context=call_context,
        call_context=call_context,
    )


def map_tool_output(tool_name: str, call_id: str, raw_output: Any) -> ToolCallResult:
    if isinstance(raw_output, ToolCallResult):
        return raw_output
    if isinstance(raw_output, ExecutionResult):
        status = ToolCallStatus.SUCCESS if raw_output.status == ExecutionStatus.SUCCESS else ToolCallStatus.ERROR
        return ToolCallResult(
            call_id=call_id,
            tool_name=tool_name,
            status=status,
            output=raw_output.value,
            error=raw_output.error,
            metadata=raw_output.metadata,
        )
    return ToolCallResult(
        call_id=call_id,
        tool_name=tool_name,
        status=ToolCallStatus.SUCCESS,
        output=raw_output,
    )


def coerce_replay_payload(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        normalized = {str(key): value for key, value in payload.items()}
        artifact_ref = normalized.get("artifact_ref")
        if artifact_ref is not None:
            normalized["artifact_ref"] = str(artifact_ref)
            normalized.setdefault("kind", "tool_result_spillover")
        return normalized
    return payload


def assemble_main_thread_tool_pool(
    registry: ToolRegistry,
    *,
    allowed_tools: Sequence[str] | None = None,
    disallowed_tools: Sequence[str] | None = None,
) -> tuple[ToolDefinition, ...]:
    return resolve_tool_pool(
        registry,
        base_pool=registry.definitions(),
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
    )


def assemble_subagent_tool_pool(
    registry: ToolRegistry,
    *,
    parent_pool: Sequence[ToolDefinition],
    allowed_tools: Sequence[str] | None = None,
    disallowed_tools: Sequence[str] | None = None,
) -> tuple[ToolDefinition, ...]:
    return resolve_tool_pool(
        registry,
        base_pool=tuple(parent_pool),
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
    )


def resolve_tool_pool(
    registry: ToolRegistry,
    *,
    base_pool: Sequence[ToolDefinition],
    allowed_tools: Sequence[str] | None = None,
    disallowed_tools: Sequence[str] | None = None,
) -> tuple[ToolDefinition, ...]:
    base_definitions = tuple(base_pool)
    if not allowed_tools:
        selected = list(base_definitions)
    else:
        selected = []
        for definition in base_definitions:
            if any(_matches_tool_selector(definition, selector) for selector in allowed_tools):
                selected.append(definition)
    if disallowed_tools:
        selected = [
            definition
            for definition in selected
            if not any(_matches_tool_selector(definition, selector) for selector in disallowed_tools)
        ]
    deduped: dict[str, ToolDefinition] = {definition.name: definition for definition in selected}
    return tuple(sorted(deduped.values(), key=lambda definition: definition.name))


def validate_input_schema(schema: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    if not schema:
        return dict(payload)
    value = _validate_schema_node(schema, payload, "$")
    if not isinstance(value, dict):
        raise ValueError("Tool input schema must validate to an object payload")
    return value


def _validate_schema_node(schema: Mapping[str, Any], value: Any, path: str) -> Any:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, Mapping):
            raise ValueError(f"{path}: expected object")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", True)
        result: dict[str, Any] = {}
        for field_name in required:
            if field_name not in value:
                raise ValueError(f"{path}.{field_name}: required field missing")
        for key, raw_item in value.items():
            if key in properties:
                result[key] = _validate_schema_node(properties[key], raw_item, f"{path}.{key}")
                continue
            if additional is False:
                raise ValueError(f"{path}.{key}: additional properties are not allowed")
            if isinstance(additional, Mapping):
                result[key] = _validate_schema_node(additional, raw_item, f"{path}.{key}")
            else:
                result[key] = raw_item
        return result

    if expected_type == "array":
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{path}: expected array")
        item_schema = schema.get("items", {})
        return [_validate_schema_node(item_schema, item, f"{path}[{index}]") for index, item in enumerate(value)]

    if expected_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path}: expected string")
        enum = schema.get("enum")
        if enum is not None and value not in enum:
            raise ValueError(f"{path}: expected one of {enum}")
        return value

    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path}: expected integer")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ValueError(f"{path}: value must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{path}: value must be <= {maximum}")
        return value

    if expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{path}: expected number")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ValueError(f"{path}: value must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{path}: value must be <= {maximum}")
        return value

    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected boolean")
        return value

    return value


def _matches_tool_selector(definition: ToolDefinition, selector: str) -> bool:
    if selector == "*":
        return True
    candidates = (definition.name, *definition.aliases)
    if any(char in selector for char in "*?[]"):
        return any(fnmatch(candidate, selector) for candidate in candidates)
    return definition.matches(selector)


async def maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


async def _dispatch_hook(context: ToolContext, payload: Any) -> Any:
    if context.runtime_services is None or context.runtime_services.hook_bus is None:
        return _EmptyHookResult()
    hook_result = await maybe_await(context.runtime_services.hook_bus.dispatch(context.session_id, payload))
    await _emit_hook_notifications(context, hook_result.notifications)
    return hook_result


async def _emit_hook_notifications(context: ToolContext, notifications: Sequence[str]) -> None:
    for notification in notifications:
        if context.runtime_services is None:
            continue
        await context.emit_notification(
            RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.NOTIFICATION,
                content=notification,
                metadata={"skip_hook_dispatch": True, "source": "hook"},
            )
        )


@dataclass(frozen=True, slots=True)
class _EmptyHookResult:
    matched_owners: tuple[str, ...] = ()
    updated_input: dict[str, Any] | None = None
    continue_execution: bool = True
    notifications: tuple[str, ...] = ()


def _tool_catalog_view(pool: Sequence[ToolDefinition]) -> ToolCatalog:
    return ToolCatalog(
        tuple(
            CatalogEntryView(
                name=definition.name,
                aliases=definition.aliases,
                description=definition.description,
                source_label=definition.origin.label,
                metadata=dict(definition.metadata),
            )
            for definition in pool
        )
    )


def _agent_catalog_view(registry: Any) -> AgentCatalog:
    if registry is None or not hasattr(registry, "definitions"):
        return AgentCatalog(())
    return AgentCatalog(
        tuple(
            CatalogEntryView(
                name=definition.name,
                aliases=(),
                description=definition.description,
                source_label=definition.origin.label,
                metadata=dict(definition.metadata),
            )
            for definition in registry.definitions()
        )
    )


def _skill_catalog_view(pool: Sequence[SkillDefinition]) -> SkillCatalog:
    return SkillCatalog(
        tuple(
            CatalogEntryView(
                name=definition.name,
                aliases=(),
                description=definition.description,
                source_label=definition.origin.label,
                metadata=dict(definition.metadata),
            )
            for definition in pool
        )
    )


def _build_tool_execution_classifications(
    definitions: Sequence[ToolDefinition],
) -> dict[str, ToolExecutionClass]:
    return {
        definition.name: _default_tool_execution_classification(definition)
        for definition in definitions
    }


def _tool_execution_class_for_definition(
    definition: ToolDefinition,
    context: ToolContext,
) -> ToolExecutionClass:
    if definition.name in context.tool_execution_classifications:
        return context.tool_execution_classifications[definition.name]
    if (
        context.internal_context is not None
        and definition.name in context.internal_context.execution_classifications
    ):
        return context.internal_context.execution_classifications[definition.name]
    return _default_tool_execution_classification(definition)


def _default_tool_execution_classification(
    definition: ToolDefinition,
) -> ToolExecutionClass:
    raw_value: str | ToolExecutionClass | None = None
    if definition.origin.source == DefinitionSource.BUNDLED:
        raw_value = definition.runtime_execution_class
        if raw_value is None:
            raw_value = definition.metadata.get("runtime_execution_class")
    if isinstance(raw_value, ToolExecutionClass):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return ToolExecutionClass(raw_value)
        except ValueError:
            return ToolExecutionClass.PUBLIC
    return ToolExecutionClass.PUBLIC


def _coerce_permission_context_view(
    context: PermissionContext | None,
) -> PermissionContextView:
    permission_context = context or PermissionContext(session_id="")
    mode = permission_context.mode
    return PermissionContextView(
        effective_mode=mode,
        interactive_prompts_allowed=mode not in {PermissionMode.DONT_ASK, PermissionMode.BUBBLE},
        bubbles_to_caller=mode == PermissionMode.BUBBLE,
        requires_host_mediation=mode != PermissionMode.BYPASS_PERMISSIONS,
        rules=tuple(
            PermissionRuleView(
                target_type=(
                    rule.target.value if getattr(rule, "target", None) is not None else "tool"
                ),
                selector=rule.selector,
                behavior=rule.behavior,
                message=rule.message,
                source=str(rule.metadata.get("source")) if rule.metadata.get("source") else None,
            )
            for rule in permission_context.rules
        ),
    )


def _guarded_memory_roots(context: ToolContext) -> tuple[Path, ...]:
    if context.runtime_services is None:
        return ()
    memory_service = getattr(context.runtime_services, "memory", None)
    if memory_service is None or not hasattr(memory_service, "guarded_roots"):
        return ()
    agent = None
    if context.agent_registry is not None and hasattr(context.agent_registry, "get"):
        agent = context.agent_registry.get(context.agent_name)
    if agent is None:
        agent = AgentDefinition(name=context.agent_name, description="", prompt="")
    roots = memory_service.guarded_roots(
        session_id=context.session_id,
        agent=agent,
        cwd=context.cwd,
    )
    return tuple(Path(root).resolve() for root in roots)


def _supported_refresh_scopes(context: ToolContext) -> frozenset[str]:
    if context.runtime_services is not None and context.runtime_services.tool_refresh_callback is not None:
        return frozenset({"tool_pool"})
    if context.tool_refresh_callback is not None:
        return frozenset({"tool_pool"})
    return frozenset()


def _tool_available_in_pool(
    requested_name: str,
    pool: Sequence[ToolDefinition],
) -> bool:
    return any(definition.matches(requested_name) for definition in pool)
