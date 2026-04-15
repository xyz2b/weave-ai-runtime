from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .agent_runtime import AgentInvocation, AgentRunResult, AgentRuntime
from .contracts import MessageRole, RuntimeMessage
from .definitions import PermissionBehavior, PermissionDecision, SkillDefinition, SkillExecutionContext
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
    ) -> SkillExecutionResult:
        skill = self._resolve_skill(skill_name)
        await self._authorize_skill(
            skill,
            arguments=arguments,
            session_id=session_id,
            permission_context=permission_context,
        )
        self._register_skill_hooks(skill, session_id=session_id)
        expanded = self._expand_skill_content(skill, session_id=session_id, arguments=arguments)
        if skill.execution_context == SkillExecutionContext.FORK:
            agent_result = await self._agent_runtime.invoke(
                AgentInvocation(
                    agent_name=skill.agent or "general-purpose",
                    prompt=expanded,
                    session_id=session_id,
                    cwd=cwd,
                    parent_tool_pool=tuple(parent_tool_pool),
                    parent_skill_pool=tuple(parent_skill_pool),
                    metadata={"permission_context": permission_context} if permission_context is not None else {},
                )
            )
            return SkillExecutionResult(
                skill_name=skill.name,
                mode=skill.execution_context,
                agent_result=agent_result,
            )

        return SkillExecutionResult(
            skill_name=skill.name,
            mode=skill.execution_context,
            injected_messages=[
                RuntimeMessage(
                    message_id=f"skill-{skill.name}",
                    role=MessageRole.SYSTEM,
                    content=expanded,
                    metadata={"skill": skill.name},
                )
            ],
        )

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

    def _register_skill_hooks(self, skill: SkillDefinition, *, session_id: str) -> None:
        if not skill.hooks:
            return
        owner = f"skill:{skill.name}"
        self._runtime_services.hook_bus.release_owner(session_id, owner)
        self._runtime_services.hook_bus.register_handlers(
            session_id=session_id,
            owner=owner,
            hooks=skill.hooks,
        )

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
