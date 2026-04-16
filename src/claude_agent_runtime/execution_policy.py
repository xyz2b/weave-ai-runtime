from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .definitions import (
    AgentDefinition,
    IsolationMode,
    MemoryScope,
    PermissionMode,
    SkillDefinition,
    ToolDefinition,
)
from .permissions import PermissionContext

EXECUTION_POLICY_STATE_KEY = "execution_policy_state"

_DEFAULT_PERMISSION_MODES = {
    PermissionMode.DEFAULT,
    PermissionMode.AUTO,
    PermissionMode.PLAN,
    PermissionMode.ACCEPT_EDITS,
}
_MEMORY_ORDER = {
    MemoryScope.LOCAL: 0,
    MemoryScope.PROJECT: 1,
    MemoryScope.USER: 2,
}
_ISOLATION_ORDER = {
    IsolationMode.NONE: 0,
    IsolationMode.WORKTREE: 1,
    IsolationMode.REMOTE: 2,
}


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    tool_pool: tuple[ToolDefinition, ...]
    skill_pool: tuple[SkillDefinition, ...]
    permission_context: PermissionContext
    memory_scope: MemoryScope | None = None
    isolation_mode: IsolationMode = IsolationMode.NONE
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionPolicyState:
    effective: ExecutionPolicy
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.history and self.effective.trace:
            self.history.append(dict(self.effective.trace))

    def apply(self, policy: ExecutionPolicy) -> ExecutionPolicy:
        self.effective = policy
        if policy.trace:
            self.history.append(dict(policy.trace))
        return policy

    def snapshot(self) -> dict[str, Any]:
        return {
            "effective": serialize_policy(self.effective),
            "history": [dict(entry) for entry in self.history],
        }


def policy_state_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> ExecutionPolicyState | None:
    if metadata is None:
        return None
    state = metadata.get(EXECUTION_POLICY_STATE_KEY)
    if isinstance(state, ExecutionPolicyState):
        return state
    return None


def build_root_execution_policy(
    agent: AgentDefinition,
    *,
    tool_pool: Sequence[ToolDefinition],
    skill_pool: Sequence[SkillDefinition],
    permission_context: PermissionContext,
    memory_scope: MemoryScope | None = None,
    isolation_mode: IsolationMode | None = None,
) -> ExecutionPolicy:
    resolved_isolation = isolation_mode or agent.isolation or IsolationMode.NONE
    resolved_memory = memory_scope if memory_scope is not None else agent.memory
    return ExecutionPolicy(
        tool_pool=tuple(tool_pool),
        skill_pool=tuple(skill_pool),
        permission_context=permission_context,
        memory_scope=resolved_memory,
        isolation_mode=resolved_isolation,
        trace={
            "source": "root",
            "name": agent.name,
            "effective_tools": [tool.name for tool in tool_pool],
            "effective_skills": [skill.name for skill in skill_pool],
            "effective_permission_mode": permission_context.mode.value,
            "effective_memory_scope": resolved_memory.value if resolved_memory is not None else None,
            "effective_isolation_mode": resolved_isolation.value,
        },
    )


def resolve_agent_execution_policy(
    agent: AgentDefinition,
    *,
    parent_policy: ExecutionPolicy | None,
    base_tool_pool: Sequence[ToolDefinition],
    base_skill_pool: Sequence[SkillDefinition],
    permission_context: PermissionContext,
) -> ExecutionPolicy:
    effective_tools = _narrow_tool_pool(
        base_pool=base_tool_pool,
        allowed_tools=agent.tools or None,
        disallowed_tools=agent.disallowed_tools or None,
    )
    effective_skills = resolve_skill_pool(base_skill_pool, agent.skills)
    resolved_mode = narrow_permission_mode(permission_context.mode, agent.permission_mode)
    effective_permission_context = PermissionContext(
        session_id=permission_context.session_id,
        mode=resolved_mode,
        rules=permission_context.rules,
        metadata=dict(permission_context.metadata),
    )
    effective_memory = narrow_memory_scope(
        parent_policy.memory_scope if parent_policy is not None else None,
        agent.memory,
    )
    effective_isolation = narrow_isolation_mode(
        parent_policy.isolation_mode if parent_policy is not None else None,
        agent.isolation,
    )
    return ExecutionPolicy(
        tool_pool=effective_tools,
        skill_pool=effective_skills,
        permission_context=effective_permission_context,
        memory_scope=effective_memory,
        isolation_mode=effective_isolation,
        trace={
            "source": "agent",
            "name": agent.name,
            "requested_tools": list(agent.tools),
            "requested_disallowed_tools": list(agent.disallowed_tools),
            "requested_skills": list(agent.skills),
            "requested_permission_mode": agent.permission_mode.value if agent.permission_mode is not None else None,
            "requested_memory_scope": agent.memory.value if agent.memory is not None else None,
            "requested_isolation_mode": agent.isolation.value if agent.isolation is not None else None,
            "effective_tools": [tool.name for tool in effective_tools],
            "effective_skills": [skill.name for skill in effective_skills],
            "effective_permission_mode": effective_permission_context.mode.value,
            "effective_memory_scope": effective_memory.value if effective_memory is not None else None,
            "effective_isolation_mode": effective_isolation.value,
        },
    )


