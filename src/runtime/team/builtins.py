from __future__ import annotations

from ..builtins.tools import builtin_tools as _shared_builtin_tools
from ..definitions import ToolDefinition

_TEAM_TOOL_NAMES = (
    "team_create",
    "team_spawn",
    "team_send",
    "team_respond",
    "team_delete",
)


def team_builtin_tools() -> tuple[ToolDefinition, ...]:
    index = {definition.name: definition for definition in _shared_builtin_tools()}
    return tuple(index[name] for name in _TEAM_TOOL_NAMES)


__all__ = ["team_builtin_tools"]
