from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from ..contracts import MessageAttachment, MessageRole, RuntimeMessage
from ..definitions import AgentDefinition
from ..registries import AgentRegistry, SkillRegistry, ToolRegistry
from ..tool_runtime import (
    ToolCall,
    ToolContext,
    ToolScheduler,
    assemble_main_thread_tool_pool,
)
from .composer import PromptComposer
from .models import ModelClient, ModelRequest, ModelStreamEventType
from ..tasking import TaskManager


@dataclass(slots=True)
class TurnResult:
    messages: list[RuntimeMessage] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    iterations: int = 0
    completed: bool = False


class TurnEngine:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        prompt_composer: PromptComposer | None = None,
        permission_handler=None,
        ask_user_handler=None,
        agent_runner=None,
        skill_runner=None,
        task_manager: TaskManager | None = None,
    ) -> None:
        self._model_client = model_client
        self._tool_registry = tool_registry
        self._agent_registry = agent_registry
        self._skill_registry = skill_registry
        self._prompt_composer = prompt_composer or PromptComposer()
        self._permission_handler = permission_handler
        self._ask_user_handler = ask_user_handler
        self._agent_runner = agent_runner
        self._skill_runner = skill_runner
        self._task_manager = task_manager or TaskManager()
        self._active_scheduler: ToolScheduler | None = None
        self._active_tool_context: ToolContext | None = None

    def interrupt(self, reason: str = "interrupt") -> None:
        if self._active_tool_context is not None:
            self._active_tool_context.request_interrupt(reason)
        if self._active_scheduler is not None:
            self._active_scheduler.interrupt(reason)

    async def run_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: list[RuntimeMessage],
        base_system_prompt: str,
        memory_fragments: list[str] | None = None,
        hook_context: list[str] | None = None,
        attachments: list[MessageAttachment] | None = None,
        runtime_context: dict[str, object] | None = None,
    ) -> TurnResult:
        result = TurnResult()
        max_iterations = agent.max_turns or 4
        working_messages = list(messages)
        iteration = 0

        while iteration < max_iterations:
            tool_pool = assemble_main_thread_tool_pool(
                self._tool_registry,
                allowed_tools=agent.tools or None,
                disallowed_tools=agent.disallowed_tools or None,
            )
            active_skills = self._skill_registry.resolve_active() if self._skill_registry is not None else ()

            composition = self._prompt_composer.compose(
                session_id=session_id,
                turn_id=turn_id,
                agent=agent,
                cwd=cwd,
                messages=working_messages,
                available_tools=[tool.name for tool in tool_pool],
                available_skills=[skill.name for skill in active_skills],
                base_system_prompt=base_system_prompt,
                memory_fragments=memory_fragments or (),
                hook_context=hook_context or (),
                attachments=attachments or (),
                runtime_context=runtime_context or {},
            )
            request = ModelRequest(
                system_prompt=composition.system_prompt,
                turn_context=composition.turn_context,
                messages=composition.messages,
                tools=tool_pool,
                skills=active_skills,
                agent=agent,
                model=agent.model,
                effort=agent.effort,
            )

            assistant_chunks: list[str] = []
            tool_calls: list[ToolCall] = []
            async for event in self._model_client.stream(request):
                if event.event_type == ModelStreamEventType.CONTENT_DELTA:
                    assistant_chunks.append(str(event.payload.get("text", "")))
                elif event.event_type == ModelStreamEventType.TOOL_CALL:
                    tool_calls.append(
                        ToolCall(
                            call_id=str(event.payload.get("call_id", uuid4().hex)),
                            tool_name=str(event.payload["tool_name"]),
                            tool_input=dict(event.payload.get("tool_input", {})),
                        )
                    )

            assistant_message = RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.ASSISTANT,
                content="".join(assistant_chunks),
                metadata={"tool_calls": [call.tool_name for call in tool_calls]},
            )
            working_messages.append(assistant_message)
            result.messages.append(assistant_message)
            result.tool_calls.extend(tool_calls)

            if not tool_calls:
                result.iterations = iteration + 1
                result.completed = True
                return result

            tool_context = ToolContext(
                session_id=session_id,
                turn_id=turn_id,
                agent_name=agent.name,
                cwd=Path(composition.turn_context.cwd),
                tool_registry=self._tool_registry,
                agent_registry=self._agent_registry,
                skill_registry=self._skill_registry,
                permission_handler=self._permission_handler,
                ask_user_handler=self._ask_user_handler,
                agent_runner=self._agent_runner,
                skill_runner=self._skill_runner,
                task_manager=self._task_manager,
            )
            self._active_tool_context = tool_context
            self._active_scheduler = ToolScheduler(self._tool_registry)
            tool_results = await self._active_scheduler.run(tool_calls, tool_context)
            self._active_scheduler = None
            self._active_tool_context = None

            for tool_result in tool_results:
                tool_message = RuntimeMessage(
                    message_id=uuid4().hex,
                    role=MessageRole.TOOL,
                    content=json.dumps(
                        {
                            "tool_name": tool_result.tool_name,
                            "status": tool_result.status.value,
                            "output": tool_result.output,
                            "error": tool_result.error,
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                )
                working_messages.append(tool_message)
                result.messages.append(tool_message)

            iteration += 1

        result.iterations = iteration
        result.completed = False
        return result
