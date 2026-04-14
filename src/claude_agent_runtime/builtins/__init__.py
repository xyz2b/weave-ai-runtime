from __future__ import annotations

from dataclasses import dataclass

from ..definitions import AgentDefinition, SkillDefinition, ToolDefinition
from .agents import builtin_agents
from .skills import builtin_skills
from .tools import builtin_tools


@dataclass(frozen=True, slots=True)
class BuiltinPack:
    tools: tuple[ToolDefinition, ...]
    agents: tuple[AgentDefinition, ...]
    skills: tuple[SkillDefinition, ...]


def load_builtin_pack() -> BuiltinPack:
    return BuiltinPack(
        tools=builtin_tools(),
        agents=builtin_agents(),
        skills=builtin_skills(),
    )

