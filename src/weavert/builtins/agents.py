from __future__ import annotations

from ..definitions import AgentDefinition, DefinitionOrigin, DefinitionSource, IsolationMode


def builtin_agents() -> tuple[AgentDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        AgentDefinition(
            name="main-router",
            description="Route the main thread turn to a direct answer, tool, skill, or subagent.",
            prompt=(
                "You are the main routing agent for the active thread. Route each turn "
                "in this order: first answer directly when no external action is needed; "
                "then use a tool when a direct tool call can complete the task; then use "
                "a skill when a reusable workflow or hook bundle is a better fit; finally "
                "delegate to a subagent when the task needs a separate execution thread, "
                "a specialized role, or background work."
            ),
            tools=("*",),
            skills=("*",),
            isolation=IsolationMode.NONE,
            origin=origin,
        ),
        AgentDefinition(
            name="general-purpose",
            description="Handle broad implementation and execution tasks.",
            prompt="You are a pragmatic implementation agent.",
            tools=("*",),
            origin=origin,
        ),
    )
