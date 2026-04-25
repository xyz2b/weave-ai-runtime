from __future__ import annotations

from collections.abc import Iterable
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
    from ..devtools.builtins import devtools_builtin_agents, devtools_builtin_tools
    from ..memory.builtins import memory_builtin_skills
    from ..team.builtins import team_builtin_tools

    tool_index = {definition.name: definition for definition in builtin_tools()}
    agent_index = {definition.name: definition for definition in builtin_agents()}
    skill_index = {definition.name: definition for definition in builtin_skills()}
    return {
        "runtime-core": BuiltinPack(
            packages=("runtime-core",),
            tools=_select_tool_definitions(
                tool_index,
                FIRST_PARTY_PACKAGE_SPECS["runtime-core"].builtin_tools,
                "runtime-core",
            ),
            agents=_select_agent_definitions(
                agent_index,
                FIRST_PARTY_PACKAGE_SPECS["runtime-core"].builtin_agents,
                "runtime-core",
            ),
            skills=(),
        ),
        "runtime-memory": BuiltinPack(
            packages=("runtime-memory",),
            tools=(),
            agents=(),
            skills=_annotate_skill_definitions(memory_builtin_skills(), "runtime-memory"),
        ),
        "runtime-team": BuiltinPack(
            packages=("runtime-team",),
            tools=_annotate_tool_definitions(team_builtin_tools(), "runtime-team"),
            agents=(),
            skills=(),
        ),
        "runtime-compaction": _empty_builtin_pack("runtime-compaction"),
        "runtime-isolation": _empty_builtin_pack("runtime-isolation"),
        "runtime-openai": _empty_builtin_pack("runtime-openai"),
        "runtime-hosts-reference": _empty_builtin_pack("runtime-hosts-reference"),
        "runtime-stores-file": _empty_builtin_pack("runtime-stores-file"),
        "runtime-builtin-workflows": BuiltinPack(
            packages=("runtime-builtin-workflows",),
            tools=(),
            agents=(),
            skills=_select_skill_definitions(
                skill_index,
                FIRST_PARTY_PACKAGE_SPECS["runtime-builtin-workflows"].builtin_skills,
                "runtime-builtin-workflows",
            ),
        ),
        "runtime-devtools": BuiltinPack(
            packages=("runtime-devtools",),
            tools=_annotate_tool_definitions(devtools_builtin_tools(), "runtime-devtools"),
            agents=_annotate_agent_definitions(devtools_builtin_agents(), "runtime-devtools"),
            skills=(),
        ),
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
    return _annotate_tool_definitions((index[name] for name in names), package_name)


def _select_agent_definitions(
    index: dict[str, AgentDefinition],
    names: tuple[str, ...],
    package_name: str,
) -> tuple[AgentDefinition, ...]:
    return _annotate_agent_definitions((index[name] for name in names), package_name)


def _select_skill_definitions(
    index: dict[str, SkillDefinition],
    names: tuple[str, ...],
    package_name: str,
) -> tuple[SkillDefinition, ...]:
    return _annotate_skill_definitions((index[name] for name in names), package_name)


def _annotate_tool_definitions(
    definitions: Iterable[ToolDefinition],
    package_name: str,
) -> tuple[ToolDefinition, ...]:
    return tuple(_annotate_builtin_owner(definition, package_name) for definition in definitions)


def _annotate_agent_definitions(
    definitions: Iterable[AgentDefinition],
    package_name: str,
) -> tuple[AgentDefinition, ...]:
    return tuple(_annotate_builtin_owner(definition, package_name) for definition in definitions)


def _annotate_skill_definitions(
    definitions: Iterable[SkillDefinition],
    package_name: str,
) -> tuple[SkillDefinition, ...]:
    return tuple(_annotate_builtin_owner(definition, package_name) for definition in definitions)


def _empty_builtin_pack(package_name: str) -> BuiltinPack:
    return BuiltinPack(
        packages=(package_name,),
        tools=(),
        agents=(),
        skills=(),
    )


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
