from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from weavert.builtins.tools import builtin_tools
from weavert.agent_execution import AgentExecutionSpec, AgentRunRecord, AgentRunStatus, SpawnMode
from weavert.agent_runtime import AgentRunResult
from weavert.child_result_projection import project_agent_run_result, project_child_run_record
from weavert.contracts import MessageRole, RuntimeMessage, TextBlock, ToolResultBlock, ToolUseBlock
from weavert.definitions import IsolationMode
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


def _delegated_scope_summary() -> dict[str, object]:
    return {
        "visible_tools": ["collect_scope"],
        "visible_skills": ["scoped-skill"],
        "permission_mode": "dontAsk",
        "memory_scope": "project",
        "isolation_mode": "worktree",
    }


def _delegated_request_metadata(
    *,
    memory_scope: str | None = "project",
    trace_memory_scope: str | None = "project",
) -> dict[str, object]:
    summary = _delegated_scope_summary()
    summary["memory_scope"] = memory_scope
    trace: dict[str, object] = {
        "effective_tools": list(summary["visible_tools"]),
        "effective_skills": list(summary["visible_skills"]),
        "effective_permission_mode": summary["permission_mode"],
        "effective_isolation_mode": summary["isolation_mode"],
    }
    if trace_memory_scope is not None:
        trace["effective_memory_scope"] = trace_memory_scope
    return {
        "policy": {
            "effective": {
                "tools": list(summary["visible_tools"]),
                "skills": list(summary["visible_skills"]),
                "permission_mode": summary["permission_mode"],
                "memory_scope": memory_scope,
                "isolation_mode": summary["isolation_mode"],
                "trace": trace,
            }
        }
    }


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
                        "scope_summary": _delegated_scope_summary(),
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
        request_metadata=_delegated_request_metadata(),
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
    assert preferred.scope_summary is not None
    assert preferred.scope_summary.visible_tools == ("collect_scope",)
    assert preferred.scope_summary.visible_skills == ("scoped-skill",)
    assert preferred.scope_summary.permission_mode == "dontAsk"
    assert preferred.scope_summary.memory_scope == "project"
    assert preferred.scope_summary.isolation_mode == "worktree"

    fallback = child_summary((child_record,), agent_name="reviewer")
    assert fallback is not None
    assert fallback.summary == "review: fallback"
    assert fallback.run_id == "review-run-2"
    assert fallback.status == "completed"
    assert fallback.scope_summary is not None
    assert fallback.scope_summary.visible_tools == ("collect_scope",)
    assert fallback.scope_summary.visible_skills == ("scoped-skill",)
    assert fallback.scope_summary.permission_mode == "dontAsk"
    assert fallback.scope_summary.memory_scope == "project"
    assert fallback.scope_summary.isolation_mode == "worktree"


def test_child_projection_builders_publish_scope_summary_on_parent_and_child_surfaces() -> None:
    request_metadata = _delegated_request_metadata()
    child_record = AgentRunRecord(
        run_id="review-run-projected",
        parent_run_id="parent-run",
        session_id="session-projected",
        parent_turn_id="turn-parent",
        turn_id="turn-child",
        agent_name="reviewer",
        spawn_mode=SpawnMode.SYNC,
        status=AgentRunStatus.COMPLETED,
        query_source="agent_tool",
        request_metadata=request_metadata,
        messages=(
            RuntimeMessage(
                message_id="review-projected-summary",
                role=MessageRole.ASSISTANT,
                content="review: projected",
            ),
        ),
    )
    execution_spec = AgentExecutionSpec(
        run_id="review-run-projected",
        parent_run_id="parent-run",
        session_id="session-projected",
        parent_turn_id="turn-parent",
        turn_id="turn-child",
        agent_name="reviewer",
        spawn_mode=SpawnMode.SYNC,
        query_source="agent_tool",
        prompt_messages=(),
        cwd=Path("."),
    )
    result = AgentRunResult(
        agent_name="reviewer",
        status="completed",
        messages=list(child_record.messages),
        background=False,
        isolation_mode=IsolationMode.WORKTREE,
        run_id=child_record.run_id,
        parent_run_id=child_record.parent_run_id,
        turn_id=child_record.turn_id,
        query_source=child_record.query_source,
        execution_spec=execution_spec,
        run_record=child_record,
    )

    parent_projection = project_agent_run_result(result)
    child_projection = project_child_run_record(child_record)

    assert parent_projection["summary"] == "review: projected"
    assert parent_projection["scope_summary"] == _delegated_scope_summary()
    assert child_projection["scope_summary"] == _delegated_scope_summary()


