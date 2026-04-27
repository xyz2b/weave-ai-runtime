from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

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


def build_stable_core_protocol_catalog() -> dict[str, Any]:
    return StableCoreProtocolCatalog(protocols=_stable_core_protocol_entries()).to_dict()


def _stable_core_protocol_entries() -> tuple[StableCoreProtocolEntry, ...]:
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
            canonical_binding_surface="RuntimeServices.job_service",
            discovery_surface="RuntimeServices.job_service",
            compatibility_status=CoreProtocolCompatibilityStatus.STABLE_WITH_COMPATIBILITY,
            retained_surfaces=(
                CoreProtocolRetainedSurface(
                    surface="TaskManager",
                    status="compatibility-only",
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
            canonical_binding_surface="RuntimeServices.task_list_service",
            discovery_surface="RuntimeServices.task_list_service",
            compatibility_status=CoreProtocolCompatibilityStatus.STABLE_WITH_COMPATIBILITY,
            retained_surfaces=(
                CoreProtocolRetainedSurface(
                    surface="TaskManager",
                    status="compatibility-only",
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
            canonical_binding_surface="PackageContribution.context_contributors",
            discovery_surface="RuntimeServices.context_contributor_execution_plan / runtime.services.metadata['context_contributors']",
            compatibility_status=CoreProtocolCompatibilityStatus.STABLE_WITH_COMPATIBILITY,
            retained_surfaces=(
                CoreProtocolRetainedSurface(
                    surface="RuntimeServices.memory.collect",
                    status="compatibility-only",
                ),
                CoreProtocolRetainedSurface(
                    surface="RuntimeServices.hooks.collect",
                    status="compatibility-only",
                ),
                CoreProtocolRetainedSurface(
                    surface="RuntimeServices.task_discipline.collect",
                    status="compatibility-only",
                ),
            ),
            metadata={
                "stage_catalog": ["memory", "hooks", "task_policy"],
            },
        ),
        StableCoreProtocolEntry(
            protocol_id="runtime.invocation-provider.registry",
            canonical_name="InvocationProviderRegistry",
            owner=_runtime_core_owner("InvocationRegistry.register_provider"),
            binding_boundary=CoreProtocolBindingBoundary.REGISTRY_OWNED,
            canonical_binding_surface="PackageContribution.invocation_providers",
            discovery_surface="RuntimeAssembly.resolve_invocations / runtime.services.metadata['invocation_provider_registrations']",
            compatibility_status=CoreProtocolCompatibilityStatus.STABLE_WITH_COMPATIBILITY,
            retained_surfaces=(
                CoreProtocolRetainedSurface(
                    surface="RuntimeConfig.extra_invocation_providers",
                    status="bounded-compatibility",
                ),
            ),
            metadata={
                "builtin_baseline": "builtin_skill_baseline",
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
                    status="bounded-compatibility",
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


__all__ = [
    "CORE_PROTOCOL_CATALOG_SCHEMA_VERSION",
    "CoreProtocolBindingBoundary",
    "CoreProtocolCompatibilityStatus",
    "CoreProtocolRetainedSurface",
    "StableCoreProtocolCatalog",
    "StableCoreProtocolEntry",
    "build_stable_core_protocol_catalog",
]
