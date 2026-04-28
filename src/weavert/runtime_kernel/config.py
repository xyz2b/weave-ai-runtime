from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from ..agent_execution import ChildRunStore
from ..context_window import (
    ModelContextWindowProfile,
    RouteContextWindowPolicy,
    coerce_model_context_window_profiles,
    coerce_route_context_window_policy,
    validate_model_context_window_profiles,
)
from ..definitions import (
    AgentDefinition,
    DefinitionSource,
    SkillDefinition,
    ToolDefinition,
)
from ..hosts.base import HostFactory
from ..jobs import JobExecutorBinding
from ..package_profiles import (
    DEFAULT_RUNTIME_DISTRIBUTION,
    RuntimeDistribution,
    normalize_runtime_distribution,
    resolve_first_party_package_names,
)
from ..public_contract import ensure_canonical_workspace_root
from ..runtime_package_manifests import RuntimePackageRegistrationSource
from ..team_config import TeammateOrchestrationConfig
from ..turn_engine.models import ModelClient, NormalizedModelCapabilities, TranscriptStore

if TYPE_CHECKING:
    from ..tool_runtime import AskUserHandler, PermissionHandler, ToolRefreshCallback


@dataclass(frozen=True, slots=True)
class DefinitionSourcePaths:
    source: DefinitionSource
    root: Path
    tools_subdir: str = "tools"
    agents_subdir: str = "agents"
    skills_subdir: str = "skills"
    enabled: bool = True

    @property
    def tools_dir(self) -> Path:
        return self.root / self.tools_subdir

    @property
    def agents_dir(self) -> Path:
        return self.root / self.agents_subdir

    @property
    def skills_dir(self) -> Path:
        return self.root / self.skills_subdir


@dataclass(slots=True)
class BuiltinPackConfig:
    tools_enabled: bool = True
    agents_enabled: bool = True
    skills_enabled: bool = True
    disabled_tools: set[str] = field(default_factory=set)
    disabled_agents: set[str] = field(default_factory=set)
    disabled_skills: set[str] = field(default_factory=set)
    tool_replacements: dict[str, ToolDefinition] = field(default_factory=dict)
    agent_replacements: dict[str, AgentDefinition] = field(default_factory=dict)
    skill_replacements: dict[str, SkillDefinition] = field(default_factory=dict)
    extra_tools: list[ToolDefinition] = field(default_factory=list)
    extra_agents: list[AgentDefinition] = field(default_factory=list)
    extra_skills: list[SkillDefinition] = field(default_factory=list)

    def tool_enabled(self, name: str) -> bool:
        return self.tools_enabled and name not in self.disabled_tools

    def agent_enabled(self, name: str) -> bool:
        return self.agents_enabled and name not in self.disabled_agents

    def skill_enabled(self, name: str) -> bool:
        return self.skills_enabled and name not in self.disabled_skills


