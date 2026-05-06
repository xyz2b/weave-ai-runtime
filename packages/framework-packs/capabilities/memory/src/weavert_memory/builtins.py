from __future__ import annotations

from weavert.definitions import DefinitionOrigin, DefinitionSource, SkillDefinition


def memory_builtin_skills() -> tuple[SkillDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        SkillDefinition(
            name="remember",
            description="Capture durable information for future turns or sessions.",
            content="Extract the stable facts worth remembering and record them in the runtime memory system.",
            origin=origin,
        ),
    )


__all__ = ["memory_builtin_skills"]
