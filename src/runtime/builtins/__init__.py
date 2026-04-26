from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from ..definitions import AgentDefinition, SkillDefinition, ToolDefinition
from ..first_party_loading import load_object
from ..package_profiles import (
    DEFAULT_RUNTIME_DISTRIBUTION,
    FIRST_PARTY_PACKAGE_SPECS,
    resolve_first_party_package_names,
)
from .agents import builtin_agents
from .tools import builtin_tools


@dataclass(frozen=True, slots=True)
class BuiltinPack:
    packages: tuple[str, ...]
    tools: tuple[ToolDefinition, ...]
    agents: tuple[AgentDefinition, ...]
    skills: tuple[SkillDefinition, ...]


_OPTIONAL_BUILTIN_LOADERS: dict[str, dict[str, str]] = {
    "runtime-memory": {
        "skills": "runtime.memory.builtins:memory_builtin_skills",
    },
    "runtime-team": {
        "tools": "runtime.team.builtins:team_builtin_tools",
    },
    "runtime-builtin-workflows": {
        "skills": "runtime.builtin_workflows.builtins:builtin_workflow_skills",
    },
    "runtime-devtools": {
        "tools": "runtime.devtools.builtins:devtools_builtin_tools",
        "agents": "runtime.devtools.builtins:devtools_builtin_agents",
    },
}


def builtin_package_catalog(
    package_names: tuple[str, ...] | list[str] | None = None,
) -> dict[str, BuiltinPack]:
    selected = (
        tuple(FIRST_PARTY_PACKAGE_SPECS)
        if package_names is None
        else tuple(package_names)
    )
    return {
        package_name: _builtin_pack_for_package(package_name)
        for package_name in selected
    }


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


def _load_optional_tool_definitions(package_name: str) -> tuple[ToolDefinition, ...]:
    expected = FIRST_PARTY_PACKAGE_SPECS[package_name].builtin_tools
    definitions = _load_optional_definitions(package_name, kind="tools")
    _validate_definition_names(definitions, expected_names=expected, package_name=package_name, kind="tool")
    return _annotate_tool_definitions(definitions, package_name)


def _load_optional_agent_definitions(package_name: str) -> tuple[AgentDefinition, ...]:
    expected = FIRST_PARTY_PACKAGE_SPECS[package_name].builtin_agents
    definitions = _load_optional_definitions(package_name, kind="agents")
    _validate_definition_names(definitions, expected_names=expected, package_name=package_name, kind="agent")
    return _annotate_agent_definitions(definitions, package_name)


def _load_optional_skill_definitions(package_name: str) -> tuple[SkillDefinition, ...]:
    expected = FIRST_PARTY_PACKAGE_SPECS[package_name].builtin_skills
    definitions = _load_optional_definitions(package_name, kind="skills")
    _validate_definition_names(definitions, expected_names=expected, package_name=package_name, kind="skill")
    return _annotate_skill_definitions(definitions, package_name)


def _load_optional_definitions(
    package_name: str,
    *,
    kind: str,
) -> tuple[ToolDefinition, ...] | tuple[AgentDefinition, ...] | tuple[SkillDefinition, ...]:
    loaders = _OPTIONAL_BUILTIN_LOADERS.get(package_name, {})
    loader_spec = loaders.get(kind)
    if loader_spec is None:
        return ()
    factory = load_object(loader_spec)
    return tuple(factory())


def _builtin_pack_for_package(package_name: str) -> BuiltinPack:
    if package_name == "runtime-core":
        return BuiltinPack(
            packages=("runtime-core",),
            tools=_annotate_tool_definitions(builtin_tools(), "runtime-core"),
            agents=_annotate_agent_definitions(builtin_agents(), "runtime-core"),
            skills=(),
        )
    if package_name == "runtime-memory":
        return BuiltinPack(
            packages=("runtime-memory",),
            tools=(),
            agents=(),
            skills=_load_optional_skill_definitions("runtime-memory"),
        )
    if package_name == "runtime-team":
        return BuiltinPack(
            packages=("runtime-team",),
            tools=_load_optional_tool_definitions("runtime-team"),
            agents=(),
            skills=(),
        )
    if package_name == "runtime-builtin-workflows":
        return BuiltinPack(
            packages=("runtime-builtin-workflows",),
            tools=(),
            agents=(),
            skills=_load_optional_skill_definitions("runtime-builtin-workflows"),
        )
    if package_name == "runtime-devtools":
        return BuiltinPack(
            packages=("runtime-devtools",),
            tools=_load_optional_tool_definitions("runtime-devtools"),
            agents=_load_optional_agent_definitions("runtime-devtools"),
            skills=(),
        )
    return _empty_builtin_pack(package_name)


def _validate_definition_names(
    definitions: Iterable[Any],
    *,
    expected_names: tuple[str, ...],
    package_name: str,
    kind: str,
) -> None:
    actual_names = tuple(getattr(definition, "name", None) for definition in definitions)
    if actual_names != expected_names:
        raise ValueError(
            f"Builtin {kind} definitions for {package_name} do not match the published package profile: "
            f"expected {expected_names}, got {actual_names}"
        )


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
