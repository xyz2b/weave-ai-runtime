from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from ..contracts import MessageAttachment, MessageRole, RuntimeMessage, TextBlock, ToolResultBlock, ToolUseBlock
from ..definitions import AgentDefinition
from ..registries import AgentRegistry, SkillRegistry, ToolRegistry
from ..tool_runtime import (
    ToolCall,
    ToolCallResult,
    ToolCallStatus,
    ToolContext,
    ToolScheduler,
    assemble_main_thread_tool_pool,
)
from .composer import PromptComposer
from .message_protocol import normalize_messages_for_api
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
            api_messages = normalize_messages_for_api(working_messages)
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
                messages=api_messages,
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

            assistant_blocks: list[object] = []
            tool_calls: list[ToolCall] = []
            async for event in self._model_client.stream(request):
                if event.event_type == ModelStreamEventType.CONTENT_DELTA:
                    _append_text_block(assistant_blocks, str(event.payload.get("text", "")))
                elif event.event_type == ModelStreamEventType.TOOL_CALL:
                    call = ToolCall(
                        call_id=str(event.payload.get("call_id", uuid4().hex)),
                        tool_name=str(event.payload["tool_name"]),
                        tool_input=dict(event.payload.get("tool_input", {})),
                    )
                    tool_calls.append(call)
                    assistant_blocks.append(
                        ToolUseBlock(
                            tool_use_id=call.call_id,
                            name=call.tool_name,
                            input=call.tool_input,
                        )
                    )

            assistant_message = RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.ASSISTANT,
                content=tuple(assistant_blocks),
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

            tool_result_blocks = tuple(_tool_result_block(tool_result) for tool_result in tool_results)
            if tool_result_blocks:
                tool_message = RuntimeMessage(
                    message_id=uuid4().hex,
                    role=MessageRole.USER,
                    content=tool_result_blocks,
                    metadata={
                        "tool_results": [
                            {
                                "tool_use_id": tool_result.call_id,
                                "tool_name": tool_result.tool_name,
                                "status": tool_result.status.value,
                            }
                            for tool_result in tool_results
                        ]
                    },
                )
                working_messages.append(tool_message)
                result.messages.append(tool_message)

            iteration += 1

        result.iterations = iteration
        result.completed = False
        return result


def _append_text_block(blocks: list[object], text: str) -> None:
    if not text:
        return
    if blocks and isinstance(blocks[-1], TextBlock):
        previous = blocks[-1]
        blocks[-1] = TextBlock(text=previous.text + text)
        return
    blocks.append(TextBlock(text=text))


def _tool_result_block(tool_result: ToolCallResult) -> ToolResultBlock:
    if tool_result.status == ToolCallStatus.SUCCESS:
        content = tool_result.output
    else:
        content = tool_result.error or ""
    return ToolResultBlock(
        tool_use_id=tool_result.call_id,
        content=content,
        is_error=tool_result.status != ToolCallStatus.SUCCESS,
    )
