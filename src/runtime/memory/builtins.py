from __future__ import annotations

from ..builtins.skills import builtin_skills as _shared_builtin_skills
from ..definitions import SkillDefinition

_MEMORY_SKILL_NAMES = ("remember",)


def memory_builtin_skills() -> tuple[SkillDefinition, ...]:
    index = {definition.name: definition for definition in _shared_builtin_skills()}
    return tuple(index[name] for name in _MEMORY_SKILL_NAMES)


__all__ = ["memory_builtin_skills"]
