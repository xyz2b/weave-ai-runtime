from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..definitions import AgentDefinition, SkillDefinition, ToolDefinition
from ..package_profiles import (
    DEFAULT_RUNTIME_DISTRIBUTION,
    FIRST_PARTY_PACKAGE_SPECS,
    resolve_first_party_package_names,
)
from ..runtime_package_manifests import official_runtime_package_manifests
from ..runtime_package_protocols import PackageAssemblyStage, PackageContext


@dataclass(frozen=True, slots=True)
class BuiltinPack:
    packages: tuple[str, ...]
    tools: tuple[ToolDefinition, ...]
    agents: tuple[AgentDefinition, ...]
    skills: tuple[SkillDefinition, ...]

def builtin_package_catalog(
    package_names: tuple[str, ...] | list[str] | None = None,
) -> dict[str, BuiltinPack]:
    selected = (
        tuple(FIRST_PARTY_PACKAGE_SPECS)
        if package_names is None
        else tuple(package_names)
    )
    manifests = official_runtime_package_manifests(selected)
    catalog: dict[str, BuiltinPack] = {}
    for manifest in manifests:
        contribution = manifest.assemble(
            PackageContext(
                manifest=manifest,
                stage=PackageAssemblyStage.BUILTINS,
                distribution=DEFAULT_RUNTIME_DISTRIBUTION.value,
                selected_packages=selected,
                working_directory=Path.cwd(),
            )
        )
        catalog[manifest.name] = BuiltinPack(
            packages=(manifest.name,),
            tools=tuple(contribution.builtin_tools),
            agents=tuple(contribution.builtin_agents),
            skills=tuple(contribution.builtin_skills),
        )
    return catalog


def load_builtin_pack(package_names: tuple[str, ...] | list[str] | None = None) -> BuiltinPack:
    resolved_packages = (
        tuple(package_names)
        if package_names is not None
        else resolve_first_party_package_names(distribution=DEFAULT_RUNTIME_DISTRIBUTION)
    )
    unknown = sorted(set(resolved_packages) - set(FIRST_PARTY_PACKAGE_SPECS))
    if unknown:
        raise ValueError(f"Unknown builtin package(s): {', '.join(unknown)}")
    catalog = builtin_package_catalog(resolved_packages)
    tools: list[ToolDefinition] = []
    agents: list[AgentDefinition] = []
    skills: list[SkillDefinition] = []
    for package_name in resolved_packages:
        pack = catalog[package_name]
        tools.extend(pack.tools)
        agents.extend(pack.agents)
        skills.extend(pack.skills)
    return BuiltinPack(
        packages=tuple(resolved_packages),
        tools=tuple(tools),
        agents=tuple(agents),
        skills=tuple(skills),
    )


__all__ = [
    "BuiltinPack",
    "builtin_package_catalog",
    "load_builtin_pack",
]
