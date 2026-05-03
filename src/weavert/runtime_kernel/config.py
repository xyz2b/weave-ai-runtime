from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum, StrEnum
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


class RuntimeAssemblyPresetName(StrEnum):
    ORDINARY_WORKFLOW = "ordinary-workflow"
    HEADLESS_LIVE = "headless-live"
    HOST_BOUND = "host-bound"


@dataclass(frozen=True, slots=True)
class RuntimeAssemblyPresetDefinition:
    name: RuntimeAssemblyPresetName | str
    summary: str
    recommended_distribution: RuntimeDistribution | str
    discovery_posture: str
    model_route_posture: str
    host_posture: str
    recommended_entrypoint: str
    builder_entrypoint: str
    notes: tuple[str, ...] = ()
    source_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", RuntimeAssemblyPresetName(self.name))
        object.__setattr__(self, "summary", str(self.summary))
        object.__setattr__(
            self,
            "recommended_distribution",
            normalize_runtime_distribution(self.recommended_distribution),
        )
        object.__setattr__(self, "discovery_posture", str(self.discovery_posture))
        object.__setattr__(self, "model_route_posture", str(self.model_route_posture))
        object.__setattr__(self, "host_posture", str(self.host_posture))
        object.__setattr__(self, "recommended_entrypoint", str(self.recommended_entrypoint))
        object.__setattr__(self, "builder_entrypoint", str(self.builder_entrypoint))
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))
        if not self.source_ref:
            object.__setattr__(
                self,
                "source_ref",
                (
                    "weavert.runtime_kernel.config:"
                    f"official_runtime_assembly_preset('{self.name.value}')"
                ),
            )

    def to_metadata(self) -> dict[str, Any]:
        payload = {
            "name": self.name.value,
            "summary": self.summary,
            "source_kind": "official-runtime-assembly-preset",
            "source_ref": self.source_ref,
            "builder_entrypoint": self.builder_entrypoint,
            "recommended_entrypoint": self.recommended_entrypoint,
            "recommended_distribution": self.recommended_distribution.value,
            "recommended_packages": list(
                resolve_first_party_package_names(
                    distribution=self.recommended_distribution,
                )
            ),
            "discovery_posture": self.discovery_posture,
            "model_route_posture": self.model_route_posture,
            "host_posture": self.host_posture,
            "published_metadata_paths": [
                "weavert.services.metadata['assembly_preset_provenance']",
                "weavert.metadata['assembly_preset_provenance']",
            ],
        }
        if self.notes:
            payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeAssemblyPresetApplication:
    definition: RuntimeAssemblyPresetDefinition
    baseline: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "baseline", deepcopy(dict(self.baseline)))

    @property
    def name(self) -> RuntimeAssemblyPresetName:
        return self.definition.name

    def to_metadata(
        self,
        *,
        config: RuntimeConfig | None = None,
    ) -> dict[str, Any]:
        payload = {
            **self.definition.to_metadata(),
            "baseline": deepcopy(self.baseline),
        }
        if config is None:
            return payload
        current = _runtime_assembly_preset_snapshot(config)
        overrides: dict[str, dict[str, Any]] = {}
        for key in sorted(set(self.baseline) | set(current)):
            baseline_value = self.baseline.get(key)
            current_value = current.get(key)
            if baseline_value != current_value:
                overrides[key] = {
                    "baseline": deepcopy(baseline_value),
                    "current": deepcopy(current_value),
                }
        payload["overridden"] = bool(overrides)
        if overrides:
            payload["overrides"] = overrides
        return payload


