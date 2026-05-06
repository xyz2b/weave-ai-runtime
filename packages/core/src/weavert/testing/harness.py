from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from ..agent_execution import AgentRunRecord
from ..contracts import RuntimeMessage
from ..permissions import AllowAllPermissionService
from ..runtime_kernel import (
    DefinitionSourcePaths,
    RuntimeConfig,
    WorkflowRunFinalizationReport,
    WorkflowRunReport,
    assemble_runtime,
)
from ..turn_engine import ModelClient, ModelRequest, TurnTerminal
from .fixtures import FixtureWorkspace, discovery_sources as default_discovery_sources

_DEFAULT_PERMISSION_SERVICE = object()


@dataclass(frozen=True, slots=True)
class WorkflowTestReport:
    workflow: WorkflowRunReport
    workspace_root: Path
    discovery_sources: tuple[DefinitionSourcePaths, ...]
    fixture_source: Path | None = None
    child_runs: tuple[AgentRunRecord, ...] = ()
    scripted_requests: tuple[ModelRequest, ...] = ()
    scripted_batch_count_consumed: int | None = None
    scripted_batch_count_remaining: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", Path(self.workspace_root).resolve())
        object.__setattr__(self, "discovery_sources", tuple(self.discovery_sources))
        object.__setattr__(self, "child_runs", tuple(self.child_runs))
        object.__setattr__(self, "scripted_requests", tuple(self.scripted_requests))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.fixture_source is not None:
            object.__setattr__(self, "fixture_source", Path(self.fixture_source).resolve())

    @property
    def session_id(self) -> str:
        return self.workflow.session_id

    @property
    def agent_name(self) -> str:
        return self.workflow.agent_name

    @property
    def cwd(self) -> str:
        return self.workflow.cwd

    @property
    def messages(self) -> tuple[RuntimeMessage, ...]:
        return self.workflow.messages

    @property
    def terminal(self) -> TurnTerminal | None:
        return self.workflow.terminal

    @property
    def final_status(self) -> str:
        return self.workflow.final_status

    @property
    def session_owner(self) -> str:
        return self.workflow.session_owner

    @property
    def finalization(self) -> WorkflowRunFinalizationReport:
        return self.workflow.finalization

    @property
    def terminal_stop_reason(self) -> str | None:
        return self.terminal.stop_reason if self.terminal is not None else None

    @property
    def terminal_metadata(self) -> dict[str, Any]:
        if self.terminal is None:
            return {}
        return dict(self.terminal.metadata)

    def as_workflow_run_report(self) -> WorkflowRunReport:
        return self.workflow


async def run_workflow_test(
    prompt: str,
    *,
    workspace: Path | str | FixtureWorkspace,
    model_client: ModelClient | None = None,
    runtime_config: RuntimeConfig | None = None,
    discovery_sources: tuple[DefinitionSourcePaths, ...] | list[DefinitionSourcePaths] | None = None,
    session_id: str | None = None,
    agent_name: str | None = None,
    cwd: str | Path | None = None,
    system_prompt: str | None = None,
    metadata: Mapping[str, object] | None = None,
    wait_for_finalization: bool = True,
    permission_service: Any = _DEFAULT_PERMISSION_SERVICE,
) -> WorkflowTestReport:
    workspace_root, fixture_source, workspace_discovery_sources = _resolve_workspace(workspace)
    resolved_discovery_sources = (
        tuple(workspace_discovery_sources) if discovery_sources is None else tuple(discovery_sources)
    )
    config = _build_runtime_config(
        workspace_root=workspace_root,
        model_client=model_client,
        runtime_config=runtime_config,
        discovery_sources=resolved_discovery_sources,
    )
    runtime = assemble_runtime(config)
    if permission_service is _DEFAULT_PERMISSION_SERVICE:
        runtime.services.permissions = AllowAllPermissionService()
    elif permission_service is not None:
        runtime.services.permissions = permission_service
    report = await runtime.run_prompt_report(
        prompt,
        session_id=session_id,
        agent_name=agent_name,
        cwd=workspace_root if cwd is None else cwd,
        system_prompt=system_prompt,
        metadata=dict(metadata or {}),
        wait_for_finalization=wait_for_finalization,
    )
    child_runs = await runtime.agent_runtime.run_store.list_by_session(report.session_id)
    scripted_requests, scripted_batch_count_consumed, scripted_batch_count_remaining = (
        _scripted_diagnostics_from_config(config)
    )
    return WorkflowTestReport(
        workflow=report,
        workspace_root=workspace_root,
        discovery_sources=resolved_discovery_sources,
        fixture_source=fixture_source,
        child_runs=tuple(child_runs),
        scripted_requests=scripted_requests,
        scripted_batch_count_consumed=scripted_batch_count_consumed,
        scripted_batch_count_remaining=scripted_batch_count_remaining,
        metadata={
            "wait_for_finalization": wait_for_finalization,
        },
    )



