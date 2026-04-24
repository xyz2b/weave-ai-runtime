from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, AsyncIterator
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
from ..hosts.base import BoundHostRuntime, HostAdapter, NullHostAdapter
from ..hooks import (
    HookDispatchTraceQuery,
    HookInventoryQuery,
    HookRegistrationRequest,
    HookScopeLifetime,
    HookSourceKind,
)
from ..invocation_catalog import SkillInvocationProvider
from ..jobs import DefaultJobService, FileJobStore, JobScopeFilter, job_record_to_payload
from ..memory import MemoryManagerService
from ..openai_client import (
    OPENAI_PROVIDER_NAME,
    OPENAI_ROUTE_NAME,
    bundled_openai_provider_binding,
    bundled_openai_route_binding,
)
from ..registries import AgentRegistry, DefinitionDiscovery, InvocationRegistry, SkillRegistry, ToolRegistry
from ..runtime_services import DefaultTranscriptService, RuntimeServices
from ..task_discipline import TaskDisciplineSidecar
from ..task_lists import (
    DefaultTaskListService,
    FileTaskListStore,
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
from ..teammate_orchestration import PersistentTeammateOrchestrator
from ..tool_runtime import ToolContext
from ..turn_engine.composer import ContextAssembler
from ..turn_engine.engine import TurnEngine, TurnStreamEvent, TurnStreamEventType
from ..turn_engine.models import ModelRequest, TranscriptStore
from .config import DefinitionSourcePaths, RuntimeConfig
from ..execution_policy import DelegationPolicyError, default_delegation_policy_metadata, policy_state_from_metadata

SKILL_DYNAMIC_ROOTS_KEY = "skill_dynamic_roots"
_UNSET = object()


@dataclass(slots=True)
class RuntimeKernel:
    config: RuntimeConfig
    tool_registry: ToolRegistry
    agent_registry: AgentRegistry
    skill_registry: SkillRegistry
    invocation_registry: InvocationRegistry
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
    task_manager: TaskManager
    job_service: DefaultJobService
    teammates: PersistentTeammateOrchestrator | None = None
    system_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def bind_host(self, host: HostAdapter) -> BoundHostRuntime:
        self.services.bind_host(host)
        return BoundHostRuntime(
            kernel=self.kernel,
            host=host,
            runtime=self,
            services=self.services,
        )

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
        session_runtime_context = dict(session.state.metadata)
        if runtime_context:
            session_runtime_context.update(runtime_context)
        return self.resolve_invocations(
            session_id=session.state.session_id,
            turn_id=session.state.active_turn_id,
            cwd=session.cwd,
            messages=session.messages,
            prompt_context=prompt_context,
            private_context=private_context,
            runtime_context=session_runtime_context,
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
    config = _with_bundled_openai_baseline(config)
    tool_registry = ToolRegistry()
    agent_registry = AgentRegistry()
    skill_registry = SkillRegistry()
    invocation_registry = InvocationRegistry()
    skill_view_resolver = _SessionSkillViewResolver(
        session_cwd=config.working_directory,
        base_registry=skill_registry,
    )
    diagnostics: list[Diagnostic] = []

    builtin_pack = load_builtin_pack()
    _register_builtin_tools(tool_registry, config, builtin_pack.tools, diagnostics)
    _register_builtin_agents(agent_registry, config, builtin_pack.agents, diagnostics)
    _register_builtin_skills(skill_registry, config, builtin_pack.skills, diagnostics)

    discovery = DefinitionDiscovery(config.discovery_sources)
    discovered = discovery.discover()
    diagnostics.extend(discovered.diagnostics)
    _register_all(tool_registry, discovered.tools, diagnostics)
    _register_all(agent_registry, discovered.agents, diagnostics)
    _register_all(skill_registry, discovered.skills, diagnostics)
    invocation_registry.register_provider(
        SkillInvocationProvider(
            skill_registry,
            skill_resolver=skill_view_resolver,
        )
    )
    for provider in config.extra_invocation_providers:
        invocation_registry.register_provider(provider)
    diagnostics.extend(invocation_registry.diagnostics())

    kernel = RuntimeKernel(
        config=config,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        invocation_registry=invocation_registry,
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
    task_manager = services.task_manager
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
    teammates = None
    teammate_config = kernel.config.teammate_orchestration
    if teammate_config is not None and teammate_config.enabled:
        teammates = PersistentTeammateOrchestrator(
            config=teammate_config,
            project_root=kernel.config.working_directory,
            runtime_services=services,
            execution_core=agent_runtime,
        )
        services.bind_teammates(teammates)
    runtime = RuntimeAssembly(
        kernel=kernel,
        services=services,
        turn_engine=turn_engine,
        agent_runtime=agent_runtime,
        skill_executor=skill_executor,
        transcript_store=transcript_store,
        task_manager=task_manager,
        job_service=services.job_service,
        teammates=teammates,
        system_prompt=kernel.config.system_prompt,
        metadata=dict(kernel.config.metadata),
    )
    _register_job_executors(kernel=kernel, services=services, agent_runtime=agent_runtime)
    _schedule_job_recovery(services.job_service)
    services.bind_execution(
        agent_runner=runtime.run_agent_tool,
        skill_runner=runtime.run_skill_tool,
    )
    return runtime


def _build_runtime_services(kernel: RuntimeKernel) -> RuntimeServices:
    transcript_store = kernel.transcript_store or InMemoryTranscriptStore()
    task_list_service = DefaultTaskListService(
        store=FileTaskListStore(kernel.config.working_directory / ".runtime" / "task_lists")
    )
    job_service = DefaultJobService(
        store=FileJobStore(kernel.config.working_directory / ".runtime" / "jobs"),
        metadata={"runtime_id": kernel.config.runtime_id},
    )
    metadata = dict(kernel.config.metadata)
    metadata["runtime_id"] = kernel.config.runtime_id
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
    services = RuntimeServices(
        transcript=DefaultTranscriptService(transcript_store),
        memory=MemoryManagerService(
            project_root=kernel.config.working_directory,
            memory_config=kernel.config.memory_config,
        ),
        jobs=job_service,
        task_lists=task_list_service,
        task_discipline=TaskDisciplineSidecar(task_lists=task_list_service),
        context_assembler=ContextAssembler(),
        metadata=metadata,
    )
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


def _register_job_executors(
    *,
    kernel: RuntimeKernel,
    services: RuntimeServices,
    agent_runtime: AgentRuntime,
) -> None:
    registry = services.job_service.executor_registry
    registry.register("agent", agent_runtime.job_executor, builtin=True, override=True)
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


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    stringified = str(value).strip()
    return stringified or None


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


def _with_bundled_openai_baseline(config: RuntimeConfig) -> RuntimeConfig:
    model_providers = dict(config.model_providers)
    if OPENAI_PROVIDER_NAME not in model_providers:
        model_providers[OPENAI_PROVIDER_NAME] = bundled_openai_provider_binding()

    model_routes = dict(config.model_routes)
    if OPENAI_ROUTE_NAME not in model_routes:
        model_routes[OPENAI_ROUTE_NAME] = bundled_openai_route_binding()

    default_model_route = config.default_model_route
    if default_model_route is None and config.model_client is None and not config.model_routes:
        default_model_route = OPENAI_ROUTE_NAME

    return replace(
        config,
        model_providers=model_providers,
        model_routes=model_routes,
        default_model_route=default_model_route,
    )


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
