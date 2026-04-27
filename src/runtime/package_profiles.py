from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FirstPartyPackageRole(StrEnum):
    CORE = "core"
    CAPABILITY = "capability"
    MECHANISM = "mechanism"
    ADAPTER = "adapter"
    PROVIDER = "provider"
    PROFILE_WORKFLOW = "profile_workflow"


class RuntimeDistribution(StrEnum):
    CORE = "runtime-core"
    DEFAULT = "runtime-default"
    FULL = "runtime-full"


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


FIRST_PARTY_PACKAGE_SPECS: dict[str, FirstPartyPackageSpec] = {
    "runtime-core": FirstPartyPackageSpec(
        name="runtime-core",
        role=FirstPartyPackageRole.CORE,
        description="Kernel assembly, root boot path, runtime control surfaces, and core built-ins.",
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
    ),
    "runtime-memory": FirstPartyPackageSpec(
        name="runtime-memory",
        role=FirstPartyPackageRole.CAPABILITY,
        description="First-party memory capability package.",
        dependencies=("runtime-core",),
        builtin_skills=("remember",),
    ),
    "runtime-team": FirstPartyPackageSpec(
        name="runtime-team",
        role=FirstPartyPackageRole.CAPABILITY,
        description="First-party team control and teammate orchestration capability package.",
        dependencies=("runtime-core",),
        builtin_tools=("team_create", "team_spawn", "team_send", "team_respond", "team_delete"),
    ),
    "runtime-compaction": FirstPartyPackageSpec(
        name="runtime-compaction",
        role=FirstPartyPackageRole.MECHANISM,
        description="First-party compaction strategies and manager package.",
        dependencies=("runtime-core",),
    ),
    "runtime-isolation": FirstPartyPackageSpec(
        name="runtime-isolation",
        role=FirstPartyPackageRole.MECHANISM,
        description="First-party isolation adapters package.",
        dependencies=("runtime-core",),
    ),
    "runtime-openai": FirstPartyPackageSpec(
        name="runtime-openai",
        role=FirstPartyPackageRole.PROVIDER,
        description="First-party OpenAI provider integration package.",
        dependencies=("runtime-core",),
    ),
    "runtime-hosts-reference": FirstPartyPackageSpec(
        name="runtime-hosts-reference",
        role=FirstPartyPackageRole.ADAPTER,
        description="First-party reference host implementations package.",
        dependencies=("runtime-core",),
    ),
    "runtime-stores-file": FirstPartyPackageSpec(
        name="runtime-stores-file",
        role=FirstPartyPackageRole.ADAPTER,
        description="First-party file-backed runtime store implementations package.",
        dependencies=("runtime-core",),
    ),
    "runtime-builtin-workflows": FirstPartyPackageSpec(
        name="runtime-builtin-workflows",
        role=FirstPartyPackageRole.PROFILE_WORKFLOW,
        description="First-party reusable workflow skills package.",
        dependencies=("runtime-core",),
        builtin_skills=("verify", "debug", "stuck", "batch", "simplify"),
    ),
    "runtime-planning": FirstPartyPackageSpec(
        name="runtime-planning",
        role=FirstPartyPackageRole.PROFILE_WORKFLOW,
        description="First-party planning profile and workflow agent package.",
        dependencies=("runtime-core",),
        builtin_agents=("planner", "coordinator", "worker"),
    ),
    "runtime-devtools": FirstPartyPackageSpec(
        name="runtime-devtools",
        role=FirstPartyPackageRole.PROFILE_WORKFLOW,
        description="First-party workspace and coding-oriented built-ins package.",
        dependencies=("runtime-core",),
        builtin_tools=("read", "glob", "grep", "edit", "write", "bash", "web_fetch", "web_search"),
        builtin_agents=("explore", "plan", "verification"),
    ),
}


RUNTIME_DISTRIBUTION_SPECS: dict[RuntimeDistribution, RuntimeDistributionSpec] = {
    RuntimeDistribution.CORE: RuntimeDistributionSpec(
        name=RuntimeDistribution.CORE,
        description="Minimal runnable kernel distribution.",
        packages=("runtime-core",),
    ),
    RuntimeDistribution.DEFAULT: RuntimeDistributionSpec(
        name=RuntimeDistribution.DEFAULT,
        description="Supported baseline distribution with first-party memory and team capabilities.",
        packages=("runtime-core", "runtime-memory", "runtime-team"),
    ),
    RuntimeDistribution.FULL: RuntimeDistributionSpec(
        name=RuntimeDistribution.FULL,
        description="Supported full first-party distribution.",
        packages=(
            "runtime-core",
            "runtime-memory",
            "runtime-team",
            "runtime-compaction",
            "runtime-isolation",
            "runtime-openai",
            "runtime-hosts-reference",
            "runtime-stores-file",
            "runtime-builtin-workflows",
            "runtime-planning",
            "runtime-devtools",
        ),
    ),
}


def normalize_runtime_distribution(value: RuntimeDistribution | str) -> RuntimeDistribution:
    if isinstance(value, RuntimeDistribution):
        return value
    return RuntimeDistribution(str(value))


def distribution_spec(value: RuntimeDistribution | str) -> RuntimeDistributionSpec:
    return RUNTIME_DISTRIBUTION_SPECS[normalize_runtime_distribution(value)]


def resolve_first_party_package_names(
    *,
    distribution: RuntimeDistribution | str = DEFAULT_RUNTIME_DISTRIBUTION,
    enabled_packages: set[str] | tuple[str, ...] | list[str] = (),
    disabled_packages: set[str] | tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    resolved_distribution = normalize_runtime_distribution(distribution)
    enabled = {str(name) for name in enabled_packages}
    disabled = {str(name) for name in disabled_packages}
    unknown = sorted((enabled | disabled) - set(FIRST_PARTY_PACKAGE_SPECS))
    if unknown:
        raise ValueError(f"Unknown first-party package(s): {', '.join(unknown)}")
    if "runtime-core" in disabled:
        raise ValueError("runtime-core cannot be disabled")
    requested = set(distribution_spec(resolved_distribution).packages)
    requested.update(enabled)
    requested.difference_update(disabled)
    return tuple(
        package_name
        for package_name in FIRST_PARTY_PACKAGE_SPECS
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
