from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .contracts import PromptContextEnvelope, RuntimeMessage, RuntimePrivateContext
from .definitions import AgentDefinition
from .execution_policy import policy_state_from_metadata
from .runtime_services import SidecarContributionResult
from .task_lists import (
    TASK_DISCIPLINE_EXTENSION_KEY,
    TASK_LIST_ID_EXTENSION_KEY,
    DefaultTaskListService,
    TaskDisciplinePolicy,
    TaskListStatus,
    coerce_private_context,
)

_TASK_TOOL_NAMES = frozenset({"task_create", "task_get", "task_update", "task_list"})


@dataclass(slots=True)
class _DisciplineState:
    turn_counter: int = 0
    last_touch_turn: int = 0
    last_reminder_turn: int = 0


@dataclass(slots=True)
class TaskDisciplineSidecar:
    task_lists: DefaultTaskListService
    _states: dict[tuple[str, str], _DisciplineState] = field(default_factory=dict, init=False)

    def record_task_touch(self, *, session_id: str, task_list_id: str) -> None:
        state = self._state_for(session_id=session_id, task_list_id=task_list_id)
        state.last_touch_turn = max(state.last_touch_turn, state.turn_counter)

    async def collect(
        self,
        *,
        session_id: str,
        turn_id: str,
        agent: AgentDefinition,
        cwd: str,
        messages: Sequence[RuntimeMessage],
        prompt_context: PromptContextEnvelope | None = None,
        private_context: RuntimePrivateContext | None = None,
        runtime_context: Mapping[str, Any] | None = None,
    ) -> SidecarContributionResult:
        _ = turn_id, agent, cwd, messages, prompt_context
        resolved_private = coerce_private_context(private_context or runtime_context)
        task_list_id = await self.task_lists.resolve_list_id(
            session_id=session_id,
            private_context=resolved_private,
        )
        state = self._state_for(session_id=session_id, task_list_id=task_list_id)
        state.turn_counter += 1

        policy = TaskDisciplinePolicy.resolve(
            private_context=resolved_private,
            runtime_metadata=runtime_context,
        )
        private_updates = {
            TASK_LIST_ID_EXTENSION_KEY: task_list_id,
            TASK_DISCIPLINE_EXTENSION_KEY: {
                "turn_counter": state.turn_counter,
                "last_touch_turn": state.last_touch_turn,
                "last_reminder_turn": state.last_reminder_turn,
                "strict_single_in_progress": policy.strict_single_in_progress,
                "reminder_turn_threshold": policy.reminder_turn_threshold,
            },
        }
        if not policy.enabled or not _task_tools_available(resolved_private, runtime_context):
            return SidecarContributionResult(private_updates=private_updates)

        snapshot = await self.task_lists.get_snapshot(task_list_id)
        remaining = [task for task in snapshot.tasks if task.status is not TaskListStatus.COMPLETED]
        if not remaining:
            return SidecarContributionResult(private_updates=private_updates)

        turns_since_touch = max(0, state.turn_counter - state.last_touch_turn)
        if turns_since_touch < policy.reminder_turn_threshold:
            return SidecarContributionResult(private_updates=private_updates)
        if state.last_reminder_turn and (
            state.turn_counter - state.last_reminder_turn < policy.reminder_turn_threshold
        ):
            return SidecarContributionResult(private_updates=private_updates)

        state.last_reminder_turn = state.turn_counter
        private_updates[TASK_DISCIPLINE_EXTENSION_KEY]["last_reminder_turn"] = state.last_reminder_turn
        return SidecarContributionResult(
            prompt_fragments=(
                _render_hidden_task_reminder(
                    task_list_id=task_list_id,
                    turns_since_touch=turns_since_touch,
                    remaining=remaining[: policy.reminder_task_limit],
                ),
            ),
            private_updates=private_updates,
        )

    def _state_for(self, *, session_id: str, task_list_id: str) -> _DisciplineState:
        key = (session_id, task_list_id)
        state = self._states.get(key)
        if state is None:
            state = _DisciplineState()
            self._states[key] = state
        return state


def _task_tools_available(
    private_context: RuntimePrivateContext,
    runtime_context: Mapping[str, Any] | None,
) -> bool:
    policy_state = private_context.policy_state or policy_state_from_metadata(runtime_context)
    if policy_state is None:
        return False
    return any(tool.name in _TASK_TOOL_NAMES for tool in policy_state.effective.tool_pool)


def _render_hidden_task_reminder(
    *,
    task_list_id: str,
    turns_since_touch: int,
    remaining: Sequence[Any],
) -> str:
    lines = [
        "Hidden runtime reminder: keep the shared planning task list current when it changes.",
        f"Resolved task_list_id: {task_list_id}",
        f"Task list has not been updated for {turns_since_touch} turn(s).",
        "Current unfinished tasks:",
    ]
    for task in remaining:
        owner = f" owner={task.owner}" if getattr(task, "owner", None) else ""
        lines.append(f"- [{task.status.value}] {task.subject}{owner}")
    return "\n".join(lines)


__all__ = ["TaskDisciplineSidecar"]
