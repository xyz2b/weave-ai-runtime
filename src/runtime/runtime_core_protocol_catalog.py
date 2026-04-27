from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .runtime_package_protocols import PackageOwnership

CORE_PROTOCOL_CATALOG_SCHEMA_VERSION = "1.0"


class CoreProtocolBindingBoundary(StrEnum):
    CONFIG_OWNED = "config-owned"
    SERVICE_OWNED = "service-owned"
    REGISTRY_OWNED = "registry-owned"
    HOST_BOUND = "host-bound"


class CoreProtocolCompatibilityStatus(StrEnum):
    STABLE = "stable"
    STABLE_WITH_COMPATIBILITY = "stable-with-compatibility"


def core_protocol_compatibility_surfaces() -> dict[str, str]:
    return {
        "TaskManager": "compatibility-only",
        "RuntimeConfig.extra_invocation_providers": "bounded-compatibility",
        "RuntimeServices.memory.collect": "compatibility-only",
        "RuntimeServices.hooks.collect": "compatibility-only",
        "RuntimeServices.task_discipline.collect": "compatibility-only",
        "HostRuntime.emit_team_event": "bounded-compatibility",
    }


def core_protocol_package_lookup_sections() -> dict[str, Any]:
    return {
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
        "compatibility_invocation_providers": {
            "embedder_config": "RuntimeConfig.extra_invocation_providers",
        },
    }


def core_protocol_invocation_provider_paths_metadata() -> dict[str, str]:
    return {
        "builtin_skill_baseline": "baseline",
        "package_contributions": "canonical-package-path",
        "extra_invocation_providers": "bounded-compatibility",
        "canonical_package_surface": "PackageContribution.invocation_providers",
        "compatibility_surface": "RuntimeConfig.extra_invocation_providers",
    }


@dataclass(frozen=True, slots=True)
class CoreProtocolRetainedSurface:
    surface: str
    status: str
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "surface", _require_non_empty(self.surface, "surface"))
        object.__setattr__(self, "status", _require_non_empty(self.status, "status"))
        if self.notes is not None:
            object.__setattr__(self, "notes", str(self.notes))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "surface": self.surface,
            "status": self.status,
        }
        if self.notes:
            payload["notes"] = self.notes
        return payload


@dataclass(frozen=True, slots=True)
class StableCoreProtocolEntry:
    protocol_id: str
    canonical_name: str
    owner: PackageOwnership
    binding_boundary: CoreProtocolBindingBoundary | str
    canonical_binding_surface: str
    discovery_surface: str
    compatibility_status: CoreProtocolCompatibilityStatus | str = CoreProtocolCompatibilityStatus.STABLE
    retained_surfaces: tuple[CoreProtocolRetainedSurface, ...] = ()
    notes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_id", _require_non_empty(self.protocol_id, "protocol_id"))
        object.__setattr__(self, "canonical_name", _require_non_empty(self.canonical_name, "canonical_name"))
        object.__setattr__(
            self,
            "binding_boundary",
            CoreProtocolBindingBoundary(self.binding_boundary),
        )
        object.__setattr__(
            self,
            "canonical_binding_surface",
            _require_non_empty(self.canonical_binding_surface, "canonical_binding_surface"),
        )
        object.__setattr__(
            self,
            "discovery_surface",
            _require_non_empty(self.discovery_surface, "discovery_surface"),
        )
        object.__setattr__(
            self,
            "compatibility_status",
            CoreProtocolCompatibilityStatus(self.compatibility_status),
        )
        object.__setattr__(self, "retained_surfaces", tuple(self.retained_surfaces))
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "protocol_id": self.protocol_id,
            "canonical_name": self.canonical_name,
            "owner": {
                "package_name": self.owner.package_name,
                "package_role": self.owner.package_role,
                "surface": self.owner.surface,
                "metadata": dict(self.owner.metadata),
            },
            "binding_boundary": self.binding_boundary.value,
            "canonical_binding_surface": self.canonical_binding_surface,
            "discovery_surface": self.discovery_surface,
            "compatibility_status": self.compatibility_status.value,
        }
        if self.retained_surfaces:
            payload["retained_surfaces"] = [surface.to_dict() for surface in self.retained_surfaces]
        if self.notes:
            payload["notes"] = list(self.notes)
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class StableCoreProtocolCatalog:
    schema_version: str = CORE_PROTOCOL_CATALOG_SCHEMA_VERSION
    published_metadata_paths: tuple[str, ...] = (
        "runtime.services.metadata['core_protocol_catalog']",
        "runtime.metadata['core_protocol_catalog']",
    )
    adjacent_metadata: dict[str, str] = field(
        default_factory=lambda: {
            "package_lookup": "source of truth for package-specific canonical keys and wrapper status",
            "compatibility_surfaces": "source of truth for compatibility-only and bounded-compatibility helpers",
            "compatibility_projections": "legacy projections that still delegate to canonical runtime capabilities",
            "invocation_provider_paths": "registry attachment guidance for builtin, package, and config-owned invocation providers",
        }
    )
    protocols: tuple[StableCoreProtocolEntry, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_non_empty(self.schema_version, "schema_version"))
        object.__setattr__(
            self,
            "published_metadata_paths",
            tuple(_require_non_empty(path, "published_metadata_path") for path in self.published_metadata_paths),
        )
        object.__setattr__(self, "adjacent_metadata", dict(self.adjacent_metadata))
        object.__setattr__(self, "protocols", tuple(self.protocols))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "published_metadata_paths": list(self.published_metadata_paths),
            "adjacent_metadata": dict(self.adjacent_metadata),
            "protocols": {
                entry.protocol_id: entry.to_dict()
                for entry in self.protocols
            },
        }


