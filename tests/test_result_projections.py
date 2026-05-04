from __future__ import annotations

from dataclasses import dataclass

from weavert.agent_execution import AgentRunRecord, AgentRunStatus, SpawnMode
from weavert.contracts import MessageRole, RuntimeMessage, TextBlock, ToolResultBlock, ToolUseBlock
from weavert.result_projections import (
    child_summary,
    final_assistant_text,
    latest_skill_outcome,
    latest_tool_outcome,
    terminal_failure,
)
from weavert.runtime_kernel import WorkflowRunReport
from weavert.turn_engine.engine import TurnTerminal, TurnTerminalReason


@dataclass(frozen=True, slots=True)
class ReportLike:
    messages: tuple[RuntimeMessage, ...]
    terminal_stop_reason: str | None = None
    terminal_metadata: dict[str, object] | None = None
    error_message: str | None = None
    child_runs: tuple[object, ...] = ()


def _workflow_messages() -> tuple[RuntimeMessage, ...]:
    return (
        RuntimeMessage(
            message_id="bash-use-1",
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(
                    tool_use_id="bash-1",
                    name="bash",
                    input={"command": "python3 -m unittest discover -s tests"},
                ),
            ),
        ),
        RuntimeMessage(
            message_id="bash-result-1",
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="bash-1",
                    content={
                        "command": "python3 -m unittest discover -s tests",
                        "exit_code": 1,
                    },
                ),
            ),
            metadata={
                "tool_results": [
                    {"tool_use_id": "bash-1", "tool_name": "bash", "status": "success"},
                ]
            },
        ),
        RuntimeMessage(
            message_id="bash-use-2",
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(
                    tool_use_id="bash-2",
                    name="bash",
                    input={"command": "python3 -m unittest discover -s tests"},
                ),
            ),
        ),
        RuntimeMessage(
            message_id="bash-result-2",
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="bash-2",
                    content={
                        "command": "python3 -m unittest discover -s tests",
                        "exit_code": 0,
                    },
                ),
            ),
            metadata={
                "tool_results": [
                    {"tool_use_id": "bash-2", "tool_name": "bash", "status": "success"},
                ]
            },
        ),
        RuntimeMessage(
            message_id="skill-use",
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(
                    tool_use_id="skill-1",
                    name="skill",
                    input={"skill": "coding-loop"},
                ),
            ),
        ),
        RuntimeMessage(
            message_id="skill-result",
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="skill-1",
                    content={
                        "skill": "coding-loop",
                        "mode": "inline",
                    },
                ),
            ),
            metadata={
                "tool_results": [
                    {"tool_use_id": "skill-1", "tool_name": "skill", "status": "success"},
                ]
            },
        ),
        RuntimeMessage(
            message_id="review-use",
            role=MessageRole.ASSISTANT,
            content=(
                ToolUseBlock(
                    tool_use_id="agent-1",
                    name="agent",
                    input={"agent": "reviewer", "prompt": "Review the workspace."},
                ),
            ),
        ),
        RuntimeMessage(
            message_id="review-result",
            role=MessageRole.USER,
            content=(
                ToolResultBlock(
                    tool_use_id="agent-1",
                    content={
                        "agent": "reviewer",
                        "status": "completed",
                        "summary": "review: pass",
                        "run_id": "review-run-1",
                        "terminal_metadata": {},
                    },
                ),
            ),
            metadata={
                "tool_results": [
                    {"tool_use_id": "agent-1", "tool_name": "agent", "status": "success"},
                ]
            },
        ),
        RuntimeMessage(
            message_id="assistant-final",
            role=MessageRole.ASSISTANT,
            content=(TextBlock("updated greeting; verification: passed; review: pass"),),
        ),
    )


def test_latest_tool_outcome_returns_latest_match_and_supports_matchers() -> None:
    messages = _workflow_messages()

    latest = latest_tool_outcome(messages, "bash")
    assert latest is not None
    assert latest.tool_use_id == "bash-2"
    assert latest.output["exit_code"] == 0
    assert latest.status == "success"

    failed = latest_tool_outcome(
        messages,
        "bash",
        matcher=lambda projection: projection.output["exit_code"] == 1,
    )
    assert failed is not None
    assert failed.tool_use_id == "bash-1"
    assert failed.output["exit_code"] == 1

    assert latest_tool_outcome(messages, "read") is None


def test_skill_and_final_text_helpers_accept_workflow_run_reports() -> None:
    report = WorkflowRunReport(
        session_id="session-1",
        agent_name="coding-assistant",
        cwd=".",
        messages=_workflow_messages(),
        terminal=TurnTerminal(reason=TurnTerminalReason.END_TURN),
    )

    skill = latest_skill_outcome(report, skill_name="coding-loop")
    assert skill is not None
    assert skill.skill_name == "coding-loop"
    assert skill.mode == "inline"
    assert final_assistant_text(report) == "updated greeting; verification: passed; review: pass"
    assert latest_skill_outcome(report, skill_name="missing-skill") is None


def test_terminal_failure_handles_turn_terminals_and_report_like_terminal_fields() -> None:
    workflow_report = WorkflowRunReport(
        session_id="session-2",
        agent_name="coding-assistant",
        cwd=".",
        messages=_workflow_messages(),
        terminal=TurnTerminal(
            reason=TurnTerminalReason.ERROR,
            error="model exploded",
            request_id="req-123",
            metadata={"failure_class": "provider_error"},
        ),
    )

    workflow_failure = terminal_failure(workflow_report)
    assert workflow_failure is not None
    assert workflow_failure.stop_reason == "error"
    assert workflow_failure.error == "model exploded"
    assert workflow_failure.failure_class == "provider_error"
    assert workflow_failure.request_id == "req-123"

    report_like = ReportLike(
        messages=_workflow_messages(),
        terminal_stop_reason="blocked",
        terminal_metadata={"failure_class": "auth_error", "error": "OPENAI_API_KEY missing"},
    )
    compatibility_failure = terminal_failure(report_like)
    assert compatibility_failure is not None
    assert compatibility_failure.stop_reason == "blocked"
    assert compatibility_failure.failure_class == "auth_error"
    assert compatibility_failure.error == "OPENAI_API_KEY missing"

    assert terminal_failure(ReportLike(messages=_workflow_messages(), terminal_stop_reason="completed")) is None


def test_child_summary_prefers_parent_visible_results_and_falls_back_to_child_runs() -> None:
    messages = _workflow_messages()
    child_record = AgentRunRecord(
        run_id="review-run-2",
        parent_run_id="parent-run",
        session_id="session-3",
        parent_turn_id="turn-3",
        turn_id="review-turn-2",
        agent_name="reviewer",
        spawn_mode=SpawnMode.SYNC,
        status=AgentRunStatus.COMPLETED,
        messages=(
            RuntimeMessage(
                message_id="review-child-summary",
                role=MessageRole.ASSISTANT,
                content="review: fallback",
            ),
        ),
    )

    preferred = child_summary(
        ReportLike(messages=messages, child_runs=(child_record,)),
        agent_name="reviewer",
    )
    assert preferred is not None
    assert preferred.summary == "review: pass"
    assert preferred.run_id == "review-run-1"

    fallback = child_summary((child_record,), agent_name="reviewer")
    assert fallback is not None
    assert fallback.summary == "review: fallback"
    assert fallback.run_id == "review-run-2"
    assert fallback.status == "completed"
