from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .agent_execution import SpawnMode
from .agent_runtime import AgentInvocation, AgentRunResult, AgentRuntime
from .control_plane import RuntimeControlPlaneContext
from .contracts import (
    MessageRole,
    RuntimeMessage,
    SkillRequestOverrideState,
)
from .definitions import (
    DefinitionSource,
    PermissionBehavior,
    PermissionDecision,
    SkillDefinition,
    SkillExecutionContext,
    SkillShell,
    ToolCallStatus,
)
from .execution_policy import (
    DELEGATION_DEPTH_METADATA_KEY,
    EXECUTION_POLICY_STATE_KEY,
    ExecutionPolicyState,
    delegation_depth_from_metadata,
    policy_allows_skill,
    resolve_skill_execution_policy,
    serialize_policy,
)
from .hosts.base import CallbackHostAdapter, NullHostAdapter
from .permissions import PermissionContext, PermissionRequest, PermissionTarget
from .registries import SkillRegistry
from .runtime_services import RuntimeServices
from .tool_runtime import ToolCall, ToolContext, execute_tool_call


@dataclass(slots=True)
class SkillExecutionResult:
    skill_name: str
    mode: SkillExecutionContext
    injected_messages: list[RuntimeMessage] = field(default_factory=list)
    agent_result: AgentRunResult | None = None
    request_override: SkillRequestOverrideState | None = None


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
        parent_run_id: str | None = None,
        policy_state: ExecutionPolicyState | None = None,
        runtime_metadata: Mapping[str, Any] | None = None,
    ) -> SkillExecutionResult:
        parent_policy = policy_state.effective if policy_state is not None else None
        available_skills = (
            tuple(parent_skill_pool)
            if parent_skill_pool
            else (parent_policy.skill_pool if parent_policy is not None else self._skill_registry.resolve_active())
        )
        skill = self._resolve_skill(skill_name, available_skills)
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
        expanded = await self._expand_skill_content(
            skill,
            session_id=session_id,
            arguments=arguments,
            cwd=cwd,
            turn_id=turn_id,
            policy_state=resolved_policy,
        )
        if skill.execution_context == SkillExecutionContext.FORK:
            hook_owner = self._skill_hook_owner(skill.name)
            agent_result = await self._agent_runtime.invoke(
                AgentInvocation(
                    agent_name=skill.agent or "general-purpose",
                    prompt=expanded,
                    session_id=session_id,
                    cwd=cwd,
                    query_source="skill_fork",
                    spawn_mode=SpawnMode.FORK,
                    parent_run_id=parent_run_id,
                    parent_turn_id=turn_id,
                    requested_model=skill.model,
                    requested_effort=skill.effort,
                    parent_tool_pool=resolved_policy.tool_pool,
                    parent_skill_pool=resolved_policy.skill_pool,
                    metadata={
                        "permission_context": resolved_policy.permission_context,
                        EXECUTION_POLICY_STATE_KEY: ExecutionPolicyState(resolved_policy),
                        DELEGATION_DEPTH_METADATA_KEY: delegation_depth_from_metadata(runtime_metadata),
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
                request_override=_skill_request_override(skill),
            )
        finally:
            if release_owner and hook_owner is not None:
                self._runtime_services.hook_bus.release_owner(session_id, hook_owner)

    def _resolve_skill(
        self,
        skill_name: str,
        available_skills: Sequence[SkillDefinition],
    ) -> SkillDefinition:
        for skill in available_skills:
            if skill.name == skill_name:
                return skill
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
        runtime_context = RuntimeControlPlaneContext(
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

    async def _expand_skill_content(
        self,
        skill: SkillDefinition,
        *,
        session_id: str,
        arguments: Sequence[str],
        cwd: Path,
        turn_id: str | None,
        policy_state: Any,
    ) -> str:
        expander = _SkillPromptExpander(
            runtime_services=self._runtime_services,
            agent_runtime=self._agent_runtime,
        )
        return await expander.expand(
            skill,
            session_id=session_id,
            arguments=arguments,
            cwd=cwd,
            turn_id=turn_id,
            policy_state=policy_state,
        )


class _SkillPromptExpander:
    _ARG_RANGE_PATTERN = re.compile(r"\$\{ARG(\d+)\.\.\.\}")
    _ARG_PATTERN = re.compile(r"\$\{ARG(\d+)\}")
    _FENCED_PATTERN = re.compile(
        r"```(?P<lang>bash|sh|shell|powershell|pwsh)?\n(?P<body>.*?)```",
        re.DOTALL,
    )
    _INLINE_PATTERN = re.compile(r"(?m)^(?P<indent>[ \t]*)!(?P<body>[^\n]+)$")

    def __init__(
        self,
        *,
        runtime_services: RuntimeServices,
        agent_runtime: AgentRuntime,
    ) -> None:
        self._runtime_services = runtime_services
        self._agent_runtime = agent_runtime

    async def expand(
        self,
        skill: SkillDefinition,
        *,
        session_id: str,
        arguments: Sequence[str],
        cwd: Path,
        turn_id: str | None,
        policy_state: Any,
    ) -> str:
        expanded = self._substitute_variables(
            skill,
            session_id=session_id,
            arguments=arguments,
        )
        if "!" not in expanded and "```" not in expanded:
            return expanded
        if not _is_local_file_backed_skill(skill):
            raise RuntimeError("Skill shell expansion is only supported for local file-backed skills")
        expanded = await self._expand_fenced_blocks(
            expanded,
            skill=skill,
            cwd=cwd,
            turn_id=turn_id,
            policy_state=policy_state,
        )
        expanded = await self._expand_inline_blocks(
            expanded,
            skill=skill,
            cwd=cwd,
            turn_id=turn_id,
            policy_state=policy_state,
        )
        return expanded

    def _substitute_variables(
        self,
        skill: SkillDefinition,
        *,
        session_id: str,
        arguments: Sequence[str],
    ) -> str:
        expanded = skill.content.replace("${CLAUDE_SESSION_ID}", session_id)
        expanded = expanded.replace("$ARGUMENTS", " ".join(arguments))
        expanded = self._ARG_RANGE_PATTERN.sub(
            lambda match: " ".join(arguments[int(match.group(1)) - 1 :]),
            expanded,
        )
        expanded = self._ARG_PATTERN.sub(
            lambda match: _argument_at(arguments, int(match.group(1))),
            expanded,
        )
        if skill.origin.path is not None:
            expanded = expanded.replace("${CLAUDE_SKILL_DIR}", str(skill.origin.path.parent))
        return expanded

    async def _expand_fenced_blocks(
        self,
        content: str,
        *,
        skill: SkillDefinition,
        cwd: Path,
        turn_id: str | None,
        policy_state: Any,
    ) -> str:
        pieces: list[str] = []
        last_index = 0
        for match in self._FENCED_PATTERN.finditer(content):
            pieces.append(content[last_index : match.start()])
            shell = _shell_from_language(match.group("lang")) or skill.shell or SkillShell.BASH
            pieces.append(
                await self._run_shell_block(
                    skill,
                    command=match.group("body").strip(),
                    shell=shell,
                    cwd=cwd,
                    turn_id=turn_id,
                    policy_state=policy_state,
                )
            )
            last_index = match.end()
        pieces.append(content[last_index:])
        return "".join(pieces)

    async def _expand_inline_blocks(
        self,
        content: str,
        *,
        skill: SkillDefinition,
        cwd: Path,
        turn_id: str | None,
        policy_state: Any,
    ) -> str:
        pieces: list[str] = []
        last_index = 0
        for match in self._INLINE_PATTERN.finditer(content):
            pieces.append(content[last_index : match.start()])
            replacement = await self._run_shell_block(
                skill,
                command=match.group("body").strip(),
                shell=skill.shell or SkillShell.BASH,
                cwd=cwd,
                turn_id=turn_id,
                policy_state=policy_state,
            )
            indentation = match.group("indent") or ""
            if replacement:
                lines = replacement.splitlines()
                pieces.append("\n".join(f"{indentation}{line}" for line in lines))
            last_index = match.end()
        pieces.append(content[last_index:])
        return "".join(pieces)

    async def _run_shell_block(
        self,
        skill: SkillDefinition,
        *,
        command: str,
        shell: SkillShell,
        cwd: Path,
        turn_id: str | None,
        policy_state: Any,
    ) -> str:
        if not command:
            return ""
        bash_definition = self._agent_runtime.tool_registry.get("bash")
        if bash_definition is None:
            raise RuntimeError("Skill shell expansion requires the bash tool")
        if not any(definition.matches("bash") for definition in policy_state.tool_pool):
            raise RuntimeError("Skill shell expansion is not available in the current execution policy")
        tool_context = ToolContext(
            session_id=str(policy_state.permission_context.session_id),
            turn_id=turn_id or uuid4().hex,
            agent_name="skill-runtime",
            cwd=cwd,
            tool_registry=self._agent_runtime.tool_registry,
            skill_registry=self._agent_runtime.skill_registry,
            tool_pool=tuple(policy_state.tool_pool),
            skill_pool=tuple(policy_state.skill_pool),
            runtime_services=self._runtime_services,
            permission_context=policy_state.permission_context,
            metadata={
                "permission_context": policy_state.permission_context,
                EXECUTION_POLICY_STATE_KEY: ExecutionPolicyState(policy_state),
                "query_source": "skill_prompt_expansion",
            },
        )
        result = await execute_tool_call(
            bash_definition,
            ToolCall(
                call_id=f"skill-shell-{uuid4().hex}",
                tool_name="bash",
                tool_input={
                    "command": command,
                    "cwd": str(cwd),
                    "shell": shell.value,
                },
            ),
            tool_context,
        )
        if result.status != ToolCallStatus.SUCCESS:
            raise RuntimeError(result.error or "Skill shell expansion failed")
        output = result.output if isinstance(result.output, dict) else {}
        stdout = str(output.get("stdout") or "")
        stderr = str(output.get("stderr") or "")
        exit_code = int(output.get("exit_code", 0) or 0)
        if exit_code != 0:
            raise RuntimeError(stderr or stdout or "Skill shell expansion failed")
        return stdout.rstrip("\n")


def _skill_request_override(skill: SkillDefinition) -> SkillRequestOverrideState | None:
    state = SkillRequestOverrideState(
        requested_model=skill.model,
        requested_effort=skill.effort,
        source_skill=skill.name if skill.model is not None or skill.effort is not None else None,
    )
    return state if state else None


def _argument_at(arguments: Sequence[str], index: int) -> str:
    resolved = index - 1
    if resolved < 0 or resolved >= len(arguments):
        return ""
    return arguments[resolved]


def _shell_from_language(value: str | None) -> SkillShell | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"bash", "sh", "shell"}:
        return SkillShell.BASH
    if normalized in {"powershell", "pwsh"}:
        return SkillShell.POWERSHELL
    return None


def _is_local_file_backed_skill(skill: SkillDefinition) -> bool:
    return skill.origin.path is not None and skill.origin.source in {
        DefinitionSource.USER,
        DefinitionSource.PROJECT,
    }

def _supports_permission_requests(host: Any) -> bool:
    if isinstance(host, CallbackHostAdapter):
        return host.permission_handler is not None
    if type(host) is NullHostAdapter:
        return False
    return True
