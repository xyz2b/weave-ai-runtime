from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .runtime_package_protocols import RuntimePackageManifest

OFFICIAL_RUNTIME_PACKAGE_CATALOG_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class OfficialRuntimePackageCatalogEntry:
    manifest: RuntimePackageManifest
    builtin_tools: tuple[str, ...] = ()
    builtin_agents: tuple[str, ...] = ()
    builtin_skills: tuple[str, ...] = ()
    invocation_providers: tuple[str, ...] = ()
    distribution_defaults: tuple[str, ...] = ()
    source_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "builtin_tools", tuple(str(name) for name in self.builtin_tools))
        object.__setattr__(self, "builtin_agents", tuple(str(name) for name in self.builtin_agents))
        object.__setattr__(self, "builtin_skills", tuple(str(name) for name in self.builtin_skills))
        object.__setattr__(
            self,
            "invocation_providers",
            tuple(str(name) for name in self.invocation_providers),
        )
        object.__setattr__(
            self,
            "distribution_defaults",
            tuple(str(name) for name in self.distribution_defaults),
        )
        if not self.source_ref:
            object.__setattr__(
                self,
                "source_ref",
                (
                    "runtime.runtime_package_catalog:"
                    f"OFFICIAL_RUNTIME_PACKAGE_CATALOG['{self.manifest.name}']"
                ),
            )

    def to_catalog_entry(self) -> dict[str, Any]:
        payload = {
            "role": self.manifest.role,
            "description": self.manifest.description,
            "dependencies": list(self.manifest.dependencies),
            "distribution_defaults": list(self.distribution_defaults),
            "assembly_provenance": {
                "provider_kind": "manifest-backed",
                "entrypoint": _serialize_assembly_entrypoint(self.manifest.assembly_entrypoint),
                "source_ref": self.source_ref,
            },
        }
        if self.builtin_tools:
            payload["builtin_tools"] = list(self.builtin_tools)
        if self.builtin_agents:
            payload["builtin_agents"] = list(self.builtin_agents)
        if self.builtin_skills:
            payload["builtin_skills"] = list(self.builtin_skills)
        if self.invocation_providers:
            payload["invocation_providers"] = list(self.invocation_providers)
        return payload

    def to_provenance(self) -> dict[str, Any]:
        payload = {
            "package_name": self.manifest.name,
            "source_kind": "official-catalog-entry",
            "source_ref": self.source_ref,
            "assembly_entrypoint": _serialize_assembly_entrypoint(self.manifest.assembly_entrypoint),
            "distribution_defaults": list(self.distribution_defaults),
            "manifest": _serialize_manifest_summary(self.manifest),
        }
        if self.builtin_tools:
            payload["builtin_tools"] = list(self.builtin_tools)
        if self.builtin_agents:
            payload["builtin_agents"] = list(self.builtin_agents)
        if self.builtin_skills:
            payload["builtin_skills"] = list(self.builtin_skills)
        if self.invocation_providers:
            payload["invocation_providers"] = list(self.invocation_providers)
        return payload


@dataclass(frozen=True, slots=True)
class OfficialRuntimeDistributionCatalogEntry:
    name: str
    description: str
    packages: tuple[str, ...]
    source_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "description", str(self.description))
        object.__setattr__(self, "packages", tuple(str(name) for name in self.packages))
        if not self.source_ref:
            object.__setattr__(
                self,
                "source_ref",
                (
                    "runtime.runtime_package_catalog:"
                    f"OFFICIAL_RUNTIME_DISTRIBUTIONS['{self.name}']"
                ),
            )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "packages": list(self.packages),
            "source_kind": "official-distribution",
            "source_ref": self.source_ref,
        }


def _official_manifest(
    *,
    name: str,
    role: str,
    description: str,
    dependencies: tuple[str, ...] = (),
    assembly_entrypoint: str,
    builtin_tools: tuple[str, ...] = (),
    builtin_agents: tuple[str, ...] = (),
    builtin_skills: tuple[str, ...] = (),
    invocation_providers: tuple[str, ...] = (),
    distribution_defaults: tuple[str, ...] = (),
) -> OfficialRuntimePackageCatalogEntry:
    manifest = RuntimePackageManifest(
        name=name,
        role=role,
        description=description,
        dependencies=dependencies,
        assembly_entrypoint=assembly_entrypoint,
        metadata={
            "builtin_tools": list(builtin_tools),
            "builtin_agents": list(builtin_agents),
            "builtin_skills": list(builtin_skills),
            "invocation_providers": list(invocation_providers),
        },
    )
    return OfficialRuntimePackageCatalogEntry(
        manifest=manifest,
        builtin_tools=builtin_tools,
        builtin_agents=builtin_agents,
        builtin_skills=builtin_skills,
        invocation_providers=invocation_providers,
        distribution_defaults=distribution_defaults,
    )


