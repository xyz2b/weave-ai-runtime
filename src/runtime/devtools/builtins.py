from __future__ import annotations

from ..builtins.agents import builtin_agents as _shared_builtin_agents
from ..builtins.tools import builtin_tools as _shared_builtin_tools
from ..definitions import AgentDefinition, ToolDefinition

_DEVTOOLS_TOOL_NAMES = (
    "read",
    "glob",
    "grep",
    "edit",
    "write",
    "bash",
    "web_fetch",
    "web_search",
)
_DEVTOOLS_AGENT_NAMES = ("explore", "plan", "verification")


def devtools_builtin_tools() -> tuple[ToolDefinition, ...]:
    index = {definition.name: definition for definition in _shared_builtin_tools()}
    return tuple(index[name] for name in _DEVTOOLS_TOOL_NAMES)


def devtools_builtin_agents() -> tuple[AgentDefinition, ...]:
    index = {definition.name: definition for definition in _shared_builtin_agents()}
    return tuple(index[name] for name in _DEVTOOLS_AGENT_NAMES)


__all__ = [
    "devtools_builtin_agents",
    "devtools_builtin_tools",
]