def _build_runtime_config(
    *,
    workspace_root: Path,
    model_client: ModelClient | None,
    runtime_config: RuntimeConfig | None,
    discovery_sources: tuple[DefinitionSourcePaths, ...],
) -> RuntimeConfig:
    if runtime_config is None:
        config = RuntimeConfig.for_ordinary_workflow(workspace_root)
    else:
        config = replace(runtime_config)
    config.working_directory = workspace_root
    config.discovery_sources = tuple(discovery_sources)
    if model_client is not None:
        config.model_client = model_client
    if config.model_client is None and not config.default_model_route and not config.model_routes:
        raise ValueError(
            "run_workflow_test() requires a model_client or a runtime_config with a configured model route."
        )
    return config



def _resolve_workspace(
    workspace: Path | str | FixtureWorkspace,
) -> tuple[Path, Path | None, tuple[DefinitionSourcePaths, ...]]:
    if isinstance(workspace, FixtureWorkspace):
        return (
            workspace.workspace_root,
            workspace.fixture_source,
            tuple(workspace.discovery_sources),
        )
    workspace_root = Path(workspace).resolve()
    return workspace_root, None, default_discovery_sources(workspace_root)



def _optional_int_attr(source: Any, name: str) -> int | None:
    value = getattr(source, name, None)
    return value if isinstance(value, int) else None


def _scripted_diagnostics_from_config(
    config: RuntimeConfig,
) -> tuple[tuple[ModelRequest, ...], int | None, int | None]:
    clients = _scripted_model_clients(config)
    active_clients = tuple(client for client in clients if _scripted_client_active(client))
    resolved_clients = active_clients or tuple(client for client in clients if _looks_like_scripted_client(client))
    if not resolved_clients:
        return (), None, None

    scripted_requests: list[ModelRequest] = []
    consumed_values: list[int] = []
    remaining_values: list[int] = []
    for client in resolved_clients:
        for request in getattr(client, "requests", ()) or ():
            if isinstance(request, ModelRequest):
                scripted_requests.append(request)
        consumed = _optional_int_attr(client, "consumed_batch_count")
        if consumed is not None:
            consumed_values.append(consumed)
        remaining = _optional_int_attr(client, "remaining_batch_count")
        if remaining is not None:
            remaining_values.append(remaining)

    consumed_total = sum(consumed_values) if consumed_values else None
    remaining_total = sum(remaining_values) if remaining_values else None
    return tuple(scripted_requests), consumed_total, remaining_total


def _scripted_model_clients(config: RuntimeConfig) -> tuple[Any, ...]:
    clients: list[Any] = []
    seen: set[int] = set()

    def _add(client: Any) -> None:
        if client is None:
            return
        identity = id(client)
        if identity in seen:
            return
        seen.add(identity)
        clients.append(client)

    _add(config.model_client)

    route_names: list[str] = []
    if config.default_model_route is not None and config.default_model_route in config.model_routes:
        route_names.append(config.default_model_route)
    route_names.extend(name for name in sorted(config.model_routes) if name not in route_names)
    provider_names: list[str] = []

    for route_name in route_names:
        binding = config.model_routes.get(route_name)
        if binding is None:
            continue
        _add(binding.client)
        if binding.provider_binding is not None and binding.provider_binding not in provider_names:
            provider_names.append(binding.provider_binding)

    provider_names.extend(name for name in sorted(config.model_providers) if name not in provider_names)
    for provider_name in provider_names:
        binding = config.model_providers.get(provider_name)
        if binding is None:
            continue
        _add(binding.client)

    return tuple(clients)


def _scripted_client_active(client: Any) -> bool:
    requests = getattr(client, "requests", None)
    if requests:
        return True
    consumed = _optional_int_attr(client, "consumed_batch_count")
    return consumed is not None and consumed > 0


def _looks_like_scripted_client(client: Any) -> bool:
    return any(
        hasattr(client, attribute)
        for attribute in ("requests", "consumed_batch_count", "remaining_batch_count")
    )


__all__ = [
    "WorkflowTestReport",
    "run_workflow_test",
]
