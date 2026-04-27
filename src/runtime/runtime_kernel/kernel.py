from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, AsyncIterator, Mapping
from uuid import uuid4

from ..agent_execution import SpawnMode
from ..agent_runtime import AgentInvocation, AgentRunResult, AgentRuntime
from ..builtins import load_builtin_pack
from ..contracts import (
    ExecutionResult,
    ExecutionStatus,
    PromptContextEnvelope,
    RuntimeMessage,
    RuntimePrivateContext,
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
    HookDispatchTraceQuery,
    HookInventoryQuery,
    HookRegistrationRequest,
    HookScopeLifetime,
    HookSourceKind,
    STABLE_PUBLIC_HOOK_HANDLER_KINDS,
    STABLE_PUBLIC_PHASE_CONTRACTS,
)
from ..invocation_catalog import SkillInvocationProvider
from ..jobs import DefaultJobService, InMemoryJobStore, JobScopeFilter, job_record_to_payload
from ..package_profiles import FIRST_PARTY_PACKAGE_SPECS
from ..runtime_package_manifests import official_runtime_package_manifests
from ..runtime_core_protocol_catalog import build_stable_core_protocol_catalog
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
from ..task_discipline import TaskDisciplineSidecar
from ..task_lists import (
    DefaultTaskListService,
    InMemoryTaskListStore,
    TaskDisciplinePolicy,
    TaskListError,
    coerce_private_context,
    task_list_entry_to_dict,
    task_list_snapshot_to_dict,
)
from ..session_runtime import (
    InMemoryTranscriptStore,
    InboundEvent,
    InboundEventType,
    SessionController,
    SessionStatus,
)
from ..skill_runtime import SkillExecutionResult, SkillExecutor
from ..tasking import TaskManager
from ..tool_runtime import ToolContext
from ..turn_engine.composer import ContextAssembler
from ..turn_engine.engine import TurnEngine, TurnStreamEvent, TurnStreamEventType
from ..turn_engine.models import ModelRequest, TranscriptStore
from .config import DefinitionSourcePaths, RuntimeConfig
from ..execution_policy import DelegationPolicyError, default_delegation_policy_metadata, policy_state_from_metadata

