from __future__ import annotations

from dataclasses import dataclass, replace

from ..definitions import AgentDefinition, SkillDefinition, ToolDefinition
from ..package_profiles import (
    DEFAULT_RUNTIME_DISTRIBUTION,
    FIRST_PARTY_PACKAGE_SPECS,
    resolve_first_party_package_names,
)
from .agents import builtin_agents
from .skills import builtin_skills
from .tools import builtin_tools


@dataclass(frozen=True, slots=True)
class BuiltinPack:
    packages: tuple[str, ...]
    tools: tuple[ToolDefinition, ...]
    agents: tuple[AgentDefinition, ...]
    skills: tuple[SkillDefinition, ...]


def builtin_package_catalog() -> dict[str, BuiltinPack]:
    tool_index = {definition.name: definition for definition in builtin_tools()}
    agent_index = {definition.name: definition for definition in builtin_agents()}
    skill_index = {definition.name: definition for definition in builtin_skills()}
    return {
        package_name: BuiltinPack(
            packages=(package_name,),
            tools=_select_tool_definitions(tool_index, spec.builtin_tools, package_name),
            agents=_select_agent_definitions(agent_index, spec.builtin_agents, package_name),
            skills=_select_skill_definitions(skill_index, spec.builtin_skills, package_name),
        )
        for package_name, spec in FIRST_PARTY_PACKAGE_SPECS.items()
    }


def load_builtin_pack(package_names: tuple[str, ...] | list[str] | None = None) -> BuiltinPack:
    resolved_packages = (
        tuple(package_names)
        if package_names is not None
        else resolve_first_party_package_names(distribution=DEFAULT_RUNTIME_DISTRIBUTION)
    )
    catalog = builtin_package_catalog()
    unknown = sorted(set(resolved_packages) - set(catalog))
    if unknown:
        raise ValueError(f"Unknown builtin package(s): {', '.join(unknown)}")
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


def _select_tool_definitions(
    index: dict[str, ToolDefinition],
    names: tuple[str, ...],
    package_name: str,
) -> tuple[ToolDefinition, ...]:
    return tuple(_annotate_builtin_owner(index[name], package_name) for name in names)


def _select_agent_definitions(
    index: dict[str, AgentDefinition],
    names: tuple[str, ...],
    package_name: str,
) -> tuple[AgentDefinition, ...]:
    return tuple(_annotate_builtin_owner(index[name], package_name) for name in names)


def _select_skill_definitions(
    index: dict[str, SkillDefinition],
    names: tuple[str, ...],
    package_name: str,
) -> tuple[SkillDefinition, ...]:
    return tuple(_annotate_builtin_owner(index[name], package_name) for name in names)


def _annotate_builtin_owner(
    definition: ToolDefinition | AgentDefinition | SkillDefinition,
    package_name: str,
) -> ToolDefinition | AgentDefinition | SkillDefinition:
    metadata = dict(definition.metadata)
    metadata["builtin_owner"] = package_name
    metadata["builtin_owner_role"] = FIRST_PARTY_PACKAGE_SPECS[package_name].role.value
    return replace(definition, metadata=metadata)


__all__ = [
    "BuiltinPack",
    "builtin_package_catalog",
    "load_builtin_pack",
]
