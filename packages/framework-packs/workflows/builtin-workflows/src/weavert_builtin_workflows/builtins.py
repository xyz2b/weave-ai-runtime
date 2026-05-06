from __future__ import annotations

from weavert.definitions import (
    DefinitionOrigin,
    DefinitionSource,
    SkillDefinition,
    SkillExecutionContext,
)


def builtin_workflow_skills() -> tuple[SkillDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        SkillDefinition(
            name="verify",
            description="Run a focused verification pass before finalizing work.",
            content="Inspect the latest changes and validate them with the strongest available checks.",
            execution_context=SkillExecutionContext.FORK,
            origin=origin,
        ),
        SkillDefinition(
            name="debug",
            description="Investigate a bug systematically.",
            content="Reproduce the issue, narrow the cause, and propose or apply the smallest fix.",
            origin=origin,
        ),
        SkillDefinition(
            name="stuck",
            description="Reframe the current obstacle and propose next actions.",
            content="Describe the blocker clearly, list assumptions, and identify the next viable path.",
            origin=origin,
        ),
        SkillDefinition(
            name="batch",
            description="Coordinate several independent steps in one pass.",
            content="Group compatible work, keep dependencies explicit, and report per-step status.",
            origin=origin,
        ),
        SkillDefinition(
            name="simplify",
            description="Reduce incidental complexity in a design or implementation.",
            content="Prefer simpler interfaces and smaller moving pieces when they preserve behavior.",
            origin=origin,
        ),
    )


__all__ = ["builtin_workflow_skills"]