SKILL_DYNAMIC_ROOTS_KEY = "skill_dynamic_roots"
_UNSET = object()
_COMPATIBILITY_RUNTIME_ASSEMBLY_PROJECTIONS = {
    "teammates": RuntimeCapabilityKey.TEAMMATES.value,
    "team_control_plane": RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value,
    "team_message_bus": RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value,
    "team_workflows": RuntimeCapabilityKey.TEAM_WORKFLOWS.value,
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
    package_manifests: tuple[RuntimePackageManifest, ...] = ()
    package_service_contributions: tuple[tuple[RuntimePackageManifest, PackageContribution], ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    model_client: Any = None
    transcript_store: Any = None
    services: RuntimeServices | None = None
    hosts: dict[str, HostAdapter] = field(default_factory=dict)
    skill_view_resolver: Any = None


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
    team_control_plane: Any = None
    team_message_bus: Any = None
    team_workflows: Any = None
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

    @property
    def task_manager(self) -> TaskManager:
        if self._task_manager is None:
            self._task_manager = self.services.task_manager
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

    def bind_hook_callback(self, name: str, handler: Any) -> None:
        self.services.hook_bus.bind_callback(name, handler)

    def register_hook(
        self,
        request: HookRegistrationRequest | dict[str, Any],
    ) -> Any:
        return self.services.hook_bus.register_request(
            request,
            source_kind=HookSourceKind.RUNTIME_CONFIG,
            owner=f"runtime:{self.kernel.config.runtime_id}",
            source_ref=self.kernel.config.runtime_id,
            default_scope_lifetime=HookScopeLifetime.SESSION_TEMPLATE,
        )

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
        if facet.available and facet.facet is not None:
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
    ) -> dict[str, Any]:
        await self.wait_until_ready()
        facet = self.services.resolve_team_workflow_host_facet()
        if facet.available and facet.facet is not None:
            record = await facet.facet.respond(
                workflow_id,
                action=action,
                host_name=host_name,
                payload=None if payload is None else dict(payload),
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
        )

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
        await self.wait_until_ready()
        session = self.create_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
        )
        final_status = "completed"
        try:
            return await self._run_prompt_in_session(
                session,
                prompt,
                metadata=metadata,
            )
        except Exception:
            final_status = _helper_session_close_status(session, default="failed")
            raise
        finally:
            await session.close(final_status=final_status)

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
        await self.wait_until_ready()
        session = self.create_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
        )
        final_status = "completed"
        try:
            await self._prepare_one_shot_session(session, prompt, metadata=metadata)
            async for event in session.stream_until_idle():
                if event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
                    final_status = _helper_session_close_status(
                        session,
                        terminal=event.terminal,
                        default=final_status,
                    )
                yield event
        except Exception:
            final_status = _helper_session_close_status(session, default="failed")
            raise
        finally:
            await session.close(
                final_status=_helper_session_close_status(session, default=final_status)
            )

    async def _run_prompt_in_session(
        self,
        session: SessionController,
        prompt: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> tuple[RuntimeMessage, ...]:
        await self._prepare_one_shot_session(session, prompt, metadata=metadata)
        produced: list[RuntimeMessage] = []
        async for event in session.stream_until_idle():
            if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
                produced.append(event.message)
        return tuple(produced)

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
        candidate = (cursor / ".runtime" / "skills").resolve()
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


def build_runtime_kernel(config: RuntimeConfig) -> RuntimeKernel:
    selected_packages = config.selected_first_party_packages()
    package_manifests = official_runtime_package_manifests(selected_packages)
    package_service_contributions = _assemble_package_contributions(
        package_manifests,
        stage=PackageAssemblyStage.SERVICES,
        config=config,
        distribution=config.resolved_distribution().value,
        working_directory=config.working_directory,
    )
    config = _with_package_model_binding_baseline(
        config,
        package_service_contributions=package_service_contributions,
    )
    tool_registry = ToolRegistry()
    agent_registry = AgentRegistry()
    skill_registry = SkillRegistry()
    invocation_registry = InvocationRegistry()
    skill_view_resolver = _SessionSkillViewResolver(
        session_cwd=config.working_directory,
        base_registry=skill_registry,
    )
    diagnostics: list[Diagnostic] = []

    builtin_pack = load_builtin_pack(selected_packages)
    _register_builtin_tools(tool_registry, config, builtin_pack.tools, diagnostics)
    _register_builtin_agents(agent_registry, config, builtin_pack.agents, diagnostics)
    _register_builtin_skills(skill_registry, config, builtin_pack.skills, diagnostics)

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
        distribution=config.resolved_distribution().value,
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
            distribution=config.resolved_distribution().value,
        )
    )

    kernel = RuntimeKernel(
        config=config,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        invocation_registry=invocation_registry,
        distribution=config.resolved_distribution().value,
        first_party_packages=selected_packages,
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
        run_store=kernel.config.child_run_store,
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
    teammates = services.resolve_capability(RuntimeCapabilityKey.TEAMMATES.value)
    team_control_plane = services.resolve_capability(RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value)
    team_message_bus = services.resolve_capability(RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)
    team_workflows = services.resolve_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value)
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
        team_control_plane=team_control_plane,
        team_message_bus=team_message_bus,
        team_workflows=team_workflows,
        system_prompt=kernel.config.system_prompt,
        metadata={
            **dict(kernel.config.metadata),
            "distribution": kernel.distribution,
            "first_party_packages": list(kernel.first_party_packages),
            "package_runtime_contributions": [manifest.name for manifest, _ in runtime_package_contributions],
            "core_protocol_catalog": dict(services.metadata.get("core_protocol_catalog", {})),
            "package_lookup": dict(services.metadata.get("package_lookup", {})),
            "context_contributors": dict(services.metadata.get("context_contributors", {})),
            "compatibility_surfaces": dict(services.metadata.get("compatibility_surfaces", {})),
            "compatibility_projections": dict(services.metadata.get("compatibility_projections", {})),
            "invocation_provider_paths": dict(services.metadata.get("invocation_provider_paths", {})),
            "invocation_provider_registrations": [
                dict(entry) for entry in services.metadata.get("invocation_provider_registrations", ())
            ],
        },
    )
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
    metadata["package_manifests"] = _package_manifest_catalog(kernel.package_manifests)
    metadata["package_service_contributions"] = [
        manifest.name for manifest, _ in kernel.package_service_contributions
    ]
    metadata["package_store_bindings"] = {
        slot: binding.owner.package_name
        for slot, binding in _store_binding_entries(kernel.package_service_contributions).items()
    }
    metadata["compatibility_surfaces"] = {
        "TaskManager": "compatibility-only",
        "runtime_context": "compatibility-only",
        "RuntimeConfig.extra_invocation_providers": "bounded-compatibility",
        "RuntimeServices.memory.collect": "compatibility-only",
        "RuntimeServices.hooks.collect": "compatibility-only",
        "RuntimeServices.task_discipline.collect": "compatibility-only",
        "RuntimeServices.compaction.prepare_turn": "dedicated-control-plane",
        "RuntimeServices.compaction.collect": "dedicated-control-plane",
        "RuntimeServices.teammates": "compatibility-only",
        "RuntimeServices.team_control_plane": "compatibility-only",
        "RuntimeServices.team_message_bus": "compatibility-only",
        "RuntimeServices.team_workflows": "compatibility-only",
        "RuntimeAssembly.teammates": "compatibility-only",
        "RuntimeAssembly.team_control_plane": "compatibility-only",
        "RuntimeAssembly.team_message_bus": "compatibility-only",
        "RuntimeAssembly.team_workflows": "compatibility-only",
        "BoundHostRuntime.list_team_workflows": "compatibility-wrapper",
        "BoundHostRuntime.respond_team_workflow": "compatibility-wrapper",
        "HostRuntime.emit_team_event": "bounded-compatibility",
    }
    metadata["core_protocol_catalog"] = build_stable_core_protocol_catalog()
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
    services.configure_compat(
        permission_handler=kernel.config.permission_handler,
        ask_user_handler=kernel.config.ask_user_handler,
        tool_refresh_callback=kernel.config.tool_refresh_callback,
    )
    if kernel.config.hooks:
        services.hook_bus.register_document(
            hooks=kernel.config.hooks,
            source_kind=HookSourceKind.RUNTIME_CONFIG,
            owner=f"runtime:{kernel.config.runtime_id}",
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
                "registration_path": "PackageContribution.invocation_providers",
                "compatibility_status": "canonical-package-path",
                "package_name": record.manifest.name,
                "package_role": record.manifest.role,
                "package_stage": PackageAssemblyStage.SERVICES.value,
                "package_index": record.package_index,
                "contribution_index": record.contribution_index,
                **dict(record.contribution.metadata),
            },
        )
    for index, provider in enumerate(config.extra_invocation_providers):
        invocation_registry.register_provider(
            provider,
            origin="config",
            order=index,
            metadata={
                "registration_path": "RuntimeConfig.extra_invocation_providers",
                "compatibility_status": "bounded-compatibility",
                "config_index": index,
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
        }
        for manifest in manifests
    }