_OFFICIAL_RUNTIME_ASSEMBLY_PRESETS: dict[str, RuntimeAssemblyPresetDefinition] = {
    RuntimeAssemblyPresetName.ORDINARY_WORKFLOW.value: RuntimeAssemblyPresetDefinition(
        name=RuntimeAssemblyPresetName.ORDINARY_WORKFLOW,
        summary="Recommended project-local baseline for ordinary workflow assembly.",
        recommended_distribution=RuntimeDistribution.FULL,
        discovery_posture="user-and-project",
        model_route_posture="provider-optional",
        host_posture="headless-or-bind-later",
        recommended_entrypoint="assemble_runtime(config)",
        builder_entrypoint="weavert.runtime_kernel.config:RuntimeConfig.for_ordinary_workflow",
        notes=(
            "Starts from the supported full distribution and canonical user/project discovery roots.",
        ),
    ),
    RuntimeAssemblyPresetName.HEADLESS_LIVE.value: RuntimeAssemblyPresetDefinition(
        name=RuntimeAssemblyPresetName.HEADLESS_LIVE,
        summary="Recommended headless baseline for provider-backed live workflow execution.",
        recommended_distribution=RuntimeDistribution.FULL,
        discovery_posture="user-and-project",
        model_route_posture="bundled-openai-default",
        host_posture="headless",
        recommended_entrypoint="assemble_runtime(config)",
        builder_entrypoint="weavert.runtime_kernel.config:RuntimeConfig.for_headless_live",
        notes=(
            "Makes the bundled OpenAI route explicit before assembly so callers can inspect and override it.",
        ),
    ),
    RuntimeAssemblyPresetName.HOST_BOUND.value: RuntimeAssemblyPresetDefinition(
        name=RuntimeAssemblyPresetName.HOST_BOUND,
        summary="Recommended baseline for CLI, SDK, and UI host-owned integration.",
        recommended_distribution=RuntimeDistribution.FULL,
        discovery_posture="user-and-project",
        model_route_posture="provider-optional",
        host_posture="bind-host",
        recommended_entrypoint="assemble_host_runtime(config) / RuntimeAssembly.bind_host(host)",
        builder_entrypoint="weavert.runtime_kernel.config:RuntimeConfig.for_host_bound",
        notes=(
            "Keeps the same RuntimeConfig surface while signalling that the runtime should be bound to a host.",
        ),
    ),
}


def official_runtime_assembly_presets() -> dict[str, RuntimeAssemblyPresetDefinition]:
    return dict(_OFFICIAL_RUNTIME_ASSEMBLY_PRESETS)


def official_runtime_assembly_preset(
    name: RuntimeAssemblyPresetName | str,
) -> RuntimeAssemblyPresetDefinition:
    return _OFFICIAL_RUNTIME_ASSEMBLY_PRESETS[RuntimeAssemblyPresetName(name).value]


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


def _project_discovery_sources(project_root: Path) -> tuple[DefinitionSourcePaths, ...]:
    user_root = ensure_canonical_workspace_root(Path.home())
    project_runtime_dir = ensure_canonical_workspace_root(project_root)
    return (
        DefinitionSourcePaths(DefinitionSource.USER, user_root),
        DefinitionSourcePaths(DefinitionSource.PROJECT, project_runtime_dir),
    )


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
    assembly_preset: RuntimeAssemblyPresetApplication | None = None
    _skip_protocol_only_matrix_evaluation: bool = False

    @classmethod
    def for_project(cls, project_root: Path) -> "RuntimeConfig":
        return cls.for_ordinary_workflow(project_root)

    @classmethod
    def from_preset(
        cls,
        preset: RuntimeAssemblyPresetName | str,
        project_root: Path,
    ) -> "RuntimeConfig":
        preset_definition = official_runtime_assembly_preset(preset)
        config = cls(
            working_directory=project_root,
            discovery_sources=_project_discovery_sources(project_root),
            distribution=preset_definition.recommended_distribution,
        )
        if preset_definition.name == RuntimeAssemblyPresetName.HEADLESS_LIVE:
            from ..openai_client import (
                OPENAI_PROVIDER_NAME,
                OPENAI_ROUTE_NAME,
                bundled_openai_provider_binding,
                bundled_openai_route_binding,
            )

            config.model_providers[OPENAI_PROVIDER_NAME] = bundled_openai_provider_binding()
            config.model_routes[OPENAI_ROUTE_NAME] = bundled_openai_route_binding()
            config.default_model_route = OPENAI_ROUTE_NAME
        return _with_runtime_assembly_preset(config, preset_definition)

    @classmethod
    def for_ordinary_workflow(cls, project_root: Path) -> "RuntimeConfig":
        return cls.from_preset(RuntimeAssemblyPresetName.ORDINARY_WORKFLOW, project_root)

    @classmethod
    def for_headless_live(cls, project_root: Path) -> "RuntimeConfig":
        return cls.from_preset(RuntimeAssemblyPresetName.HEADLESS_LIVE, project_root)

    @classmethod
    def for_host_bound(cls, project_root: Path) -> "RuntimeConfig":
        return cls.from_preset(RuntimeAssemblyPresetName.HOST_BOUND, project_root)

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

    def assembly_preset_metadata(self) -> dict[str, Any]:
        published = self.metadata.get("assembly_preset_provenance")
        if isinstance(published, Mapping):
            return deepcopy(dict(published))
        return _live_runtime_assembly_preset_metadata(self)


