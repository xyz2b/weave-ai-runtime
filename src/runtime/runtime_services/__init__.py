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
from ..runtime_package_protocols import (
    CapabilityBinding,
    CapabilityRegistry,
    HostFacetBinding,
    HostFacetRegistry,
    HostFacetResolution,
    IngressReceiptHandlerBinding,
    IngressReceiptRegistry,
    PackageContribution,
    PackageLifecycleParticipant,
    PackageLifecyclePhase,
    PackageLifecycleRegistry,
    RuntimeCapabilityKey,
    RuntimeHostFacetKey,
    RuntimePackageManifest,
)
from ..tasking import TaskManager
from ..task_lists import DefaultTaskListService


_COMPATIBILITY_CAPABILITY_PROJECTIONS = {
    "teammates": RuntimeCapabilityKey.TEAMMATES.value,
    "team_control_plane": RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value,
    "team_message_bus": RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value,
    "team_workflows": RuntimeCapabilityKey.TEAM_WORKFLOWS.value,
}


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
    capability_registry: CapabilityRegistry = field(default_factory=CapabilityRegistry)
    lifecycle_registry: PackageLifecycleRegistry = field(default_factory=PackageLifecycleRegistry)
    host_facets: HostFacetRegistry = field(default_factory=HostFacetRegistry)
    ingress_receipts: IngressReceiptRegistry = field(default_factory=IngressReceiptRegistry)
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
    team_control_plane: Any = None
    team_message_bus: Any = None
    team_workflows: Any = None
    runtime_ready: bool = False
    runtime_lifecycle_failures: tuple[dict[str, Any], ...] = ()
    runtime_lifecycle_exception: BaseException | None = None
    runtime_lifecycle_task: asyncio.Task[tuple[dict[str, Any], ...]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __getattribute__(self, name: str) -> Any:
        capability_key = _COMPATIBILITY_CAPABILITY_PROJECTIONS.get(name)
        if capability_key is not None:
            # Retained team_* projections stay delegated to the capability registry.
            fallback = object.__getattribute__(self, name)
            return object.__getattribute__(self, "resolve_capability")(capability_key, fallback)
        return object.__getattribute__(self, name)

    def __post_init__(self) -> None:
        manager = self.tasks.manager
        if manager is not None:
            self.jobs = manager.job_service
        elif self.jobs is None:
            self.jobs = DefaultJobService()
        if self.jobs is None:  # pragma: no cover - defensive boundary
            self.jobs = DefaultJobService()
        self._bind_job_runtime(self.jobs)

    def bind_job_service(self, job_service: DefaultJobService) -> None:
        previous_kernel = self.jobs.kernel if self.jobs is not None else None
        self.jobs = job_service
        manager = self.tasks.manager
        if manager is not None and manager.job_service is not job_service:
            self.tasks = DefaultTaskService(TaskManager(job_service=job_service))
        self._bind_job_runtime(job_service, kernel=previous_kernel)

    def bind_task_manager(self, task_manager: TaskManager) -> None:
        previous_kernel = self.jobs.kernel if self.jobs is not None else None
        self.jobs = task_manager.job_service
        self.tasks = DefaultTaskService(task_manager)
        self._bind_job_runtime(task_manager.job_service, kernel=previous_kernel)

    @property
    def task_manager(self) -> TaskManager:
        if self.tasks.manager is None:  # pragma: no cover - defensive boundary
            self.tasks = DefaultTaskService(TaskManager(job_service=self.job_service))
            accesses = self.metadata.setdefault("compatibility_accesses", [])
            if isinstance(accesses, list) and "TaskManager" not in accesses:
                accesses.append("TaskManager")
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

    def _bind_job_runtime(self, job_service: DefaultJobService, *, kernel: Any | None = None) -> None:
        resolved_kernel = job_service.kernel if job_service.kernel is not None else kernel
        job_service.bind_runtime(
            runtime_id=str(self.metadata.get("runtime_id") or "default"),
            services=self,
            kernel=resolved_kernel,
        )

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

    def bind_team_services(
        self,
        *,
        control_plane: Any = None,
        message_bus: Any = None,
        workflow_service: Any = None,
    ) -> None:
        self.team_control_plane = control_plane
        self.team_message_bus = message_bus
        self.team_workflows = workflow_service

    def configure_compat(
        self,
        *,
        permission_handler: Any = None,
        ask_user_handler: Any = None,
        tool_refresh_callback: Any = None,
        notification_provider: Callable[[], Sequence[RuntimeMessage]] | None = None,
        notification_sink: Callable[[RuntimeMessage], Any] | None = None,
        turn_event_sink: Callable[[str, Any], Any] | None = None,
        team_event_sink: Callable[[Any], Any] | None = None,
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
                team_event_sink,
            )
        ):
            self.host = CallbackHostAdapter(
                permission_handler=permission_handler,
                ask_user_handler=ask_user_handler,
                notification_provider=notification_provider,
                notification_sink=notification_sink,
                turn_event_sink=turn_event_sink,
                team_event_sink=team_event_sink,
            )

    def bind_capability(self, binding: CapabilityBinding, *, override: bool = True) -> CapabilityBinding | None:
        return self.capability_registry.bind(binding, override=override)

    def resolve_capability(self, key: str, default: Any = None) -> Any:
        return self.capability_registry.resolve(key, default)

    def require_capability(self, key: str) -> Any:
        return self.capability_registry.require(key)

    def resolve_teammates(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.TEAMMATES.value)

    def resolve_team_control_plane(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value)

    def resolve_team_message_bus(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)

    def resolve_team_workflows(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value)

    def register_lifecycle_participant(self, participant: PackageLifecycleParticipant) -> None:
        self.lifecycle_registry.register(participant)

    def lifecycle_participants(
        self,
        phase: PackageLifecyclePhase | str | None = None,
    ) -> tuple[PackageLifecycleParticipant, ...]:
        return self.lifecycle_registry.participants(phase)

    def register_host_facet(self, binding: HostFacetBinding, *, override: bool = True) -> HostFacetBinding | None:
        return self.host_facets.register(binding, override=override)

    def resolve_host_facet(self, name: str) -> HostFacetResolution:
        return self.host_facets.resolve(name)

    def require_host_facet(self, name: str) -> Any:
        return self.host_facets.require(name)

    def resolve_team_workflow_host_facet(self) -> HostFacetResolution:
        return self.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)

    def register_ingress_receipt_handler(
        self,
        binding: IngressReceiptHandlerBinding,
        *,
        override: bool = True,
    ) -> IngressReceiptHandlerBinding | None:
        return self.ingress_receipts.register(binding, override=override)

    def resolve_ingress_receipt_handler(self, kind: str) -> Any:
        return self.ingress_receipts.resolve(kind)

    async def execute_ingress_completion_receipt(
        self,
        receipt: Any,
        **kwargs: Any,
    ) -> Any:
        handler = self.resolve_ingress_receipt_handler(receipt.kind)
        if handler is None:
            raise LookupError(
                f"Ingress completion receipt '{receipt.kind}' is not registered in the active runtime"
            )
        return await _maybe_await(
            handler(
                receipt=receipt,
                services=self,
                **kwargs,
            )
        )

    def apply_package_contribution(
        self,
        manifest: RuntimePackageManifest,
        contribution: PackageContribution,
        *,
        stage: str | None = None,
    ) -> None:
        for capability in contribution.capabilities:
            self.bind_capability(capability, override=True)
            self.metadata.setdefault("package_capability_owners", {})[capability.key] = {
                "package_name": capability.owner.package_name,
                "package_role": capability.owner.package_role,
                "surface": capability.owner.surface,
            }
        for participant in contribution.lifecycle_participants:
            self.register_lifecycle_participant(participant)
        for facet in contribution.host_facets:
            self.register_host_facet(facet, override=True)
            self.metadata.setdefault("package_host_facet_owners", {})[facet.name] = {
                "package_name": facet.owner.package_name,
                "package_role": facet.owner.package_role,
                "surface": facet.owner.surface,
            }
        for binding in contribution.ingress_receipt_handlers:
            self.register_ingress_receipt_handler(binding, override=True)
            self.metadata.setdefault("package_ingress_receipt_owners", {})[binding.kind] = {
                "package_name": binding.owner.package_name,
                "package_role": binding.owner.package_role,
                "surface": binding.owner.surface,
            }
        entry = {
            "package_name": manifest.name,
            "package_role": manifest.role,
            "stage": stage,
            "capabilities": [binding.key for binding in contribution.capabilities],
            "lifecycle_participants": [participant.name for participant in contribution.lifecycle_participants],
            "host_facets": [facet.name for facet in contribution.host_facets],
            "ingress_receipt_handlers": [binding.kind for binding in contribution.ingress_receipt_handlers],
            "store_bindings": [binding.slot for binding in contribution.store_bindings],
            "model_providers": [binding.name for binding in contribution.model_providers],
            "model_routes": [binding.name for binding in contribution.model_routes],
            "job_executors": [binding.kind for binding in contribution.job_executors],
            "diagnostics": [getattr(diagnostic, "code", None) for diagnostic in contribution.diagnostics],
        }
        self.metadata.setdefault("package_contributions", []).append(entry)

    def begin_runtime_lifecycle(
        self,
        task: asyncio.Task[tuple[dict[str, Any], ...]],
    ) -> None:
        self.runtime_ready = False
        self.runtime_lifecycle_failures = ()
        self.runtime_lifecycle_exception = None
        self.runtime_lifecycle_task = task
        self.metadata["runtime_ready"] = False

        def _complete(completed: asyncio.Task[tuple[dict[str, Any], ...]]) -> None:
            if completed.cancelled():
                self.runtime_lifecycle_task = None
                self.runtime_ready = False
                self.metadata["runtime_lifecycle_cancelled"] = True
                return
            try:
                failures = completed.result()
            except Exception as exc:  # pragma: no cover - defensive task boundary
                self.runtime_lifecycle_task = None
                self.runtime_ready = False
                self.runtime_lifecycle_exception = exc
                self.metadata["runtime_lifecycle_error"] = str(exc)
                return
            self.mark_runtime_ready(failures)

        task.add_done_callback(_complete)

    def mark_runtime_ready(
        self,
        failures: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    ) -> tuple[dict[str, Any], ...]:
        normalized = tuple(dict(entry) for entry in failures)
        self.runtime_lifecycle_task = None
        self.runtime_lifecycle_failures = normalized
        self.runtime_lifecycle_exception = None
        self.runtime_ready = True
        self.metadata["runtime_ready"] = True
        self.metadata["runtime_lifecycle_failures"] = [dict(entry) for entry in normalized]
        return normalized

    async def wait_until_runtime_ready(self) -> tuple[dict[str, Any], ...]:
        task = self.runtime_lifecycle_task
        if task is not None:
            current = asyncio.current_task()
            if current is task:
                return self.runtime_lifecycle_failures
            failures = await asyncio.shield(task)
            return self.mark_runtime_ready(failures)
        if self.runtime_lifecycle_exception is not None:
            raise self.runtime_lifecycle_exception
        if self.runtime_ready:
            return self.runtime_lifecycle_failures
        return self.mark_runtime_ready(())

    async def dispatch_lifecycle_phase(
        self,
        phase: PackageLifecyclePhase | str,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], ...]:
        normalized_phase = PackageLifecyclePhase(phase)
        failures: list[dict[str, Any]] = []
        for participant in self.lifecycle_participants(normalized_phase):
            try:
                await _maybe_await(
                    participant.handler(
                        phase=normalized_phase,
                        services=self,
                        **kwargs,
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive lifecycle boundary
                failure = {
                    "phase": normalized_phase.value,
                    "participant": participant.name,
                    "package_name": participant.owner.package_name,
                    "error": str(exc),
                }
                failures.append(failure)
                self.metadata.setdefault("lifecycle_participant_failures", []).append(failure)
        return tuple(failures)


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


__all__ = [
    "CapabilityBinding",
    "CapabilityRegistry",
    "CallbackToolCatalogService",
    "CompactionService",
    "ContextContributionService",
    "DefaultTaskService",
    "DefaultTranscriptService",
    "ElicitationService",
    "HostFacetBinding",
    "HostFacetRegistry",
    "HostFacetResolution",
    "IngressReceiptHandlerBinding",
    "IngressReceiptRegistry",
    "NoopCompactionService",
    "NoopHookService",
    "NoopMemoryService",
    "PackageContribution",
    "PackageLifecycleParticipant",
    "PackageLifecyclePhase",
    "PackageLifecycleRegistry",
    "PermissionService",
    "RuntimeServices",
    "RuntimePackageManifest",
    "ToolCatalogService",
]
