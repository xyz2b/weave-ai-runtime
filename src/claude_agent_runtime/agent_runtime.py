from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from .contracts import MessageRole, RuntimeMessage
from .definitions import AgentDefinition, IsolationMode, SkillDefinition, ToolDefinition
from .registries import AgentRegistry, SkillRegistry, ToolRegistry
from .runtime_services import DefaultTaskService, RuntimeServices
from .tasking import TaskManager, TaskStatus
from .tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler, assemble_subagent_tool_pool
from .turn_engine.engine import TurnEngine


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    agent_name: str
    prompt: str
    session_id: str
    cwd: Path
    background: bool = False
    parent_tool_pool: tuple[ToolDefinition, ...] = ()
    parent_skill_pool: tuple[SkillDefinition, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentRunResult:
    agent_name: str
    status: str
    messages: list[RuntimeMessage] = field(default_factory=list)
    task_id: str | None = None
    background: bool = False
    isolation_mode: IsolationMode | None = None
    notification: RuntimeMessage | None = None


class IsolationAdapter:
    mode = IsolationMode.NONE

    def prepare(self, cwd: Path) -> Path:
        return cwd


class WorktreeIsolationAdapter(IsolationAdapter):
    mode = IsolationMode.WORKTREE


class RemoteIsolationAdapter(IsolationAdapter):
    mode = IsolationMode.REMOTE


class AgentRuntime:
    def __init__(
        self,
        *,
        turn_engine: TurnEngine,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        skill_registry: SkillRegistry,
        task_manager: TaskManager | None = None,
        runtime_services: RuntimeServices | None = None,
    ) -> None:
        self._turn_engine = turn_engine
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._runtime_services = runtime_services or RuntimeServices(
            tasks=DefaultTaskService(task_manager or TaskManager())
        )
        if task_manager is not None and self._runtime_services.task_manager is not task_manager:
            self._runtime_services.tasks = DefaultTaskService(task_manager)
        self._task_manager = self._runtime_services.task_manager
        self._skill_executor: Any = None
        self._background_tasks: dict[str, asyncio.Task[AgentRunResult]] = {}
        self._notifications: list[RuntimeMessage] = []

    @property
    def notifications(self) -> tuple[RuntimeMessage, ...]:
        return tuple(self._notifications)

    @property
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

    def bind_skill_executor(self, skill_executor: Any) -> None:
        self._skill_executor = skill_executor

    async def invoke(self, invocation: AgentInvocation) -> AgentRunResult:
        agent = self._resolve_agent(invocation.agent_name)
        if agent.name == "main-router":
            routed = await self._try_compat_route(invocation)
            if routed is not None:
                return routed

        if invocation.background or agent.background:
            return self._start_background(invocation, agent)
        return await self._run_agent(invocation, agent)

    async def wait_for_background(self, task_id: str) -> AgentRunResult:
        return await self._background_tasks[task_id]

    async def _try_compat_route(self, invocation: AgentInvocation) -> AgentRunResult | None:
        # These string-prefixed routes remain as a compatibility/debug surface.
        # The assembled turn engine is the primary execution path.
        stripped = invocation.prompt.strip()
        if stripped.startswith("/tool "):
            _, remainder = stripped.split(" ", 1)
            tool_name, raw_payload = remainder.split(" ", 1)
            payload = json.loads(raw_payload)
            scheduler = ToolScheduler(self._tool_registry)
            compat_message = RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.USER,
                content=invocation.prompt,
            )
            tool_pool = tuple(invocation.parent_tool_pool) or self._tool_registry.definitions()
            skill_pool = tuple(invocation.parent_skill_pool) or self._skill_registry.resolve_active()
            context = self._turn_engine.create_tool_context(
                session_id=invocation.session_id,
                turn_id=uuid4().hex,
                agent_name="main-router",
                cwd=invocation.cwd,
                messages=(compat_message,),
                tool_pool=tool_pool,
                skill_pool=skill_pool,
                metadata={**invocation.metadata, "compat_route": True},
            )
            result = await scheduler.run(
                [ToolCall(call_id=uuid4().hex, tool_name=tool_name, tool_input=payload)],
                context,
            )
            content = json.dumps(result[0].output, ensure_ascii=True) if result[0].status == ToolCallStatus.SUCCESS else result[0].error
            return AgentRunResult(
                agent_name="main-router",
                status="completed",
                messages=[
                    RuntimeMessage(
                        message_id=uuid4().hex,
                        role=MessageRole.TOOL,
                        content=content,
                    )
                ],
            )
        if stripped.startswith("/skill "):
            _, remainder = stripped.split(" ", 1)
            skill_name, *arguments = remainder.split()
            executor = self._skill_executor
            if executor is None:
                from .skill_runtime import SkillExecutor

                executor = SkillExecutor(skill_registry=self._skill_registry, agent_runtime=self)
            skill_result = await executor.execute(
                skill_name,
                arguments=arguments,
                session_id=invocation.session_id,
                cwd=invocation.cwd,
                parent_tool_pool=invocation.parent_tool_pool,
                parent_skill_pool=invocation.parent_skill_pool,
            )
            return AgentRunResult(
                agent_name="main-router",
                status="completed",
                messages=skill_result.injected_messages
                or (skill_result.agent_result.messages if skill_result.agent_result else []),
            )
        if stripped.startswith("/agent "):
            _, remainder = stripped.split(" ", 1)
            agent_name, prompt = remainder.split(" ", 1)
            return await self.invoke(
                AgentInvocation(
                    agent_name=agent_name,
                    prompt=prompt,
                    session_id=invocation.session_id,
                    cwd=invocation.cwd,
                    parent_tool_pool=invocation.parent_tool_pool,
                    parent_skill_pool=invocation.parent_skill_pool,
                    metadata={**invocation.metadata, "compat_route": True},
                )
            )
        return None

    def _start_background(self, invocation: AgentInvocation, agent: AgentDefinition) -> AgentRunResult:
        task_id = uuid4().hex
        self._task_manager.create(task_id, title=f"agent:{agent.name}", metadata={"agent": agent.name})

        async def runner() -> AgentRunResult:
            self._task_manager.update(task_id, status=TaskStatus.RUNNING)
            try:
                result = await self._run_agent(invocation, agent)
                self._task_manager.update(task_id, status=TaskStatus.COMPLETED)
                notification = RuntimeMessage(
                    message_id=uuid4().hex,
                    role=MessageRole.NOTIFICATION,
                    content=f"Background agent '{agent.name}' completed",
                    metadata={"task_id": task_id},
                )
                result.notification = notification
                self._notifications.append(notification)
                return result
            except Exception as exc:  # pragma: no cover - defensive boundary
                self._task_manager.update(task_id, status=TaskStatus.FAILED, error=str(exc))
                raise

        task = asyncio.create_task(runner())
        self._background_tasks[task_id] = task
        return AgentRunResult(
            agent_name=agent.name,
            status="running",
            task_id=task_id,
            background=True,
            isolation_mode=agent.isolation,
        )

    async def _run_agent(self, invocation: AgentInvocation, agent: AgentDefinition) -> AgentRunResult:
        effective_cwd = self._prepare_isolation(agent.isolation, invocation.cwd)
        effective_tools = self._resolve_tool_pool(agent, invocation.parent_tool_pool)
        effective_skills = self._resolve_skill_pool(agent, invocation.parent_skill_pool)
        effective_agent = replace(
            agent,
            tools=tuple(tool.name for tool in effective_tools),
            skills=tuple(skill.name for skill in effective_skills),
        )
        prompt_message = RuntimeMessage(
            message_id=uuid4().hex,
            role=MessageRole.USER,
            content=invocation.prompt,
        )
        turn_result = await self._turn_engine.run_turn(
            session_id=invocation.session_id,
            turn_id=uuid4().hex,
            agent=effective_agent,
            cwd=str(effective_cwd),
            messages=[prompt_message],
            base_system_prompt=invocation.metadata.get("system_prompt", ""),
            runtime_context={"agent_name": agent.name, "background": invocation.background},
        )
        return AgentRunResult(
            agent_name=agent.name,
            status="completed" if turn_result.completed else "max_turns",
            messages=turn_result.messages,
            background=invocation.background or agent.background,
            isolation_mode=agent.isolation,
        )

    def _resolve_agent(self, name: str) -> AgentDefinition:
        agent = self._agent_registry.get(name)
        if agent is None:
            raise KeyError(name)
        return agent

    def _resolve_tool_pool(
        self,
        agent: AgentDefinition,
        parent_pool: Sequence[ToolDefinition],
    ) -> tuple[ToolDefinition, ...]:
        if parent_pool:
            return assemble_subagent_tool_pool(
                self._tool_registry,
                parent_pool=parent_pool,
                allowed_tools=agent.tools or None,
                disallowed_tools=agent.disallowed_tools or None,
            )
        return assemble_subagent_tool_pool(
            self._tool_registry,
            parent_pool=self._tool_registry.definitions(),
            allowed_tools=agent.tools or None,
            disallowed_tools=agent.disallowed_tools or None,
        )

    def _resolve_skill_pool(
        self,
        agent: AgentDefinition,
        parent_pool: Sequence[SkillDefinition],
    ) -> tuple[SkillDefinition, ...]:
        available = tuple(parent_pool) if parent_pool else self._skill_registry.resolve_active()
        if not agent.skills or agent.skills == ("*",):
            return available
        selected = []
        for skill in available:
            if skill.name in agent.skills:
                selected.append(skill)
        return tuple(selected)

    def _prepare_isolation(self, mode: IsolationMode | None, cwd: Path) -> Path:
        adapter: IsolationAdapter
        if mode == IsolationMode.WORKTREE:
            adapter = WorktreeIsolationAdapter()
        elif mode == IsolationMode.REMOTE:
            adapter = RemoteIsolationAdapter()
        else:
            adapter = IsolationAdapter()
        return adapter.prepare(cwd)