OFFICIAL_RUNTIME_PACKAGE_CATALOG: dict[str, OfficialRuntimePackageCatalogEntry] = {
    "runtime-core": _official_manifest(
        name="runtime-core",
        role="core",
        description="Kernel assembly, root boot path, runtime control surfaces, and core built-ins.",
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_core_package",
        builtin_tools=(
            "agent",
            "skill",
            "ask_user",
            "sleep",
            "task_create",
            "task_get",
            "task_update",
            "task_claim",
            "task_release",
            "task_assign_next",
            "task_block",
            "task_unblock",
            "task_archive",
            "task_unarchive",
            "task_delete",
            "task_list",
            "job_get",
            "job_list",
            "job_stop",
        ),
        builtin_agents=("main-router", "general-purpose"),
        distribution_defaults=("runtime-core", "runtime-default", "runtime-full"),
    ),
    "runtime-memory": _official_manifest(
        name="runtime-memory",
        role="capability",
        description="First-party memory capability package.",
        dependencies=("runtime-core",),
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_memory_package",
        builtin_skills=("remember",),
        distribution_defaults=("runtime-default", "runtime-full"),
    ),
    "runtime-team": _official_manifest(
        name="runtime-team",
        role="capability",
        description="First-party team control and teammate orchestration capability package.",
        dependencies=("runtime-core",),
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_team_package",
        builtin_tools=("team_create", "team_spawn", "team_send", "team_respond", "team_delete"),
        distribution_defaults=("runtime-default", "runtime-full"),
    ),
    "runtime-compaction": _official_manifest(
        name="runtime-compaction",
        role="mechanism",
        description="First-party compaction strategies and manager package.",
        dependencies=("runtime-core",),
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_compaction_package",
        distribution_defaults=("runtime-full",),
    ),
    "runtime-isolation": _official_manifest(
        name="runtime-isolation",
        role="mechanism",
        description="First-party isolation adapters package.",
        dependencies=("runtime-core",),
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_isolation_package",
        distribution_defaults=("runtime-full",),
    ),
    "runtime-openai": _official_manifest(
        name="runtime-openai",
        role="provider",
        description="First-party OpenAI provider integration package.",
        dependencies=("runtime-core",),
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_openai_package",
        distribution_defaults=("runtime-full",),
    ),
    "runtime-hosts-reference": _official_manifest(
        name="runtime-hosts-reference",
        role="adapter",
        description="First-party reference host implementations package.",
        dependencies=("runtime-core",),
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_hosts_reference_package",
        distribution_defaults=("runtime-full",),
    ),
    "runtime-stores-file": _official_manifest(
        name="runtime-stores-file",
        role="adapter",
        description="First-party file-backed runtime store implementations package.",
        dependencies=("runtime-core",),
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_stores_file_package",
        distribution_defaults=("runtime-full",),
    ),
    "runtime-builtin-workflows": _official_manifest(
        name="runtime-builtin-workflows",
        role="profile_workflow",
        description="First-party reusable workflow skills package.",
        dependencies=("runtime-core",),
        assembly_entrypoint=(
            "runtime.runtime_package_manifests:assemble_runtime_builtin_workflows_package"
        ),
        builtin_skills=("verify", "debug", "stuck", "batch", "simplify"),
        distribution_defaults=("runtime-full",),
    ),
    "runtime-planning": _official_manifest(
        name="runtime-planning",
        role="profile_workflow",
        description="First-party planning profile and workflow agent package.",
        dependencies=("runtime-core",),
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_planning_package",
        builtin_agents=("planner", "coordinator", "worker"),
        distribution_defaults=("runtime-full",),
    ),
    "runtime-devtools": _official_manifest(
        name="runtime-devtools",
        role="profile_workflow",
        description="First-party workspace and coding-oriented built-ins package.",
        dependencies=("runtime-core",),
        assembly_entrypoint="runtime.runtime_package_manifests:assemble_runtime_devtools_package",
        builtin_tools=("read", "glob", "grep", "edit", "write", "bash", "web_fetch", "web_search"),
        builtin_agents=("explore", "plan", "verification"),
        distribution_defaults=("runtime-full",),
    ),
}


_OFFICIAL_RUNTIME_DISTRIBUTION_DESCRIPTIONS: dict[str, str] = {
    "runtime-core": "Minimal runnable kernel distribution.",
    "runtime-default": "Supported baseline distribution with first-party memory and team capabilities.",
    "runtime-full": "Supported full first-party distribution.",
}