def resolve_skill_execution_policy(
    skill: SkillDefinition,
    *,
    parent_policy: ExecutionPolicy | None,
    base_tool_pool: Sequence[ToolDefinition],
    base_skill_pool: Sequence[SkillDefinition],
    permission_context: PermissionContext,
) -> ExecutionPolicy:
    effective_tools = _narrow_tool_pool(
        base_pool=base_tool_pool,
        allowed_tools=skill.allowed_tools or None,
    )
    effective_skills = tuple(base_skill_pool)
    effective_permission_context = PermissionContext(
        session_id=permission_context.session_id,
        mode=permission_context.mode,
        rules=permission_context.rules,
        metadata=dict(permission_context.metadata),
    )
    effective_memory = parent_policy.memory_scope if parent_policy is not None else None
    effective_isolation = (
        parent_policy.isolation_mode if parent_policy is not None else IsolationMode.NONE
    )
    return ExecutionPolicy(
        tool_pool=effective_tools,
        skill_pool=effective_skills,
        permission_context=effective_permission_context,
        memory_scope=effective_memory,
        isolation_mode=effective_isolation,
        trace={
            "source": "skill",
            "name": skill.name,
            "execution_context": skill.execution_context.value,
            "requested_allowed_tools": list(skill.allowed_tools),
            "effective_tools": [tool.name for tool in effective_tools],
            "effective_skills": [member.name for member in effective_skills],
            "effective_permission_mode": effective_permission_context.mode.value,
            "effective_memory_scope": effective_memory.value if effective_memory is not None else None,
            "effective_isolation_mode": effective_isolation.value,
        },
    )


def resolve_skill_pool(
    base_pool: Sequence[SkillDefinition],
    selectors: Sequence[str] | None,
) -> tuple[SkillDefinition, ...]:
    available = tuple(base_pool)
    if not selectors or selectors == ("*",):
        return available
    selected: list[SkillDefinition] = []
    for skill in available:
        if skill.name in selectors:
            selected.append(skill)
    return tuple(selected)


def policy_allows_skill(
    skill_name: str,
    pool: Sequence[SkillDefinition],
) -> bool:
    return any(skill.name == skill_name for skill in pool)


def serialize_policy(policy: ExecutionPolicy) -> dict[str, Any]:
    return {
        "tools": [tool.name for tool in policy.tool_pool],
        "skills": [skill.name for skill in policy.skill_pool],
        "permission_mode": policy.permission_context.mode.value,
        "memory_scope": policy.memory_scope.value if policy.memory_scope is not None else None,
        "isolation_mode": policy.isolation_mode.value,
        "trace": dict(policy.trace),
    }


def narrow_memory_scope(
    parent_scope: MemoryScope | None,
    requested_scope: MemoryScope | None,
) -> MemoryScope | None:
    if parent_scope is None:
        return requested_scope
    if requested_scope is None:
        return parent_scope
    return parent_scope if _MEMORY_ORDER[parent_scope] <= _MEMORY_ORDER[requested_scope] else requested_scope


def narrow_isolation_mode(
    parent_mode: IsolationMode | None,
    requested_mode: IsolationMode | None,
) -> IsolationMode:
    resolved_parent = parent_mode or IsolationMode.NONE
    resolved_requested = requested_mode or IsolationMode.NONE
    if _ISOLATION_ORDER[resolved_parent] >= _ISOLATION_ORDER[resolved_requested]:
        return resolved_parent
    return resolved_requested


def narrow_permission_mode(
    parent_mode: PermissionMode,
    requested_mode: PermissionMode | None,
) -> PermissionMode:
    if requested_mode is None:
        return parent_mode
    if parent_mode == PermissionMode.BYPASS_PERMISSIONS:
        return requested_mode
    if parent_mode in _DEFAULT_PERMISSION_MODES:
        if requested_mode == PermissionMode.BYPASS_PERMISSIONS:
            return parent_mode
        return requested_mode
    if parent_mode == PermissionMode.BUBBLE:
        if requested_mode in {PermissionMode.BUBBLE, PermissionMode.DONT_ASK}:
            return requested_mode
        return parent_mode
    if parent_mode == PermissionMode.DONT_ASK:
        return PermissionMode.DONT_ASK
    return requested_mode if requested_mode == parent_mode else parent_mode


def trace_policy_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    state = policy_state_from_metadata(metadata)
    if state is None:
        return None
    return state.snapshot()


def _narrow_tool_pool(
    *,
    base_pool: Sequence[ToolDefinition],
    allowed_tools: Sequence[str] | None = None,
    disallowed_tools: Sequence[str] | None = None,
) -> tuple[ToolDefinition, ...]:
    selected = list(base_pool)
    if allowed_tools:
        selected = [
            definition
            for definition in selected
            if any(_matches_tool_selector(definition, selector) for selector in allowed_tools)
        ]
    if disallowed_tools:
        selected = [
            definition
            for definition in selected
            if not any(_matches_tool_selector(definition, selector) for selector in disallowed_tools)
        ]
    deduped: dict[str, ToolDefinition] = {definition.name: definition for definition in selected}
    return tuple(sorted(deduped.values(), key=lambda definition: definition.name))


def _matches_tool_selector(definition: ToolDefinition, selector: str) -> bool:
    if selector == "*":
        return True
    if any(char in selector for char in "*?[]"):
        return any(_glob_match(candidate, selector) for candidate in (definition.name, *definition.aliases))
    return definition.matches(selector)


def _glob_match(candidate: str, selector: str) -> bool:
    from fnmatch import fnmatch

    return fnmatch(candidate, selector)


def serialize_runtime_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    if metadata is None:
        return serialized
    for key, value in metadata.items():
        if key == EXECUTION_POLICY_STATE_KEY:
            continue
        serialized[key] = _serialize_value(value)
    state = policy_state_from_metadata(metadata)
    if state is not None:
        serialized["policy"] = state.snapshot()
    return serialized


def _serialize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, PermissionContext):
        return {
            "session_id": value.session_id,
            "mode": value.mode.value,
            "rules": [rule.selector for rule in value.rules],
        }
    if isinstance(value, Mapping):
        return {str(key): _serialize_value(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    return str(value)