def _invocation_provider_paths_metadata() -> dict[str, Any]:
    return {
        "builtin_skill_baseline": "baseline",
        "package_contributions": "canonical-package-path",
        "extra_invocation_providers": "bounded-compatibility",
        "canonical_package_surface": "PackageContribution.invocation_providers",
        "compatibility_surface": "RuntimeConfig.extra_invocation_providers",
    }


def _serialize_invocation_provider_registration(
    registration: InvocationProviderRegistration,
) -> dict[str, Any]:
    return {
        "provider_name": registration.name,
        "origin": registration.origin,
        "order": registration.order,
        "sequence": registration.sequence,
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
        "canonical_control_plane_services": {
            "job_service": "RuntimeServices.job_service",
            "task_list_service": "RuntimeServices.task_list_service",
        },
        "canonical_context_contributors": {
            "package_contributions": "PackageContribution.context_contributors",
            "registry": "RuntimeServices.context_contributor_execution_plan",
            "stage_catalog": [
                "memory",
                "hooks",
                "task_policy",
            ],
        },
        "canonical_invocation_providers": {
            "package_contributions": "PackageContribution.invocation_providers",
            "builtins": "builtin_skill_baseline",
        },
        "compatibility_context_contributors": {
            "RuntimeServices.memory.collect": "compatibility-only",
            "RuntimeServices.hooks.collect": "compatibility-only",
            "RuntimeServices.task_discipline.collect": "compatibility-only",
        },
        "dedicated_control_plane_paths": {
            "compaction": "RuntimeServices.compaction.prepare_turn / RuntimeServices.compaction.collect",
        },
        "compatibility_invocation_providers": {
            "embedder_config": "RuntimeConfig.extra_invocation_providers",
        },
        "canonical_lifecycle_phase": PackageLifecyclePhase.SESSION_OPEN.value,
        "canonical_post_ingress_path": "completion_receipts",
        "compatibility_wrappers": [
            "TaskManager",
            "RuntimeServices.teammates",
            "RuntimeServices.team_*",
            "RuntimeAssembly.teammates",
            "RuntimeAssembly.team_*",
            "BoundHostRuntime.list_team_workflows",
            "BoundHostRuntime.respond_team_workflow",
            "HostRuntime.emit_team_event",
        ],
        "wrapper_exit_criteria": [
            "runtime-owned workflow helpers resolve through capability lookup or host facets only",
            "team compatibility projections stop being required by runtime-owned primary paths",
            "TaskManager usage remains compatibility-scoped behind JobService and TaskListService",
        ],
    }


