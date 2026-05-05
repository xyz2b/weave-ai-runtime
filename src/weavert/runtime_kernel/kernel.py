from __future__ import annotations

import asyncio
import hashlib
import inspect
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, AsyncIterator, Literal, Mapping, Sequence
from uuid import uuid4

from ..agent_execution import InMemoryChildRunStore, SpawnMode
from ..agent_runtime import AgentInvocation, AgentRunResult, AgentRuntime
from ..closure import (
    ClosureActivationState,
    ClosureStatus,
    LEGACY_COMPATIBILITY_FAMILIES,
    LEGACY_COMPATIBILITY_FAMILY_INDEX,
    LEGACY_RUNTIME_CONTEXT_AUTHORITATIVE_KEYS,
    LegacyCompatibilityProfile,
    PersistenceDurabilityState,
    family_activation_state,
    resolve_legacy_compatibility_profile,
)
from ..contracts import (
    ExecutionResult,
    ExecutionStatus,
    PromptContextEnvelope,
    RuntimeMessage,
    RuntimePrivateContext,
    SessionStatus,
    merge_runtime_private_context,
    serialize_content_blocks,
)
from ..child_result_projection import project_agent_run_result
from ..definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    InvocationCapabilityView,
    InvocationDiagnostics,
    InvocationResolutionContext,
    IsolationMode,
    PermissionMode,
    ResolvedInvocationCatalog,
    SkillDefinition,
    ToolDefinition,
)
from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..errors import RegistryConflictError
from ..first_party_loading import load_object
from ..hosts.base import BoundHostRuntime, HostAdapter, NullHostAdapter
from ..hooks import (
    ADVANCED_HOOK_HANDLER_KINDS,
    ADVANCED_PUBLIC_PHASE_CONTRACTS,
    ConfiguredHookRegistrar,
    HookDispatchTraceQuery,
    HookInventoryQuery,
    HookRegistrationRequest,
    HookScopeLifetime,
    HookSourceKind,
    STABLE_PUBLIC_HOOK_HANDLER_KINDS,
    STABLE_PUBLIC_PHASE_CONTRACTS,
    build_configured_hook_registrar,
)
from ..invocation_catalog import SkillInvocationProvider
from ..jobs import DefaultJobService, FileJobStore, InMemoryJobStore, JobScopeFilter, job_record_to_payload
from ..memory.models import MemoryTurnResult
from ..memory.providers import FileMemoryProvider
from ..package_profiles import FIRST_PARTY_PACKAGE_SPECS, distribution_spec
from ..runtime_package_catalog import (
    official_runtime_distribution_catalog,
    official_runtime_package_catalog_metadata,
    official_runtime_package_catalog_provenance,
    official_runtime_package_names,
)
from ..runtime_package_manifests import (
    RuntimePackageRegistrationReport,
    official_runtime_package_manifests,
    register_external_runtime_package_manifests,
)
from ..runtime_package_resolution import (
    RuntimePackageResolutionError,
    RuntimePackageResolutionReport,
    build_runtime_package_catalog,
    build_runtime_package_request,
    resolve_runtime_package_graph,
)
from ..runtime_core_protocol_catalog import (
    build_stable_core_protocol_catalog,
    core_protocol_compatibility_surfaces,
    core_protocol_invocation_provider_paths_metadata,
    core_protocol_package_lookup_sections,
)
from ..runtime_package_protocols import (
    InvocationProviderContribution,
    InvocationProviderFactoryContext,
    PackageAssemblyStage,
    PackageContext,
    PackageContribution,
    PackageLifecyclePhase,
    RuntimeCapabilityKey,
    RuntimeHostFacetKey,
    RuntimePackageManifest,
    preserve_builtin_owner,
)
from ..registries import (
    AgentRegistry,
    DefinitionDiscovery,
    InvocationProviderRegistration,
    InvocationRegistry,
    SkillRegistry,
    ToolRegistry,
)
from ..runtime_services import DefaultTranscriptService, NoopCompactionService, NoopMemoryService, RuntimeServices
from ..public_contract import workspace_skill_root_candidates
from ..stores_file import FileChildRunStore
from ..task_discipline import TaskDisciplineSidecar
from ..task_lists import (
    DefaultTaskListService,
    FileTaskListStore,
    InMemoryTaskListStore,
    TaskDisciplinePolicy,
    TaskListError,
    coerce_private_context,
    task_list_entry_to_dict,
    task_list_snapshot_to_dict,
)
from ..session_runtime import (
    FileTranscriptStore,
    InMemoryTranscriptStore,
    InboundEvent,
    InboundEventType,
    SessionController,
    SessionStatus,
)
from ..skill_runtime import SkillExecutionResult, SkillExecutor
from ..tasking import TaskManager
from ..team_control_plane import FileBackedTeamStore, InMemoryTeamStore
from ..tool_runtime import ToolContext
from ..turn_engine.composer import ContextAssembler
from ..turn_engine.engine import TurnEngine, TurnStreamEvent, TurnStreamEventType, TurnTerminal
from ..turn_engine.models import ModelRequest, TranscriptStore
from ..workflow_observability import (
    WorkflowRunKind,
    WorkflowRunObservability,
    workflow_run_observability_from_report,
)
from .config import (
    DefinitionSourcePaths,
    RuntimeConfig,
    _publish_runtime_assembly_preset_metadata,
)
from .preflight import (
    ModelRoutePreflightReport,
    preflight_model_route as _preflight_model_route,
)
from ..execution_policy import DelegationPolicyError, default_delegation_policy_metadata, policy_state_from_metadata

SKILL_DYNAMIC_ROOTS_KEY = "skill_dynamic_roots"
_UNSET = object()
_COMPATIBILITY_RUNTIME_ASSEMBLY_PROJECTIONS = {
    "teammates": RuntimeCapabilityKey.TEAMMATES.value,
}


@dataclass(slots=True)
class RuntimeKernel:
    config: RuntimeConfig
    tool_registry: ToolRegistry
    agent_registry: AgentRegistry
    skill_registry: SkillRegistry
    invocation_registry: InvocationRegistry
    distribution: str
    first_party_packages: tuple[str, ...] = ()
    package_registration: RuntimePackageRegistrationReport = field(
        default_factory=RuntimePackageRegistrationReport
    )
    package_resolution: RuntimePackageResolutionReport | None = None
    package_manifests: tuple[RuntimePackageManifest, ...] = ()
    package_service_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    model_client: Any = None
    transcript_store: Any = None
    services: RuntimeServices | None = None
    hosts: dict[str, HostAdapter] = field(default_factory=dict)
    skill_view_resolver: Any = None


