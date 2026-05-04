from __future__ import annotations

from typing import Any, Sequence

from ..contracts import RuntimeMessage, ToolResultBlock
from ..result_projections import (
    ChildSummaryMatcher,
    ChildSummaryProjection,
    SkillOutcomeMatcher,
    SkillOutcomeProjection,
    ToolOutcomeMatcher,
    ToolOutcomeProjection,
    child_summary,
    latest_skill_outcome,
    latest_tool_outcome,
    terminal_failure,
)



def assert_tool_outcome(
    source: Any,
    tool_name: str,
    *,
    matcher: ToolOutcomeMatcher | None = None,
) -> ToolOutcomeProjection:
    projection = latest_tool_outcome(source, tool_name, matcher=matcher)
    if projection is None:
        detail = " matching the provided predicate" if matcher is not None else ""
        raise AssertionError(f"Expected tool outcome for '{tool_name}'{detail}.")
    return projection



def assert_tool_result(source: Any, tool_use_id: str) -> Any:
    messages = _messages_from_source(source)
    for message in messages:
        for block in message.content:
            if isinstance(block, ToolResultBlock) and block.tool_use_id == tool_use_id:
                return block.content
    raise AssertionError(f"Missing tool result for '{tool_use_id}'.")



def extract_tool_result(source: Any, tool_use_id: str) -> Any:
    return assert_tool_result(source, tool_use_id)



def assert_skill_outcome(
    source: Any,
    skill_name: str | None = None,
    *,
    matcher: SkillOutcomeMatcher | None = None,
) -> SkillOutcomeProjection:
    projection = latest_skill_outcome(source, skill_name=skill_name, matcher=matcher)
    if projection is None:
        expected = f" '{skill_name}'" if skill_name is not None else ""
        detail = " matching the provided predicate" if matcher is not None else ""
        raise AssertionError(f"Expected skill outcome{expected}{detail}.")
    return projection



def assert_child_summary(
    source: Any,
    *,
    agent_name: str | None = None,
    matcher: ChildSummaryMatcher | None = None,
    child_runs: Sequence[Any] | None = None,
) -> ChildSummaryProjection:
    projection = child_summary(
        source,
        agent_name=agent_name,
        matcher=matcher,
        child_runs=child_runs,
    )
    if projection is None:
        expected = f" for agent '{agent_name}'" if agent_name is not None else ""
        detail = " matching the provided predicate" if matcher is not None else ""
        raise AssertionError(f"Expected child-run summary{expected}{detail}.")
    return projection



def assert_no_terminal_failure(source: Any) -> None:
    failure = terminal_failure(source)
    if failure is None:
        return
    detail = failure.error or failure.abort_reason or failure.stop_reason or "unknown failure"
    raise AssertionError(f"Workflow terminated unsuccessfully: {detail}")



def _messages_from_source(source: Any) -> tuple[RuntimeMessage, ...]:
    if isinstance(source, tuple) and _is_message_tuple(source):
        return source
    if isinstance(source, list) and _is_message_tuple(tuple(source)):
        return tuple(source)
    messages = getattr(source, "messages", ())
    if _is_message_tuple(tuple(messages)):
        return tuple(messages)
    return ()



def _is_message_tuple(messages: tuple[Any, ...]) -> bool:
    return all(isinstance(message, RuntimeMessage) for message in messages)


__all__ = [
    "assert_child_summary",
    "assert_no_terminal_failure",
    "assert_skill_outcome",
    "assert_tool_outcome",
    "assert_tool_result",
    "extract_tool_result",
]