def _project_capability_compatibility_surfaces(services: RuntimeServices) -> None:
    teammates = services.resolve_capability(RuntimeCapabilityKey.TEAMMATES.value)
    control_plane = services.resolve_capability(RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value)
    message_bus = services.resolve_capability(RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)
    workflows = services.resolve_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value)
    projections = services.metadata.setdefault("compatibility_projections", {})
    if teammates is not None:
        services.bind_teammates(teammates)
        projections["teammates"] = RuntimeCapabilityKey.TEAMMATES.value
    if any(component is not None for component in (control_plane, message_bus, workflows)):
        services.bind_team_services(
            control_plane=control_plane,
            message_bus=message_bus,
            workflow_service=workflows,
        )
        if control_plane is not None:
            projections["team_control_plane"] = RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value
        if message_bus is not None:
            projections["team_message_bus"] = RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value
        if workflows is not None:
            projections["team_workflows"] = RuntimeCapabilityKey.TEAM_WORKFLOWS.value


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
    manager_type = load_object("runtime.isolation:IsolationManager")
    adapter_type = load_object("runtime.isolation:BaseIsolationAdapter")
    return manager_type(adapters={IsolationMode.NONE: adapter_type()})


def _first_party_package_catalog(
    selected_packages: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for package_name in selected_packages:
        spec = FIRST_PARTY_PACKAGE_SPECS[package_name]
        entry: dict[str, Any] = {
            "role": spec.role.value,
            "description": spec.description,
            "dependencies": list(spec.dependencies),
        }
        if spec.builtin_tools:
            entry["builtin_tools"] = list(spec.builtin_tools)
        if spec.builtin_agents:
            entry["builtin_agents"] = list(spec.builtin_agents)
        if spec.builtin_skills:
            entry["builtin_skills"] = list(spec.builtin_skills)
        catalog[package_name] = entry
    return catalog


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
            "selected": "runtime-devtools" in selected_packages,
            "target_distribution": "runtime-full",
            "target_package": "runtime-devtools",
            "tools": list(FIRST_PARTY_PACKAGE_SPECS["runtime-devtools"].builtin_tools),
            "agents": list(FIRST_PARTY_PACKAGE_SPECS["runtime-devtools"].builtin_agents),
        },
        "planning_profiles": {
            "selected": "runtime-planning" in selected_packages,
            "target_distribution": "runtime-full",
            "target_package": "runtime-planning",
            "agents": list(FIRST_PARTY_PACKAGE_SPECS["runtime-planning"].builtin_agents),
            "shared_primitives_owner": "runtime-core",
            "shared_primitives": ["task_*", "job_*"],
            "helper_agent": "plan",
            "helper_package": "runtime-devtools",
        },
        "hook_contract": {
            "stable_public_phases": stable_phases,
            "advanced_public_phases": advanced_phases,
            "stable_handler_kinds": [kind.value for kind in STABLE_PUBLIC_HOOK_HANDLER_KINDS],
            "advanced_handler_kinds": [kind.value for kind in ADVANCED_HOOK_HANDLER_KINDS],
        },
        "capability_packages": {
            "remember": "runtime-memory",
            "team_create": "runtime-team",
            "team_spawn": "runtime-team",
            "team_send": "runtime-team",
            "team_respond": "runtime-team",
            "team_delete": "runtime-team",
            "verify": "runtime-builtin-workflows",
            "debug": "runtime-builtin-workflows",
            "stuck": "runtime-builtin-workflows",
            "batch": "runtime-builtin-workflows",
            "simplify": "runtime-builtin-workflows",
        },
        "package_lookup": _package_lookup_metadata(),
    }
    return metadata


def _package_migration_diagnostics(
    *,
    selected_packages: tuple[str, ...],
    distribution: str,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    if "runtime-devtools" not in selected_packages:
        diagnostics.append(
            Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="runtime_devtools_not_selected",
                message=(
                    "Workspace-oriented tools and coding agents now live in "
                    "runtime-devtools and are only included automatically in "
                    "runtime-full."
                ),
                details={
                    "distribution": distribution,
                    "target_package": "runtime-devtools",
                    "target_distribution": "runtime-full",
                    "tools": list(FIRST_PARTY_PACKAGE_SPECS["runtime-devtools"].builtin_tools),
                    "agents": list(FIRST_PARTY_PACKAGE_SPECS["runtime-devtools"].builtin_agents),
                },
            )
        )
    if "runtime-planning" not in selected_packages:
        diagnostics.append(
            Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="runtime_planning_not_selected",
                message=(
                    "Official shared-planning profiles now live in runtime-planning and are only "
                    "included automatically in runtime-full; core task/job primitives remain in "
                    "runtime-core."
                ),
                details={
                    "distribution": distribution,
                    "target_package": "runtime-planning",
                    "target_distribution": "runtime-full",
                    "agents": list(FIRST_PARTY_PACKAGE_SPECS["runtime-planning"].builtin_agents),
                    "shared_primitives_owner": "runtime-core",
                    "shared_primitives": ["task_*", "job_*"],
                    "helper_agent": "plan",
                    "helper_package": "runtime-devtools",
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
    merged: dict[str, object] = {}
    if runtime_context:
        merged.update(runtime_context)
    if private_context is not None:
        merged.update(coerce_private_context(private_context).compat_metadata())
    return coerce_private_context(merged)


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
