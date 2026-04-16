from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agent_dispatcher import AgentDispatcher
from .agent_execution import AgentExecutionSpec, AgentRunRecord, ChildRunStore, InMemoryChildRunStore, SpawnMode
from .agent_execution_service import AgentExecutionService
from .contracts import MessageRole, RuntimeMessage
from .definitions import IsolationMode, PermissionMode, SkillDefinition, ToolDefinition
from .execution_policy import policy_state_from_metadata
from .registries import AgentRegistry, SkillRegistry, ToolRegistry
from .runtime_services import DefaultTaskService, RuntimeServices
from .runtime_kernel.config import ModelRouteBinding
from .tasking import TaskManager
from .tool_runtime import ToolCall, ToolCallStatus, ToolScheduler
from .turn_engine.engine import TurnEngine


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    agent_name: str
    prompt: str
    session_id: str
    cwd: Path
    background: bool = False
    query_source: str | None = None
    spawn_mode: SpawnMode | None = None
    parent_run_id: str | None = None
    parent_turn_id: str | None = None
    requested_model_route: str | None = None
    requested_model: str | None = None
    requested_permission_mode: PermissionMode | None = None
    requested_isolation: IsolationMode | None = None
    max_turns: int | None = None
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
    run_id: str | None = None
    parent_run_id: str | None = None
    turn_id: str | None = None
    query_source: str | None = None
    execution_spec: AgentExecutionSpec | None = None
    run_record: AgentRunRecord | None = None


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
        run_store: ChildRunStore | None = None,
        model_routes: dict[str, ModelRouteBinding] | None = None,
        default_model_route: str | None = None,
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
        self._run_store = run_store or InMemoryChildRunStore()
        self._execution_service = AgentExecutionService(
            turn_engine=turn_engine,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            runtime_services=self._runtime_services,
            run_store=self._run_store,
            model_routes=model_routes,
            default_model_route=default_model_route,
        )
        self._dispatcher = AgentDispatcher(
            execution_service=self._execution_service,
            runtime_services=self._runtime_services,
        )
        self._skill_executor: Any = None

    @property
    def notifications(self) -> tuple[RuntimeMessage, ...]:
        return self._dispatcher.notifications

    @property
    def runtime_services(self) -> RuntimeServices:
        return self._runtime_services

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    @property
    def run_store(self) -> ChildRunStore:
        return self._run_store

    def bind_skill_executor(self, skill_executor: Any) -> None:
        self._skill_executor = skill_executor

    async def invoke(self, invocation: AgentInvocation) -> AgentRunResult:
        agent = self._dispatcher.resolve_agent(invocation.agent_name)
        execution_spec = self._dispatcher.build_execution_spec(invocation, agent)
        if agent.name == "main-router":
            routed = await self._try_compat_route(invocation, execution_spec)
            if routed is not None:
                return routed
        return await self._dispatcher.dispatch(
            invocation,
            agent=agent,
            execution_spec=execution_spec,
        )

    async def wait_for_background(self, task_id: str) -> AgentRunResult:
        return await self._dispatcher.wait_for_background(task_id)

    async def _try_compat_route(
        self,
        invocation: AgentInvocation,
        execution_spec: AgentExecutionSpec,
    ) -> AgentRunResult | None:
        # These string-prefixed routes remain as a compatibility/debug surface.
        # The assembled dispatcher/execution service path is the primary runtime path.
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
                metadata={
                    **invocation.metadata,
                    "compat_route": True,
                    "run_id": execution_spec.run_id,
                    "parent_run_id": execution_spec.parent_run_id,
                    "turn_id": execution_spec.turn_id,
                    "parent_turn_id": execution_spec.parent_turn_id,
                    "spawn_mode": execution_spec.spawn_mode.value,
                    "query_source": execution_spec.query_source,
                },
            )
            result = await scheduler.run(
                [ToolCall(call_id=uuid4().hex, tool_name=tool_name, tool_input=payload)],
                context,
            )
            content = (
                json.dumps(result[0].output, ensure_ascii=True)
                if result[0].status == ToolCallStatus.SUCCESS
                else result[0].error
            )
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
                permission_context=invocation.metadata.get("permission_context"),
                turn_id=execution_spec.turn_id,
                parent_run_id=execution_spec.run_id,
                policy_state=policy_state_from_metadata(invocation.metadata),
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
                    query_source="compat_agent_route",
                    parent_run_id=execution_spec.run_id,
                    parent_turn_id=execution_spec.turn_id,
                    parent_tool_pool=invocation.parent_tool_pool,
                    parent_skill_pool=invocation.parent_skill_pool,
                    metadata={**invocation.metadata, "compat_route": True},
                )
            )
        return None