def _live_runtime_assembly_preset_metadata(config: RuntimeConfig) -> dict[str, Any]:
    if config.assembly_preset is None:
        return {}
    return config.assembly_preset.to_metadata(config=config)


def _publish_runtime_assembly_preset_metadata(config: RuntimeConfig) -> RuntimeConfig:
    preset_metadata = _live_runtime_assembly_preset_metadata(config)
    if not preset_metadata:
        return config
    return replace(
        config,
        metadata={
            **dict(config.metadata),
            "assembly_preset_provenance": preset_metadata,
        },
    )


def _runtime_assembly_object_descriptor(value: object) -> dict[str, Any]:
    value_type = type(value)
    descriptor: dict[str, Any] = {
        "type": f"{value_type.__module__}.{value_type.__qualname__}",
        "instance": hex(id(value)),
    }
    if callable(value):
        callable_module = getattr(value, "__module__", value_type.__module__)
        callable_name = getattr(
            value,
            "__qualname__",
            getattr(value, "__name__", value_type.__qualname__),
        )
        descriptor["callable"] = f"{callable_module}.{callable_name}"
    return descriptor


def _runtime_assembly_value_sort_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _serialize_runtime_assembly_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return {
            "type": "builtins.bytes",
            "hex": value.hex(),
        }
    if is_dataclass(value):
        return {
            field_info.name: _serialize_runtime_assembly_value(getattr(value, field_info.name))
            for field_info in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _serialize_runtime_assembly_value(item_value)
            for key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, set | frozenset):
        return sorted(
            (_serialize_runtime_assembly_value(item) for item in value),
            key=_runtime_assembly_value_sort_key,
        )
    if isinstance(value, tuple | list):
        return [_serialize_runtime_assembly_value(item) for item in value]
    return _runtime_assembly_object_descriptor(value)


def _runtime_assembly_preset_snapshot(config: RuntimeConfig) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for field_info in fields(RuntimeConfig):
        if field_info.name in {"metadata", "assembly_preset"} or field_info.name.startswith("_"):
            continue
        snapshot[field_info.name] = _serialize_runtime_assembly_value(
            getattr(config, field_info.name)
        )
    snapshot["selected_first_party_packages"] = list(config.selected_first_party_packages())
    return snapshot


def _with_runtime_assembly_preset(
    config: RuntimeConfig,
    preset: RuntimeAssemblyPresetDefinition,
) -> RuntimeConfig:
    return replace(
        config,
        assembly_preset=RuntimeAssemblyPresetApplication(
            definition=preset,
            baseline=_runtime_assembly_preset_snapshot(config),
        ),
    )