def test_child_projection_builders_fallback_to_trace_memory_scope_and_preserve_unknown_memory_scope() -> None:
    trace_only_metadata = _delegated_request_metadata(
        memory_scope=None,
        trace_memory_scope="local",
    )
    child_record = AgentRunRecord(
        run_id="review-run-trace-fallback",
        parent_run_id="parent-run",
        session_id="session-trace-fallback",
        parent_turn_id="turn-parent",
        turn_id="turn-child",
        agent_name="reviewer",
        spawn_mode=SpawnMode.SYNC,
        status=AgentRunStatus.COMPLETED,
        query_source="agent_tool",
        request_metadata=trace_only_metadata,
        messages=(
            RuntimeMessage(
                message_id="review-trace-summary",
                role=MessageRole.ASSISTANT,
                content="review: trace fallback",
            ),
        ),
    )
    trace_execution_spec = AgentExecutionSpec(
        run_id="review-run-trace-fallback",
        parent_run_id="parent-run",
        session_id="session-trace-fallback",
        parent_turn_id="turn-parent",
        turn_id="turn-child",
        agent_name="reviewer",
        spawn_mode=SpawnMode.SYNC,
        query_source="agent_tool",
        prompt_messages=(),
        cwd=Path("."),
    )
    trace_result = AgentRunResult(
        agent_name="reviewer",
        status="completed",
        messages=list(child_record.messages),
        background=False,
        isolation_mode=IsolationMode.WORKTREE,
        run_id=child_record.run_id,
        parent_run_id=child_record.parent_run_id,
        turn_id=child_record.turn_id,
        query_source=child_record.query_source,
        execution_spec=trace_execution_spec,
        run_record=child_record,
    )

    parent_projection = project_agent_run_result(trace_result)
    child_projection = project_child_run_record(child_record)
    assert parent_projection["scope_summary"] is not None
    assert parent_projection["scope_summary"]["memory_scope"] == "local"
    assert child_projection["scope_summary"] is not None
    assert child_projection["scope_summary"]["memory_scope"] == "local"

    summary_from_child_run = child_summary((child_record,), agent_name="reviewer")
    assert summary_from_child_run is not None
    assert summary_from_child_run.scope_summary is not None
    assert summary_from_child_run.scope_summary.memory_scope == "local"

    unknown_memory_metadata = _delegated_request_metadata(
        memory_scope=None,
        trace_memory_scope=None,
    )
    unknown_record = AgentRunRecord(
        run_id="review-run-memory-unknown",
        parent_run_id="parent-run",
        session_id="session-memory-unknown",
        parent_turn_id="turn-parent",
        turn_id="turn-child",
        agent_name="reviewer",
        spawn_mode=SpawnMode.SYNC,
        status=AgentRunStatus.COMPLETED,
        query_source="agent_tool",
        request_metadata=unknown_memory_metadata,
        messages=(
            RuntimeMessage(
                message_id="review-unknown-summary",
                role=MessageRole.ASSISTANT,
                content="review: memory unknown",
            ),
        ),
    )
    unknown_execution_spec = AgentExecutionSpec(
        run_id="review-run-memory-unknown",
        parent_run_id="parent-run",
        session_id="session-memory-unknown",
        parent_turn_id="turn-parent",
        turn_id="turn-child",
        agent_name="reviewer",
        spawn_mode=SpawnMode.SYNC,
        query_source="agent_tool",
        prompt_messages=(),
        cwd=Path("."),
    )
    unknown_result = AgentRunResult(
        agent_name="reviewer",
        status="completed",
        messages=list(unknown_record.messages),
        background=False,
        isolation_mode=IsolationMode.WORKTREE,
        run_id=unknown_record.run_id,
        parent_run_id=unknown_record.parent_run_id,
        turn_id=unknown_record.turn_id,
        query_source=unknown_record.query_source,
        execution_spec=unknown_execution_spec,
        run_record=unknown_record,
    )

    unknown_parent_projection = project_agent_run_result(unknown_result)
    unknown_projection = project_child_run_record(unknown_record)
    assert unknown_parent_projection["scope_summary"] == {
        "visible_tools": ["collect_scope"],
        "visible_skills": ["scoped-skill"],
        "permission_mode": "dontAsk",
        "memory_scope": None,
        "isolation_mode": "worktree",
    }
    assert unknown_projection["scope_summary"] == {
        "visible_tools": ["collect_scope"],
        "visible_skills": ["scoped-skill"],
        "permission_mode": "dontAsk",
        "memory_scope": None,
        "isolation_mode": "worktree",
    }

    unknown_summary = child_summary((unknown_record,), agent_name="reviewer")
    assert unknown_summary is not None
    assert unknown_summary.scope_summary is not None
    assert unknown_summary.scope_summary.visible_tools == ("collect_scope",)
    assert unknown_summary.scope_summary.memory_scope is None


def test_builtin_agent_output_schema_declares_scope_summary_contract() -> None:
    agent_tool = next(tool for tool in builtin_tools() if tool.name == "agent")
    scope_schema = agent_tool.output_schema["properties"]["scope_summary"]

    assert scope_schema["type"] == ["object", "null"]
    assert scope_schema["required"] == [
        "visible_tools",
        "visible_skills",
        "permission_mode",
        "isolation_mode",
        "memory_scope",
    ]
    assert scope_schema["properties"]["memory_scope"]["type"] == ["string", "null"]
