from __future__ import annotations

from ..definitions import AgentDefinition, DefinitionOrigin, DefinitionSource, IsolationMode


def builtin_agents() -> tuple[AgentDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        AgentDefinition(
            name="main-router",
            description="Route the main thread turn to a direct answer, tool, skill, or subagent.",
            prompt=(
                "You are the main routing agent. Decide whether to answer directly, "
                "invoke tools, invoke a skill, or delegate to a subagent."
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
        AgentDefinition(
            name="explore",
            description="Investigate the codebase and summarize findings.",
            prompt="You are an exploration agent focused on gathering accurate context.",
            tools=("read", "glob", "grep", "web_fetch", "web_search"),
            origin=origin,
        ),
        AgentDefinition(
            name="plan",
            description="Break a larger task into defensible execution steps.",
            prompt="You are a planning agent. Produce concrete, ordered next steps.",
            tools=("read", "glob", "grep"),
            origin=origin,
        ),
        AgentDefinition(
            name="verification",
            description="Run tests, validations, and quality checks.",
            prompt="You are a verification agent. Focus on tests and regressions.",
            tools=("read", "glob", "grep", "bash"),
            origin=origin,
        ),
    )