@dataclass(frozen=True, slots=True)
class WorkflowRunFinalizationTask:
    kind: str
    task_id: str
    waited: bool = False
    result: MemoryTurnResult | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowRunFinalizationReport:
    requested: bool = False
    tasks: tuple[WorkflowRunFinalizationTask, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tasks", tuple(self.tasks))

    @property
    def awaited(self) -> bool:
        return any(task.waited for task in self.tasks)


@dataclass(frozen=True, slots=True)
class WorkflowRunReport:
    session_id: str
    agent_name: str
    cwd: str
    turn_id: str | None = None
    messages: tuple[RuntimeMessage, ...] = ()
    terminal: TurnTerminal | None = None
    final_status: str = "completed"
    session_owner: Literal["helper", "caller"] = "helper"
    finalization: WorkflowRunFinalizationReport = field(
        default_factory=WorkflowRunFinalizationReport
    )
    workflow_observability: WorkflowRunObservability | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        if self.workflow_observability is None:
            object.__setattr__(
                self,
                "workflow_observability",
                workflow_run_observability_from_report(self),
            )

    @property
    def run_id(self) -> str:
        if self.workflow_observability is not None:
            return self.workflow_observability.run_id
        return self.turn_id or self.session_id


@dataclass(frozen=True, slots=True)
class RuntimeAssemblyVisibleInvocationSnapshot:
    name: str
    source_kind: str
    description: str
    display_name: str | None = None
    argument_hint: str | None = None
    user_invocable: bool = True
    model_invocable: bool = True
    source_label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "source_kind": self.source_kind,
            "description": self.description,
            "display_name": self.display_name,
            "argument_hint": self.argument_hint,
            "user_invocable": self.user_invocable,
            "model_invocable": self.model_invocable,
            "source_label": self.source_label,
        }
        if self.metadata:
            payload["metadata"] = deepcopy(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeAssemblyInvocationDiagnosticsSnapshot:
    name: str
    source_kind: str
    visible: bool
    user_invocable: bool
    model_invocable: bool
    hidden_reason: str | None = None
    matched_paths: tuple[str, ...] = ()
    path_match_state: str = "matched"
    narrowed_by_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched_paths", tuple(self.matched_paths))
        object.__setattr__(self, "narrowed_by_policy", deepcopy(dict(self.narrowed_by_policy)))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "source_kind": self.source_kind,
            "visible": self.visible,
            "user_invocable": self.user_invocable,
            "model_invocable": self.model_invocable,
            "hidden_reason": self.hidden_reason,
            "matched_paths": list(self.matched_paths),
            "path_match_state": self.path_match_state,
            "narrowed_by_policy": deepcopy(self.narrowed_by_policy),
        }
        if self.metadata:
            payload["metadata"] = deepcopy(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeAssemblyPostureReport:
    session_id: str
    default_model_route: str | None
    default_route_preflight: ModelRoutePreflightReport
    assembly_preset_provenance: dict[str, Any] = field(default_factory=dict)
    visible_invocations: tuple[RuntimeAssemblyVisibleInvocationSnapshot, ...] = ()
    invocation_diagnostics: tuple[RuntimeAssemblyInvocationDiagnosticsSnapshot, ...] = ()
    closure_status: str | None = None
    persistence_profile: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "assembly_preset_provenance", deepcopy(dict(self.assembly_preset_provenance)))
        object.__setattr__(self, "visible_invocations", tuple(self.visible_invocations))
        object.__setattr__(self, "invocation_diagnostics", tuple(self.invocation_diagnostics))
        object.__setattr__(self, "persistence_profile", deepcopy(dict(self.persistence_profile)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "default_model_route": self.default_model_route,
            "assembly_preset_provenance": deepcopy(self.assembly_preset_provenance),
            "visible_invocations": [entry.to_dict() for entry in self.visible_invocations],
            "invocation_diagnostics": [entry.to_dict() for entry in self.invocation_diagnostics],
            "default_route_preflight": self.default_route_preflight.to_dict(),
            "closure_status": self.closure_status,
            "persistence_profile": deepcopy(self.persistence_profile),
        }


@dataclass(slots=True)
class _WorkflowRunCollectorState:
    messages: list[RuntimeMessage] = field(default_factory=list)
    terminal: TurnTerminal | None = None
    turn_id: str | None = None
    final_status: str = "completed"
    workflow_observability: WorkflowRunObservability | None = None


class WorkflowRunReportStream:
    def __init__(
        self,
        *,
        runtime: "RuntimeAssembly",
        session: SessionController,
        prompt: str,
        metadata: dict[str, object] | None = None,
        session_owner: Literal["helper", "caller"],
        wait_for_finalization: bool = False,
    ) -> None:
        self._runtime = runtime
        self._session = session
        self._prompt = prompt
        self._metadata = dict(metadata) if metadata is not None else None
        self._session_owner = session_owner
        self._wait_for_finalization = wait_for_finalization
        self._collector = _WorkflowRunCollectorState()
        self._lock = asyncio.Lock()
        self._events: AsyncIterator[TurnStreamEvent] | None = None
        self._finalization_cursor: _WorkflowRunFinalizationCursor | None = None
        self._report: WorkflowRunReport | None = None
        self._failure: Exception | None = None
        self._started = False
        self._stream_advanced = False
        self._interrupt_requested = False
        self._explicit_close_requested = False
        self._iteration_finished = False
        self._iteration_owner: asyncio.Task[Any] | None = None

    def __aiter__(self) -> "WorkflowRunReportStream":
        return self

    async def __anext__(self) -> TurnStreamEvent:
        current_task = asyncio.current_task()
        if (
            self._iteration_owner is not None
            and current_task is not None
            and self._iteration_owner is not current_task
            and not self._iteration_finished
        ):
            raise RuntimeError(
                "WorkflowRunReportStream supports only one iteration consumer task"
            )
        if self._iteration_owner is None and current_task is not None:
            self._iteration_owner = current_task
        async with self._lock:
            if self._failure is not None:
                raise self._failure
            await self._ensure_started_locked()
            if self._iteration_finished:
                raise StopAsyncIteration
            try:
                return await self._advance_locked()
            except StopAsyncIteration:
                await self._finish_locked()
                raise
            except Exception as exc:
                await self._record_failure_locked(exc)
                raise

    async def report(self) -> WorkflowRunReport:
        async with self._lock:
            if self._report is not None:
                return self._report
            if self._failure is not None:
                raise self._failure
            await self._ensure_started_locked()
            await self._drain_locked(interrupt=False)
            assert self._report is not None  # pragma: no cover - set by _drain_locked()
            return self._report

    async def aclose(self) -> None:
        async with self._lock:
            if self._report is not None:
                return
            if self._failure is not None:
                raise self._failure
            await self._ensure_started_locked()
            await self._drain_locked(interrupt=True)

    async def __aenter__(self) -> "WorkflowRunReportStream":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        _ = exc_type, tb
        try:
            async with self._lock:
                if (
                    self._report is None
                    and self._failure is None
                    and not self._started
                ):
                    self._close_without_start_locked()
                    return
            await self.aclose()
        except Exception:
            if exc is None:
                raise

    def _close_without_start_locked(self) -> None:
        self._explicit_close_requested = True
        self._iteration_finished = True
        self._collector.final_status = "interrupted"
        self._report = _workflow_run_report_from_collector(
            self._session,
            self._collector,
            session_owner=self._session_owner,
            finalization=WorkflowRunFinalizationReport(),
        )
        if self._session_owner == "helper":
            _workflow_run_discard_unused_helper_owned_session(self._session)

    async def _ensure_started_locked(self) -> None:
        if self._started:
            return
        try:
            await self._runtime.wait_until_ready()
            self._finalization_cursor = _workflow_run_finalization_cursor(self._session)
            await self._runtime._prepare_one_shot_session(
                self._session,
                self._prompt,
                metadata=self._metadata,
            )
            self._events = self._session.stream_until_idle().__aiter__()
            self._started = True
        except Exception as exc:
            await self._record_failure_locked(exc)
            raise

    async def _advance_locked(self) -> TurnStreamEvent:
        if self._events is None:  # pragma: no cover - guarded by _ensure_started_locked()
            raise StopAsyncIteration
        event = await anext(self._events)
        self._stream_advanced = True
        _workflow_run_collect_event(self._collector, self._session, event)
        return event

    async def _drain_locked(self, *, interrupt: bool) -> None:
        if interrupt:
            self._explicit_close_requested = True
            if (
                self._stream_advanced
                and self._collector.terminal is None
                and not self._interrupt_requested
            ):
                self._session.interrupt("stream_close")
                self._interrupt_requested = True
        while not self._iteration_finished:
            try:
                event = await self._advance_locked()
            except StopAsyncIteration:
                await self._finish_locked()
                return
            except Exception as exc:
                await self._record_failure_locked(exc)
                raise
            if (
                interrupt
                and not self._interrupt_requested
                and event.event_type != TurnStreamEventType.TERMINAL
            ):
                self._session.interrupt("stream_close")
                self._interrupt_requested = True

    async def _finish_locked(self) -> None:
        if self._report is not None:
            self._iteration_finished = True
            return
        self._iteration_finished = True
        assert self._finalization_cursor is not None  # pragma: no cover - set on start
        self._report = await _workflow_run_complete_report(
            self._session,
            self._collector,
            session_owner=self._session_owner,
            wait_for_finalization=self._wait_for_finalization,
            include_consolidation=self._session_owner == "helper",
            finalization_cursor=self._finalization_cursor,
        )
        if self._explicit_close_requested and self._session_owner == "caller":
            _workflow_run_reset_caller_owned_session(self._session)

    async def _record_failure_locked(self, exc: Exception) -> None:
        if self._failure is not None:
            return
        self._failure = exc
        self._iteration_finished = True
        self._collector.final_status = _helper_session_close_status(
            self._session,
            terminal=self._collector.terminal,
            default="failed",
        )
        if self._session_owner == "helper":
            try:
                await self._session.close(final_status=self._collector.final_status)
            except Exception:
                pass
        elif self._explicit_close_requested:
            _workflow_run_reset_caller_owned_session(self._session)


@dataclass(frozen=True, slots=True)
class _WorkflowRunFinalizationCursor:
    extraction_count: int = 0
    consolidation_count: int = 0


@dataclass(frozen=True, slots=True)
class _CachedSkillRoot:
    fingerprint: tuple[tuple[str, str], ...] = ()
    skills: tuple[SkillDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class _ResolvedPackageInvocationProvider:
    manifest: RuntimePackageManifest
    contribution: InvocationProviderContribution
    provider: Any
    package_index: int
    contribution_index: int

    @property
    def registration_key(self) -> tuple[int, int, int, str]:
        return (
            self.contribution.order,
            self.package_index,
            self.contribution_index,
            self.contribution.name,
        )


class _SessionSkillViewResolver:
    def __init__(
        self,
        *,
        session_cwd: Path,
        base_registry: SkillRegistry,
    ) -> None:
        self._session_cwd = session_cwd.resolve()
        self._base_registry = base_registry
        self._skill_cache: dict[str, _CachedSkillRoot] = {}

    def resolve(self, context: InvocationResolutionContext) -> tuple[SkillDefinition, ...]:
        merged: tuple[SkillDefinition, ...] = self._base_registry.definitions()
        root_records = _discover_dynamic_skill_root_records(
            session_cwd=self._session_cwd,
            observed_paths=context.observed_paths,
            existing=context.metadata.get(SKILL_DYNAMIC_ROOTS_KEY),
        )
        for record in root_records:
            merged = _merge_skill_definitions(
                merged,
                self._load_root(
                    Path(str(record["root"])),
                    source=_coerce_definition_source(record.get("source")),
                ),
            )
        return merged

    def root_records(
        self,
        *,
        observed_paths: tuple[str, ...] | list[str] = (),
        existing: Any = None,
    ) -> tuple[dict[str, Any], ...]:
        return _discover_dynamic_skill_root_records(
            session_cwd=self._session_cwd,
            observed_paths=tuple(str(path) for path in observed_paths),
            existing=existing,
        )

    def _load_root(
        self,
        root: Path,
        *,
        source: DefinitionSource,
    ) -> tuple[SkillDefinition, ...]:
        resolved_root = root.resolve()
        cache_key = str(resolved_root)
        fingerprint = _skill_root_fingerprint(resolved_root)
        cached = self._skill_cache.get(cache_key)
        if cached is not None and cached.fingerprint == fingerprint:
            return cached.skills

        report = DefinitionDiscovery(
            (
                DefinitionSourcePaths(
                    source=source,
                    root=resolved_root.parent,
                    skills_subdir=resolved_root.name,
                ),
            )
        ).discover()
        loaded: list[SkillDefinition] = []
        for skill in report.skills:
            metadata = dict(skill.metadata)
            metadata["dynamic_root"] = cache_key
            loaded.append(
                replace(
                    skill,
                    metadata=metadata,
                    origin=DefinitionOrigin(
                        source=source,
                        path=skill.origin.path,
                        root=resolved_root,
                    ),
                )
            )
        cached_entry = _CachedSkillRoot(
            fingerprint=fingerprint,
            skills=tuple(loaded),
        )
        self._skill_cache[cache_key] = cached_entry
        return cached_entry.skills


def _skill_root_fingerprint(root: Path) -> tuple[tuple[str, str], ...]:
    if not root.exists():
        return (("__missing__", ""),)
    if not root.is_dir():
        return (("__not_a_directory__", ""),)
    fingerprint: list[tuple[str, str]] = []
    for skill_path in sorted(root.rglob("SKILL.md")):
        relative = str(skill_path.relative_to(root))
        try:
            digest = hashlib.sha1(skill_path.read_bytes()).hexdigest()
        except OSError:
            digest = "__unreadable__"
        fingerprint.append((relative, digest))
    return tuple(fingerprint)


class _UnconfiguredModelClient:
    def _error(self) -> RuntimeError:
        return RuntimeError("RuntimeConfig.model_client is required for runnable turn execution")

    async def complete(self, request: ModelRequest):  # pragma: no cover - defensive boundary
        _ = request
        raise self._error()

    async def stream(self, request: ModelRequest):
        _ = request
        raise self._error()
        if False:  # pragma: no cover - marks this as an async generator
            yield None


@dataclass(slots=True)
class RuntimeAssembly:
    kernel: RuntimeKernel
    services: RuntimeServices
    turn_engine: TurnEngine
    agent_runtime: AgentRuntime
    skill_executor: SkillExecutor
    transcript_store: TranscriptStore
    _task_manager: TaskManager | None
    job_service: DefaultJobService
    teammates: Any = None
    system_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __getattribute__(self, name: str) -> Any:
        capability_key = _COMPATIBILITY_RUNTIME_ASSEMBLY_PROJECTIONS.get(name)
        if capability_key is not None:
            # RuntimeAssembly keeps team_* projections as compatibility-only views.
            fallback = object.__getattribute__(self, name)
            services = object.__getattribute__(self, "services")
            if services is None:
                return fallback
            return services.resolve_capability(capability_key, fallback)
        return object.__getattribute__(self, name)

    def query_assembly_view(self) -> dict[str, Any]:
        keys = (
            "distribution",
            "first_party_packages",
            "first_party_package_catalog",
            "official_package_catalog_provenance",
            "resolved_active_package_graph_provenance",
            "assembly_preset_provenance",
            "closure_report",
            "protocol_only_conformance",
            "package_resolution",
            "package_manifests",
            "package_registration",
        )
        return {
            key: deepcopy(self.metadata.get(key))
            for key in keys
        }

    def query_closure_report(self) -> dict[str, Any]:
        return deepcopy(self.metadata.get("closure_report", {}))

    def query_assembly_preset_provenance(self) -> dict[str, Any]:
        value = self.metadata.get("assembly_preset_provenance")
        return deepcopy(value) if isinstance(value, Mapping) else {}

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

    @property
    def task_manager(self) -> TaskManager:
        if self._task_manager is None:
            self._task_manager = self.services.task_manager
        self.services.record_compatibility_usage(
            family="task_manager",
            surface="RuntimeAssembly.task_manager",
            access_label="TaskManager",
        )
        return self._task_manager

    def bind_host(self, host: HostAdapter) -> BoundHostRuntime:
        self.services.bind_host(host)
        return BoundHostRuntime(
            kernel=self.kernel,
            host=host,
            runtime=self,
            services=self.services,
        )

    def resolve_capability(self, key: str, default: Any = None) -> Any:
        return self.services.resolve_capability(key, default)

    def resolve_host_facet(self, name: str) -> Any:
        return self.services.resolve_host_facet(name)

    async def wait_until_ready(self) -> tuple[dict[str, Any], ...]:
        if self.services is None or not hasattr(self.services, "wait_until_runtime_ready"):
            return ()
        return await self.services.wait_until_runtime_ready()

    async def preflight_model_route(
        self,
        route_name: str | None = None,
        *,
        deeper_probe: bool = False,
    ) -> ModelRoutePreflightReport:
        return await _preflight_model_route(
            self.kernel.config,
            route_name=route_name,
            deeper_probe=deeper_probe,
        )

    async def preflight_default_model_route(
        self,
        *,
        deeper_probe: bool = False,
    ) -> ModelRoutePreflightReport:
        return await self.preflight_model_route(
            route_name=None,
            deeper_probe=deeper_probe,
        )

    async def query_assembly_posture(
        self,
        session: SessionController,
        *,
        deeper_probe: bool = False,
    ) -> RuntimeAssemblyPostureReport:
        catalog = self.resolve_session_invocations(session)
        preflight = await self.preflight_default_model_route(deeper_probe=deeper_probe)
        closure_report = self.query_closure_report()
        return RuntimeAssemblyPostureReport(
            session_id=session.state.session_id,
            default_model_route=self.kernel.config.default_model_route,
            default_route_preflight=preflight,
            assembly_preset_provenance=self.query_assembly_preset_provenance(),
            visible_invocations=tuple(
                _visible_invocation_snapshot(entry) for entry in catalog.visible_capabilities()
            ),
            invocation_diagnostics=tuple(
                _invocation_diagnostics_snapshot(entry) for entry in catalog.diagnostics
            ),
            closure_status=_coerce_optional_string(closure_report.get("status")),
            persistence_profile=self.query_persistence_profile(),
        )

    def bind_hook_callback(self, name: str, handler: Any) -> None:
        self.services.hook_bus.bind_callback(name, handler)

    @property
    def hooks(self) -> ConfiguredHookRegistrar:
        return build_configured_hook_registrar(
            bus=self.services.hook_bus,
            source_kind=HookSourceKind.RUNTIME_CONFIG,
            owner=lambda: f"weavert:{self.kernel.config.runtime_id}",
            source_ref=lambda: self.kernel.config.runtime_id,
            session_id=None,
            turn_id=None,
            default_scope_lifetime=HookScopeLifetime.SESSION_TEMPLATE,
            list_hooks=self.list_hooks,
            list_hook_dispatch_traces=self.list_hook_dispatch_traces,
        )

    def register_hook(
        self,
        request: HookRegistrationRequest | dict[str, Any],
    ) -> Any:
        return self.hooks.raw.register(request)

    def list_hooks(
        self,
        query: HookInventoryQuery | dict[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        return self.services.hook_bus.list_hooks(query)

    def list_hook_dispatch_traces(
        self,
        query: HookDispatchTraceQuery | dict[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        return self.services.hook_bus.list_hook_dispatch_traces(query)

    def resolve_invocations(
        self,
        *,
        session_id: str,
        cwd: str | Path | None = None,
        messages: tuple[RuntimeMessage, ...] | list[RuntimeMessage] = (),
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
        turn_id: str | None = None,
    ) -> ResolvedInvocationCatalog:
        resolved_cwd = Path(cwd) if cwd is not None else self.kernel.config.working_directory
        return self.turn_engine.resolve_invocation_catalog(
            session_id=session_id,
            turn_id=turn_id,
            cwd=resolved_cwd,
            messages=tuple(messages),
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=runtime_context,
        )

    def resolve_session_invocations(
        self,
        session: SessionController,
        *,
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> ResolvedInvocationCatalog:
        return self.resolve_invocations(
            session_id=session.state.session_id,
            turn_id=session.state.active_turn_id,
            cwd=session.cwd,
            messages=session.messages,
            prompt_context=prompt_context or session.current_prompt_context(),
            private_context=private_context or session.current_private_context(),
            runtime_context=runtime_context,
        )

    def visible_invocations(
        self,
        session: SessionController,
        *,
        user_invocable: bool | None = None,
        model_invocable: bool | None = None,
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> tuple[InvocationCapabilityView, ...]:
        catalog = self.resolve_session_invocations(
            session,
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=runtime_context,
        )
        return catalog.visible_capabilities(
            user_invocable=user_invocable,
            model_invocable=model_invocable,
        )

    def invocation_diagnostics(
        self,
        session: SessionController,
        *,
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> tuple[InvocationDiagnostics, ...]:
        catalog = self.resolve_session_invocations(
            session,
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=runtime_context,
        )
        return catalog.diagnostics

    async def resolve_task_list_id(
        self,
        *,
        session_id: str,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> str:
        return await self.services.task_list_service.resolve_list_id(
            session_id=session_id,
            private_context=_merged_private_context(private_context, runtime_context),
        )

    async def create_task(
        self,
        *,
        subject: str,
        description: str | None = None,
        active_form: str | None = None,
        owner: str | None = None,
        blocks: tuple[str, ...] | list[str] = (),
        blocked_by: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="create_task requires either list_id or session_id",
        )
        try:
            task = await self.services.task_list_service.create(
                resolved_list_id,
                subject=subject,
                description=description,
                active_form=active_form,
                owner=owner,
                blocks=blocks,
                blocked_by=blocked_by,
                metadata=metadata,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {
            "task_list_id": resolved_list_id,
            "task": await self._task_payload(resolved_list_id, task.task_id),
        }

    async def get_task(
        self,
        task_id: str,
        *,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="get_task requires either list_id or session_id",
        )
        task = await self.services.task_list_service.get_orchestration_task(
            resolved_list_id,
            task_id,
            include_archived=True,
        )
        if task is None:
            return _structured_task_error(
                "not_found",
                f"Task '{task_id}' was not found",
                task_list_id=resolved_list_id,
                task_id=task_id,
            )
        return {"task_list_id": resolved_list_id, "task": task_list_entry_to_dict(task)}

    async def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        subject: str | None = None,
        description: Any = _UNSET,
        active_form: Any = _UNSET,
        metadata: Mapping[str, Any] | None = None,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="update_task requires either list_id or session_id",
        )
        patch: dict[str, Any] = {}
        if status is not None:
            patch["status"] = status
        if subject is not None:
            patch["subject"] = subject
        if description is not _UNSET:
            patch["description"] = description
        if active_form is not _UNSET:
            patch["active_form"] = active_form
        if metadata is not None:
            patch["metadata"] = dict(metadata)
        if not patch:
            return _structured_task_error(
                "invalid_request",
                "task_update requires at least one supported mutable field",
                task_list_id=resolved_list_id,
                task_id=task_id,
            )
        try:
            task = await self.services.task_list_service.update(
                resolved_list_id,
                task_id,
                patch=patch,
                strict_single_in_progress=self._task_discipline_policy(
                    private_context=private_context,
                    runtime_context=runtime_context,
                ).strict_single_in_progress,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {
            "task_list_id": resolved_list_id,
            "task": await self._task_payload(resolved_list_id, task.task_id),
        }

    async def claim_task(
        self,
        task_id: str,
        *,
        owner: str | None = None,
        set_in_progress: bool = True,
        enforce_owner_busy: bool = False,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="claim_task requires either list_id or session_id",
        )
        try:
            task = await self.services.task_list_service.claim(
                resolved_list_id,
                task_id,
                owner,
                set_in_progress=set_in_progress,
                enforce_owner_busy=enforce_owner_busy,
                strict_single_in_progress=self._task_discipline_policy(
                    private_context=private_context,
                    runtime_context=runtime_context,
                ).strict_single_in_progress,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {
            "task_list_id": resolved_list_id,
            "task": await self._task_payload(resolved_list_id, task.task_id),
        }

    async def release_task(
        self,
        task_id: str,
        *,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="release_task requires either list_id or session_id",
        )
        try:
            task = await self.services.task_list_service.release(
                resolved_list_id,
                task_id,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {
            "task_list_id": resolved_list_id,
            "task": await self._task_payload(resolved_list_id, task.task_id),
        }

    async def assign_next_task(
        self,
        *,
        owner: str | None = None,
        set_in_progress: bool = True,
        enforce_owner_busy: bool = False,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="assign_next_task requires either list_id or session_id",
        )
        try:
            task = await self.services.task_list_service.assign_next(
                resolved_list_id,
                owner,
                set_in_progress=set_in_progress,
                enforce_owner_busy=enforce_owner_busy,
                strict_single_in_progress=self._task_discipline_policy(
                    private_context=private_context,
                    runtime_context=runtime_context,
                ).strict_single_in_progress,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {
            "task_list_id": resolved_list_id,
            "task": (
                await self._task_payload(resolved_list_id, task.task_id)
                if task is not None
                else None
            ),
        }

    async def block_task(
        self,
        *,
        blocker_task_id: str,
        blocked_task_id: str,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="block_task requires either list_id or session_id",
        )
        try:
            blocker_task, blocked_task = await self.services.task_list_service.add_dependency(
                resolved_list_id,
                blocker_task_id,
                blocked_task_id,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {
            "task_list_id": resolved_list_id,
            "blocker_task": await self._task_payload(resolved_list_id, blocker_task.task_id),
            "blocked_task": await self._task_payload(resolved_list_id, blocked_task.task_id),
        }

    async def unblock_task(
        self,
        *,
        blocker_task_id: str,
        blocked_task_id: str,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="unblock_task requires either list_id or session_id",
        )
        try:
            blocker_task, blocked_task = await self.services.task_list_service.remove_dependency(
                resolved_list_id,
                blocker_task_id,
                blocked_task_id,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {
            "task_list_id": resolved_list_id,
            "blocker_task": await self._task_payload(resolved_list_id, blocker_task.task_id),
            "blocked_task": await self._task_payload(resolved_list_id, blocked_task.task_id),
        }

    async def archive_task(
        self,
        task_id: str,
        *,
        archived_by: str | None = None,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="archive_task requires either list_id or session_id",
        )
        try:
            task = await self.services.task_list_service.archive(
                resolved_list_id,
                task_id,
                archived_by=archived_by,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {
            "task_list_id": resolved_list_id,
            "task": await self._task_payload(resolved_list_id, task.task_id),
        }

    async def unarchive_task(
        self,
        task_id: str,
        *,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="unarchive_task requires either list_id or session_id",
        )
        try:
            task = await self.services.task_list_service.unarchive(
                resolved_list_id,
                task_id,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {
            "task_list_id": resolved_list_id,
            "task": await self._task_payload(resolved_list_id, task.task_id),
        }

    async def delete_task(
        self,
        task_id: str,
        *,
        list_id: str | None = None,
        session_id: str | None = None,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        resolved_list_id = await self._resolve_task_target(
            list_id=list_id,
            session_id=session_id,
            private_context=private_context,
            runtime_context=runtime_context,
            required_message="delete_task requires either list_id or session_id",
        )
        task = await self.services.task_list_service.get_orchestration_task(
            resolved_list_id,
            task_id,
            include_archived=True,
        )
        if task is None:
            return _structured_task_error(
                "not_found",
                f"Task '{task_id}' was not found",
                task_list_id=resolved_list_id,
                task_id=task_id,
            )
        try:
            await self.services.task_list_service.delete(
                resolved_list_id,
                task_id,
            )
        except TaskListError as exc:
            return _task_list_error_result(exc)
        return {"task_list_id": resolved_list_id, "task": task_list_entry_to_dict(task)}

    async def list_task_lists(
        self,
        *,
        session_id: str | None = None,
        list_id: str | None = None,
        include_archived: bool = False,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        if list_id is not None or session_id is not None:
            resolved_list_id = list_id or await self.resolve_task_list_id(
                session_id=str(session_id),
                private_context=private_context,
                runtime_context=runtime_context,
            )
            snapshot = await self.services.task_list_service.get_orchestration_snapshot(
                resolved_list_id,
                include_archived=include_archived,
            )
            return (task_list_snapshot_to_dict(snapshot),)
        snapshots = await self.services.task_list_service.list_snapshots()
        results: list[dict[str, Any]] = []
        for snapshot in snapshots:
            orchestration = await self.services.task_list_service.get_orchestration_snapshot(
                snapshot.list_id,
                include_archived=include_archived,
            )
            results.append(task_list_snapshot_to_dict(orchestration))
        return tuple(results)

    async def get_task_list(
        self,
        *,
        list_id: str | None = None,
        session_id: str | None = None,
        include_archived: bool = False,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        if list_id is None and session_id is None:
            raise ValueError("get_task_list requires either list_id or session_id")
        resolved_list_id = list_id or await self.resolve_task_list_id(
            session_id=str(session_id),
            private_context=private_context,
            runtime_context=runtime_context,
        )
        snapshot = await self.services.task_list_service.get_orchestration_snapshot(
            resolved_list_id,
            include_archived=include_archived,
        )
        return task_list_snapshot_to_dict(snapshot)

    async def watch_task_list(
        self,
        *,
        callback: Any,
        list_id: str | None = None,
        session_id: str | None = None,
        include_archived: bool = False,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> Any:
        if list_id is None and session_id is None:
            raise ValueError("watch_task_list requires either list_id or session_id")
        resolved_list_id = list_id or await self.resolve_task_list_id(
            session_id=str(session_id),
            private_context=private_context,
            runtime_context=runtime_context,
        )

        async def emit(snapshot: Any) -> Any:
            orchestration = await self.services.task_list_service.get_orchestration_snapshot(
                snapshot.list_id,
                include_archived=include_archived,
            )
            return callback(task_list_snapshot_to_dict(orchestration))

        return await self.services.task_list_service.watch(resolved_list_id, emit)

    async def list_jobs(
        self,
        *,
        session_id: str | None = None,
        team_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        jobs = await self.services.job_service.list(
            scope=JobScopeFilter(session_id=session_id, team_id=team_id)
            if session_id is not None or team_id is not None
            else None
        )
        return tuple(_serialize_job(job) for job in jobs)

    async def get_job(
        self,
        job_id: str,
        *,
        session_id: str | None = None,
        team_id: str | None = None,
    ) -> dict[str, Any] | None:
        job = await self.services.job_service.get(
            job_id,
            scope=JobScopeFilter(session_id=session_id, team_id=team_id)
            if session_id is not None or team_id is not None
            else None,
        )
        return None if job is None else _serialize_job(job)

    async def watch_jobs(
        self,
        *,
        callback: Any,
        session_id: str | None = None,
        team_id: str | None = None,
    ) -> Any:
        return await self.services.job_service.watch(
            callback=lambda snapshot: callback([_serialize_job(job) for job in snapshot]),
            scope=JobScopeFilter(session_id=session_id, team_id=team_id)
            if session_id is not None or team_id is not None
            else None,
        )

    async def stop_job(
        self,
        job_id: str,
        *,
        session_id: str | None = None,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        job = await self.services.job_service.stop(
            job_id,
            scope=JobScopeFilter(session_id=session_id, team_id=team_id)
            if session_id is not None or team_id is not None
            else None,
        )
        return _serialize_job(job)

    async def list_team_workflows(
        self,
        *,
        team_id: str | None = None,
        session_id: str | None = None,
        pending_only: bool | None = True,
    ) -> tuple[dict[str, Any], ...]:
        await self.wait_until_ready()
        facet = self.services.resolve_team_workflow_host_facet()
        if facet.available and facet.facet is not None and (team_id is not None or session_id is not None):
            records = await facet.facet.list_workflows(
                team_id=team_id,
                session_id=session_id,
                pending_only=pending_only,
            )
            return tuple(_serialize_team_workflow_record(record) for record in records)
        service = self.services.resolve_team_workflows()
        if service is None:
            return ()
        resolved_team_id = team_id
        team_control_plane = self.services.resolve_team_control_plane()
        if resolved_team_id is None and session_id is not None and team_control_plane is not None:
            team = team_control_plane.active_team_for_leader_session(session_id)
            if team is not None:
                resolved_team_id = team.team_id
        records = service.list_workflows(team_id=resolved_team_id, pending_only=pending_only)
        return tuple(_serialize_team_workflow_record(record) for record in records)

    async def respond_team_workflow(
        self,
        workflow_id: str,
        *,
        action: str,
        host_name: str | None = None,
        payload: Mapping[str, Any] | None = None,
        team_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        await self.wait_until_ready()
        facet = self.services.resolve_team_workflow_host_facet()
        if facet.available and facet.facet is not None and (team_id is not None or session_id is not None):
            record = await facet.facet.respond(
                workflow_id,
                action=action,
                host_name=host_name,
                payload=None if payload is None else dict(payload),
                team_id=team_id,
                session_id=session_id,
            )
            return _serialize_team_workflow_record(record)
        service = self.services.resolve_team_workflows()
        if service is None:
            raise RuntimeError("Runtime team workflow service is not configured")
        record = await service.respond_host(
            workflow_id=workflow_id,
            action=action,
            host_name=host_name,
            payload=payload,
        )
        return _serialize_team_workflow_record(record)

    def create_session(
        self,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        close_callback: Any = None,
    ) -> SessionController:
        selected_agent = self._resolve_agent(agent_name or self.kernel.config.default_agent)
        session_cwd = Path(cwd) if cwd is not None else self.kernel.config.working_directory
        return SessionController(
            session_id=session_id or uuid4().hex,
            agent=selected_agent,
            turn_engine=self.turn_engine,
            transcript_store=self.transcript_store,
            cwd=str(session_cwd),
            system_prompt=self.system_prompt if system_prompt is None else system_prompt,
            runtime_services=self.services,
            close_callback=close_callback,
            assembly_posture_reporter=self.query_assembly_posture,
        )

    def stream_prompt_report(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
        wait_for_finalization: bool = False,
    ) -> WorkflowRunReportStream:
        session = self.create_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
        )
        return WorkflowRunReportStream(
            runtime=self,
            session=session,
            prompt=prompt,
            metadata=metadata,
            session_owner="helper",
            wait_for_finalization=wait_for_finalization,
        )

    def stream_prompt_report_in_session(
        self,
        session: SessionController,
        prompt: str,
        *,
        metadata: dict[str, object] | None = None,
        wait_for_finalization: bool = False,
    ) -> WorkflowRunReportStream:
        return WorkflowRunReportStream(
            runtime=self,
            session=session,
            prompt=prompt,
            metadata=metadata,
            session_owner="caller",
            wait_for_finalization=wait_for_finalization,
        )

    async def run_prompt_report(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
        wait_for_finalization: bool = False,
    ) -> WorkflowRunReport:
        return await self.stream_prompt_report(
            prompt,
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
            metadata=metadata,
            wait_for_finalization=wait_for_finalization,
        ).report()

    async def run_prompt_report_in_session(
        self,
        session: SessionController,
        prompt: str,
        *,
        metadata: dict[str, object] | None = None,
        wait_for_finalization: bool = False,
    ) -> WorkflowRunReport:
        return await self.stream_prompt_report_in_session(
            session,
            prompt,
            metadata=metadata,
            wait_for_finalization=wait_for_finalization,
        ).report()

    async def run_prompt(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> tuple[RuntimeMessage, ...]:
        report = await self.run_prompt_report(
            prompt,
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
            metadata=metadata,
        )
        return report.messages

    async def stream_prompt(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AsyncIterator[TurnStreamEvent]:
        stream = self.stream_prompt_report(
            prompt,
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
            metadata=metadata,
        )
        async with stream as report_stream:
            async for event in report_stream:
                yield event

    async def _run_prompt_in_session(
        self,
        session: SessionController,
        prompt: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> tuple[RuntimeMessage, ...]:
        report = await self._run_prompt_report_in_session(
            session,
            prompt,
            metadata=metadata,
            session_owner="caller",
        )
        return report.messages

    async def _run_prompt_report_in_session(
        self,
        session: SessionController,
        prompt: str,
        *,
        metadata: dict[str, object] | None = None,
        session_owner: Literal["helper", "caller"],
        wait_for_finalization: bool = False,
    ) -> WorkflowRunReport:
        stream = WorkflowRunReportStream(
            runtime=self,
            session=session,
            prompt=prompt,
            metadata=metadata,
            session_owner=session_owner,
            wait_for_finalization=wait_for_finalization,
        )
        return await stream.report()

    async def _prepare_one_shot_session(
        self,
        session: SessionController,
        prompt: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await session.resume()
        await session.start()
        session.enqueue_event(
            InboundEvent(
                InboundEventType.USER_PROMPT,
                prompt,
                metadata=metadata or {},
            )
        )

    async def run_agent_tool(
        self,
        agent_name: str,
        prompt: str,
        context: ToolContext,
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
    ) -> dict[str, Any]:
        metadata = _merged_private_context(context.private_context, dict(context.metadata)).compat_metadata()
        metadata.setdefault("submitted_by", context.agent_name)
        if reason is not None:
            metadata["delegation_reason"] = reason
        normalized_model_route = _coerce_optional_string(model_route)
        if (
            normalized_model_route is not None
            and normalized_model_route not in self.kernel.config.model_routes
        ):
            raise ValueError(f"Unknown model route: {normalized_model_route}")
        try:
            result = await self.agent_runtime.invoke(
                AgentInvocation(
                    agent_name=agent_name,
                    prompt=prompt,
                    session_id=context.session_id,
                    cwd=_resolve_invocation_cwd(context.cwd, cwd),
                    background=background,
                    query_source="agent_tool",
                    spawn_mode=_coerce_spawn_mode(spawn_mode),
                    parent_run_id=_coerce_optional_string(metadata.get("run_id")),
                    parent_turn_id=context.turn_id,
                    requested_model_route=normalized_model_route,
                    requested_model=_coerce_optional_string(model),
                    requested_permission_mode=_coerce_permission_mode(permission_mode),
                    requested_isolation=_coerce_isolation_mode(isolation),
                    max_turns=max_turns,
                    parent_tool_pool=context.tool_pool,
                    parent_skill_pool=context.skill_pool,
                    metadata=metadata,
                )
            )
        except DelegationPolicyError as exc:
            return _delegation_policy_error_result(exc)
        return _serialize_agent_run_result(result, runtime_metadata=self.services.metadata)

    async def run_skill_tool(
        self,
        skill_name: str,
        arguments: list[str] | tuple[str, ...],
        context: ToolContext,
    ) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
        metadata = _merged_private_context(context.private_context, dict(context.metadata)).compat_metadata()
        try:
            result = await self.skill_executor.execute(
                skill_name,
                arguments=tuple(arguments),
                session_id=context.session_id,
                cwd=context.cwd,
                parent_tool_pool=context.tool_pool,
                parent_skill_pool=context.skill_pool,
                permission_context=context.permission_context,
                turn_id=context.turn_id,
                parent_run_id=_coerce_optional_string(metadata.get("run_id")),
                policy_state=policy_state_from_metadata(metadata),
                runtime_metadata=metadata,
            )
        except DelegationPolicyError as exc:
            return _delegation_policy_error_result(exc)
        return _serialize_skill_execution_result(result, runtime_metadata=self.services.metadata)

    def _resolve_agent(self, agent_name: str) -> AgentDefinition:
        agent = self.kernel.agent_registry.get(agent_name)
        if agent is None:
            raise KeyError(agent_name)
        return agent

    async def _resolve_task_target(
        self,
        *,
        list_id: str | None,
        session_id: str | None,
        private_context: RuntimePrivateContext | dict[str, object] | None,
        runtime_context: dict[str, object] | None,
        required_message: str,
    ) -> str:
        if list_id is not None:
            return list_id
        if session_id is None:
            raise ValueError(required_message)
        return await self.resolve_task_list_id(
            session_id=str(session_id),
            private_context=private_context,
            runtime_context=runtime_context,
        )

    async def _task_payload(self, list_id: str, task_id: str) -> dict[str, Any]:
        task = await self.services.task_list_service.get_orchestration_task(
            list_id,
            task_id,
            include_archived=True,
        )
        if task is None:
            raise ValueError(f"Task '{task_id}' was not found in task list '{list_id}'")
        return task_list_entry_to_dict(task)

    def _task_discipline_policy(
        self,
        *,
        private_context: RuntimePrivateContext | dict[str, object] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> TaskDisciplinePolicy:
        runtime_metadata: dict[str, Any] = dict(getattr(self.services, "metadata", {}) or {})
        if runtime_context:
            runtime_metadata.update(runtime_context)
        return TaskDisciplinePolicy.resolve(
            private_context=_merged_private_context(private_context, runtime_context),
            runtime_metadata=runtime_metadata or None,
        )


def _discover_dynamic_skill_root_records(
    *,
    session_cwd: Path,
    observed_paths: tuple[str, ...] | list[str],
    existing: Any = None,
) -> tuple[dict[str, Any], ...]:
    ledger: dict[str, dict[str, Any]] = {}
    for record in _coerce_dynamic_skill_root_records(existing):
        ledger[record["root"]] = record
    for observed_path in observed_paths:
        for root in _discover_roots_for_observed_path(
            session_cwd=session_cwd,
            observed_path=str(observed_path),
        ):
            entry = ledger.setdefault(
                root,
                {
                    "root": root,
                    "source": DefinitionSource.PROJECT.value,
                    "discovered_from": [],
                },
            )
            discovered_from = {
                str(path)
                for path in entry.get("discovered_from", ())
                if isinstance(path, str) and path.strip()
            }
            discovered_from.add(str(observed_path))
            entry["discovered_from"] = sorted(discovered_from)
    return tuple(
        ledger[root]
        for root in sorted(
            ledger,
            key=lambda candidate: (len(Path(candidate).parts), candidate),
        )
    )


def _coerce_dynamic_skill_root_records(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        root = str(item.get("root") or "").strip()
        if not root:
            continue
        normalized.append(
            {
                "root": str(Path(root).resolve()),
                "source": str(item.get("source") or DefinitionSource.PROJECT.value),
                "discovered_from": sorted(
                    {
                        str(path)
                        for path in item.get("discovered_from", ())
                        if str(path).strip()
                    }
                ),
            }
        )
    return tuple(normalized)


def _discover_roots_for_observed_path(
    *,
    session_cwd: Path,
    observed_path: str,
) -> tuple[str, ...]:
    resolved_path = _resolve_path_within_cwd(session_cwd, observed_path)
    if resolved_path is None:
        return ()
    cursor = resolved_path if resolved_path.is_dir() else resolved_path.parent
    resolved_cwd = session_cwd.resolve()
    discovered: list[str] = []
    while True:
        for candidate in workspace_skill_root_candidates(cursor):
            candidate = candidate.resolve()
            if candidate.is_dir():
                discovered.append(str(candidate))
        if cursor == resolved_cwd:
            break
        if resolved_cwd not in cursor.parents:
            break
        cursor = cursor.parent
    return tuple(dict.fromkeys(discovered))


def _resolve_path_within_cwd(session_cwd: Path, value: str) -> Path | None:
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (session_cwd / candidate).resolve()
    try:
        resolved.relative_to(session_cwd.resolve())
    except ValueError:
        return None
    return resolved


def _merge_skill_definitions(
    current: tuple[SkillDefinition, ...],
    incoming: tuple[SkillDefinition, ...],
) -> tuple[SkillDefinition, ...]:
    merged: dict[str, SkillDefinition] = {skill.name: skill for skill in current}
    for skill in incoming:
        existing = merged.get(skill.name)
        if existing is None or _prefer_skill_definition(skill, existing):
            merged[skill.name] = skill
    return tuple(merged.values())


def _prefer_skill_definition(incoming: SkillDefinition, existing: SkillDefinition) -> bool:
    if incoming.origin.priority != existing.origin.priority:
        return incoming.origin.priority > existing.origin.priority
    if incoming.origin.source == existing.origin.source:
        incoming_specificity = _root_specificity(incoming.origin.root)
        existing_specificity = _root_specificity(existing.origin.root)
        if incoming_specificity != existing_specificity:
            return incoming_specificity > existing_specificity
    return incoming.origin.label < existing.origin.label


def _root_specificity(root: Path | None) -> int:
    if root is None:
        return -1
    return len(root.resolve().parts)


def _coerce_definition_source(value: Any) -> DefinitionSource:
    if isinstance(value, DefinitionSource):
        return value
    try:
        return DefinitionSource(str(value))
    except ValueError:
        return DefinitionSource.PROJECT


def _legacy_compatibility_profile(config: RuntimeConfig) -> LegacyCompatibilityProfile:
    return resolve_legacy_compatibility_profile(config.legacy_compatibility)


def build_runtime_kernel(config: RuntimeConfig) -> RuntimeKernel:
    resolved_distribution = config.resolved_distribution()
    selected_packages = config.selected_first_party_packages()
    first_party_manifests = official_runtime_package_manifests(selected_packages)
    package_registration = register_external_runtime_package_manifests(
        config.extra_package_manifests,
        selected_first_party_manifests=first_party_manifests,
    )
    package_request = build_runtime_package_request(
        distribution=resolved_distribution.value,
        baseline_packages=distribution_spec(resolved_distribution).packages,
        enabled_packages=config.enabled_packages,
        disabled_packages=config.disabled_packages,
        explicit_package_requests=config.requested_packages,
        selected_first_party_packages=tuple(manifest.name for manifest in first_party_manifests),
        first_party_package_names=official_runtime_package_names(),
    )
    package_catalog = build_runtime_package_catalog(
        first_party_manifests,
        package_registration,
    )
    package_resolution = resolve_runtime_package_graph(package_request, package_catalog)
    if not package_resolution.success:
        raise RuntimePackageResolutionError(package_resolution)
    package_manifests = package_resolution.resolved_manifests
    builtin_package_contributions = _assemble_package_contributions(
        package_manifests,
        stage=PackageAssemblyStage.BUILTINS,
        config=config,
        distribution=resolved_distribution.value,
        working_directory=config.working_directory,
    )
    package_service_contributions = _assemble_package_contributions(
        package_manifests,
        stage=PackageAssemblyStage.SERVICES,
        config=config,
        distribution=resolved_distribution.value,
        working_directory=config.working_directory,
    )
    config = _publish_runtime_assembly_preset_metadata(config)
    config = _with_package_model_binding_baseline(
        config,
        package_service_contributions=package_service_contributions,
    )
    legacy_profile = _legacy_compatibility_profile(config)
    tool_registry = ToolRegistry()
    agent_registry = AgentRegistry(
        allow_legacy_agent_hooks=legacy_profile.is_enabled("agent_owned_hooks")
    )
    skill_registry = SkillRegistry()
    invocation_registry = InvocationRegistry()
    skill_view_resolver = _SessionSkillViewResolver(
        session_cwd=config.working_directory,
        base_registry=skill_registry,
    )
    diagnostics: list[Diagnostic] = list(package_registration.as_diagnostics())

    builtin_tools, builtin_agents, builtin_skills, builtin_diagnostics = _collect_package_builtins(
        builtin_package_contributions
    )
    diagnostics.extend(builtin_diagnostics)
    _register_builtin_tools(tool_registry, config, builtin_tools, diagnostics)
    _register_builtin_agents(agent_registry, config, builtin_agents, diagnostics)
    _register_builtin_skills(skill_registry, config, builtin_skills, diagnostics)

    discovery = DefinitionDiscovery(config.discovery_sources)
    discovered = discovery.discover()
    diagnostics.extend(discovered.diagnostics)
    _register_all(tool_registry, discovered.tools, diagnostics)
    _register_all(agent_registry, discovered.agents, diagnostics)
    _register_all(skill_registry, discovered.skills, diagnostics)
    _register_runtime_invocation_providers(
        invocation_registry=invocation_registry,
        config=config,
        skill_registry=skill_registry,
        skill_view_resolver=skill_view_resolver,
        package_service_contributions=package_service_contributions,
        distribution=resolved_distribution.value,
        working_directory=config.working_directory,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
    )
    diagnostics.extend(invocation_registry.diagnostics())
    for _, contribution in package_service_contributions:
        diagnostics.extend(contribution.diagnostics)
    diagnostics.extend(
        _package_migration_diagnostics(
            selected_packages=selected_packages,
            distribution=resolved_distribution.value,
        )
    )

    kernel = RuntimeKernel(
        config=config,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        invocation_registry=invocation_registry,
        distribution=resolved_distribution.value,
        first_party_packages=selected_packages,
        package_registration=package_registration,
        package_resolution=package_resolution,
        package_manifests=package_manifests,
        package_service_contributions=package_service_contributions,
        diagnostics=tuple(diagnostics),
        model_client=_default_model_client(config),
        transcript_store=config.transcript_store,
        skill_view_resolver=skill_view_resolver,
    )
    kernel.services = _build_runtime_services(kernel)
    kernel.transcript_store = kernel.services.transcript_store
    for binding in config.host_bindings:
        kernel.hosts[binding.name] = binding.factory(binding.name, binding.config, kernel)
    return kernel


def assemble_runtime(config: RuntimeConfig) -> RuntimeAssembly:
    kernel = build_runtime_kernel(config)
    return _assemble_runtime_stack(kernel)


def assemble_host_runtime(
    config: RuntimeConfig,
    host_name: str | None = None,
) -> BoundHostRuntime:
    runtime = assemble_runtime(config)
    kernel = runtime.kernel
    if host_name is None:
        host = next(iter(kernel.hosts.values()), NullHostAdapter())
    else:
        host = kernel.hosts.get(host_name)
        if host is None:
            raise KeyError(host_name)
    return runtime.bind_host(host)


def _assemble_runtime_stack(kernel: RuntimeKernel) -> RuntimeAssembly:
    services = kernel.services or _build_runtime_services(kernel)
    kernel.services = services
    services.job_service.bind_runtime(
        runtime_id=kernel.config.runtime_id,
        services=services,
        kernel=kernel,
    )
    transcript_store = services.transcript_store
    kernel.transcript_store = transcript_store
    task_manager = services.tasks.manager
    store_bindings = _store_binding_values(kernel.package_service_contributions)
    turn_engine = TurnEngine(
        model_client=kernel.model_client or _UnconfiguredModelClient(),
        tool_registry=kernel.tool_registry,
        agent_registry=kernel.agent_registry,
        skill_registry=kernel.skill_registry,
        invocation_registry=kernel.invocation_registry,
        runtime_services=services,
        model_providers=kernel.config.model_providers,
        model_routes=kernel.config.model_routes,
        default_model_route=kernel.config.default_model_route,
    )
    agent_runtime = AgentRuntime(
        turn_engine=turn_engine,
        agent_registry=kernel.agent_registry,
        tool_registry=kernel.tool_registry,
        skill_registry=kernel.skill_registry,
        runtime_services=services,
        run_store=kernel.config.child_run_store or store_bindings.get("child_run_store"),
        model_providers=kernel.config.model_providers,
        model_routes=kernel.config.model_routes,
        default_model_route=kernel.config.default_model_route,
    )
    skill_executor = SkillExecutor(
        skill_registry=kernel.skill_registry,
        agent_runtime=agent_runtime,
        runtime_services=services,
    )
    agent_runtime.bind_skill_executor(skill_executor)
    services.configure_compat(
        permission_handler=kernel.config.permission_handler,
        ask_user_handler=kernel.config.ask_user_handler,
        notification_provider=lambda: agent_runtime.notifications,
        tool_refresh_callback=kernel.config.tool_refresh_callback,
    )
    runtime_package_contributions = _assemble_package_contributions(
        kernel.package_manifests,
        stage=PackageAssemblyStage.RUNTIME,
        config=kernel.config,
        distribution=kernel.distribution,
        working_directory=kernel.config.working_directory,
        resources={
            "runtime_services": services,
            "execution_core": agent_runtime,
            "store_bindings": _store_binding_values(kernel.package_service_contributions),
        },
    )
    for manifest, contribution in runtime_package_contributions:
        services.apply_package_contribution(
            manifest,
            contribution,
            stage=PackageAssemblyStage.RUNTIME.value,
        )
    runtime_diagnostics = tuple(
        diagnostic
        for _, contribution in runtime_package_contributions
        for diagnostic in contribution.diagnostics
    )
    if runtime_diagnostics:
        kernel.diagnostics = kernel.diagnostics + runtime_diagnostics
    _project_capability_compatibility_surfaces(services)
    _sync_package_service_protocol_metadata(services)
    _sync_compatibility_boundary_metadata(services, kernel=kernel)
    _sync_core_protocol_catalog_metadata(services)
    teammates = services.resolve_capability(RuntimeCapabilityKey.TEAMMATES.value)
    runtime = RuntimeAssembly(
        kernel=kernel,
        services=services,
        turn_engine=turn_engine,
        agent_runtime=agent_runtime,
        skill_executor=skill_executor,
        transcript_store=transcript_store,
        _task_manager=task_manager,
        job_service=services.job_service,
        teammates=teammates,
        system_prompt=kernel.config.system_prompt,
        metadata={
            **dict(kernel.config.metadata),
            "distribution": kernel.distribution,
            "first_party_packages": list(kernel.first_party_packages),
            "first_party_package_catalog": dict(services.metadata.get("first_party_package_catalog", {})),
            "official_package_catalog_provenance": dict(
                services.metadata.get("official_package_catalog_provenance", {})
            ),
            "resolved_active_package_graph_provenance": dict(
                services.metadata.get("resolved_active_package_graph_provenance", {})
            ),
            "closure_report": dict(services.metadata.get("closure_report", {})),
            "package_registration": dict(services.metadata.get("package_registration", {})),
            "package_resolution": dict(services.metadata.get("package_resolution", {})),
            "package_manifests": dict(services.metadata.get("package_manifests", {})),
            "package_runtime_contributions": [manifest.name for manifest, _ in runtime_package_contributions],
            "core_protocol_catalog": dict(services.metadata.get("core_protocol_catalog", {})),
            "package_lookup": dict(services.metadata.get("package_lookup", {})),
            "migration": dict(services.metadata.get("migration", {})),
            "context_contributors": dict(services.metadata.get("context_contributors", {})),
            "compatibility_surfaces": dict(services.metadata.get("compatibility_surfaces", {})),
            "compatibility_boundaries": dict(services.metadata.get("compatibility_boundaries", {})),
            "compatibility_projections": dict(services.metadata.get("compatibility_projections", {})),
            "package_service_protocols": dict(services.metadata.get("package_service_protocols", {})),
            "invocation_provider_paths": dict(services.metadata.get("invocation_provider_paths", {})),
            "invocation_provider_registrations": [
                dict(entry) for entry in services.metadata.get("invocation_provider_registrations", ())
            ],
            "protocol_only_conformance": dict(services.metadata.get("protocol_only_conformance", {})),
        },
    )
    services.attach_metadata_mirror(runtime.metadata)
    services.attach_runtime_assembly(runtime)
    _register_job_executors(
        kernel=kernel,
        services=services,
        agent_runtime=agent_runtime,
        package_contributions=(
            kernel.package_service_contributions + runtime_package_contributions
        ),
    )
    services.bind_execution(
        agent_runner=runtime.run_agent_tool,
        skill_runner=runtime.run_skill_tool,
    )
    _start_runtime_lifecycle(
        services,
        runtime=runtime,
        kernel=kernel,
    )
    return runtime


def _build_runtime_services(kernel: RuntimeKernel) -> RuntimeServices:
    store_bindings = _store_binding_values(kernel.package_service_contributions)
    transcript_store = (
        kernel.transcript_store
        or store_bindings.get("transcript_store")
        or InMemoryTranscriptStore()
    )
    task_list_service = DefaultTaskListService(
        store=(
            store_bindings.get("task_list_store")
            or InMemoryTaskListStore()
        )
    )
    job_service = DefaultJobService(
        store=(
            store_bindings.get("job_store")
            or InMemoryJobStore()
        ),
        metadata={"runtime_id": kernel.config.runtime_id},
    )
    metadata = dict(kernel.config.metadata)
    metadata["runtime_id"] = kernel.config.runtime_id
    metadata["distribution"] = kernel.distribution
    metadata["first_party_packages"] = list(kernel.first_party_packages)
    metadata["first_party_package_catalog"] = _first_party_package_catalog(kernel.first_party_packages)
    metadata["official_package_catalog_provenance"] = _official_package_catalog_provenance_metadata()
    metadata["resolved_active_package_graph_provenance"] = _resolved_active_package_graph_provenance_metadata(
        distribution=kernel.distribution,
        selected_packages=kernel.first_party_packages,
        package_resolution=kernel.package_resolution,
    )
    metadata["package_registration"] = kernel.package_registration.to_metadata()
    metadata["package_resolution"] = (
        {}
        if kernel.package_resolution is None
        else kernel.package_resolution.to_metadata()
    )
    metadata["package_manifests"] = _package_manifest_catalog(kernel.package_manifests)
    metadata["package_service_contributions"] = [
        manifest.name for manifest, _ in kernel.package_service_contributions
    ]
    metadata["package_store_bindings"] = {
        slot: binding.owner.package_name
        for slot, binding in _store_binding_entries(kernel.package_service_contributions).items()
    }
    metadata["legacy_compatibility"] = _legacy_compatibility_profile(kernel.config).to_metadata()
    metadata["compatibility_surfaces"] = {
        **core_protocol_compatibility_surfaces(),
        "runtime_context": "compatibility-only",
        "RuntimeServices.teammates": "compatibility-only",
        "RuntimeAssembly.teammates": "compatibility-only",
    }
    metadata["package_lookup"] = _package_lookup_metadata()
    metadata["invocation_provider_paths"] = _invocation_provider_paths_metadata()
    metadata["invocation_provider_registrations"] = [
        _serialize_invocation_provider_registration(registration)
        for registration in kernel.invocation_registry.registrations()
    ]
    metadata["migration"] = _migration_metadata(
        selected_packages=kernel.first_party_packages,
        distribution=kernel.distribution,
    )
    metadata.setdefault(
        "task_discipline",
        {
            "enabled": True,
            "reminder_turn_threshold": 3,
            "strict_single_in_progress": False,
            "reminder_task_limit": 8,
        },
    )
    metadata.setdefault("delegation", default_delegation_policy_metadata())
    reference_hosts = _resolve_capability_from_contributions(
        kernel.package_service_contributions,
        RuntimeCapabilityKey.REFERENCE_HOST_TYPES.value,
    )
    if reference_hosts is not None:
        metadata["reference_hosts"] = sorted(reference_hosts)
    memory_service = _resolve_capability_from_contributions(
        kernel.package_service_contributions,
        RuntimeCapabilityKey.MEMORY_SERVICE.value,
    )
    compaction_manager = _resolve_capability_from_contributions(
        kernel.package_service_contributions,
        RuntimeCapabilityKey.COMPACTION_MANAGER.value,
    )
    isolation_manager = _resolve_capability_from_contributions(
        kernel.package_service_contributions,
        RuntimeCapabilityKey.ISOLATION_MANAGER.value,
    )
    services = RuntimeServices(
        transcript=DefaultTranscriptService(transcript_store),
        memory=memory_service if memory_service is not None else NoopMemoryService(),
        compaction=(
            compaction_manager
            if compaction_manager is not None
            else NoopCompactionService()
        ),
        isolation=(
            isolation_manager
            if isolation_manager is not None
            else _assemble_core_isolation_manager()
        ),
        jobs=job_service,
        task_lists=task_list_service,
        task_discipline=TaskDisciplineSidecar(task_lists=task_list_service),
        context_assembler=ContextAssembler(),
        metadata=metadata,
    )
    for manifest, contribution in kernel.package_service_contributions:
        services.apply_package_contribution(
            manifest,
            contribution,
            stage=PackageAssemblyStage.SERVICES.value,
        )
    _project_capability_compatibility_surfaces(services)
    _sync_package_service_protocol_metadata(services)
    _sync_compatibility_boundary_metadata(services, kernel=kernel)
    _sync_core_protocol_catalog_metadata(services)
    services.configure_compat(
        permission_handler=kernel.config.permission_handler,
        ask_user_handler=kernel.config.ask_user_handler,
        tool_refresh_callback=kernel.config.tool_refresh_callback,
    )
    if kernel.config.hooks:
        services.hook_bus.register_document(
            hooks=kernel.config.hooks,
            source_kind=HookSourceKind.RUNTIME_CONFIG,
            owner=f"weavert:{kernel.config.runtime_id}",
            source_ref=kernel.config.runtime_id,
            default_scope_lifetime=HookScopeLifetime.SESSION_TEMPLATE,
        )
    return services


def _assemble_package_contributions(
    manifests: tuple[RuntimePackageManifest, ...],
    *,
    stage: PackageAssemblyStage,
    config: RuntimeConfig,
    distribution: str,
    working_directory: Path,
    resources: Mapping[str, Any] | None = None,
) -> tuple[tuple[RuntimePackageManifest, PackageContribution], ...]:
    records: list[tuple[RuntimePackageManifest, PackageContribution]] = []
    for manifest in manifests:
        contribution = manifest.assemble(
            PackageContext(
                manifest=manifest,
                stage=stage,
                distribution=distribution,
                selected_packages=tuple(record.name for record in manifests),
                working_directory=working_directory,
                config=config,
                resources=dict(resources or {}),
            )
        )
        records.append((manifest, contribution))
    return tuple(records)


def _collect_package_builtins(
    package_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...],
) -> tuple[
    tuple[ToolDefinition, ...],
    tuple[AgentDefinition, ...],
    tuple[SkillDefinition, ...],
    tuple[Diagnostic, ...],
]:
    tools: list[ToolDefinition] = []
    agents: list[AgentDefinition] = []
    skills: list[SkillDefinition] = []
    diagnostics: list[Diagnostic] = []
    for _, contribution in package_contributions:
        tools.extend(contribution.builtin_tools)
        agents.extend(contribution.builtin_agents)
        skills.extend(contribution.builtin_skills)
        diagnostics.extend(contribution.diagnostics)
    return tuple(tools), tuple(agents), tuple(skills), tuple(diagnostics)


def _with_package_model_binding_baseline(
    config: RuntimeConfig,
    *,
    package_service_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...],
) -> RuntimeConfig:
    model_providers = dict(config.model_providers)
    model_routes = dict(config.model_routes)
    default_route_candidate: str | None = None

    for _, contribution in package_service_contributions:
        for provider in contribution.model_providers:
            model_providers.setdefault(provider.name, provider.binding)
        for route in contribution.model_routes:
            model_routes.setdefault(route.name, route.binding)
            if default_route_candidate is None:
                default_route_candidate = route.name

    default_model_route = config.default_model_route
    if (
        default_model_route is None
        and config.model_client is None
        and not config.model_routes
        and default_route_candidate is not None
    ):
        default_model_route = default_route_candidate

    return replace(
        config,
        model_providers=model_providers,
        model_routes=model_routes,
        default_model_route=default_model_route,
    )


def _register_runtime_invocation_providers(
    *,
    invocation_registry: InvocationRegistry,
    config: RuntimeConfig,
    skill_registry: SkillRegistry,
    skill_view_resolver: _SessionSkillViewResolver,
    package_service_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...],
    distribution: str,
    working_directory: Path,
    tool_registry: ToolRegistry,
    agent_registry: AgentRegistry,
) -> None:
    invocation_registry.register_provider(
        SkillInvocationProvider(
            skill_registry,
            skill_resolver=skill_view_resolver,
        ),
        origin="builtin",
        metadata={
            "registration_path": "builtin_skill_baseline",
            "provider_tier": "builtin-baseline",
            "compatibility_status": "baseline",
        },
    )
    for record in _resolve_package_invocation_providers(
        package_service_contributions=package_service_contributions,
        config=config,
        distribution=distribution,
        working_directory=working_directory,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        skill_view_resolver=skill_view_resolver,
    ):
        invocation_registry.register_provider(
            record.provider,
            origin="package",
            owner=record.contribution.owner,
            order=record.contribution.order,
            metadata={
                **dict(record.contribution.metadata),
                "registration_path": "PackageContribution.invocation_providers",
                "provider_tier": "package-contribution",
                "compatibility_status": "canonical-package-path",
                "package_name": record.manifest.name,
                "package_role": record.manifest.role,
                "package_stage": PackageAssemblyStage.SERVICES.value,
                "package_index": record.package_index,
                "contribution_index": record.contribution_index,
            },
        )


def _resolve_package_invocation_providers(
    *,
    package_service_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...],
    config: RuntimeConfig,
    distribution: str,
    working_directory: Path,
    tool_registry: ToolRegistry,
    agent_registry: AgentRegistry,
    skill_registry: SkillRegistry,
    skill_view_resolver: _SessionSkillViewResolver,
) -> tuple[_ResolvedPackageInvocationProvider, ...]:
    records: list[_ResolvedPackageInvocationProvider] = []
    for package_index, (manifest, contribution) in enumerate(package_service_contributions):
        ordered_contributions = sorted(
            enumerate(contribution.invocation_providers),
            key=lambda item: (item[1].order, item[1].name, item[0]),
        )
        for contribution_index, (_, binding) in enumerate(ordered_contributions):
            provider = binding.build_provider(
                InvocationProviderFactoryContext(
                    manifest=manifest,
                    owner=binding.owner,
                    distribution=distribution,
                    working_directory=working_directory,
                    config=config,
                    resources={
                        "tool_registry": tool_registry,
                        "agent_registry": agent_registry,
                        "skill_registry": skill_registry,
                        "skill_view_resolver": skill_view_resolver,
                        "package_contribution": contribution,
                    },
                    metadata={
                        "package_index": package_index,
                        "contribution_index": contribution_index,
                        "registration_path": "PackageContribution.invocation_providers",
                    },
                )
            )
            records.append(
                _ResolvedPackageInvocationProvider(
                    manifest=manifest,
                    contribution=binding,
                    provider=provider,
                    package_index=package_index,
                    contribution_index=contribution_index,
                )
            )
    return tuple(sorted(records, key=lambda record: record.registration_key))


def _resolve_capability_from_contributions(
    package_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...],
    key: str,
) -> Any:
    resolved = None
    for _, contribution in package_contributions:
        for binding in contribution.capabilities:
            if binding.key == key:
                resolved = binding.value
    return resolved


def _store_binding_entries(
    package_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...],
) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    for _, contribution in package_contributions:
        for binding in contribution.store_bindings:
            entries[binding.slot] = binding
    return entries


def _store_binding_values(
    package_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...],
) -> dict[str, Any]:
    return {
        slot: binding.store
        for slot, binding in _store_binding_entries(package_contributions).items()
    }


def _package_manifest_catalog(
    manifests: tuple[RuntimePackageManifest, ...],
) -> dict[str, dict[str, Any]]:
    return {
        manifest.name: {
            "role": manifest.role,
            "description": manifest.description,
            "dependencies": list(manifest.dependencies),
            "invocation_providers": list(manifest.metadata.get("invocation_providers", ())),
            **{
                key: (
                    list(manifest.metadata[key])
                    if isinstance(manifest.metadata[key], (tuple, list))
                    else dict(manifest.metadata[key])
                    if isinstance(manifest.metadata[key], dict)
                    else manifest.metadata[key]
                )
                for key in (
                    "package_pattern",
                    "baseline_dependencies",
                    "invocation_providers",
                    "provider_registration_path",
                    "provider_registration_order",
                    "provider_package_ordering",
                    "capabilities",
                    "capability_registration_path",
                    "context_contributors",
                    "context_contributor_registration_path",
                    "context_contributor_stages",
                )
                if key in manifest.metadata
            },
        }
        for manifest in manifests
    }


def _official_package_catalog_provenance_metadata() -> dict[str, Any]:
    return official_runtime_package_catalog_provenance()


def _resolved_active_package_graph_provenance_metadata(
    *,
    distribution: str,
    selected_packages: tuple[str, ...],
    package_resolution: RuntimePackageResolutionReport | None,
) -> dict[str, Any]:
    distribution_catalog = official_runtime_distribution_catalog()
    distribution_entry = distribution_catalog.get(str(distribution))
    official_provenance = official_runtime_package_catalog_provenance()
    official_entries = official_provenance.get("entries", {})
    if not isinstance(official_entries, Mapping):
        official_entries = {}
    resolved_packages: list[dict[str, Any]] = []
    resolved_order: list[str] = []
    if package_resolution is not None:
        for index, candidate in enumerate(package_resolution.resolved_candidates):
            source = dict(candidate.source)
            package_name = candidate.package_name
            official_entry = official_entries.get(package_name, {})
            if not isinstance(official_entry, Mapping):
                official_entry = {}
            resolved_order.append(package_name)
            resolved_packages.append(
                {
                    "package_name": package_name,
                    "candidate_id": candidate.candidate_id,
                    "origin": str(source.get("origin") or ""),
                    "source_kind": str(source.get("source_kind") or ""),
                    "source_ref": str(source.get("source_ref") or ""),
                    "assembly_entrypoint": str(
                        official_entry.get("assembly_entrypoint")
                        or _serialize_manifest_assembly_entrypoint(candidate.manifest)
                    ),
                    "dependencies": list(candidate.manifest.dependencies),
                    "resolution_position": index,
                }
            )
    metadata: dict[str, Any] = {
        "schema_version": "1.0",
        "published_metadata_paths": [
            "weavert.services.metadata['resolved_active_package_graph_provenance']",
            "weavert.metadata['resolved_active_package_graph_provenance']",
        ],
        "distribution": distribution,
        "selected_first_party_packages": list(selected_packages),
        "resolved_order": resolved_order,
        "resolved_packages": resolved_packages,
        "source_paths": {
            "official_catalog": "weavert.services.metadata['official_package_catalog_provenance']",
            "resolution_report": "weavert.services.metadata['package_resolution']",
        },
    }
    if distribution_entry is not None:
        metadata["baseline_distribution_packages"] = list(distribution_entry.packages)
        metadata["distribution_source_ref"] = distribution_entry.source_ref
    return metadata


def _serialize_manifest_assembly_entrypoint(manifest: RuntimePackageManifest) -> str:
    entrypoint = manifest.assembly_entrypoint
    if entrypoint is None:
        return ""
    if isinstance(entrypoint, str):
        return entrypoint
    module = getattr(entrypoint, "__module__", "")
    qualname = getattr(entrypoint, "__qualname__", "")
    if module and qualname:
        return f"{module}:{qualname}"
    return repr(entrypoint)


def _invocation_provider_paths_metadata() -> dict[str, Any]:
    return core_protocol_invocation_provider_paths_metadata()


def _serialize_invocation_provider_registration(
    registration: InvocationProviderRegistration,
) -> dict[str, Any]:
    registration_path = str(registration.metadata.get("registration_path") or "")
    provider_tier = str(registration.metadata.get("provider_tier") or registration.origin)
    return {
        "provider_name": registration.name,
        "origin": registration.origin,
        "order": registration.order,
        "sequence": registration.sequence,
        "registration_path": registration_path,
        "provider_tier": provider_tier,
        "owner": (
            None
            if registration.owner is None
            else {
                "package_name": registration.owner.package_name,
                "package_role": registration.owner.package_role,
                "surface": registration.owner.surface,
                "metadata": dict(registration.owner.metadata),
            }
        ),
        "metadata": dict(registration.metadata),
    }


def _package_lookup_metadata() -> dict[str, Any]:
    core_sections = core_protocol_package_lookup_sections()
    return {
        "canonical_capabilities": {
            "teammates": RuntimeCapabilityKey.TEAMMATES.value,
            "team_control_plane": RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value,
            "team_message_bus": RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value,
            "team_workflows": RuntimeCapabilityKey.TEAM_WORKFLOWS.value,
        },
        "canonical_host_facets": {
            "team_workflows": RuntimeHostFacetKey.TEAM_WORKFLOWS.value,
        },
        "canonical_control_plane_services": dict(core_sections["canonical_control_plane_services"]),
        "canonical_service_family_protocols": dict(core_sections["canonical_service_family_protocols"]),
        "canonical_context_contributors": dict(core_sections["canonical_context_contributors"]),
        "canonical_invocation_providers": dict(core_sections["canonical_invocation_providers"]),
        "compatibility_context_contributors": dict(core_sections["compatibility_context_contributors"]),
        "compatibility_service_projections": dict(core_sections["compatibility_service_projections"]),
        "canonical_service_family_resolvers": {
            family: spec["resolver"]
            for family, spec in _PACKAGE_SERVICE_PROTOCOL_SPECS.items()
        },
        "canonical_lifecycle_phase": PackageLifecyclePhase.SESSION_OPEN.value,
        "canonical_post_ingress_path": "completion_receipts",
        "canonical_extension_event_contract": {
            "emit": "HostRuntime.emit_extension_event",
            "envelope": "weavert.hosts.HostExtensionEvent",
            "unknown_namespace_behavior": "ignore_or_handle_generically",
        },
        "compatibility_wrappers": [
            "TaskManager",
            "RuntimeServices.memory",
            "RuntimeServices.compaction",
            "RuntimeServices.isolation",
            "RuntimeServices.teammates",
            "RuntimeAssembly.teammates",
        ],
        "wrapper_exit_criteria": [
            "memory, compaction, and isolation runtime-owned call sites resolve through package-service protocols only",
            "teammate orchestration callers resolve through capability lookup only",
            "TaskManager usage remains compatibility-scoped behind JobService and TaskListService",
        ],
    }


_PACKAGE_SERVICE_PROTOCOL_SPECS: dict[str, dict[str, Any]] = {
    "memory": {
        "capability_key": RuntimeCapabilityKey.MEMORY_SERVICE.value,
        "resolver": "RuntimeServices.resolve_memory_service",
        "projection_surface": "RuntimeServices.memory",
        "retained_surfaces": (
            "RuntimeServices.memory",
            "RuntimeServices.memory.collect",
        ),
    },
    "compaction": {
        "capability_key": RuntimeCapabilityKey.COMPACTION_MANAGER.value,
        "resolver": "RuntimeServices.resolve_compaction_service",
        "projection_surface": "RuntimeServices.compaction",
        "retained_surfaces": (
            "RuntimeServices.compaction",
            "RuntimeServices.compaction.prepare_turn",
            "RuntimeServices.compaction.collect",
        ),
    },
    "isolation": {
        "capability_key": RuntimeCapabilityKey.ISOLATION_MANAGER.value,
        "resolver": "RuntimeServices.resolve_isolation_service",
        "projection_surface": "RuntimeServices.isolation",
        "retained_surfaces": ("RuntimeServices.isolation",),
    },
}


_RUNTIME_CONTEXT_INVOCATION_BOUNDARIES = frozenset(
    {
        "RuntimeAssembly.resolve_invocations",
        "RuntimeAssembly.resolve_session_invocations",
        "RuntimeAssembly.visible_invocations",
        "RuntimeAssembly.invocation_diagnostics",
        "TurnEngine.resolve_invocation_catalog",
    }
)
_RUNTIME_CONTEXT_TASK_LIST_BOUNDARIES = frozenset(
    {
        "RuntimeAssembly.resolve_task_list_id",
        "RuntimeAssembly.create_task",
        "RuntimeAssembly.get_task",
        "RuntimeAssembly.update_task",
        "RuntimeAssembly.claim_task",
        "RuntimeAssembly.release_task",
        "RuntimeAssembly.assign_next_task",
        "RuntimeAssembly.block_task",
        "RuntimeAssembly.unblock_task",
        "RuntimeAssembly.archive_task",
        "RuntimeAssembly.unarchive_task",
        "RuntimeAssembly.delete_task",
        "RuntimeAssembly.list_task_lists",
        "RuntimeAssembly.get_task_list",
        "RuntimeAssembly.watch_task_list",
    }
)
_TASK_MANAGER_COMPATIBILITY_SURFACE_METADATA: dict[str, dict[str, Any]] = {
    "RuntimeServices.task_manager": {
        "kind": "compatibility-wrapper",
        "exit_criteria": [
            "legacy embedder code stops requesting RuntimeServices.task_manager",
            "job_* and task_* primary paths stay on shared services directly",
        ],
    },
    "RuntimeAssembly.task_manager": {
        "kind": "compatibility-wrapper",
        "exit_criteria": [
            "runtime-owned integrations stop depending on RuntimeAssembly.task_manager",
            "compat callers migrate to JobService or TaskListService",
        ],
    },
    "RuntimeServices.bind_task_manager": {
        "kind": "legacy-injection-adapter",
        "exit_criteria": [
            "constructor seams inject RuntimeServices or JobService instead",
        ],
    },
    "TurnEngine.__init__(task_manager=...)": {
        "kind": "legacy-constructor-adapter",
        "exit_criteria": [
            "embedder-owned TurnEngine wiring injects JobService or RuntimeServices instead",
        ],
    },
    "AgentRuntime.__init__(task_manager=...)": {
        "kind": "legacy-constructor-adapter",
        "exit_criteria": [
            "embedder-owned AgentRuntime wiring injects JobService or RuntimeServices instead",
        ],
    },
}


def _ordered_public_method_surfaces(
    cls: type[Any],
    *,
    parameter_name: str,
) -> tuple[str, ...]:
    surfaces: list[str] = []
    for name, member in cls.__dict__.items():
        if name.startswith("_") or isinstance(member, property) or not callable(member):
            continue
        try:
            signature = inspect.signature(member)
        except (TypeError, ValueError):  # pragma: no cover - defensive introspection
            continue
        if parameter_name in signature.parameters:
            surfaces.append(f"{cls.__name__}.{name}")
    return tuple(surfaces)


def _property_surface(
    cls: type[Any],
    property_name: str,
) -> tuple[str, ...]:
    return (
        (f"{cls.__name__}.{property_name}",)
        if isinstance(cls.__dict__.get(property_name), property)
        else ()
    )


def _constructor_surface(
    cls: type[Any],
    *,
    parameter_name: str,
) -> tuple[str, ...]:
    try:
        signature = inspect.signature(cls.__init__)
    except (TypeError, ValueError):  # pragma: no cover - defensive introspection
        return ()
    if parameter_name not in signature.parameters:
        return ()
    return (f"{cls.__name__}.__init__({parameter_name}=...)",)


def _runtime_context_compatibility_surfaces() -> tuple[str, ...]:
    return (
        *_ordered_public_method_surfaces(RuntimeAssembly, parameter_name="runtime_context"),
        *_ordered_public_method_surfaces(TurnEngine, parameter_name="runtime_context"),
        *_ordered_public_method_surfaces(ContextAssembler, parameter_name="runtime_context"),
    )


def _task_manager_compatibility_surfaces() -> tuple[str, ...]:
    return (
        *_property_surface(RuntimeServices, "task_manager"),
        *_property_surface(RuntimeAssembly, "task_manager"),
        *_ordered_public_method_surfaces(RuntimeServices, parameter_name="task_manager"),
        *_constructor_surface(TurnEngine, parameter_name="task_manager"),
        *_constructor_surface(AgentRuntime, parameter_name="task_manager"),
    )


def _runtime_context_surface_metadata(surface: str) -> dict[str, Any] | None:
    if surface in _RUNTIME_CONTEXT_INVOCATION_BOUNDARIES:
        return {
            "kind": "compatibility-api-boundary",
            "exit_criteria": [
                "callers provide PromptContextEnvelope directly",
                "callers provide RuntimePrivateContext directly",
            ],
        }
    if surface in _RUNTIME_CONTEXT_TASK_LIST_BOUNDARIES:
        return {
            "kind": "compatibility-api-boundary",
            "exit_criteria": [
                "callers provide RuntimePrivateContext directly for task-list resolution",
                "raw runtime_context remains a boundary-only convenience input",
            ],
        }
    if surface == "TurnEngine.run_turn":
        return {
            "kind": "compatibility-api-boundary",
            "exit_criteria": [
                "legacy callers stop passing raw runtime_context payloads",
                "prompt/private carriers remain the only authoritative write path",
            ],
        }
    if surface == "TurnEngine.run_turn_stream":
        return {
            "kind": "compatibility-api-boundary",
            "exit_criteria": [
                "streaming callers stop passing raw runtime_context payloads",
                "compatibility snapshot stays read-only for sidecars and hooks",
            ],
        }
    if surface == "ContextAssembler.assemble":
        return {
            "kind": "compatibility-helper-boundary",
            "exit_criteria": [
                "callers compose PromptContextEnvelope directly",
                "legacy prompt hints stop flowing through runtime_context compatibility maps",
            ],
        }
    return None


def _compatibility_boundaries_metadata(
    *,
    compatibility_surfaces: Mapping[str, Any],
    package_lookup: Mapping[str, Any],
) -> dict[str, Any]:
    canonical_services = package_lookup.get("canonical_control_plane_services")
    if not isinstance(canonical_services, Mapping):
        canonical_services = core_protocol_package_lookup_sections()["canonical_control_plane_services"]
    runtime_context_surfaces = _runtime_context_compatibility_surfaces()
    runtime_context_unknown: list[str] = []
    runtime_context_entries: list[dict[str, Any]] = []
    for surface in runtime_context_surfaces:
        surface_metadata = _runtime_context_surface_metadata(surface)
        if surface_metadata is None:
            runtime_context_unknown.append(surface)
            surface_metadata = {
                "kind": "unclassified-compatibility-surface",
                "exit_criteria": [
                    "classify this runtime_context compatibility boundary before relying on it",
                ],
            }
        runtime_context_entries.append(
            {
                "surface": surface,
                **surface_metadata,
            }
        )

    task_manager_surfaces = _task_manager_compatibility_surfaces()
    task_manager_unknown: list[str] = []
    task_manager_entries: list[dict[str, Any]] = []
    for surface in task_manager_surfaces:
        surface_metadata = _TASK_MANAGER_COMPATIBILITY_SURFACE_METADATA.get(surface)
        if surface_metadata is None:
            task_manager_unknown.append(surface)
            surface_metadata = {
                "kind": "unclassified-compatibility-surface",
                "exit_criteria": [
                    "classify this TaskManager compatibility adapter before relying on it",
                ],
            }
        task_manager_entries.append(
            {
                "surface": surface,
                **surface_metadata,
            }
        )
    return {
        "runtime_context": {
            "status": str(compatibility_surfaces.get("runtime_context") or "compatibility-only"),
            "canonical_carriers": {
                "prompt_context": "PromptContextEnvelope",
                "private_context": "RuntimePrivateContext",
            },
            "normalization_helpers": [
                "weavert.contracts.prompt_context_from_legacy_runtime_context",
                "weavert.contracts.merge_runtime_private_context",
                "weavert.contracts.compatibility_runtime_context_snapshot",
            ],
            "entry_points": runtime_context_entries,
            "unclassified_surfaces": list(runtime_context_unknown),
        },
        "TaskManager": {
            "status": str(compatibility_surfaces.get("TaskManager") or "compatibility-only"),
            "canonical_services": {
                "job_service": str(
                    canonical_services.get("job_service") or "RuntimeServices.job_service"
                ),
                "task_list_service": str(
                    canonical_services.get("task_list_service") or "RuntimeServices.task_list_service"
                ),
            },
            "materialization_adapters": task_manager_entries,
            "unclassified_surfaces": list(task_manager_unknown),
        },
    }


def _serialize_owner_metadata(owner: Any | None) -> dict[str, Any] | None:
    if owner is None:
        return None
    return {
        "package_name": owner.package_name,
        "package_role": owner.package_role,
        "surface": owner.surface,
        "metadata": dict(owner.metadata),
    }


def _package_service_protocol_metadata(services: RuntimeServices) -> dict[str, Any]:
    compatibility_surfaces = services.metadata.get("compatibility_surfaces")
    if not isinstance(compatibility_surfaces, Mapping):
        compatibility_surfaces = {}
    metadata: dict[str, Any] = {}
    for family, spec in _PACKAGE_SERVICE_PROTOCOL_SPECS.items():
        capability_key = str(spec["capability_key"])
        projection_surface = str(spec["projection_surface"])
        owner = services.capability_registry.owner(capability_key)
        metadata[family] = {
            "canonical_key": capability_key,
            "resolver": str(spec["resolver"]),
            "owner": _serialize_owner_metadata(owner),
            "compatibility_projection": {
                "surface": projection_surface,
                "status": str(compatibility_surfaces.get(projection_surface) or "compatibility-only"),
            },
            "retained_surfaces": [
                {
                    "surface": surface,
                    "status": str(compatibility_surfaces.get(surface) or "compatibility-only"),
                }
                for surface in spec["retained_surfaces"]
            ],
        }
    return metadata


def _legacy_profile_from_runtime_metadata(metadata: Mapping[str, Any]) -> LegacyCompatibilityProfile:
    raw = metadata.get("legacy_compatibility")
    if not isinstance(raw, Mapping):
        return LegacyCompatibilityProfile()
    enabled = tuple(
        sorted(
            str(item)
            for item in raw.get("enabled_families", ())
            if str(item) in LEGACY_COMPATIBILITY_FAMILY_INDEX
        )
    )
    unknown = tuple(sorted(str(item) for item in raw.get("unknown_families", ()) if str(item).strip()))
    return LegacyCompatibilityProfile(
        enabled_families=enabled,
        preset=str(raw.get("preset") or "none"),
        unknown_families=unknown,
        raw=(
            dict(raw.get("raw"))
            if isinstance(raw.get("raw"), Mapping)
            else {str(key): value for key, value in raw.items()}
        ),
    )


def _compatibility_retirement_surface_entries(
    family: str,
    *,
    compatibility_boundaries: Mapping[str, Any],
    package_service_protocols: Mapping[str, Any],
    context_contributors: Mapping[str, Any],
    compatibility_surfaces: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if family == "task_manager":
        boundary = compatibility_boundaries.get("TaskManager")
        entries = boundary.get("materialization_adapters", ()) if isinstance(boundary, Mapping) else ()
        return [
            {
                "surface": str(entry.get("surface") or ""),
                "kind": str(entry.get("kind") or "compatibility-surface"),
                "status": str(compatibility_surfaces.get(entry.get("surface")) or "compatibility-only"),
            }
            for entry in entries
            if isinstance(entry, Mapping) and entry.get("surface")
        ]
    if family == "runtime_context_authority":
        boundary = compatibility_boundaries.get("runtime_context")
        entries = boundary.get("entry_points", ()) if isinstance(boundary, Mapping) else ()
        return [
            {
                "surface": str(entry.get("surface") or ""),
                "kind": str(entry.get("kind") or "compatibility-surface"),
                "status": str(compatibility_surfaces.get("runtime_context") or "compatibility-only"),
            }
            for entry in entries
            if isinstance(entry, Mapping) and entry.get("surface")
        ]
    if family == "context_contributor_adapters":
        surfaces = (
            context_contributors.get("compatibility_surfaces", {})
            if isinstance(context_contributors, Mapping)
            else {}
        )
        if not isinstance(surfaces, Mapping):
            surfaces = {}
        return [
            {
                "surface": str(surface),
                "kind": "compatibility-context-contributor",
                "status": str(status or "compatibility-only"),
            }
            for surface, status in surfaces.items()
        ]
    if family in {"memory_projection", "compaction_projection", "isolation_projection"}:
        protocol_key = family.partition("_")[0]
        protocol = package_service_protocols.get(protocol_key)
        retained = protocol.get("retained_surfaces", ()) if isinstance(protocol, Mapping) else ()
        return [
            {
                "surface": str(entry.get("surface") or ""),
                "kind": "compatibility-projection",
                "status": str(entry.get("status") or "compatibility-only"),
            }
            for entry in retained
            if isinstance(entry, Mapping) and entry.get("surface")
        ]
    if family == "teammates_projection":
        return [
            {
                "surface": surface,
                "kind": "compatibility-projection",
                "status": str(compatibility_surfaces.get(surface) or "compatibility-only"),
            }
            for surface in ("RuntimeServices.teammates", "RuntimeAssembly.teammates")
        ]
    if family == "agent_owned_hooks":
        return [
            {
                "surface": "AgentDefinition.hooks",
                "kind": "legacy-authoring-surface",
                "status": "rejected-by-default",
            }
        ]
    return []


def _compatibility_usage_from_runtime_metadata(
    metadata: Mapping[str, Any],
) -> dict[str, tuple[str, ...]]:
    raw = metadata.get("compatibility_usage")
    if not isinstance(raw, Mapping):
        return {}
    usage: dict[str, tuple[str, ...]] = {}
    for family, surfaces in raw.items():
        if not isinstance(surfaces, Sequence) or isinstance(surfaces, (str, bytes)):
            continue
        normalized: list[str] = []
        for surface in surfaces:
            text = str(surface).strip()
            if text and text not in normalized:
                normalized.append(text)
        if normalized:
            usage[str(family)] = tuple(normalized)
    return usage


def _compatibility_retirement_metadata(services: RuntimeServices) -> dict[str, Any]:
    profile = _legacy_profile_from_runtime_metadata(services.metadata)
    compatibility_boundaries = services.metadata.get("compatibility_boundaries", {})
    if not isinstance(compatibility_boundaries, Mapping):
        compatibility_boundaries = {}
    package_service_protocols = services.metadata.get("package_service_protocols", {})
    if not isinstance(package_service_protocols, Mapping):
        package_service_protocols = {}
    context_contributors = services.metadata.get("context_contributors", {})
    if not isinstance(context_contributors, Mapping):
        context_contributors = {}
    compatibility_surfaces = services.metadata.get("compatibility_surfaces", {})
    if not isinstance(compatibility_surfaces, Mapping):
        compatibility_surfaces = {}
    observed_usage = _compatibility_usage_from_runtime_metadata(services.metadata)

    families: list[dict[str, Any]] = []
    active_families: list[str] = []
    for definition in LEGACY_COMPATIBILITY_FAMILIES:
        observed_surfaces = observed_usage.get(definition.family, ())
        activation = family_activation_state(definition.family, profile)
        if observed_surfaces:
            activation = ClosureActivationState.LEGACY_MODE_ENABLED
        if activation is ClosureActivationState.LEGACY_MODE_ENABLED:
            active_families.append(definition.family)
        surfaces = _compatibility_retirement_surface_entries(
            definition.family,
            compatibility_boundaries=compatibility_boundaries,
            package_service_protocols=package_service_protocols,
            context_contributors=context_contributors,
            compatibility_surfaces=compatibility_surfaces,
        )
        families.append(
            {
                **definition.to_metadata(),
                "activation": activation.value,
                "legacy_mode_enabled": profile.is_enabled(definition.family),
                "compatibility_observed": bool(observed_surfaces),
                "observed_surfaces": list(observed_surfaces),
                "surfaces": surfaces,
            }
        )
    return {
        "schema_version": "1.0",
        "documented_families": [definition.family for definition in LEGACY_COMPATIBILITY_FAMILIES],
        "inventory_complete": len(families) == len(LEGACY_COMPATIBILITY_FAMILIES),
        "legacy_profile": profile.to_metadata(),
        "active_families": active_families,
        "observed_usage": {family: list(surfaces) for family, surfaces in observed_usage.items()},
        "families": families,
        "supported_hook_migration_paths": {
            "skill_and_invocation_definition_hooks": "normalized into HookRegistrationRequest before activation",
            "agent_owned_hooks": "rejected by default unless the agent_owned_hooks legacy family is enabled",
        },
    }


def _durability_entry(
    state: PersistenceDurabilityState,
    *,
    component: Any = None,
    available: bool = True,
) -> dict[str, Any]:
    return {
        "durability": state.value,
        "available": bool(available),
        "provider": (type(component).__name__ if component is not None else None),
    }


def _classify_durability(
    component: Any,
    *,
    durable_types: tuple[type[Any], ...],
    non_durable_types: tuple[type[Any], ...],
    available: bool = True,
) -> dict[str, Any]:
    if component is None:
        return _durability_entry(
            PersistenceDurabilityState.NON_DURABLE,
            component=None,
            available=available,
        )
    if isinstance(component, durable_types):
        return _durability_entry(PersistenceDurabilityState.DURABLE, component=component, available=available)
    if isinstance(component, non_durable_types):
        return _durability_entry(
            PersistenceDurabilityState.NON_DURABLE,
            component=component,
            available=available,
        )
    return _durability_entry(PersistenceDurabilityState.HOST_PROVIDED, component=component, available=available)


def _memory_durability_entry(memory_service: Any) -> dict[str, Any]:
    if memory_service is None or isinstance(memory_service, NoopMemoryService):
        return _durability_entry(PersistenceDurabilityState.NON_DURABLE, available=False)
    provider = getattr(getattr(memory_service, "manager", None), "provider", None)
    if isinstance(provider, FileMemoryProvider):
        return _durability_entry(PersistenceDurabilityState.DURABLE, component=provider)
    if provider is None:
        return _durability_entry(PersistenceDurabilityState.HOST_PROVIDED, component=memory_service)
    return _durability_entry(PersistenceDurabilityState.HOST_PROVIDED, component=provider)


def _persistence_profile_metadata(
    services: RuntimeServices,
    *,
    runtime: RuntimeAssembly | None = None,
) -> dict[str, Any]:
    distribution = str(services.metadata.get("distribution") or "")
    profile_kind = "production_oriented" if distribution == "weavert-full" else "lightweight"
    team_control_plane = services.resolve_team_control_plane()
    team_store = getattr(team_control_plane, "store", None) if team_control_plane is not None else None
    run_store = getattr(getattr(runtime, "agent_runtime", None), "run_store", None)
    transcript_store = getattr(getattr(services, "transcript", None), "store", None)
    surfaces = {
        "transcript": _classify_durability(
            transcript_store,
            durable_types=(FileTranscriptStore,),
            non_durable_types=(InMemoryTranscriptStore,),
        ),
        "child_runs": _classify_durability(
            run_store,
            durable_types=(FileChildRunStore,),
            non_durable_types=(InMemoryChildRunStore,),
        ),
        "jobs": _classify_durability(
            services.job_service.store,
            durable_types=(FileJobStore,),
            non_durable_types=(InMemoryJobStore,),
        ),
        "task_lists": _classify_durability(
            services.task_list_service.store,
            durable_types=(FileTaskListStore,),
            non_durable_types=(InMemoryTaskListStore,),
        ),
        "team_state": _classify_durability(
            team_store,
            durable_types=(FileBackedTeamStore,),
            non_durable_types=(InMemoryTeamStore,),
            available=team_control_plane is not None,
        ),
        "memory": _memory_durability_entry(services.resolve_memory_service()),
    }
    findings: list[str] = []
    if distribution == "weavert-full":
        if surfaces["transcript"]["durability"] != PersistenceDurabilityState.DURABLE.value:
            findings.append("weavert-full requires a durable transcript store")
        if surfaces["child_runs"]["durability"] != PersistenceDurabilityState.DURABLE.value:
            findings.append("weavert-full requires a durable child-run store")
    return {
        "schema_version": "1.0",
        "profile_name": distribution or "custom",
        "profile_kind": profile_kind,
        "status": "pass" if not findings else "fail",
        "surfaces": surfaces,
        "findings": findings,
    }


def _isolation_readiness_metadata(services: RuntimeServices) -> dict[str, Any]:
    isolation_service = services.resolve_isolation_service()
    raw_modes = (
        isolation_service.describe_modes()
        if isolation_service is not None and hasattr(isolation_service, "describe_modes")
        else {
            IsolationMode.NONE.value: {"status": "ready"},
            IsolationMode.WORKTREE.value: {"status": "unknown"},
            IsolationMode.REMOTE.value: {"status": "unknown"},
        }
    )
    modes = {
        mode.value: (
            dict(raw_modes.get(mode.value, {}))
            if isinstance(raw_modes.get(mode.value), Mapping)
            else {"status": "unknown", "effective_mode": mode.value}
        )
        for mode in IsolationMode
    }
    worktree_status = str(modes[IsolationMode.WORKTREE.value].get("status") or "unknown")
    remote_status = str(modes[IsolationMode.REMOTE.value].get("status") or "unknown")
    findings: list[str] = []
    if worktree_status not in {"ready", "not_available"}:
        findings.append("worktree isolation must publish a real local lease or an honest unavailable state")
    if remote_status not in {"ready", "adapter_provided", "not_configured", "not_available"}:
        findings.append("remote isolation must use adapter-backed readiness or an honest unavailable state")
    return {
        "schema_version": "1.0",
        "status": "pass" if not findings else "fail",
        "modes": modes,
        "findings": findings,
    }


def _closure_report_metadata(
    services: RuntimeServices,
    *,
    runtime: RuntimeAssembly | None = None,
) -> dict[str, Any]:
    compatibility_retirement = _compatibility_retirement_metadata(services)
    persistence_profile = _persistence_profile_metadata(services, runtime=runtime)
    isolation_readiness = _isolation_readiness_metadata(services)
    blocking_reasons: list[str] = []
    if compatibility_retirement.get("active_families"):
        blocking_reasons.extend(
            f"legacy compatibility enabled: {family}"
            for family in compatibility_retirement["active_families"]
        )
    if persistence_profile.get("status") != "pass":
        blocking_reasons.extend(str(item) for item in persistence_profile.get("findings", ()))
    if isolation_readiness.get("status") != "pass":
        blocking_reasons.extend(str(item) for item in isolation_readiness.get("findings", ()))
    status = ClosureStatus.GREEN if not blocking_reasons else ClosureStatus.RED
    return {
        "schema_version": "1.0",
        "published_metadata_paths": [
            "weavert.services.metadata['closure_report']",
            "weavert.metadata['closure_report']",
        ],
        "status": status.value,
        "closure_green": status is ClosureStatus.GREEN,
        "blocking_reasons": blocking_reasons,
        "compatibility_retirement": compatibility_retirement,
        "persistence_profile": persistence_profile,
        "isolation_readiness": isolation_readiness,
    }


def _team_protocol_only_findings(
    *,
    distribution: str,
    team_protocol_only: Mapping[str, Any],
    services: RuntimeServices | None = None,
    runtime: RuntimeAssembly | None = None,
) -> list[dict[str, Any]]:
    if not team_protocol_only:
        return []
    replacement_matrix = team_protocol_only.get("replacement_matrix", ())
    if not isinstance(replacement_matrix, Sequence):
        replacement_matrix = ()
    replacement_map = {
        str(entry.get("surface")): entry
        for entry in replacement_matrix
        if isinstance(entry, Mapping) and entry.get("surface")
    }
    team_selected = bool(team_protocol_only.get("team_package_selected"))
    host_facet = team_protocol_only.get("host_facet_keys")
    if not isinstance(host_facet, Mapping):
        host_facet = {}
    extension_contract = team_protocol_only.get("extension_event_contract")
    if not isinstance(extension_contract, Mapping):
        extension_contract = {}
    capability_keys = team_protocol_only.get("capability_keys")
    if not isinstance(capability_keys, Mapping):
        capability_keys = {}
    capability_available = {
        name: (
            services.resolve_capability(str(capability_keys.get(name) or ""))
            if services is not None and capability_keys.get(name)
            else None
        )
        for name in (
            "team_control_plane",
            "team_message_bus",
            "team_workflows",
        )
    }
    host_facet_resolution = (
        services.resolve_team_workflow_host_facet()
        if services is not None and hasattr(services, "resolve_team_workflow_host_facet")
        else None
    )
    services_projection_absent = (
        services is None
        or all(
            not hasattr(services, name)
            for name in (
                "team_control_plane",
                "team_message_bus",
                "team_workflows",
            )
        )
    )
    runtime_projection_absent = (
        runtime is None
        or all(
            not hasattr(runtime, name)
            for name in (
                "team_control_plane",
                "team_message_bus",
                "team_workflows",
            )
        )
    )
    capability_state_matches_selection = (
        all(value is not None for value in capability_available.values())
        if team_selected
        else all(value is None for value in capability_available.values())
    )
    host_facet_state_matches_selection = (
        host_facet_resolution is not None
        and host_facet_resolution.available is team_selected
        and ((host_facet_resolution.facet is not None) if team_selected else (host_facet_resolution.facet is None))
    )
    extension_event_contract_live = (
        services is not None and hasattr(getattr(services, "host", None), "emit_extension_event")
    )

    workflow_surfaces = (
        "BoundHostRuntime.list_team_workflows",
        "BoundHostRuntime.respond_team_workflow",
    )
    workflow_finding = {
        "rule_id": "team_workflow_wrapper_authority",
        "family": "team-bridge",
        "status": (
            "pass"
            if all(surface in replacement_map for surface in workflow_surfaces)
            and host_facet_state_matches_selection
            else "fail"
        ),
        "distribution": distribution,
        "canonical_path": "RuntimeAssembly.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)",
        "compat_surface": "BoundHostRuntime.list_team_workflows",
        "replacement_path": "RuntimeHostFacetKey.TEAM_WORKFLOWS.value",
        "availability": "team-present" if team_selected else "team-absent",
        "evidence": [
            *workflow_surfaces,
            str(host_facet.get("team_workflows") or RuntimeHostFacetKey.TEAM_WORKFLOWS.value),
        ],
    }

    host_event_surface = "HostRuntime.emit_team_event"
    host_event_finding = {
        "rule_id": "team_host_event_bridge_authority",
        "family": "team-bridge",
        "status": (
            "pass"
            if host_event_surface in replacement_map and extension_event_contract_live
            else "fail"
        ),
        "distribution": distribution,
        "canonical_path": "HostRuntime.emit_extension_event",
        "compat_surface": host_event_surface,
        "replacement_path": str(
            replacement_map.get(host_event_surface, {}).get("replacement_path")
            or "HostRuntime.emit_extension_event"
        ),
        "availability": "team-present" if team_selected else "team-absent",
        "evidence": [
            "HostRuntime.emit_extension_event",
            str(extension_contract.get("namespace") or "weavert.team"),
        ],
    }

    projection_surfaces = (
        "RuntimeServices.team_control_plane",
        "RuntimeServices.team_message_bus",
        "RuntimeServices.team_workflows",
        "RuntimeAssembly.team_control_plane",
        "RuntimeAssembly.team_message_bus",
        "RuntimeAssembly.team_workflows",
    )
    projection_finding = {
        "rule_id": "team_runtime_projection_authority",
        "family": "team-bridge",
        "status": (
            "pass"
            if all(surface in replacement_map for surface in projection_surfaces)
            and capability_state_matches_selection
            and services_projection_absent
            and runtime_projection_absent
            else "fail"
        ),
        "distribution": distribution,
        "canonical_path": (
            "RuntimeServices.resolve_team_* / "
            "RuntimeAssembly.resolve_capability(RuntimeCapabilityKey.TEAM_*.value)"
        ),
        "replacement_path": (
            "RuntimeCapabilityKey.TEAM_CONTROL_PLANE / "
            "RuntimeCapabilityKey.TEAM_MESSAGE_BUS / "
            "RuntimeCapabilityKey.TEAM_WORKFLOWS"
        ),
        "availability": "team-present" if team_selected else "team-absent",
        "evidence": list(projection_surfaces),
    }
    return [projection_finding, workflow_finding, host_event_finding]


def _provider_provenance_findings(
    *,
    distribution: str,
    invocation_provider_registrations: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    canonical_path = "builtin_skill_baseline / PackageContribution.invocation_providers"
    replacement_path = "PackageContribution.invocation_providers"
    baseline_tier: list[dict[str, Any]] = []
    package_tiers: list[dict[str, Any]] = []
    unexpected_registrations: list[dict[str, Any]] = []
    evidence: list[str] = []

    for index, raw_entry in enumerate(invocation_provider_registrations):
        if not isinstance(raw_entry, Mapping):
            unexpected_registrations.append(
                {"index": index, "reason": "invalid-registration-metadata"}
            )
            continue
        provider_name = str(raw_entry.get("provider_name") or "")
        origin = str(raw_entry.get("origin") or "")
        registration_path = str(raw_entry.get("registration_path") or "")
        provider_tier = str(raw_entry.get("provider_tier") or "")
        owner = raw_entry.get("owner")
        if not provider_tier:
            if origin == "builtin" and registration_path == "builtin_skill_baseline":
                provider_tier = "builtin-baseline"
            elif origin == "package" and registration_path == "PackageContribution.invocation_providers":
                provider_tier = "package-contribution"

        label = provider_name or f"<unnamed:{index}>"
        if registration_path:
            label = f"{label}@{registration_path}"
        evidence.append(label)

        entry: dict[str, Any] = {
            "provider_name": provider_name,
            "origin": origin,
            "registration_path": registration_path,
            "provider_tier": provider_tier,
        }
        if isinstance(owner, Mapping) and owner.get("package_name"):
            entry["package_name"] = str(owner.get("package_name"))

        if (
            index == 0
            and origin == "builtin"
            and registration_path == "builtin_skill_baseline"
            and provider_tier == "builtin-baseline"
        ):
            baseline_tier.append(entry)
            continue
        if (
            origin == "package"
            and registration_path == "PackageContribution.invocation_providers"
            and provider_tier == "package-contribution"
        ):
            package_tiers.append(entry)
            continue
        unexpected_registrations.append(entry)

    finding: dict[str, Any] = {
        "rule_id": "invocation_provider_provenance",
        "family": "provider-provenance",
        "status": "pass" if baseline_tier and not unexpected_registrations else "fail",
        "distribution": distribution,
        "canonical_path": canonical_path,
        "replacement_path": replacement_path,
        "evidence": evidence,
        "baseline_tier": baseline_tier,
        "package_tiers": package_tiers,
    }
    if unexpected_registrations:
        finding["unexpected_registrations"] = unexpected_registrations
    return [finding]


_PROTOCOL_ONLY_REQUIRED_FINDING_FIELDS = (
    "rule_id",
    "family",
    "status",
    "distribution",
    "evidence",
    "canonical_path",
)
_PROTOCOL_ONLY_OPTIONAL_FINDING_FIELDS = (
    "compat_surface",
    "replacement_path",
)
_PROTOCOL_ONLY_REQUIRED_GATE_FAMILIES = (
    "privileged-service-slot",
    "context-authority",
    "task-authority",
    "team-bridge",
    "provider-provenance",
    "kernel-assembly",
    "compatibility-retirement",
    "persistence-profile",
    "isolation-readiness",
)
_PROTOCOL_ONLY_GATE_GREEN_CRITERIA = {
    "required_distributions": [
        "weavert-core",
        "weavert-default",
        "weavert-full",
    ],
    "required_optional_package_cases": [
        "team-present",
        "team-absent",
        "explicit-package-enabled",
        "explicit-package-disabled",
    ],
}
_PROTOCOL_ONLY_MATRIX_CASES = (
    {
        "case_id": "weavert-core",
        "distribution": "weavert-core",
        "enabled_packages": (),
        "disabled_packages": (),
        "availability": ("team-absent",),
    },
    {
        "case_id": "weavert-default",
        "distribution": "weavert-default",
        "enabled_packages": (),
        "disabled_packages": (),
        "availability": ("team-present",),
    },
    {
        "case_id": "weavert-full",
        "distribution": "weavert-full",
        "enabled_packages": (),
        "disabled_packages": (),
        "availability": ("team-present",),
    },
    {
        "case_id": "weavert-core+weavert-planning",
        "distribution": "weavert-core",
        "enabled_packages": ("weavert-planning",),
        "disabled_packages": (),
        "availability": ("explicit-package-enabled",),
    },
    {
        "case_id": "weavert-full-weavert-planning",
        "distribution": "weavert-full",
        "enabled_packages": (),
        "disabled_packages": ("weavert-planning",),
        "availability": ("explicit-package-disabled",),
    },
)


def _protocol_only_finding_schema() -> dict[str, Any]:
    return {
        "required_fields": list(_PROTOCOL_ONLY_REQUIRED_FINDING_FIELDS),
        "optional_fields": list(_PROTOCOL_ONLY_OPTIONAL_FINDING_FIELDS),
    }


def _kernel_assembly_findings(
    *,
    distribution: str,
    official_package_catalog_provenance: Mapping[str, Any],
    resolved_active_package_graph_provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    provider_kind = str(official_package_catalog_provenance.get("provider_kind") or "")
    provider_path = str(official_package_catalog_provenance.get("provider_path") or "")
    retired_helpers = official_package_catalog_provenance.get("retired_kernel_helpers", ())
    if not isinstance(retired_helpers, Sequence) or isinstance(retired_helpers, (str, bytes)):
        retired_helpers = ()
    official_entries = official_package_catalog_provenance.get("entries", {})
    if not isinstance(official_entries, Mapping):
        official_entries = {}
    resolved_packages = resolved_active_package_graph_provenance.get("resolved_packages", ())
    if not isinstance(resolved_packages, Sequence) or isinstance(resolved_packages, (str, bytes)):
        resolved_packages = ()

    official_graph_entries = [
        entry
        for entry in resolved_packages
        if isinstance(entry, Mapping) and str(entry.get("origin") or "") == "first_party"
    ]
    evidence = [
        (
            f"{entry.get('package_name')}@{entry.get('assembly_entrypoint')}"
            if entry.get("assembly_entrypoint")
            else str(entry.get("package_name") or "<unknown>")
        )
        for entry in official_graph_entries
    ]
    missing_catalog_entries = [
        str(entry.get("package_name") or "")
        for entry in official_graph_entries
        if str(entry.get("package_name") or "") not in official_entries
    ]
    missing_entrypoints = [
        str(entry.get("package_name") or "")
        for entry in official_graph_entries
        if not str(entry.get("assembly_entrypoint") or "")
    ]
    legacy_helper_retired = (
        "weavert.runtime_package_manifests.assembly_function_name" in retired_helpers
    )
    status = (
        "pass"
        if provider_kind == "manifest-backed"
        and provider_path == "weavert.runtime_package_catalog:official_runtime_package_catalog"
        and legacy_helper_retired
        and not missing_catalog_entries
        and not missing_entrypoints
        else "fail"
    )
    finding: dict[str, Any] = {
        "rule_id": "official_package_catalog_authority",
        "family": "kernel-assembly",
        "status": status,
        "distribution": distribution,
        "canonical_path": "weavert.runtime_package_catalog:official_runtime_package_catalog",
        "replacement_path": "RuntimePackageManifest.assembly_entrypoint",
        "evidence": evidence,
    }
    if missing_catalog_entries:
        finding["missing_catalog_entries"] = missing_catalog_entries
    if missing_entrypoints:
        finding["missing_entrypoints"] = missing_entrypoints
    if provider_kind and provider_kind != "manifest-backed":
        finding["provider_kind"] = provider_kind
    return [finding]


def _protocol_only_rule_sources() -> dict[str, dict[str, Any]]:
    return {
        "memory_service_slot_authority": {
            "family": "privileged-service-slot",
            "source_path": "weavert.services.metadata['package_service_protocols']['memory']",
        },
        "compaction_service_slot_authority": {
            "family": "privileged-service-slot",
            "source_path": "weavert.services.metadata['package_service_protocols']['compaction']",
        },
        "isolation_service_slot_authority": {
            "family": "privileged-service-slot",
            "source_path": "weavert.services.metadata['package_service_protocols']['isolation']",
        },
        "invocation_provider_provenance": {
            "family": "provider-provenance",
            "source_path": "weavert.services.metadata['invocation_provider_registrations']",
        },
        "runtime_context_authority": {
            "family": "context-authority",
            "source_path": "weavert.services.metadata['compatibility_boundaries']['runtime_context']",
        },
        "task_manager_authority": {
            "family": "task-authority",
            "source_path": "weavert.services.metadata['compatibility_boundaries']['TaskManager']",
        },
        "team_runtime_projection_authority": {
            "family": "team-bridge",
            "source_path": "weavert.services.metadata['migration']['team_protocol_only']",
        },
        "team_workflow_wrapper_authority": {
            "family": "team-bridge",
            "source_path": "weavert.services.metadata['migration']['team_protocol_only']",
        },
        "team_host_event_bridge_authority": {
            "family": "team-bridge",
            "source_path": "weavert.services.metadata['migration']['team_protocol_only']",
        },
        "official_package_catalog_authority": {
            "family": "kernel-assembly",
            "source_path": (
                "weavert.services.metadata['official_package_catalog_provenance'] / "
                "weavert.services.metadata['resolved_active_package_graph_provenance']"
            ),
        },
        "compatibility_retirement_state": {
            "family": "compatibility-retirement",
            "source_path": "weavert.services.metadata['closure_report']['compatibility_retirement']",
        },
        "persistence_profile_state": {
            "family": "persistence-profile",
            "source_path": "weavert.services.metadata['closure_report']['persistence_profile']",
        },
        "isolation_readiness_state": {
            "family": "isolation-readiness",
            "source_path": "weavert.services.metadata['closure_report']['isolation_readiness']",
        },
    }


def _protocol_only_family_status(
    findings: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for finding in findings:
        family = str(finding.get("family") or "")
        if not family:
            continue
        grouped.setdefault(family, []).append(finding)
    return {
        family: {
            "status": (
                "pass"
                if entries and all(str(entry.get("status") or "") == "pass" for entry in entries)
                else "fail"
            ),
            "rule_ids": [str(entry.get("rule_id") or "") for entry in entries],
        }
        for family, entries in grouped.items()
    }


def _protocol_only_required_family_status(
    findings: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    family_status = _protocol_only_family_status(findings)
    return {
        family: dict(
            family_status.get(
                family,
                {
                    "status": "fail",
                    "rule_ids": [],
                },
            )
        )
        for family in _PROTOCOL_ONLY_REQUIRED_GATE_FAMILIES
    }


def _protocol_only_status(family_status: Mapping[str, Mapping[str, Any]]) -> str:
    return (
        "pass"
        if all(str(entry.get("status") or "") == "pass" for entry in family_status.values())
        else "fail"
    )


def _protocol_only_current_assembly_metadata(
    findings: Sequence[Mapping[str, Any]],
    *,
    distribution: str,
    selected_packages: Sequence[str] = (),
) -> dict[str, Any]:
    family_status = _protocol_only_required_family_status(findings)
    return {
        "distribution": distribution,
        "selected_packages": [str(name) for name in selected_packages],
        "status": _protocol_only_status(family_status),
        "family_status": family_status,
    }


def _protocol_only_matrix_case_results(kernel: RuntimeKernel) -> list[dict[str, Any]]:
    case_results: list[dict[str, Any]] = []
    base_config = kernel.config
    for case in _PROTOCOL_ONLY_MATRIX_CASES:
        case_config = replace(
            base_config,
            runtime_id=f"{base_config.runtime_id}:{case['case_id']}",
            distribution=str(case["distribution"]),
            enabled_packages={str(name) for name in case.get("enabled_packages", ())},
            disabled_packages={str(name) for name in case.get("disabled_packages", ())},
            _skip_protocol_only_matrix_evaluation=True,
        )
        case_runtime = assemble_runtime(case_config)
        case_findings = case_runtime.metadata.get("protocol_only_conformance", {}).get("findings", ())
        if not isinstance(case_findings, Sequence) or isinstance(case_findings, (str, bytes)):
            case_findings = ()
        case_family_status = _protocol_only_required_family_status(case_findings)
        case_results.append(
            {
                "case_id": str(case["case_id"]),
                "distribution": str(case["distribution"]),
                "availability": [str(name) for name in case.get("availability", ())],
                "selected_packages": list(case_runtime.kernel.first_party_packages),
                "status": _protocol_only_status(case_family_status),
                "family_status": case_family_status,
            }
        )
    return case_results


def _protocol_only_supports_matrix_evaluation(
    *,
    selected_packages: Sequence[str],
    resolved_active_package_graph_provenance: Mapping[str, Any],
) -> bool:
    official_package_set = set(official_runtime_package_names())
    if not selected_packages:
        return False
    if any(str(name) not in official_package_set for name in selected_packages):
        return False
    resolved_packages = resolved_active_package_graph_provenance.get("resolved_packages", ())
    if not isinstance(resolved_packages, Sequence) or isinstance(resolved_packages, (str, bytes)):
        return False
    return all(
        isinstance(entry, Mapping)
        and str(entry.get("package_name") or "") in official_package_set
        for entry in resolved_packages
    )


def _protocol_only_matrix_family_status(
    case_results: Sequence[Mapping[str, Any]],
    *,
    current_assembly: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    family_status: dict[str, dict[str, Any]] = {}
    for family in _PROTOCOL_ONLY_REQUIRED_GATE_FAMILIES:
        case_entries: list[dict[str, Any]] = []
        rule_ids: list[str] = []
        for case in case_results:
            case_family_status = case.get("family_status", {})
            if not isinstance(case_family_status, Mapping):
                case_family_status = {}
            family_entry = case_family_status.get(family, {})
            if not isinstance(family_entry, Mapping):
                family_entry = {}
            case_entries.append(
                {
                    "case_id": str(case.get("case_id") or ""),
                    "distribution": str(case.get("distribution") or ""),
                    "availability": [str(name) for name in case.get("availability", ())],
                    "status": str(family_entry.get("status") or "fail"),
                }
            )
            for rule_id in family_entry.get("rule_ids", ()):
                value = str(rule_id)
                if value and value not in rule_ids:
                    rule_ids.append(value)
        current_family_status = (
            current_assembly.get("family_status", {}).get(family, {})
            if isinstance(current_assembly, Mapping)
            else {}
        )
        if not isinstance(current_family_status, Mapping):
            current_family_status = {}
        case_entries.append(
            {
                "case_id": "current-assembly",
                "distribution": (
                    str(current_assembly.get("distribution") or "")
                    if isinstance(current_assembly, Mapping)
                    else ""
                ),
                "availability": ["current-assembly"],
                "status": str(current_family_status.get("status") or "fail"),
            }
        )
        for rule_id in current_family_status.get("rule_ids", ()):
            value = str(rule_id)
            if value and value not in rule_ids:
                rule_ids.append(value)
        family_status[family] = {
            "status": (
                "pass"
                if case_entries and all(entry["status"] == "pass" for entry in case_entries)
                else "fail"
            ),
            "rule_ids": rule_ids,
            "cases": case_entries,
        }
    return family_status


def _protocol_only_gate_metadata(
    findings: Sequence[Mapping[str, Any]],
    *,
    distribution: str,
    selected_packages: Sequence[str] = (),
    case_results: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    current_assembly = _protocol_only_current_assembly_metadata(
        findings,
        distribution=distribution,
        selected_packages=selected_packages,
    )
    if case_results:
        family_status = _protocol_only_matrix_family_status(
            case_results,
            current_assembly=current_assembly,
        )
        scope = "distribution-matrix"
        status = _protocol_only_status(family_status)
    else:
        family_status = current_assembly["family_status"]
        scope = "current-assembly"
        status = current_assembly["status"]
    gate: dict[str, Any] = {
        "mode": "enforced",
        "scope": scope,
        "status": status,
        "required_families": list(_PROTOCOL_ONLY_REQUIRED_GATE_FAMILIES),
        "family_status": family_status,
        "green_criteria": dict(_PROTOCOL_ONLY_GATE_GREEN_CRITERIA),
        "current_assembly": current_assembly,
    }
    if case_results:
        gate["matrix_cases"] = [
            {
                "case_id": str(case.get("case_id") or ""),
                "distribution": str(case.get("distribution") or ""),
                "availability": [str(name) for name in case.get("availability", ())],
                "selected_packages": [str(name) for name in case.get("selected_packages", ())],
                "status": str(case.get("status") or "fail"),
            }
            for case in case_results
        ]
    return gate


def _protocol_only_conformance_metadata(
    *,
    distribution: str,
    compatibility_boundaries: Mapping[str, Any],
    package_service_protocols: Mapping[str, Any],
    closure_report: Mapping[str, Any],
    invocation_provider_registrations: Sequence[Mapping[str, Any]] = (),
    team_protocol_only: Mapping[str, Any] | None = None,
    official_package_catalog_provenance: Mapping[str, Any] | None = None,
    resolved_active_package_graph_provenance: Mapping[str, Any] | None = None,
    services: RuntimeServices | None = None,
    runtime: RuntimeAssembly | None = None,
) -> dict[str, Any]:
    if not isinstance(resolved_active_package_graph_provenance, Mapping):
        resolved_active_package_graph_provenance = {}
    selected_packages = resolved_active_package_graph_provenance.get("selected_first_party_packages", ())
    if not isinstance(selected_packages, Sequence) or isinstance(selected_packages, (str, bytes)):
        selected_packages = ()
    if not isinstance(closure_report, Mapping):
        closure_report = {}
    compatibility_retirement = closure_report.get("compatibility_retirement", {})
    if not isinstance(compatibility_retirement, Mapping):
        compatibility_retirement = {}
    persistence_profile = closure_report.get("persistence_profile", {})
    if not isinstance(persistence_profile, Mapping):
        persistence_profile = {}
    isolation_readiness = closure_report.get("isolation_readiness", {})
    if not isinstance(isolation_readiness, Mapping):
        isolation_readiness = {}
    runtime_context = compatibility_boundaries.get("runtime_context")
    task_manager = compatibility_boundaries.get("TaskManager")
    runtime_context_entries = (
        runtime_context.get("entry_points", ())
        if isinstance(runtime_context, Mapping)
        else ()
    )
    runtime_context_unknown = (
        [
            str(surface)
            for surface in runtime_context.get("unclassified_surfaces", ())
        ]
        if isinstance(runtime_context, Mapping)
        else []
    )
    task_manager_adapters = (
        task_manager.get("materialization_adapters", ())
        if isinstance(task_manager, Mapping)
        else ()
    )
    task_manager_unknown = (
        [
            str(surface)
            for surface in task_manager.get("unclassified_surfaces", ())
        ]
        if isinstance(task_manager, Mapping)
        else []
    )
    runtime_context_finding: dict[str, Any] = {
        "rule_id": "runtime_context_authority",
        "family": "context-authority",
        "status": "pass" if not runtime_context_unknown else "fail",
        "distribution": distribution,
        "canonical_path": "PromptContextEnvelope / RuntimePrivateContext",
        "compat_surface": "runtime_context",
        "evidence": [
            str(entry.get("surface"))
            for entry in runtime_context_entries
            if isinstance(entry, Mapping)
        ],
    }
    if runtime_context_unknown:
        runtime_context_finding["unknown_surfaces"] = list(runtime_context_unknown)

    task_manager_finding: dict[str, Any] = {
        "rule_id": "task_manager_authority",
        "family": "task-authority",
        "status": "pass" if not task_manager_unknown else "fail",
        "distribution": distribution,
        "canonical_path": "RuntimeServices.job_service / RuntimeServices.task_list_service",
        "compat_surface": "TaskManager",
        "evidence": [
            str(entry.get("surface"))
            for entry in task_manager_adapters
            if isinstance(entry, Mapping)
        ],
    }
    if task_manager_unknown:
        task_manager_finding["unknown_surfaces"] = list(task_manager_unknown)
    privileged_service_findings: list[dict[str, Any]] = []
    for family, spec in _PACKAGE_SERVICE_PROTOCOL_SPECS.items():
        protocol_metadata = package_service_protocols.get(family)
        if not isinstance(protocol_metadata, Mapping):
            protocol_metadata = {}
        retained_surfaces = protocol_metadata.get("retained_surfaces", ())
        if not isinstance(retained_surfaces, Sequence):
            retained_surfaces = ()
        projection = protocol_metadata.get("compatibility_projection")
        compat_surface = (
            str(projection.get("surface"))
            if isinstance(projection, Mapping) and projection.get("surface")
            else str(spec["projection_surface"])
        )
        canonical_path = str(protocol_metadata.get("canonical_key") or "")
        owner = protocol_metadata.get("owner")
        owner_available = isinstance(owner, Mapping) and bool(owner.get("package_name"))
        evidence = [
            str(surface.get("surface"))
            for surface in retained_surfaces
            if isinstance(surface, Mapping) and surface.get("surface")
        ]
        privileged_service_findings.append(
            {
                "rule_id": f"{family}_service_slot_authority",
                "family": "privileged-service-slot",
                "status": (
                    "pass"
                    if canonical_path == str(spec["capability_key"]) and owner_available
                    else "fail"
                ),
                "distribution": distribution,
                "canonical_path": canonical_path,
                "compat_surface": compat_surface,
                "evidence": evidence,
            }
        )
    findings = [
        *privileged_service_findings,
        *_provider_provenance_findings(
            distribution=distribution,
            invocation_provider_registrations=invocation_provider_registrations,
        ),
        runtime_context_finding,
        task_manager_finding,
        *_team_protocol_only_findings(
            distribution=distribution,
            team_protocol_only=team_protocol_only or {},
            services=services,
            runtime=runtime,
        ),
        *_kernel_assembly_findings(
            distribution=distribution,
            official_package_catalog_provenance=official_package_catalog_provenance or {},
            resolved_active_package_graph_provenance=(
                resolved_active_package_graph_provenance or {}
            ),
        ),
        {
            "rule_id": "compatibility_retirement_state",
            "family": "compatibility-retirement",
            "status": (
                "pass"
                if compatibility_retirement.get("inventory_complete") is True
                and not compatibility_retirement.get("active_families")
                else "fail"
            ),
            "distribution": distribution,
            "canonical_path": "weavert.metadata['closure_report']['compatibility_retirement']",
            "evidence": [
                str(item.get("family") or "")
                for item in compatibility_retirement.get("families", ())
                if isinstance(item, Mapping)
            ],
        },
        {
            "rule_id": "persistence_profile_state",
            "family": "persistence-profile",
            "status": "pass" if persistence_profile.get("status") == "pass" else "fail",
            "distribution": distribution,
            "canonical_path": "weavert.metadata['closure_report']['persistence_profile']",
            "evidence": [
                f"{name}:{entry.get('durability')}"
                for name, entry in persistence_profile.get("surfaces", {}).items()
                if isinstance(entry, Mapping)
            ],
        },
        {
            "rule_id": "isolation_readiness_state",
            "family": "isolation-readiness",
            "status": "pass" if isolation_readiness.get("status") == "pass" else "fail",
            "distribution": distribution,
            "canonical_path": "weavert.metadata['closure_report']['isolation_readiness']",
            "evidence": [
                f"{name}:{entry.get('status')}"
                for name, entry in isolation_readiness.get("modes", {}).items()
                if isinstance(entry, Mapping)
            ],
        },
    ]
    kernel = getattr(runtime, "kernel", None) if runtime is not None else None
    case_results = ()
    if (
        kernel is not None
        and not kernel.config._skip_protocol_only_matrix_evaluation
        and _protocol_only_supports_matrix_evaluation(
            selected_packages=selected_packages,
            resolved_active_package_graph_provenance=resolved_active_package_graph_provenance,
        )
    ):
        case_results = _protocol_only_matrix_case_results(kernel)
    return {
        "schema_version": "1.0",
        "published_metadata_paths": [
            "weavert.services.metadata['protocol_only_conformance']",
            "weavert.metadata['protocol_only_conformance']",
        ],
        "finding_schema": _protocol_only_finding_schema(),
        "rule_sources": _protocol_only_rule_sources(),
        "findings": findings,
        "gate": _protocol_only_gate_metadata(
            findings,
            distribution=distribution,
            selected_packages=selected_packages,
            case_results=case_results,
        ),
    }


def _sync_package_service_protocol_metadata(services: RuntimeServices) -> None:
    services.metadata["package_service_protocols"] = _package_service_protocol_metadata(services)


def _sync_compatibility_boundary_metadata(
    services: RuntimeServices,
    *,
    kernel: RuntimeKernel | None = None,
    runtime: RuntimeAssembly | None = None,
) -> None:
    _ = kernel
    compatibility_surfaces = services.metadata.get("compatibility_surfaces")
    if not isinstance(compatibility_surfaces, Mapping):
        compatibility_surfaces = {}
    package_lookup = services.metadata.get("package_lookup")
    if not isinstance(package_lookup, Mapping):
        package_lookup = {}
    package_service_protocols = services.metadata.get("package_service_protocols")
    if not isinstance(package_service_protocols, Mapping):
        package_service_protocols = {}
    migration = services.metadata.get("migration")
    if not isinstance(migration, Mapping):
        migration = {}
    official_package_catalog_provenance = services.metadata.get("official_package_catalog_provenance")
    if not isinstance(official_package_catalog_provenance, Mapping):
        official_package_catalog_provenance = {}
    resolved_active_package_graph_provenance = services.metadata.get(
        "resolved_active_package_graph_provenance"
    )
    if not isinstance(resolved_active_package_graph_provenance, Mapping):
        resolved_active_package_graph_provenance = {}
    compatibility_boundaries = _compatibility_boundaries_metadata(
        compatibility_surfaces=compatibility_surfaces,
        package_lookup=package_lookup,
    )
    services.metadata["compatibility_boundaries"] = compatibility_boundaries
    services.metadata["closure_report"] = _closure_report_metadata(
        services,
        runtime=runtime,
    )
    closure_report = services.metadata.get("closure_report")
    if not isinstance(closure_report, Mapping):
        closure_report = {}
    services.metadata["protocol_only_conformance"] = _protocol_only_conformance_metadata(
        distribution=str(services.metadata.get("distribution") or ""),
        compatibility_boundaries=compatibility_boundaries,
        package_service_protocols=package_service_protocols,
        closure_report=closure_report,
        invocation_provider_registrations=(
            services.metadata.get("invocation_provider_registrations", ())
            if isinstance(services.metadata.get("invocation_provider_registrations"), Sequence)
            else ()
        ),
        team_protocol_only=(
            migration.get("team_protocol_only")
            if isinstance(migration.get("team_protocol_only"), Mapping)
            else {}
        ),
        official_package_catalog_provenance=official_package_catalog_provenance,
        resolved_active_package_graph_provenance=resolved_active_package_graph_provenance,
        services=services,
        runtime=runtime,
    )


def _sync_core_protocol_catalog_metadata(services: RuntimeServices) -> None:
    services.metadata["core_protocol_catalog"] = build_stable_core_protocol_catalog(
        compatibility_surfaces=services.metadata.get("compatibility_surfaces"),
        package_lookup=services.metadata.get("package_lookup"),
        invocation_provider_paths=services.metadata.get("invocation_provider_paths"),
    )


def _project_capability_compatibility_surfaces(services: RuntimeServices) -> None:
    memory = services.resolve_capability(RuntimeCapabilityKey.MEMORY_SERVICE.value)
    compaction = services.resolve_capability(RuntimeCapabilityKey.COMPACTION_MANAGER.value)
    isolation = services.resolve_capability(RuntimeCapabilityKey.ISOLATION_MANAGER.value)
    teammates = services.resolve_capability(RuntimeCapabilityKey.TEAMMATES.value)
    projections = services.metadata.setdefault("compatibility_projections", {})
    for projection_name in (
        "memory",
        "compaction",
        "isolation",
        "teammates",
    ):
        projections.pop(projection_name, None)
    if memory is not None:
        projections["memory"] = RuntimeCapabilityKey.MEMORY_SERVICE.value
    if compaction is not None:
        projections["compaction"] = RuntimeCapabilityKey.COMPACTION_MANAGER.value
    if isolation is not None:
        projections["isolation"] = RuntimeCapabilityKey.ISOLATION_MANAGER.value
    if teammates is not None:
        services.bind_teammates(teammates)
        projections["teammates"] = RuntimeCapabilityKey.TEAMMATES.value


async def _run_runtime_lifecycle(
    services: RuntimeServices,
    *,
    runtime: RuntimeAssembly,
    kernel: RuntimeKernel,
) -> tuple[dict[str, Any], ...]:
    failures: list[dict[str, Any]] = []
    failures.extend(
        await services.dispatch_lifecycle_phase(
            PackageLifecyclePhase.RUNTIME_START,
            runtime=runtime,
            kernel=kernel,
        )
    )
    _schedule_job_recovery(services.job_service)
    failures.extend(
        await services.dispatch_lifecycle_phase(
            PackageLifecyclePhase.RUNTIME_RECOVERY,
            runtime=runtime,
            kernel=kernel,
        )
    )
    return tuple(failures)


def _start_runtime_lifecycle(
    services: RuntimeServices,
    **kwargs: Any,
) -> None:
    if not hasattr(services, "dispatch_lifecycle_phase"):
        if hasattr(services, "mark_runtime_ready"):
            services.mark_runtime_ready(())
        _schedule_job_recovery(services.job_service)
        return
    coroutine = _run_runtime_lifecycle(services, **kwargs)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        failures = asyncio.run(coroutine)
        if hasattr(services, "mark_runtime_ready"):
            services.mark_runtime_ready(failures)
        return
    task = loop.create_task(coroutine)
    if hasattr(services, "begin_runtime_lifecycle"):
        services.begin_runtime_lifecycle(task)


def _register_job_executors(
    *,
    kernel: RuntimeKernel,
    services: RuntimeServices,
    agent_runtime: AgentRuntime,
    package_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...] = (),
) -> None:
    registry = services.job_service.executor_registry
    registry.register("agent", agent_runtime.job_executor, builtin=True, override=True)
    for manifest, contribution in package_contributions:
        for executor_binding in contribution.job_executors:
            binding = executor_binding.binding
            executor = (
                binding.executor
                if binding.executor is not None
                else binding.factory(executor_binding.kind, binding, kernel, services)
            )
            registry.register(
                executor_binding.kind,
                executor,
                builtin=True,
                override=True,
            )
            services.metadata.setdefault("package_job_executors", []).append(
                {
                    "kind": executor_binding.kind,
                    "package_name": manifest.name,
                }
            )
    for executor_kind, binding in kernel.config.job_executors.items():
        executor = (
            binding.executor
            if binding.executor is not None
            else binding.factory(executor_kind, binding, kernel, services)
        )
        registry.register(executor_kind, executor, override=True)


def _schedule_job_recovery(job_service: DefaultJobService) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(job_service.recover_inflight())
        return
    loop.create_task(job_service.recover_inflight())


def _assemble_core_isolation_manager() -> Any:
    manager_type = load_object("weavert.isolation:IsolationManager")
    adapter_type = load_object("weavert.isolation:BaseIsolationAdapter")
    return manager_type(adapters={IsolationMode.NONE: adapter_type()})


def _first_party_package_catalog(
    selected_packages: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    return official_runtime_package_catalog_metadata(selected_packages)


def _team_bridge_replacement_matrix() -> list[dict[str, Any]]:
    return [
        {
            "surface": "RuntimeServices.team_control_plane",
            "status": "removed",
            "replacement_path": "RuntimeServices.resolve_team_control_plane()",
            "team_present_semantics": "returns the canonical weavert.team.control_plane capability",
            "team_absent_semantics": "returns None because weavert-team is not selected",
        },
        {
            "surface": "RuntimeServices.team_message_bus",
            "status": "removed",
            "replacement_path": "RuntimeServices.resolve_team_message_bus()",
            "team_present_semantics": "returns the canonical weavert.team.message_bus capability",
            "team_absent_semantics": "returns None because weavert-team is not selected",
        },
        {
            "surface": "RuntimeServices.team_workflows",
            "status": "removed",
            "replacement_path": "RuntimeServices.resolve_team_workflows()",
            "team_present_semantics": "returns the canonical weavert.team.workflows capability",
            "team_absent_semantics": "returns None because weavert-team is not selected",
        },
        {
            "surface": "RuntimeAssembly.team_control_plane",
            "status": "removed",
            "replacement_path": (
                "RuntimeAssembly.resolve_capability(RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value)"
            ),
            "team_present_semantics": "resolves the canonical weavert.team.control_plane capability",
            "team_absent_semantics": "returns None because weavert-team is not selected",
        },
        {
            "surface": "RuntimeAssembly.team_message_bus",
            "status": "removed",
            "replacement_path": (
                "RuntimeAssembly.resolve_capability(RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)"
            ),
            "team_present_semantics": "resolves the canonical weavert.team.message_bus capability",
            "team_absent_semantics": "returns None because weavert-team is not selected",
        },
        {
            "surface": "RuntimeAssembly.team_workflows",
            "status": "removed",
            "replacement_path": (
                "RuntimeAssembly.resolve_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value)"
            ),
            "team_present_semantics": "resolves the canonical weavert.team.workflows capability",
            "team_absent_semantics": "returns None because weavert-team is not selected",
        },
        {
            "surface": "BoundHostRuntime.list_team_workflows",
            "status": "removed",
            "replacement_path": "BoundHostRuntime.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)",
            "team_present_semantics": "the resolved host facet lists team workflows",
            "team_absent_semantics": "host facet resolution returns not_available without restoring helpers",
        },
        {
            "surface": "BoundHostRuntime.respond_team_workflow",
            "status": "removed",
            "replacement_path": "BoundHostRuntime.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)",
            "team_present_semantics": "the resolved host facet responds to team workflows",
            "team_absent_semantics": "host facet resolution returns not_available without restoring helpers",
        },
        {
            "surface": "HostRuntime.emit_team_event",
            "status": "removed",
            "replacement_path": "HostRuntime.emit_extension_event(HostExtensionEvent(namespace='weavert.team', ...))",
            "team_present_semantics": "team packages emit namespace-scoped extension events",
            "team_absent_semantics": "no weavert.team extension events are emitted",
        },
    ]


def _team_protocol_only_migration_metadata(
    *,
    selected_packages: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "team_package_selected": "weavert-team" in selected_packages,
        "capability_keys": {
            "team_control_plane": RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value,
            "team_message_bus": RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value,
            "team_workflows": RuntimeCapabilityKey.TEAM_WORKFLOWS.value,
        },
        "host_facet_keys": {
            "team_workflows": RuntimeHostFacetKey.TEAM_WORKFLOWS.value,
        },
        "extension_event_contract": {
            "emit": "HostRuntime.emit_extension_event",
            "envelope": "weavert.hosts.HostExtensionEvent",
            "namespace": "weavert.team",
            "schema_version": "1.0",
            "unknown_namespace_behavior": "ignore_or_handle_generically",
        },
        "replacement_matrix": _team_bridge_replacement_matrix(),
    }


def _migration_metadata(
    *,
    selected_packages: tuple[str, ...],
    distribution: str,
) -> dict[str, Any]:
    stable_phases = sorted(STABLE_PUBLIC_PHASE_CONTRACTS)
    advanced_phases = sorted(ADVANCED_PUBLIC_PHASE_CONTRACTS)
    metadata: dict[str, Any] = {
        "distribution": distribution,
        "devtools": {
            "selected": "weavert-devtools" in selected_packages,
            "target_distribution": "weavert-full",
            "target_package": "weavert-devtools",
            "tools": list(FIRST_PARTY_PACKAGE_SPECS["weavert-devtools"].builtin_tools),
            "agents": list(FIRST_PARTY_PACKAGE_SPECS["weavert-devtools"].builtin_agents),
        },
        "planning_profiles": {
            "selected": "weavert-planning" in selected_packages,
            "target_distribution": "weavert-full",
            "target_package": "weavert-planning",
            "agents": list(FIRST_PARTY_PACKAGE_SPECS["weavert-planning"].builtin_agents),
            "shared_primitives_owner": "weavert-core",
            "shared_primitives": ["task_*", "job_*"],
            "helper_agent": "plan",
            "helper_package": "weavert-devtools",
        },
        "hook_contract": {
            "stable_public_phases": stable_phases,
            "advanced_public_phases": advanced_phases,
            "stable_handler_kinds": [kind.value for kind in STABLE_PUBLIC_HOOK_HANDLER_KINDS],
            "advanced_handler_kinds": [kind.value for kind in ADVANCED_HOOK_HANDLER_KINDS],
        },
        "capability_packages": {
            "remember": "weavert-memory",
            "team_create": "weavert-team",
            "team_spawn": "weavert-team",
            "team_send": "weavert-team",
            "team_respond": "weavert-team",
            "team_delete": "weavert-team",
            "verify": "weavert-builtin-workflows",
            "debug": "weavert-builtin-workflows",
            "stuck": "weavert-builtin-workflows",
            "batch": "weavert-builtin-workflows",
            "simplify": "weavert-builtin-workflows",
        },
        "package_lookup": _package_lookup_metadata(),
        "team_protocol_only": _team_protocol_only_migration_metadata(
            selected_packages=selected_packages,
        ),
    }
    return metadata


def _package_migration_diagnostics(
    *,
    selected_packages: tuple[str, ...],
    distribution: str,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    if "weavert-devtools" not in selected_packages:
        diagnostics.append(
            Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="runtime_devtools_not_selected",
                message=(
                    "Workspace-oriented tools and coding agents now live in "
                    "weavert-devtools and are only included automatically in "
                    "weavert-full."
                ),
                details={
                    "distribution": distribution,
                    "target_package": "weavert-devtools",
                    "target_distribution": "weavert-full",
                    "tools": list(FIRST_PARTY_PACKAGE_SPECS["weavert-devtools"].builtin_tools),
                    "agents": list(FIRST_PARTY_PACKAGE_SPECS["weavert-devtools"].builtin_agents),
                },
            )
        )
    if "weavert-planning" not in selected_packages:
        diagnostics.append(
            Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="runtime_planning_not_selected",
                message=(
                    "Official shared-planning profiles now live in weavert-planning and are only "
                    "included automatically in weavert-full; core task/job primitives remain in "
                    "weavert-core."
                ),
                details={
                    "distribution": distribution,
                    "target_package": "weavert-planning",
                    "target_distribution": "weavert-full",
                    "agents": list(FIRST_PARTY_PACKAGE_SPECS["weavert-planning"].builtin_agents),
                    "shared_primitives_owner": "weavert-core",
                    "shared_primitives": ["task_*", "job_*"],
                    "helper_agent": "plan",
                    "helper_package": "weavert-devtools",
                },
            )
        )
    return tuple(diagnostics)


def _serialize_agent_run_result(
    result: AgentRunResult,
    *,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return project_agent_run_result(result, runtime_metadata=runtime_metadata)


def _serialize_skill_execution_result(
    result: SkillExecutionResult,
    *,
    runtime_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "skill": result.skill_name,
        "mode": result.mode.value,
        "injected_messages": [_serialize_message(message) for message in result.injected_messages],
        "request_override": (
            result.request_override.serialize()
            if result.request_override is not None
            else None
        ),
    }
    if result.agent_result is not None:
        payload["agent_result"] = _serialize_agent_run_result(
            result.agent_result,
            runtime_metadata=runtime_metadata,
        )
    return payload


def _delegation_policy_error_result(
    exc: DelegationPolicyError,
) -> ExecutionResult[dict[str, Any]]:
    payload = exc.to_payload()
    return ExecutionResult(
        status=ExecutionStatus.FAILED,
        value=payload,
        error=str(exc),
        metadata=payload,
    )


def _task_list_error_result(exc: TaskListError) -> ExecutionResult[dict[str, Any]]:
    return _structured_task_error(exc.code, str(exc), **exc.details)


def _structured_task_error(code: str, message: str, **details: Any) -> ExecutionResult[dict[str, Any]]:
    return ExecutionResult(
        status=ExecutionStatus.FAILED,
        value={"error": {"code": code, "message": message, "details": details}},
        error=message,
        metadata={"category": code, **details},
    )


def _serialize_message(message: RuntimeMessage) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "role": message.role.value,
        "content": serialize_content_blocks(message.content),
        "metadata": dict(message.metadata),
    }


def _merged_private_context(
    private_context: RuntimePrivateContext | dict[str, object] | None,
    runtime_context: dict[str, object] | None,
) -> RuntimePrivateContext:
    return merge_runtime_private_context(
        coerce_private_context(private_context),
        runtime_context,
    )


def _serialize_job(task: Any) -> dict[str, Any]:
    if hasattr(task, "job_id"):
        return job_record_to_payload(task)
    return {
        "job_id": task.task_id,
        "executor_kind": str(task.metadata.get("executor_kind") or task.metadata.get("kind") or "legacy"),
        "summary": task.title,
        "description": task.description,
        "status": task.status.value,
        "control": {
            "stoppable": bool(task.metadata.get("stoppable", False)),
            "stop_requested": task.stop_requested,
        },
        "timestamps": {
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "started_at": None,
            "ended_at": task.updated_at.isoformat()
            if task.status.value in {"completed", "failed", "stopped"}
            else None,
        },
        "visibility": {
            "session_id": task.metadata.get("session_id"),
            "team_id": task.metadata.get("team_id"),
            "submitted_by": task.metadata.get("submitted_by"),
            "projection_kind": task.metadata.get("projection_kind") or task.metadata.get("kind"),
        },
        "linkage": {
            "parent_run_id": task.metadata.get("run_id"),
            "parent_turn_id": task.metadata.get("turn_id"),
        },
        "result": task.result,
        "error": task.error,
        "metadata": dict(task.metadata),
        "sidecars": [],
    }


def _serialize_team_workflow_record(record: Any) -> dict[str, Any]:
    workflow_kind = getattr(record, "workflow_kind", None)
    status = getattr(record, "status", None)
    return {
        "workflow_id": getattr(record, "workflow_id", ""),
        "team_id": getattr(record, "team_id", ""),
        "workflow_kind": getattr(workflow_kind, "value", workflow_kind),
        "requester_member_id": getattr(record, "requester_member_id", ""),
        "requester_name": getattr(record, "requester_name", None),
        "responder_member_id": getattr(record, "responder_member_id", None),
        "responder_name": getattr(record, "responder_name", None),
        "leader_session_id": getattr(record, "leader_session_id", None),
        "status": getattr(status, "value", status),
        "allowed_actions": list(getattr(record, "allowed_actions", ()) or ()),
        "request_payload": dict(getattr(record, "request_payload", {}) or {}),
        "response_payload": (
            None
            if getattr(record, "response_payload", None) is None
            else dict(getattr(record, "response_payload", {}) or {})
        ),
        "message_ids": list(getattr(record, "message_ids", ()) or ()),
        "created_at": _serialize_optional_datetime(getattr(record, "created_at", None)),
        "updated_at": _serialize_optional_datetime(getattr(record, "updated_at", None)),
        "deadline_at": _serialize_optional_datetime(getattr(record, "deadline_at", None)),
        "terminal_at": _serialize_optional_datetime(getattr(record, "terminal_at", None)),
        "terminal": bool(getattr(record, "terminal", False)),
        "metadata": dict(getattr(record, "metadata", {}) or {}),
    }


def _visible_invocation_snapshot(
    value: InvocationCapabilityView,
) -> RuntimeAssemblyVisibleInvocationSnapshot:
    return RuntimeAssemblyVisibleInvocationSnapshot(
        name=value.name,
        source_kind=value.source_kind.value,
        description=value.description,
        display_name=value.display_name,
        argument_hint=value.argument_hint,
        user_invocable=value.user_invocable,
        model_invocable=value.model_invocable,
        source_label=value.source_label,
        metadata=value.metadata,
    )


def _invocation_diagnostics_snapshot(
    value: InvocationDiagnostics,
) -> RuntimeAssemblyInvocationDiagnosticsSnapshot:
    return RuntimeAssemblyInvocationDiagnosticsSnapshot(
        name=value.name,
        source_kind=value.source_kind.value,
        visible=value.visible,
        user_invocable=value.user_invocable,
        model_invocable=value.model_invocable,
        hidden_reason=value.hidden_reason.value if value.hidden_reason is not None else None,
        matched_paths=tuple(value.matched_paths),
        path_match_state=value.path_match_state.value,
        narrowed_by_policy=value.narrowed_by_policy,
        metadata=value.metadata,
    )


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    stringified = str(value).strip()
    return stringified or None


def _serialize_optional_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _resolve_invocation_cwd(base_cwd: Path, requested_cwd: str | None) -> Path:
    if requested_cwd is None:
        return base_cwd
    resolved = Path(requested_cwd)
    if not resolved.is_absolute():
        resolved = (base_cwd / resolved).resolve()
    return resolved


def _coerce_spawn_mode(value: str | None) -> SpawnMode | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    return SpawnMode(normalized)


def _coerce_permission_mode(value: str | None) -> PermissionMode | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    return PermissionMode(normalized)


def _coerce_isolation_mode(value: str | None) -> IsolationMode | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    return IsolationMode(normalized)


def _default_model_client(config: RuntimeConfig) -> Any:
    if config.model_client is not None:
        return config.model_client
    if config.default_model_route is not None:
        binding = config.model_routes.get(config.default_model_route)
        if binding is not None:
            if binding.client is not None:
                return binding.client
            if binding.provider_binding is not None:
                provider = config.model_providers.get(binding.provider_binding)
                if provider is not None:
                    return provider.client
    return None


def _helper_session_close_status(
    session: SessionController,
    *,
    terminal: Any | None = None,
    default: str = "completed",
) -> str:
    if terminal is not None:
        if getattr(terminal, "error", None):
            return "failed"
        if getattr(terminal, "abort_reason", None):
            return "interrupted"
        post_effects = getattr(terminal, "post_effects", None)
        if post_effects is not None:
            session_status_hint = getattr(post_effects, "session_status_hint", None)
            if session_status_hint == "waiting":
                return "stopped"
            if session_status_hint == "interrupted":
                return "interrupted"
        terminal_metadata = getattr(terminal, "metadata", None)
        if isinstance(terminal_metadata, dict):
            failure_class = terminal_metadata.get("failure_class")
            if failure_class not in {None, "", "none"}:
                return "failed"
            if terminal_metadata.get("continuation_blocked"):
                return "stopped"
        if getattr(terminal, "stop_reason", None) == "interrupted":
            return "interrupted"
        if getattr(terminal, "stop_reason", None) == "blocked":
            return "stopped"
    if session.state.status == SessionStatus.INTERRUPTED:
        return "interrupted"
    if session.state.status == SessionStatus.FAILED:
        return "failed"
    if session.state.status == SessionStatus.STOPPED:
        return "stopped"
    return default


def _workflow_run_collect_event(
    state: _WorkflowRunCollectorState,
    session: SessionController,
    event: TurnStreamEvent,
) -> None:
    if state.turn_id is None:
        request = getattr(event, "request", None)
        turn_context = getattr(request, "turn_context", None)
        state.turn_id = (
            getattr(turn_context, "turn_id", None)
            or getattr(getattr(event, "workflow_observation", None), "turn_id", None)
            or session.state.active_turn_id
        )
    observation = getattr(event, "workflow_observation", None)
    if observation is not None and observation.workflow.run_kind == WorkflowRunKind.ROOT:
        state.workflow_observability = observation.workflow
    if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
        state.messages.append(event.message)
    elif event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
        state.terminal = event.terminal
        state.final_status = _helper_session_close_status(
            session,
            terminal=event.terminal,
            default=state.final_status,
        )


def _workflow_run_report_from_collector(
    session: SessionController,
    state: _WorkflowRunCollectorState,
    *,
    session_owner: Literal["helper", "caller"],
    finalization: WorkflowRunFinalizationReport | None = None,
) -> WorkflowRunReport:
    return WorkflowRunReport(
        session_id=session.state.session_id,
        agent_name=session.state.current_agent,
        cwd=session.cwd,
        turn_id=state.turn_id,
        messages=tuple(state.messages),
        terminal=state.terminal,
        final_status=_helper_session_close_status(
            session,
            terminal=state.terminal,
            default=state.final_status,
        ),
        session_owner=session_owner,
        finalization=finalization or WorkflowRunFinalizationReport(),
        workflow_observability=state.workflow_observability,
    )


async def _workflow_run_complete_report(
    session: SessionController,
    state: _WorkflowRunCollectorState,
    *,
    session_owner: Literal["helper", "caller"],
    wait_for_finalization: bool,
    include_consolidation: bool,
    finalization_cursor: _WorkflowRunFinalizationCursor,
) -> WorkflowRunReport:
    report = _workflow_run_report_from_collector(
        session,
        state,
        session_owner=session_owner,
    )
    if session_owner == "helper":
        await session.close(final_status=report.final_status)
    finalization = await _workflow_run_finalization_report(
        session,
        requested=wait_for_finalization,
        include_consolidation=include_consolidation,
        cursor=finalization_cursor,
    )
    return replace(report, finalization=finalization)


def _workflow_run_reset_caller_owned_session(session: SessionController) -> None:
    session.state.active_turn_id = None
    session.state.status = SessionStatus.READY


def _workflow_run_discard_unused_helper_owned_session(session: SessionController) -> None:
    session.state.active_turn_id = None
    session.state.status = SessionStatus.INTERRUPTED
    session.state.queued_commands.clear()
    if hasattr(session, "_started"):
        session._started = False
    if hasattr(session, "_session_open_dispatched"):
        session._session_open_dispatched = False
    if hasattr(session, "_closed"):
        session._closed = True
    if hasattr(session.runtime_services, "session_registry"):
        session.runtime_services.session_registry.unregister(
            session.state.session_id,
            session=session,
        )
    try:
        if session.runtime_services.hook_bus is not None:
            session.runtime_services.hook_bus.clear_session(session.state.session_id)
    except Exception:
        pass


async def _workflow_run_finalization_report(
    session: SessionController,
    *,
    requested: bool,
    include_consolidation: bool,
    cursor: _WorkflowRunFinalizationCursor | None = None,
) -> WorkflowRunFinalizationReport:
    tasks = _workflow_run_finalization_tasks(
        session,
        include_consolidation=include_consolidation,
        cursor=cursor,
    )
    if not tasks:
        return WorkflowRunFinalizationReport(requested=requested)
    memory_service = session.runtime_services.resolve_memory_service()
    reports: list[WorkflowRunFinalizationTask] = []
    for kind, task_id in tasks:
        waited = False
        result: MemoryTurnResult | None = None
        error: str | None = None
        if requested:
            wait_method = _workflow_run_wait_method(memory_service, kind)
            if wait_method is not None:
                waited = True
                try:
                    pending = wait_method(task_id)
                    resolved = await pending if inspect.isawaitable(pending) else pending
                    if isinstance(resolved, MemoryTurnResult):
                        result = resolved
                except Exception as exc:  # pragma: no cover - defensive reporting path
                    error = str(exc)
        reports.append(
            WorkflowRunFinalizationTask(
                kind=kind,
                task_id=task_id,
                waited=waited,
                result=result,
                error=error,
            )
        )
    return WorkflowRunFinalizationReport(
        requested=requested,
        tasks=tuple(reports),
    )


def _workflow_run_finalization_tasks(
    session: SessionController,
    *,
    include_consolidation: bool,
    cursor: _WorkflowRunFinalizationCursor | None = None,
) -> tuple[tuple[str, str], ...]:
    tasks: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    _collect_workflow_run_task_ids(
        tasks,
        seen,
        kind="background_memory_extraction",
        raw_ids=session.state.metadata.get("background_memory_tasks"),
        start=cursor.extraction_count if cursor is not None else 0,
    )
    if include_consolidation:
        _collect_workflow_run_task_ids(
            tasks,
            seen,
            kind="background_memory_consolidation",
            raw_ids=session.state.metadata.get("background_memory_consolidation_tasks"),
            start=cursor.consolidation_count if cursor is not None else 0,
        )
    return tuple(tasks)


def _collect_workflow_run_task_ids(
    tasks: list[tuple[str, str]],
    seen: set[tuple[str, str]],
    *,
    kind: str,
    raw_ids: Any,
    start: int = 0,
) -> None:
    if not isinstance(raw_ids, list):
        return
    for value in raw_ids[max(start, 0) :]:
        normalized = str(value).strip()
        key = (kind, normalized)
        if not normalized or key in seen:
            continue
        seen.add(key)
        tasks.append((kind, normalized))


def _workflow_run_finalization_cursor(
    session: SessionController,
) -> _WorkflowRunFinalizationCursor:
    return _WorkflowRunFinalizationCursor(
        extraction_count=_workflow_run_task_count(
            session.state.metadata.get("background_memory_tasks")
        ),
        consolidation_count=_workflow_run_task_count(
            session.state.metadata.get("background_memory_consolidation_tasks")
        ),
    )


def _workflow_run_task_count(raw_ids: Any) -> int:
    if not isinstance(raw_ids, list):
        return 0
    return len(raw_ids)


def _workflow_run_wait_method(memory_service: Any, kind: str) -> Any | None:
    if memory_service is None:
        return None
    if kind == "background_memory_extraction":
        return getattr(memory_service, "wait_for_background_extraction", None)
    if kind == "background_memory_consolidation":
        return getattr(memory_service, "wait_for_background_consolidation", None)
    return None


def _register_builtin_tools(
    registry: ToolRegistry,
    config: RuntimeConfig,
    definitions: tuple[ToolDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        if not config.builtins.tool_enabled(definition.name):
            continue
        replacement = config.builtins.tool_replacements.get(definition.name, definition)
        if replacement is not definition:
            replacement = preserve_builtin_owner(
                replacement,
                original_definition=definition,
            )
        diagnostics.extend(registry.register(replacement).diagnostics)
    for extra in config.builtins.extra_tools:
        diagnostics.extend(registry.register(extra).diagnostics)


def _register_builtin_agents(
    registry: AgentRegistry,
    config: RuntimeConfig,
    definitions: tuple[AgentDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        if not config.builtins.agent_enabled(definition.name):
            continue
        replacement = config.builtins.agent_replacements.get(definition.name, definition)
        if replacement is not definition:
            replacement = preserve_builtin_owner(
                replacement,
                original_definition=definition,
            )
        diagnostics.extend(registry.register(replacement).diagnostics)
    for extra in config.builtins.extra_agents:
        diagnostics.extend(registry.register(extra).diagnostics)


def _register_builtin_skills(
    registry: SkillRegistry,
    config: RuntimeConfig,
    definitions: tuple[SkillDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        if not config.builtins.skill_enabled(definition.name):
            continue
        replacement = config.builtins.skill_replacements.get(definition.name, definition)
        if replacement is not definition:
            replacement = preserve_builtin_owner(
                replacement,
                original_definition=definition,
            )
        diagnostics.extend(registry.register(replacement).diagnostics)
    for extra in config.builtins.extra_skills:
        diagnostics.extend(registry.register(extra).diagnostics)


def _register_all(
    registry: ToolRegistry | AgentRegistry | SkillRegistry,
    definitions: tuple[ToolDefinition, ...]
    | tuple[AgentDefinition, ...]
    | tuple[SkillDefinition, ...],
    diagnostics: list[Diagnostic],
) -> None:
    for definition in definitions:
        try:
            diagnostics.extend(registry.register(definition).diagnostics)
        except RegistryConflictError as exc:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code=exc.code.value,
                    message=str(exc),
                    definition_type=getattr(registry, "definition_type", "definition"),
                    source=definition.origin.source.value,
                    location=definition.origin.label,
                    details=exc.details,
                )
            )
