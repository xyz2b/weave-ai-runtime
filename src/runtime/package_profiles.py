from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .public_contract import canonical_distribution_name, canonical_first_party_name
from .runtime_package_catalog import (
    official_runtime_distribution_catalog,
    official_runtime_package_catalog,
    official_runtime_package_names,
)


class FirstPartyPackageRole(StrEnum):
    CORE = "core"
    CAPABILITY = "capability"
    MECHANISM = "mechanism"
    ADAPTER = "adapter"
    PROVIDER = "provider"
    PROFILE_WORKFLOW = "profile_workflow"


class RuntimeDistribution(StrEnum):
    CORE = "weavert-core"
    DEFAULT = "weavert-default"
    FULL = "weavert-full"


DEFAULT_RUNTIME_DISTRIBUTION = RuntimeDistribution.FULL


@dataclass(frozen=True, slots=True)
class FirstPartyPackageSpec:
    name: str
    role: FirstPartyPackageRole
    description: str
    dependencies: tuple[str, ...] = ()
    builtin_tools: tuple[str, ...] = ()
    builtin_agents: tuple[str, ...] = ()
    builtin_skills: tuple[str, ...] = ()
    invocation_providers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeDistributionSpec:
    name: RuntimeDistribution
    description: str
    packages: tuple[str, ...]


def _first_party_package_specs() -> dict[str, FirstPartyPackageSpec]:
    catalog = official_runtime_package_catalog()
    return {
        package_name: FirstPartyPackageSpec(
            name=entry.manifest.name,
            role=FirstPartyPackageRole(entry.manifest.role),
            description=entry.manifest.description,
            dependencies=entry.manifest.dependencies,
            builtin_tools=entry.builtin_tools,
            builtin_agents=entry.builtin_agents,
            builtin_skills=entry.builtin_skills,
            invocation_providers=entry.invocation_providers,
        )
        for package_name, entry in catalog.items()
    }


def _runtime_distribution_specs() -> dict[RuntimeDistribution, RuntimeDistributionSpec]:
    catalog = official_runtime_distribution_catalog()
    return {
        RuntimeDistribution(name): RuntimeDistributionSpec(
            name=RuntimeDistribution(name),
            description=entry.description,
            packages=entry.packages,
        )
        for name, entry in catalog.items()
    }


FIRST_PARTY_PACKAGE_SPECS: dict[str, FirstPartyPackageSpec] = _first_party_package_specs()


RUNTIME_DISTRIBUTION_SPECS: dict[RuntimeDistribution, RuntimeDistributionSpec] = (
    _runtime_distribution_specs()
)


def normalize_runtime_distribution(value: RuntimeDistribution | str) -> RuntimeDistribution:
    if isinstance(value, RuntimeDistribution):
        return value
    return RuntimeDistribution(canonical_distribution_name(str(value)))


def distribution_spec(value: RuntimeDistribution | str) -> RuntimeDistributionSpec:
    return RUNTIME_DISTRIBUTION_SPECS[normalize_runtime_distribution(value)]


def resolve_first_party_package_names(
    *,
    distribution: RuntimeDistribution | str = DEFAULT_RUNTIME_DISTRIBUTION,
    enabled_packages: set[str] | tuple[str, ...] | list[str] = (),
    disabled_packages: set[str] | tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    resolved_distribution = normalize_runtime_distribution(distribution)
    enabled = {canonical_first_party_name(str(name)) for name in enabled_packages}
    disabled = {canonical_first_party_name(str(name)) for name in disabled_packages}
    known_packages = set(official_runtime_package_names())
    unknown = sorted((enabled | disabled) - known_packages)
    if unknown:
        raise ValueError(f"Unknown first-party package(s): {', '.join(unknown)}")
    if RuntimeDistribution.CORE.value in disabled:
        raise ValueError(f"{RuntimeDistribution.CORE.value} cannot be disabled")
    requested = set(distribution_spec(resolved_distribution).packages)
    requested.update(enabled)
    requested.difference_update(disabled)
    return tuple(
        package_name
        for package_name in official_runtime_package_names()
        if package_name in requested
    )


__all__ = [
    "DEFAULT_RUNTIME_DISTRIBUTION",
    "FIRST_PARTY_PACKAGE_SPECS",
    "FirstPartyPackageRole",
    "FirstPartyPackageSpec",
    "RUNTIME_DISTRIBUTION_SPECS",
    "RuntimeDistribution",
    "RuntimeDistributionSpec",
    "distribution_spec",
    "normalize_runtime_distribution",
    "resolve_first_party_package_names",
]
