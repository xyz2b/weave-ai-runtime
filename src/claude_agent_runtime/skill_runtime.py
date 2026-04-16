from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from .agent_runtime import AgentInvocation, AgentRunResult, AgentRuntime
from .contracts import MessageRole, RuntimeMessage
from .definitions import PermissionBehavior, PermissionDecision, SkillDefinition, SkillExecutionContext
from .execution_policy import (
    EXECUTION_POLICY_STATE_KEY,
    ExecutionPolicyState,
    policy_allows_skill,
    resolve_skill_execution_policy,
    serialize_policy,
)
from .hosts.base import CallbackHostAdapter, NullHostAdapter
from .permissions import PermissionContext, PermissionRequest, PermissionTarget
from .registries import SkillRegistry
from .runtime_services import RuntimeServices


@dataclass(slots=True)
class SkillExecutionResult:
    skill_name: str
    mode: SkillExecutionContext
    injected_messages: list[RuntimeMessage] = field(default_factory=list)
    agent_result: AgentRunResult | None = None


class SkillExecutor:
    def __init__(
        self,
        *,
        skill_registry: SkillRegistry,
        agent_runtime: AgentRuntime,
        runtime_services: RuntimeServices | None = None,
    ) -> None:
        self._skill_registry = skill_registry
        self._agent_runtime = agent_runtime
        self._runtime_services = runtime_services or agent_runtime.runtime_services

    @property
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

    async def execute(
        self,
        skill_name: str,
        *,
        arguments: Sequence[str],
        session_id: str,
        cwd: Path,
        parent_tool_pool=(),
        parent_skill_pool=(),
        permission_context: PermissionContext | None = None,
        turn_id: str | None = None,
        policy_state: ExecutionPolicyState | None = None,
    ) -> SkillExecutionResult:
        skill = self._resolve_skill(skill_name)
        parent_policy = policy_state.effective if policy_state is not None else None
        available_skills = (
            tuple(parent_skill_pool)
            if parent_skill_pool
            else (parent_policy.skill_pool if parent_policy is not None else self._skill_registry.resolve_active())
        )
        if (parent_policy is not None or parent_skill_pool) and not policy_allows_skill(skill.name, available_skills):
            raise PermissionError(f"Skill '{skill.name}' is not available in the current execution policy")
        resolved_permission_context = (
            permission_context
            or (parent_policy.permission_context if parent_policy is not None else PermissionContext(session_id=session_id))
        )
        base_tool_pool = (
            tuple(parent_tool_pool)
            if parent_tool_pool
            else (
                parent_policy.tool_pool
                if parent_policy is not None
                else self._agent_runtime.tool_registry.definitions()
            )
        )
        resolved_policy = resolve_skill_execution_policy(
            skill,
            parent_policy=parent_policy,
            base_tool_pool=base_tool_pool,
            base_skill_pool=available_skills,
            permission_context=resolved_permission_context,
        )
        await self._authorize_skill(
            skill,
            arguments=arguments,
            session_id=session_id,
            permission_context=resolved_policy.permission_context,
        )
        expanded = self._expand_skill_content(skill, session_id=session_id, arguments=arguments)
        if skill.execution_context == SkillExecutionContext.FORK:
            hook_owner = self._skill_hook_owner(skill.name)
            agent_result = await self._agent_runtime.invoke(
                AgentInvocation(
                    agent_name=skill.agent or "general-purpose",
                    prompt=expanded,
                    session_id=session_id,
                    cwd=cwd,
                    parent_tool_pool=resolved_policy.tool_pool,
                    parent_skill_pool=resolved_policy.skill_pool,
                    metadata={
                        "permission_context": resolved_policy.permission_context,
                        EXECUTION_POLICY_STATE_KEY: ExecutionPolicyState(resolved_policy),
                        "skill_hooks": dict(skill.hooks),
                        "skill_hook_owner": hook_owner,
                        "skill_policy_trace": dict(resolved_policy.trace),
                    },
                )
            )
            return SkillExecutionResult(
                skill_name=skill.name,
                mode=skill.execution_context,
                agent_result=agent_result,
            )

        hook_owner: str | None = None
        release_owner = False
        if skill.hooks:
            hook_owner = self._register_skill_hooks(
                skill,
                session_id=session_id,
                turn_id=turn_id,
            )
            release_owner = turn_id is None
        try:
            return SkillExecutionResult(
                skill_name=skill.name,
                mode=skill.execution_context,
                injected_messages=self._complete_inline_execution(
                    skill,
                    expanded=expanded,
                    policy_state=policy_state,
                    resolved_policy=resolved_policy,
                ),
            )
        finally:
            if release_owner and hook_owner is not None:
                self._runtime_services.hook_bus.release_owner(session_id, hook_owner)

    def _resolve_skill(self, skill_name: str) -> SkillDefinition:
        skill = self._skill_registry.get(skill_name)
        if skill is None:
            raise KeyError(skill_name)
        return skill

    async def _authorize_skill(
        self,
        skill: SkillDefinition,
        *,
        arguments: Sequence[str],
        session_id: str,
        permission_context: PermissionContext | None,
    ) -> None:
        initial = PermissionDecision(
            PermissionBehavior.ASK
            if (skill.execution_context == SkillExecutionContext.FORK or skill.hooks)
            and _supports_permission_requests(self._runtime_services.host)
            else PermissionBehavior.ALLOW
        )
        request = PermissionRequest(
            session_id=session_id,
            turn_id=None,
            target=PermissionTarget.SKILL,
            name=skill.name,
            payload={"arguments": list(arguments)},
            context=permission_context,
            message=f"Skill '{skill.name}' requires permission",
        )
        runtime_context = _PermissionRuntimeContext(
            runtime_services=self._runtime_services,
            permission_context=permission_context,
        )
        outcome = await self._runtime_services.permissions.evaluate(  # type: ignore[attr-defined]
            request,
            initial_decision=initial,
            runtime_context=runtime_context,
        )
        if outcome.behavior != PermissionBehavior.ALLOW:
            raise PermissionError(outcome.message or f"Skill '{skill.name}' was denied")

    def _register_skill_hooks(
        self,
        skill: SkillDefinition,
        *,
        session_id: str,
        turn_id: str | None,
    ) -> str:
        if not skill.hooks:
            return ""
        owner = self._skill_hook_owner(skill.name)
        self._runtime_services.hook_bus.register_handlers(
            session_id=session_id,
            owner=owner,
            hooks=skill.hooks,
            turn_id=turn_id,
        )
        return owner

    @staticmethod
    def _skill_hook_owner(skill_name: str) -> str:
        return f"skill:{skill_name}:{uuid4().hex}"

    @staticmethod
    def _complete_inline_execution(
        skill: SkillDefinition,
        *,
        expanded: str,
        policy_state: ExecutionPolicyState | None,
        resolved_policy: Any,
    ) -> list[RuntimeMessage]:
        if policy_state is not None:
            policy_state.apply(resolved_policy)
        return [
            RuntimeMessage(
                message_id=f"skill-{skill.name}",
                role=MessageRole.SYSTEM,
                content=expanded,
                metadata={"skill": skill.name, "policy": serialize_policy(resolved_policy)},
            )
        ]

    @staticmethod
    def _expand_skill_content(
        skill: SkillDefinition,
        *,
        session_id: str,
        arguments: Sequence[str],
    ) -> str:
        expanded = skill.content.replace("${CLAUDE_SESSION_ID}", session_id)
        expanded = expanded.replace("$ARGUMENTS", " ".join(arguments))
        for index, argument in enumerate(arguments, start=1):
            expanded = expanded.replace(f"${{ARG{index}}}", argument)
        if skill.origin.path is not None:
            expanded = expanded.replace("${CLAUDE_SKILL_DIR}", str(skill.origin.path.parent))
        return expanded


@dataclass(frozen=True, slots=True)
class _PermissionRuntimeContext:
    runtime_services: RuntimeServices
    permission_context: PermissionContext | None = None


def _supports_permission_requests(host: Any) -> bool:
    if isinstance(host, CallbackHostAdapter):
        return host.permission_handler is not None
    if type(host) is NullHostAdapter:
        return False
    return True
