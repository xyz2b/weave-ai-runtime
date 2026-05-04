from __future__ import annotations

import asyncio
from copy import deepcopy
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
    ContextContributorBinding,
    ContextContributorExecutionEntry,
    ContextContributorRegistry,
    ContextContributorStage,
    HostFacetBinding,
    HostFacetRegistry,
    HostFacetResolution,
    IngressReceiptHandlerBinding,
    IngressReceiptRegistry,
    PackageContribution,
    PackageLifecycleParticipant,
    PackageLifecyclePhase,
    PackageLifecycleRegistry,
    PackageOwnership,
    RuntimeCapabilityKey,
    RuntimeHostFacetKey,
    RuntimePackageManifest,
)
from ..tasking import TaskManager
from ..task_lists import DefaultTaskListService


_SERVICE_FAMILY_CAPABILITY_PROJECTIONS = {
    "memory": RuntimeCapabilityKey.MEMORY_SERVICE.value,
    "compaction": RuntimeCapabilityKey.COMPACTION_MANAGER.value,
    "isolation": RuntimeCapabilityKey.ISOLATION_MANAGER.value,
}

_COMPATIBILITY_CAPABILITY_PROJECTIONS = {
    "teammates": RuntimeCapabilityKey.TEAMMATES.value,
}

_LEGACY_MEMORY_CONTEXT_SURFACE = "RuntimeServices.memory.collect"
_LEGACY_HOOK_CONTEXT_SURFACE = "RuntimeServices.hooks.collect"
_LEGACY_TASK_DISCIPLINE_CONTEXT_SURFACE = "RuntimeServices.task_discipline.collect"


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
    context_contributors: ContextContributorRegistry = field(default_factory=ContextContributorRegistry)
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
    runtime_ready: bool = False
    runtime_lifecycle_failures: tuple[dict[str, Any], ...] = ()
    runtime_lifecycle_exception: BaseException | None = None
    runtime_lifecycle_task: asyncio.Task[tuple[dict[str, Any], ...]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _runtime_metadata_mirror: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _runtime_assembly: Any | None = field(default=None, init=False, repr=False)
    _compatibility_projection_ready: bool = field(default=False, init=False, repr=False)

    def __getattribute__(self, name: str) -> Any:
        capability_key = _SERVICE_FAMILY_CAPABILITY_PROJECTIONS.get(name)
        if capability_key is not None:
            return object.__getattribute__(self, "resolve_capability")(capability_key)
        capability_key = _COMPATIBILITY_CAPABILITY_PROJECTIONS.get(name)
        if capability_key is not None:
            # Retained team_* projections stay delegated to the capability registry.
            fallback = object.__getattribute__(self, name)
            return object.__getattribute__(self, "resolve_capability")(capability_key, fallback)
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        capability_key = _SERVICE_FAMILY_CAPABILITY_PROJECTIONS.get(name)
        if capability_key is None:
            return
        try:
            ready = object.__getattribute__(self, "_compatibility_projection_ready")
        except AttributeError:
            return
        if not ready:
            return
        self._bind_compatibility_projection(name, capability_key, value)
        self._refresh_published_protocol_metadata()

    def __post_init__(self) -> None:
        manager = self.tasks.manager
        if manager is not None:
            self.jobs = manager.job_service
        elif self.jobs is None:
            self.jobs = DefaultJobService()
        if self.jobs is None:  # pragma: no cover - defensive boundary
            self.jobs = DefaultJobService()
        self._bind_job_runtime(self.jobs)
        self._seed_service_family_capabilities()
        self._compatibility_projection_ready = True
        self._sync_context_contributor_metadata()
        self._refresh_published_protocol_metadata()

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
        self.record_compatibility_usage(
            family="task_manager",
            surface="RuntimeServices.bind_task_manager",
            access_label="TaskManager",
        )

    @property
    def task_manager(self) -> TaskManager:
        if self.tasks.manager is None:  # pragma: no cover - defensive boundary
            self.tasks = DefaultTaskService(TaskManager(job_service=self.job_service))
        self.record_compatibility_usage(
            family="task_manager",
            surface="RuntimeServices.task_manager",
            access_label="TaskManager",
        )
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

    def configure_compat(
        self,
        *,
        permission_handler: Any = None,
        ask_user_handler: Any = None,
        tool_refresh_callback: Any = None,
        notification_provider: Callable[[], Sequence[RuntimeMessage]] | None = None,
        notification_sink: Callable[[RuntimeMessage], Any] | None = None,
        turn_event_sink: Callable[[str, Any], Any] | None = None,
        extension_event_sink: Callable[[Any], Any] | None = None,
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
                extension_event_sink,
            )
        ):
            self.host = CallbackHostAdapter(
                permission_handler=permission_handler,
                ask_user_handler=ask_user_handler,
                notification_provider=notification_provider,
                notification_sink=notification_sink,
                turn_event_sink=turn_event_sink,
                extension_event_sink=extension_event_sink,
            )

    def bind_capability(self, binding: CapabilityBinding, *, override: bool = True) -> CapabilityBinding | None:
        previous = self.capability_registry.bind(binding, override=override)
        self._refresh_published_protocol_metadata()
        return previous

    def register_context_contributor(
        self,
        binding: ContextContributorBinding,
        *,
        override: bool = True,
    ) -> ContextContributorBinding | None:
        previous = self.context_contributors.register(binding, override=override)
        self._sync_context_contributor_metadata()
        return previous

    def context_contributor_execution_plan(self) -> tuple[ContextContributorExecutionEntry, ...]:
        registered = list(self.context_contributors.execution_plan())
        sequence = len(registered)
        for binding in self._legacy_context_contributor_bindings():
            stage = self.context_contributors.stage(binding.stage)
            registered.append(
                ContextContributorExecutionEntry(
                    binding=binding,
                    stage=stage,
                    sequence=sequence,
                )
            )
            sequence += 1
        return tuple(
            sorted(
                registered,
                key=lambda entry: entry.ordering_key,
            )
        )

    def resolve_capability(self, key: str, default: Any = None) -> Any:
        return self.capability_registry.resolve(key, default)

    def require_capability(self, key: str) -> Any:
        return self.capability_registry.require(key)

    def resolve_teammates(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.TEAMMATES.value)

    def resolve_memory_service(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.MEMORY_SERVICE.value)

    def resolve_compaction_service(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.COMPACTION_MANAGER.value)

    def resolve_isolation_service(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.ISOLATION_MANAGER.value)

    def resolve_team_control_plane(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value)

    def resolve_team_message_bus(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)

    def resolve_team_workflows(self) -> Any:
        return self.resolve_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value)

    def record_compatibility_usage(
        self,
        *,
        family: str,
        surface: str,
        access_label: str | None = None,
    ) -> None:
        normalized_family = str(family).strip()
        normalized_surface = str(surface).strip()
        changed = False

        raw_usage = self.metadata.get("compatibility_usage")
        if not isinstance(raw_usage, dict):
            raw_usage = {}
            self.metadata["compatibility_usage"] = raw_usage
            changed = True
        family_usage = raw_usage.get(normalized_family)
        if not isinstance(family_usage, list):
            family_usage = (
                [str(item) for item in family_usage if str(item).strip()]
                if isinstance(family_usage, Sequence) and not isinstance(family_usage, (str, bytes))
                else []
            )
            raw_usage[normalized_family] = family_usage
            changed = True
        if normalized_surface and normalized_surface not in family_usage:
            family_usage.append(normalized_surface)
            changed = True

        if access_label is not None:
            accesses = self.metadata.setdefault("compatibility_accesses", [])
            if isinstance(accesses, list) and access_label not in accesses:
                accesses.append(access_label)
                changed = True

        if changed:
            self._refresh_published_protocol_metadata()

    def query_closure_report(self) -> dict[str, Any]:
        report = self.metadata.get("closure_report")
        return deepcopy(report) if isinstance(report, Mapping) else {}

    def query_compatibility_retirement(self) -> dict[str, Any]:
        report = self.query_closure_report()
        value = report.get("compatibility_retirement")
        return deepcopy(value) if isinstance(value, Mapping) else {}

    def query_persistence_profile(self) -> dict[str, Any]:
        report = self.query_closure_report()
        value = report.get("persistence_profile")
        return deepcopy(value) if isinstance(value, Mapping) else {}

    def query_isolation_readiness(self) -> dict[str, Any]:
        report = self.query_closure_report()
        value = report.get("isolation_readiness")
        return deepcopy(value) if isinstance(value, Mapping) else {}

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
        for binding in contribution.context_contributors:
            self.register_context_contributor(binding, override=True)
            self.metadata.setdefault("package_context_contributor_owners", {})[binding.name] = {
                "package_name": binding.owner.package_name,
                "package_role": binding.owner.package_role,
                "surface": binding.owner.surface,
                "stage": binding.stage.value,
                "order": binding.order,
            }
            compatibility_surface = str(binding.metadata.get("compatibility_surface") or "").strip()
            if compatibility_surface:
                self.metadata.setdefault("context_contributor_surface_owners", {})[
                    compatibility_surface
                ] = {
                    "binding": binding.name,
                    "package_name": binding.owner.package_name,
                    "package_role": binding.owner.package_role,
                    "stage": binding.stage.value,
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
            "invocation_providers": [binding.name for binding in contribution.invocation_providers],
            "context_contributors": [binding.name for binding in contribution.context_contributors],
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
        if contribution.metadata:
            entry["metadata"] = deepcopy(contribution.metadata)
        self.metadata.setdefault("package_contributions", []).append(entry)
        self._sync_context_contributor_metadata()

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

    def _sync_context_contributor_metadata(self) -> None:
        compatibility_surfaces = self.metadata.setdefault("compatibility_surfaces", {})
        compatibility_surfaces.setdefault("RuntimeServices.memory", "compatibility-only")
        compatibility_surfaces.setdefault(_LEGACY_MEMORY_CONTEXT_SURFACE, "compatibility-only")
        compatibility_surfaces.setdefault("RuntimeServices.compaction", "compatibility-only")
        compatibility_surfaces.setdefault("RuntimeServices.isolation", "compatibility-only")
        compatibility_surfaces.setdefault(_LEGACY_HOOK_CONTEXT_SURFACE, "compatibility-only")
        compatibility_surfaces.setdefault(
            _LEGACY_TASK_DISCIPLINE_CONTEXT_SURFACE,
            "compatibility-only",
        )
        compatibility_surfaces.setdefault(
            "RuntimeServices.compaction.prepare_turn",
            "compatibility-only",
        )
        compatibility_surfaces.setdefault(
            "RuntimeServices.compaction.collect",
            "compatibility-only",
        )
        self.metadata["context_contributors"] = {
            "stages": [
                {
                    "name": stage.name.value,
                    "order": stage.order,
                    "prompt_channel": stage.prompt_channel.value,
                    "metadata": dict(stage.metadata),
                }
                for stage in self.context_contributors.stage_catalog()
            ],
            "bindings": [
                {
                    "name": entry.binding.name,
                    "stage": entry.stage.name.value,
                    "stage_order": entry.stage.order,
                    "prompt_channel": entry.stage.prompt_channel.value,
                    "order": entry.binding.order,
                    "timeout_seconds": entry.binding.timeout_seconds,
                    "owner": self._serialize_package_owner(entry.binding.owner),
                    "metadata": dict(entry.binding.metadata),
                }
                for entry in self.context_contributor_execution_plan()
            ],
            "compatibility_surfaces": {
                _LEGACY_MEMORY_CONTEXT_SURFACE: compatibility_surfaces[_LEGACY_MEMORY_CONTEXT_SURFACE],
                _LEGACY_HOOK_CONTEXT_SURFACE: compatibility_surfaces[_LEGACY_HOOK_CONTEXT_SURFACE],
                _LEGACY_TASK_DISCIPLINE_CONTEXT_SURFACE: compatibility_surfaces[
                    _LEGACY_TASK_DISCIPLINE_CONTEXT_SURFACE
                ],
            },
            "compatibility_service_projections": {
                "memory": {
                    "surface": "RuntimeServices.memory",
                    "status": compatibility_surfaces["RuntimeServices.memory"],
                },
                "compaction": {
                    "surface": "RuntimeServices.compaction",
                    "status": compatibility_surfaces["RuntimeServices.compaction"],
                },
                "isolation": {
                    "surface": "RuntimeServices.isolation",
                    "status": compatibility_surfaces["RuntimeServices.isolation"],
                },
            },
        }
        self._sync_metadata_mirror()

    def _legacy_context_contributor_bindings(self) -> tuple[ContextContributorBinding, ...]:
        bindings: list[ContextContributorBinding] = []
        if not self._context_contributor_surface_claimed(_LEGACY_MEMORY_CONTEXT_SURFACE):
            memory = self.resolve_memory_service()
            if memory is not None and hasattr(memory, "collect") and not isinstance(memory, NoopMemoryService):
                bindings.append(
                    ContextContributorBinding(
                        name="compat.memory.collect",
                        stage=ContextContributorStage.MEMORY,
                        contributor=memory,
                        owner=self._legacy_context_contributor_owner(
                            surface=_LEGACY_MEMORY_CONTEXT_SURFACE,
                            capability_key=RuntimeCapabilityKey.MEMORY_SERVICE.value,
                            default_package_name="weavert-core",
                            default_package_role="core",
                        ),
                        metadata={
                            "compatibility_only": True,
                            "compatibility_surface": _LEGACY_MEMORY_CONTEXT_SURFACE,
                        },
                    )
                )
        if not self._context_contributor_surface_claimed(_LEGACY_HOOK_CONTEXT_SURFACE):
            hooks = self.hooks
            if hooks is not None and hasattr(hooks, "collect") and not isinstance(hooks, NoopHookService):
                bindings.append(
                    ContextContributorBinding(
                        name="compat.hooks.collect",
                        stage=ContextContributorStage.HOOKS,
                        contributor=hooks,
                        owner=self._legacy_context_contributor_owner(
                            surface=_LEGACY_HOOK_CONTEXT_SURFACE,
                            default_package_name="weavert-core",
                            default_package_role="core",
                        ),
                        metadata={
                            "compatibility_only": True,
                            "compatibility_surface": _LEGACY_HOOK_CONTEXT_SURFACE,
                        },
                    )
                )
        if not self._context_contributor_surface_claimed(_LEGACY_TASK_DISCIPLINE_CONTEXT_SURFACE):
            task_discipline = self.task_discipline
            if (
                task_discipline is not None
                and hasattr(task_discipline, "collect")
                and not isinstance(task_discipline, NoopHookService)
            ):
                bindings.append(
                    ContextContributorBinding(
                        name="compat.task_discipline.collect",
                        stage=ContextContributorStage.TASK_POLICY,
                        contributor=task_discipline,
                        owner=self._legacy_context_contributor_owner(
                            surface=_LEGACY_TASK_DISCIPLINE_CONTEXT_SURFACE,
                            default_package_name="weavert-core",
                            default_package_role="core",
                        ),
                        metadata={
                            "compatibility_only": True,
                            "compatibility_surface": _LEGACY_TASK_DISCIPLINE_CONTEXT_SURFACE,
                        },
                    )
                )
        return tuple(bindings)

    def _context_contributor_surface_claimed(self, surface: str) -> bool:
        for entry in self.context_contributors.execution_plan():
            if entry.binding.metadata.get("compatibility_surface") == surface:
                return True
        return False

    def _legacy_context_contributor_owner(
        self,
        *,
        surface: str,
        capability_key: str | None = None,
        default_package_name: str,
        default_package_role: str,
    ) -> PackageOwnership:
        owner = (
            self.capability_registry.owner(capability_key)
            if capability_key is not None
            else None
        )
        if owner is not None:
            return owner
        return PackageOwnership(
            package_name=default_package_name,
            package_role=default_package_role,
            surface="compatibility_context_contributor",
            metadata={"compatibility_surface": surface},
        )

    def attach_metadata_mirror(self, metadata: dict[str, Any]) -> None:
        self._runtime_metadata_mirror = metadata
        self._sync_metadata_mirror()

    def attach_runtime_assembly(self, runtime: Any) -> None:
        self._runtime_assembly = runtime
        self._refresh_published_protocol_metadata()

    def _seed_service_family_capabilities(self) -> None:
        for field_name, capability_key in _SERVICE_FAMILY_CAPABILITY_PROJECTIONS.items():
            if self.capability_registry.binding(capability_key) is not None:
                continue
            value = object.__getattribute__(self, field_name)
            self._bind_compatibility_projection(field_name, capability_key, value)

    def _bind_compatibility_projection(
        self,
        field_name: str,
        capability_key: str,
        value: Any,
    ) -> None:
        self.capability_registry.bind(
            CapabilityBinding(
                key=capability_key,
                value=value,
                owner=self._compatibility_projection_owner(field_name),
                metadata={
                    "compatibility_surface": f"RuntimeServices.{field_name}",
                    "compatibility_only": True,
                },
            ),
            override=True,
        )

    def _compatibility_projection_owner(self, field_name: str) -> PackageOwnership:
        return PackageOwnership(
            package_name="weavert-core",
            package_role="compatibility",
            surface="compatibility_projection",
            metadata={"compatibility_surface": f"RuntimeServices.{field_name}"},
        )

    def _refresh_published_protocol_metadata(self) -> None:
        from ..runtime_kernel.kernel import (
            _project_capability_compatibility_surfaces,
            _sync_compatibility_boundary_metadata,
            _sync_package_service_protocol_metadata,
        )

        runtime = self._runtime_assembly
        kernel = getattr(runtime, "kernel", None) if runtime is not None else None
        _project_capability_compatibility_surfaces(self)
        _sync_package_service_protocol_metadata(self)
        _sync_compatibility_boundary_metadata(self, kernel=kernel, runtime=runtime)
        self._sync_metadata_mirror()

    def _sync_metadata_mirror(self) -> None:
        mirror = self._runtime_metadata_mirror
        if mirror is None:
            return
        for key in (
            "core_protocol_catalog",
            "closure_report",
            "context_contributors",
            "compatibility_surfaces",
            "compatibility_boundaries",
            "compatibility_projections",
            "official_package_catalog_provenance",
            "package_service_protocols",
            "resolved_active_package_graph_provenance",
            "protocol_only_conformance",
        ):
            mirror[key] = deepcopy(self.metadata.get(key, {}))

    def _serialize_package_owner(self, owner: PackageOwnership) -> dict[str, Any]:
        return {
            "package_name": owner.package_name,
            "package_role": owner.package_role,
            "surface": owner.surface,
            "metadata": dict(owner.metadata),
        }


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
