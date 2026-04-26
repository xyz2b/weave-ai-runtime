from __future__ import annotations

from ..definitions import AgentDefinition, DefinitionOrigin, DefinitionSource

_PLANNER_TOOL_SELECTORS = ("task_*",)
_COORDINATOR_TOOL_SELECTORS = ("task_*", "job_*", "agent")
_WORKER_DISALLOWED_TOOL_SELECTORS = ("task_*", "job_*")


def _planning_profile_metadata(
    *,
    kind: str,
    tool_selectors: tuple[str, ...] = (),
    disallowed_tool_selectors: tuple[str, ...] = (),
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "planning_profile_kind": kind,
        "shared_planning_primitives_owner": "runtime-core",
    }
    if tool_selectors:
        metadata["planning_profile_tool_selectors"] = list(tool_selectors)
    if disallowed_tool_selectors:
        metadata["planning_profile_disallowed_tool_selectors"] = list(disallowed_tool_selectors)
    return metadata


def planning_builtin_agents() -> tuple[AgentDefinition, ...]:
    origin = DefinitionOrigin(DefinitionSource.BUNDLED)
    return (
        AgentDefinition(
            name="planner",
            description="Maintain shared planning state through the runtime task control plane.",
            prompt=(
                "You are the official shared-planning profile. Break work into concrete tasks, "
                "keep the shared task list current, and use runtime task tools instead of "
                "inventing private TODO tracking."
            ),
            tools=_PLANNER_TOOL_SELECTORS,
            metadata=_planning_profile_metadata(
                kind="planner",
                tool_selectors=_PLANNER_TOOL_SELECTORS,
            ),
            origin=origin,
        ),
        AgentDefinition(
            name="coordinator",
            description="Coordinate shared planning state and execution observation without redefining runtime ownership.",
            prompt=(
                "You are the official planning coordinator profile. Use task tools for shared plan "
                "state, job tools for execution observation, and keep planning state separate from "
                "background execution state."
            ),
            tools=_COORDINATOR_TOOL_SELECTORS,
            metadata=_planning_profile_metadata(
                kind="coordinator",
                tool_selectors=_COORDINATOR_TOOL_SELECTORS,
            ),
            origin=origin,
        ),
        AgentDefinition(
            name="worker",
            description="Execute assigned work without owning the shared planning task list by default.",
            prompt=(
                "You are the official execution-focused worker profile. Carry out concrete work, "
                "report progress clearly, and leave shared task-list ownership to planner or "
                "coordinator roles unless explicitly instructed otherwise."
            ),
            tools=("*",),
            disallowed_tools=_WORKER_DISALLOWED_TOOL_SELECTORS,
            metadata=_planning_profile_metadata(
                kind="worker",
                tool_selectors=("*",),
                disallowed_tool_selectors=_WORKER_DISALLOWED_TOOL_SELECTORS,
            ),
            origin=origin,
        ),
    )


__all__ = ["planning_builtin_agents"]
