from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .agent_runtime import AgentInvocation, AgentRunResult, AgentRuntime
from .contracts import MessageRole, RuntimeMessage
from .definitions import SkillDefinition, SkillExecutionContext
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
    ) -> SkillExecutionResult:
        skill = self._resolve_skill(skill_name)
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