def build_stable_core_protocol_catalog(
    *,
    compatibility_surfaces: Mapping[str, str] | None = None,
    package_lookup: Mapping[str, Any] | None = None,
    invocation_provider_paths: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_package_lookup = (
        core_protocol_package_lookup_sections()
        if package_lookup is None
        else dict(package_lookup)
    )
    resolved_compatibility_surfaces = (
        core_protocol_compatibility_surfaces()
        if compatibility_surfaces is None
        else dict(compatibility_surfaces)
    )
    resolved_invocation_provider_paths = (
        core_protocol_invocation_provider_paths_metadata()
        if invocation_provider_paths is None
        else dict(invocation_provider_paths)
    )
    return StableCoreProtocolCatalog(
        protocols=_stable_core_protocol_entries(
            compatibility_surfaces=resolved_compatibility_surfaces,
            package_lookup=resolved_package_lookup,
            invocation_provider_paths=resolved_invocation_provider_paths,
        )
    ).to_dict()


def _stable_core_protocol_entries(
    *,
    compatibility_surfaces: Mapping[str, str],
    package_lookup: Mapping[str, Any],
    invocation_provider_paths: Mapping[str, Any],
) -> tuple[StableCoreProtocolEntry, ...]:
    control_plane_services = _require_mapping(
        package_lookup,
        "canonical_control_plane_services",
    )
    context_contributors = _require_mapping(
        package_lookup,
        "canonical_context_contributors",
    )
    invocation_providers = _require_mapping(
        package_lookup,
        "canonical_invocation_providers",
    )
    context_stage_catalog = _require_string_list(
        context_contributors.get("stage_catalog"),
        field_name="canonical_context_contributors.stage_catalog",
    )
    return (
        StableCoreProtocolEntry(
            protocol_id="runtime.transcript.store",
            canonical_name="TranscriptStore",
            owner=_runtime_core_owner("RuntimeConfig.transcript_store"),
            binding_boundary=CoreProtocolBindingBoundary.CONFIG_OWNED,
            canonical_binding_surface="RuntimeConfig.transcript_store",
            discovery_surface="RuntimeServices.transcript_store / RuntimeAssembly.transcript_store",
            notes=(
                "PackageContribution.store_bindings['transcript_store'] may satisfy the config-owned binding during assembly.",
            ),
            metadata={
                "assembly_inputs": [
                    "RuntimeConfig.transcript_store",
                    "PackageContribution.store_bindings['transcript_store']",
                ],
            },
        ),
        StableCoreProtocolEntry(
            protocol_id="runtime.job.service",
            canonical_name="JobService",
            owner=_runtime_core_owner("RuntimeServices.job_service"),
            binding_boundary=CoreProtocolBindingBoundary.SERVICE_OWNED,
            canonical_binding_surface=_require_string(
                control_plane_services,
                "job_service",
                field_name="canonical_control_plane_services.job_service",
            ),
            discovery_surface=_require_string(
                control_plane_services,
                "job_service",
                field_name="canonical_control_plane_services.job_service",
            ),
            compatibility_status=CoreProtocolCompatibilityStatus.STABLE_WITH_COMPATIBILITY,
            retained_surfaces=(
                CoreProtocolRetainedSurface(
                    surface="TaskManager",
                    status=_require_string(
                        compatibility_surfaces,
                        "TaskManager",
                        field_name="compatibility_surfaces.TaskManager",
                    ),
                    notes="Compatibility facade over JobService and TaskListService.",
                ),
            ),
            metadata={
                "package_lookup_key": "canonical_control_plane_services.job_service",
            },
        ),
        StableCoreProtocolEntry(
            protocol_id="runtime.task-list.service",
            canonical_name="TaskListService",
            owner=_runtime_core_owner("RuntimeServices.task_list_service"),
            binding_boundary=CoreProtocolBindingBoundary.SERVICE_OWNED,
            canonical_binding_surface=_require_string(
                control_plane_services,
                "task_list_service",
                field_name="canonical_control_plane_services.task_list_service",
            ),
            discovery_surface=_require_string(
                control_plane_services,
                "task_list_service",
                field_name="canonical_control_plane_services.task_list_service",
            ),
            compatibility_status=CoreProtocolCompatibilityStatus.STABLE_WITH_COMPATIBILITY,
            retained_surfaces=(
                CoreProtocolRetainedSurface(
                    surface="TaskManager",
                    status=_require_string(
                        compatibility_surfaces,
                        "TaskManager",
                        field_name="compatibility_surfaces.TaskManager",
                    ),
                    notes="Compatibility facade over JobService and TaskListService.",
                ),
            ),
            metadata={
                "package_lookup_key": "canonical_control_plane_services.task_list_service",
            },
        ),
        StableCoreProtocolEntry(
            protocol_id="runtime.permission.service",
            canonical_name="PermissionService",
            owner=_runtime_core_owner("RuntimeServices.permissions"),
            binding_boundary=CoreProtocolBindingBoundary.SERVICE_OWNED,
            canonical_binding_surface="RuntimeServices.permissions",
            discovery_surface="RuntimeServices.permissions",
        ),
        StableCoreProtocolEntry(
            protocol_id="runtime.elicitation.service",
            canonical_name="ElicitationService",
            owner=_runtime_core_owner("RuntimeServices.elicitation"),
            binding_boundary=CoreProtocolBindingBoundary.SERVICE_OWNED,
            canonical_binding_surface="RuntimeServices.elicitation",
            discovery_surface="RuntimeServices.elicitation",
        ),
        StableCoreProtocolEntry(
            protocol_id="runtime.context-contributors.registry",
            canonical_name="ContextContributorRegistry",
            owner=_runtime_core_owner("RuntimeServices.context_contributor_execution_plan"),
            binding_boundary=CoreProtocolBindingBoundary.REGISTRY_OWNED,
            canonical_binding_surface=_require_string(
                context_contributors,
                "package_contributions",
                field_name="canonical_context_contributors.package_contributions",
            ),
            discovery_surface=(
                f"{_require_string(context_contributors, 'registry', field_name='canonical_context_contributors.registry')}"
                " / runtime.services.metadata['context_contributors']"
            ),
            compatibility_status=CoreProtocolCompatibilityStatus.STABLE_WITH_COMPATIBILITY,
            retained_surfaces=(
                CoreProtocolRetainedSurface(
                    surface="RuntimeServices.memory.collect",
                    status=_require_string(
                        compatibility_surfaces,
                        "RuntimeServices.memory.collect",
                        field_name="compatibility_surfaces.RuntimeServices.memory.collect",
                    ),
                ),
                CoreProtocolRetainedSurface(
                    surface="RuntimeServices.hooks.collect",
                    status=_require_string(
                        compatibility_surfaces,
                        "RuntimeServices.hooks.collect",
                        field_name="compatibility_surfaces.RuntimeServices.hooks.collect",
                    ),
                ),
                CoreProtocolRetainedSurface(
                    surface="RuntimeServices.task_discipline.collect",
                    status=_require_string(
                        compatibility_surfaces,
                        "RuntimeServices.task_discipline.collect",
                        field_name="compatibility_surfaces.RuntimeServices.task_discipline.collect",
                    ),
                ),
            ),
            metadata={
                "stage_catalog": context_stage_catalog,
            },
        ),
        StableCoreProtocolEntry(
            protocol_id="runtime.invocation-provider.registry",
            canonical_name="InvocationProviderRegistry",
            owner=_runtime_core_owner("InvocationRegistry.register_provider"),
            binding_boundary=CoreProtocolBindingBoundary.REGISTRY_OWNED,
            canonical_binding_surface=_require_string(
                invocation_providers,
                "package_contributions",
                field_name="canonical_invocation_providers.package_contributions",
            ),
            discovery_surface="RuntimeAssembly.resolve_invocations / runtime.services.metadata['invocation_provider_registrations']",
            compatibility_status=CoreProtocolCompatibilityStatus.STABLE_WITH_COMPATIBILITY,
            retained_surfaces=(
                CoreProtocolRetainedSurface(
                    surface="RuntimeConfig.extra_invocation_providers",
                    status=_require_string(
                        compatibility_surfaces,
                        "RuntimeConfig.extra_invocation_providers",
                        field_name="compatibility_surfaces.RuntimeConfig.extra_invocation_providers",
                    ),
                ),
            ),
            metadata={
                "builtin_baseline": _require_string(
                    invocation_providers,
                    "builtins",
                    field_name="canonical_invocation_providers.builtins",
                ),
                "builtin_baseline_status": _require_string(
                    invocation_provider_paths,
                    "builtin_skill_baseline",
                    field_name="invocation_provider_paths.builtin_skill_baseline",
                ),
                "path_metadata": "runtime.services.metadata['invocation_provider_paths']",
            },
        ),
        StableCoreProtocolEntry(
            protocol_id="runtime.host.binding",
            canonical_name="HostRuntime",
            owner=_runtime_core_owner("RuntimeAssembly.bind_host"),
            binding_boundary=CoreProtocolBindingBoundary.HOST_BOUND,
            canonical_binding_surface="RuntimeAssembly.bind_host",
            discovery_surface="RuntimeServices.host",
            compatibility_status=CoreProtocolCompatibilityStatus.STABLE_WITH_COMPATIBILITY,
            retained_surfaces=(
                CoreProtocolRetainedSurface(
                    surface="HostRuntime.emit_team_event",
                    status=_require_string(
                        compatibility_surfaces,
                        "HostRuntime.emit_team_event",
                        field_name="compatibility_surfaces.HostRuntime.emit_team_event",
                    ),
                    notes="Team event egress is retained as a bounded compatibility sink, not as the canonical host extension story.",
                ),
            ),
        ),
    )


def _runtime_core_owner(surface: str) -> PackageOwnership:
    return PackageOwnership(
        package_name="runtime-core",
        package_role="core",
        surface=surface,
    )


def _require_non_empty(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _require_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping")
    return value


def _require_string(
    mapping: Mapping[str, Any],
    key: str,
    *,
    field_name: str,
) -> str:
    if key not in mapping:
        raise ValueError(f"{field_name} must be present")
    return _require_non_empty(mapping[key], field_name)


def _require_string_list(value: object, *, field_name: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list of strings")
    return [_require_non_empty(item, field_name) for item in value]


__all__ = [
    "CORE_PROTOCOL_CATALOG_SCHEMA_VERSION",
    "CoreProtocolBindingBoundary",
    "CoreProtocolCompatibilityStatus",
    "CoreProtocolRetainedSurface",
    "StableCoreProtocolCatalog",
    "StableCoreProtocolEntry",
    "build_stable_core_protocol_catalog",
]