def _build_official_runtime_distributions() -> dict[str, OfficialRuntimeDistributionCatalogEntry]:
    return {
        distribution_name: OfficialRuntimeDistributionCatalogEntry(
            name=distribution_name,
            description=description,
            packages=tuple(
                package_name
                for package_name, entry in OFFICIAL_RUNTIME_PACKAGE_CATALOG.items()
                if distribution_name in entry.distribution_defaults
            ),
        )
        for distribution_name, description in _OFFICIAL_RUNTIME_DISTRIBUTION_DESCRIPTIONS.items()
    }


OFFICIAL_RUNTIME_DISTRIBUTIONS: dict[str, OfficialRuntimeDistributionCatalogEntry] = (
    _build_official_runtime_distributions()
)


def official_runtime_package_catalog() -> dict[str, OfficialRuntimePackageCatalogEntry]:
    return dict(OFFICIAL_RUNTIME_PACKAGE_CATALOG)


def official_runtime_package_catalog_entry(
    package_name: str,
) -> OfficialRuntimePackageCatalogEntry:
    return OFFICIAL_RUNTIME_PACKAGE_CATALOG[str(package_name)]


def official_runtime_package_manifest_catalog() -> dict[str, RuntimePackageManifest]:
    return {
        package_name: entry.manifest
        for package_name, entry in OFFICIAL_RUNTIME_PACKAGE_CATALOG.items()
    }


def official_runtime_package_names() -> tuple[str, ...]:
    return tuple(OFFICIAL_RUNTIME_PACKAGE_CATALOG)


def official_runtime_distribution_catalog() -> dict[str, OfficialRuntimeDistributionCatalogEntry]:
    return dict(OFFICIAL_RUNTIME_DISTRIBUTIONS)


def official_runtime_distribution_entry(
    distribution_name: str,
) -> OfficialRuntimeDistributionCatalogEntry:
    return OFFICIAL_RUNTIME_DISTRIBUTIONS[str(distribution_name)]


def official_runtime_package_catalog_metadata(
    package_names: tuple[str, ...] | list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    selected = (
        official_runtime_package_names()
        if package_names is None
        else tuple(str(name) for name in package_names)
    )
    catalog = official_runtime_package_catalog()
    return {
        package_name: catalog[package_name].to_catalog_entry()
        for package_name in selected
    }


def official_runtime_package_catalog_provenance() -> dict[str, Any]:
    return {
        "schema_version": OFFICIAL_RUNTIME_PACKAGE_CATALOG_SCHEMA_VERSION,
        "provider_kind": "manifest-backed",
        "provider_path": "runtime.runtime_package_catalog:official_runtime_package_catalog",
        "published_metadata_paths": [
            "runtime.services.metadata['official_package_catalog_provenance']",
            "runtime.metadata['official_package_catalog_provenance']",
        ],
        "entries": {
            package_name: entry.to_provenance()
            for package_name, entry in OFFICIAL_RUNTIME_PACKAGE_CATALOG.items()
        },
        "distributions": {
            name: entry.to_metadata()
            for name, entry in OFFICIAL_RUNTIME_DISTRIBUTIONS.items()
        },
        "retired_kernel_helpers": [
            "runtime.runtime_package_manifests.assembly_function_name",
            "runtime.runtime_kernel.kernel._first_party_package_catalog",
        ],
        "retired_compatibility_views": [
            "runtime.package_profiles.FIRST_PARTY_PACKAGE_SPECS",
            "runtime.package_profiles.RUNTIME_DISTRIBUTION_SPECS",
        ],
    }


def _serialize_assembly_entrypoint(entrypoint: Any) -> str:
    if entrypoint is None:
        return ""
    if isinstance(entrypoint, str):
        return entrypoint
    module = getattr(entrypoint, "__module__", "")
    qualname = getattr(entrypoint, "__qualname__", "")
    if module and qualname:
        return f"{module}:{qualname}"
    return repr(entrypoint)


def _serialize_manifest_summary(manifest: RuntimePackageManifest) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "name": manifest.name,
        "role": manifest.role,
        "description": manifest.description,
        "dependencies": list(manifest.dependencies),
    }
    metadata = dict(getattr(manifest, "metadata", {}) or {})
    for key in ("builtin_tools", "builtin_agents", "builtin_skills", "invocation_providers"):
        values = metadata.get(key, ())
        if values:
            summary[key] = [str(value) for value in values]
    return summary


__all__ = [
    "OFFICIAL_RUNTIME_PACKAGE_CATALOG_SCHEMA_VERSION",
    "OfficialRuntimeDistributionCatalogEntry",
    "OfficialRuntimePackageCatalogEntry",
    "official_runtime_distribution_catalog",
    "official_runtime_distribution_entry",
    "official_runtime_package_catalog",
    "official_runtime_package_catalog_entry",
    "official_runtime_package_catalog_metadata",
    "official_runtime_package_catalog_provenance",
    "official_runtime_package_manifest_catalog",
    "official_runtime_package_names",
]