@dataclass(frozen=True, slots=True)
class HostBinding:
    name: str
    factory: HostFactory
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelProviderBinding:
    client: ModelClient
    provider_name: str
    capabilities: NormalizedModelCapabilities | None = None
    context_window_profiles: tuple[ModelContextWindowProfile, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "context_window_profiles",
            coerce_model_context_window_profiles(self.context_window_profiles),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        diagnostics = validate_model_context_window_profiles(self.context_window_profiles)
        if diagnostics:
            raise ValueError(", ".join(diagnostics))


@dataclass(frozen=True, slots=True)
class ModelRouteBinding:
    client: ModelClient | None = None
    default_model: str | None = None
    provider_name: str | None = None
    provider_binding: str | None = None
    context_window_policy: RouteContextWindowPolicy | None = None
    context_window_profiles: tuple[ModelContextWindowProfile, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    capabilities: NormalizedModelCapabilities | None = None

    def __post_init__(self) -> None:
        if self.context_window_policy is not None and not isinstance(
            self.context_window_policy,
            RouteContextWindowPolicy,
        ):
            policy = coerce_route_context_window_policy(self.context_window_policy)
            object.__setattr__(self, "context_window_policy", policy)
        object.__setattr__(
            self,
            "context_window_profiles",
            coerce_model_context_window_profiles(self.context_window_profiles),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        diagnostics = validate_model_context_window_profiles(self.context_window_profiles)
        if diagnostics:
            raise ValueError(", ".join(diagnostics))


@dataclass(frozen=True, slots=True)
class ResolvedModelRouteBinding:
    client: ModelClient
    default_model: str | None = None
    provider_name: str | None = None
    capabilities: NormalizedModelCapabilities | None = None
    context_window_policy: RouteContextWindowPolicy | None = None
    context_window_profiles: tuple[ModelContextWindowProfile, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "context_window_profiles",
            coerce_model_context_window_profiles(self.context_window_profiles),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))


def _coerce_optional_string(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _resolve_route_default_model(
    default_model: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> str | None:
    env_name = _coerce_optional_string((metadata or {}).get("default_model_env"))
    if env_name is not None:
        override = os.environ.get(env_name, "").strip()
        if override:
            return override
    return default_model


def resolve_model_route_binding(
    *,
    requested_model_route: str | None,
    agent_model_route: str | None,
    inherited_route: str | None,
    default_model_route: str | None,
    model_providers: Mapping[str, ModelProviderBinding] | None = None,
    model_routes: Mapping[str, ModelRouteBinding] | None = None,
) -> tuple[str | None, ResolvedModelRouteBinding | None]:
    resolved_route = requested_model_route or agent_model_route or inherited_route or default_model_route
    if resolved_route is None:
        return None, None
    binding = (model_routes or {}).get(resolved_route)
    if binding is None:
        raise ValueError(f"Unknown model route: {resolved_route}")
    provider_binding = (
        (model_providers or {}).get(binding.provider_binding)
        if binding.provider_binding is not None
        else None
    )
    client = binding.client or (provider_binding.client if provider_binding is not None else None)
    if client is None:
        raise ValueError(f"Model route '{resolved_route}' does not resolve a model client")
    metadata = {
        **(dict(provider_binding.metadata) if provider_binding is not None else {}),
        **dict(binding.metadata),
        "provider_binding": binding.provider_binding,
    }
    profiles = (
        tuple(provider_binding.context_window_profiles) if provider_binding is not None else ()
    ) + tuple(binding.context_window_profiles)
    return resolved_route, ResolvedModelRouteBinding(
        client=client,
        default_model=_resolve_route_default_model(binding.default_model, metadata),
        provider_name=(
            binding.provider_name
            or (provider_binding.provider_name if provider_binding is not None else None)
        ),
        capabilities=binding.capabilities
        or (provider_binding.capabilities if provider_binding is not None else None),
        context_window_policy=binding.context_window_policy,
        context_window_profiles=profiles,
        metadata=metadata,
    )


@dataclass(slots=True)
class RuntimeConfig:
    runtime_id: str = "default"
    working_directory: Path = field(default_factory=Path.cwd)
    discovery_sources: tuple[DefinitionSourcePaths, ...] = ()
    distribution: RuntimeDistribution | str = DEFAULT_RUNTIME_DISTRIBUTION
    enabled_packages: set[str] = field(default_factory=set)
    disabled_packages: set[str] = field(default_factory=set)
    extra_package_manifests: tuple[RuntimePackageRegistrationSource, ...] | list[RuntimePackageRegistrationSource] = ()
    requested_packages: set[str] = field(default_factory=set)
    builtins: BuiltinPackConfig = field(default_factory=BuiltinPackConfig)
    hooks: Mapping[str, Any] = field(default_factory=dict)
    host_bindings: tuple[HostBinding, ...] = ()
    model_client: ModelClient | None = None
    model_providers: dict[str, ModelProviderBinding] = field(default_factory=dict)
    model_routes: dict[str, ModelRouteBinding] = field(default_factory=dict)
    default_model_route: str | None = None
    transcript_store: TranscriptStore | None = None
    child_run_store: ChildRunStore | None = None
    default_agent: str = "main-router"
    system_prompt: str = ""
    permission_handler: PermissionHandler | None = None
    ask_user_handler: AskUserHandler | None = None
    tool_refresh_callback: ToolRefreshCallback | None = None
    memory_config: Mapping[str, Any] | None = None
    teammate_orchestration: TeammateOrchestrationConfig | None = None
    job_executors: dict[str, JobExecutorBinding] = field(default_factory=dict)
    legacy_compatibility: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _skip_protocol_only_matrix_evaluation: bool = False

    @classmethod
    def for_project(cls, project_root: Path) -> "RuntimeConfig":
        user_root = ensure_canonical_workspace_root(Path.home())
        project_runtime_dir = ensure_canonical_workspace_root(project_root)
        return cls(
            working_directory=project_root,
            discovery_sources=(
                DefinitionSourcePaths(DefinitionSource.USER, user_root),
                DefinitionSourcePaths(DefinitionSource.PROJECT, project_runtime_dir),
            ),
        )

    def resolved_distribution(self) -> RuntimeDistribution:
        return normalize_runtime_distribution(self.distribution)

    def selected_first_party_packages(self) -> tuple[str, ...]:
        return resolve_first_party_package_names(
            distribution=self.resolved_distribution(),
            enabled_packages=self.enabled_packages,
            disabled_packages=self.disabled_packages,
        )

    def package_enabled(self, package_name: str) -> bool:
        return package_name in self.selected_first_party_packages()
