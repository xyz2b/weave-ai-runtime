from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from demos._shared.common import extract_tool_result
from demos._shared.scripted_model import ScriptedModelClient, text_batch, tool_call_batch
from demos.apps.code_assistant.app import assemble_demo_runtime, default_layout, inspect_demo, reset_demo_state, run_demo
from weavert.openai_client import OPENAI_ROUTE_NAME
from weavert.runtime_kernel import RuntimeDistribution

PYTHON = sys.executable


def _layout(tmp_path: Path):
    return default_layout(state_root=tmp_path / "state")


def _scripted_run_report(tmp_path: Path):
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)

    def _assert_main_request(request) -> None:
        assert request.agent is not None
        assert request.agent.name == "code-assistant"
        assert {"read", "grep", "edit", "write", "bash", "agent", "skill"}.issubset(
            set(request.turn_context.available_tools)
        )
        assert "v1-code-workflow" in request.turn_context.available_skills

    def _skill_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-1",
            tool_name="skill",
            tool_input={"skill": "v1-code-workflow"},
            call_id="call-skill",
        )

    def _task_one_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-2",
            tool_name="task_create",
            tool_input={"subject": "Inspect failing greeting test"},
            call_id="call-task-one",
        )

    def _task_two_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-3",
            tool_name="task_create",
            tool_input={"subject": "Fix greeting and add live note"},
            call_id="call-task-two",
        )

    def _grep_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-4",
            tool_name="grep",
            tool_input={"pattern": "WeaveRT", "path": "tests"},
            call_id="call-grep",
        )

    def _read_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-5",
            tool_name="read",
            tool_input={"file_path": "src/demo_service/greeting.py"},
            call_id="call-read",
        )

    def _edit_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-6",
            tool_name="edit",
            tool_input={
                "file_path": "src/demo_service/greeting.py",
                "old_string": 'DEFAULT_NAME = "runtime"',
                "new_string": 'DEFAULT_NAME = "WeaveRT"',
            },
            call_id="call-edit",
        )

    def _write_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-7",
            tool_name="write",
            tool_input={
                "file_path": "notes/live_demo.md",
                "content": "The live code assistant updated the greeting fixture.\n",
            },
            call_id="call-write",
        )

    def _bash_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-8",
            tool_name="bash",
            tool_input={"command": "python3 -m unittest discover -s tests"},
            call_id="call-bash",
        )

    def _reviewer_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-9",
            tool_name="agent",
            tool_input={"agent": "reviewer", "prompt": "Review the greeting change and note."},
            call_id="call-reviewer",
        )

    def _reviewer_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "reviewer"
        assert set(request.turn_context.available_tools) == {"read", "grep", "task_list"}
        return text_batch(request_id="req-reviewer-1", text="review: no issues found")

    def _verifier_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-10",
            tool_name="agent",
            tool_input={"agent": "verifier", "prompt": "Confirm the verification result."},
            call_id="call-verifier",
        )

    def _verifier_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "verifier"
        assert set(request.turn_context.available_tools) == {"read", "bash", "task_list"}
        return text_batch(request_id="req-verifier-1", text="verification: tests passed")

    def _task_list_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-11",
            tool_name="task_list",
            tool_input={},
            call_id="call-task-list",
        )

    def _final_batch(request):
        _assert_main_request(request)
        return text_batch(request_id="req-code-12", text="completed live coding workflow")

    client = ScriptedModelClient(
        [
            _skill_batch,
            _task_one_batch,
            _task_two_batch,
            _grep_batch,
            _read_batch,
            _edit_batch,
            _write_batch,
            _bash_batch,
            _reviewer_batch,
            _reviewer_child_batch,
            _verifier_batch,
            _verifier_child_batch,
            _task_list_batch,
            _final_batch,
        ]
    )
    report = asyncio.run(
        run_demo(
            prompt="Use the default coding workflow.",
            auto_approve=True,
            layout=layout,
            model_client=client,
            output_writer=lambda _line: None,
        )
    )
    return report, layout


def test_reset_demo_state_materializes_fixture_and_workspace_local_defs(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    workspace = reset_demo_state(layout=layout)

    assert workspace == layout.workspace_root
    assert (workspace / ".weavert" / "agents" / "code-assistant.md").exists()
    assert (workspace / ".weavert" / "agents" / "reviewer.md").exists()
    assert (workspace / ".weavert" / "agents" / "verifier.md").exists()
    assert (workspace / ".weavert" / "skills" / "v1-code-workflow" / "SKILL.md").exists()
    assert (workspace / "src" / "demo_service" / "greeting.py").exists()
    assert not (layout.fixture_root / ".weavert" / "transcripts").exists()


def test_demo_runtime_defaults_to_full_distribution_and_live_openai_route(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)

    runtime = assemble_demo_runtime(layout=layout)
    profile = runtime.query_persistence_profile()

    assert runtime.kernel.distribution == RuntimeDistribution.FULL.value
    assert runtime.kernel.config.default_model_route == OPENAI_ROUTE_NAME
    assert profile["profile_name"] == RuntimeDistribution.FULL.value
    assert profile["surfaces"]["transcript"]["durability"] == "durable"
    assert profile["surfaces"]["child_runs"]["durability"] == "durable"
    assert profile["surfaces"]["task_lists"]["durability"] == "durable"


def test_run_demo_with_scripted_model_exercises_tools_planning_and_child_runs(tmp_path: Path) -> None:
    report, layout = _scripted_run_report(tmp_path)

    assert report.ok is True
    assert report.final_text == "completed live coding workflow"
    assert [approval.name for approval in report.approvals] == ["edit", "write", "bash"]
    assert all(approval.approved for approval in report.approvals)
    assert [child["agent"] for child in report.child_runs] == ["reviewer", "verifier"]
    assert report.task_list_id.startswith("session:")
    assert len(report.task_list["tasks"]) == 2
    assert report.transcript_path.exists()
    assert report.child_run_index_path.exists()
    assert report.memory_root == layout.workspace_root / ".weavert" / "memory"
    assert (layout.workspace_root / "notes" / "live_demo.md").read_text(encoding="utf-8").strip() == (
        "The live code assistant updated the greeting fixture."
    )
    assert 'DEFAULT_NAME = "WeaveRT"' in (layout.workspace_root / "src" / "demo_service" / "greeting.py").read_text(
        encoding="utf-8"
    )

    skill_result = extract_tool_result(report.messages, "call-skill")
    bash_result = extract_tool_result(report.messages, "call-bash")
    reviewer_result = extract_tool_result(report.messages, "call-reviewer")
    verifier_result = extract_tool_result(report.messages, "call-verifier")

    assert skill_result["skill"] == "v1-code-workflow"
    assert skill_result["mode"] == "inline"
    assert bash_result["exit_code"] == 0
    assert reviewer_result["agent"] == "reviewer"
    assert reviewer_result["status"] == "completed"
    assert verifier_result["agent"] == "verifier"
    assert verifier_result["status"] == "completed"

    completed = subprocess.run(
        [PYTHON, "-m", "unittest", "discover", "-s", "tests"],
        cwd=layout.workspace_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "OK" in completed.stdout or "OK" in completed.stderr


def test_run_demo_surfaces_missing_live_credentials_without_fallback(tmp_path: Path, monkeypatch) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    report = asyncio.run(
        run_demo(
            prompt="Say hello.",
            auto_approve=True,
            layout=layout,
            output_writer=lambda _line: None,
        )
    )

    assert report.ok is False
    assert report.default_model_route == OPENAI_ROUTE_NAME
    assert report.terminal_metadata["failure_class"] == "auth_error"
    assert "OPENAI_API_KEY" in str(report.error_message)
    assert report.final_text == ""


def test_inspect_demo_reports_durable_state_and_reset_clears_generated_outputs(tmp_path: Path) -> None:
    report, layout = _scripted_run_report(tmp_path)

    inspect_before = inspect_demo(layout=layout)

    assert inspect_before.workspace_exists is True
    assert inspect_before.distribution == RuntimeDistribution.FULL.value
    assert inspect_before.default_model_route == OPENAI_ROUTE_NAME
    assert inspect_before.persistence_profile["surfaces"]["memory"]["durability"] == "durable"
    assert any(session["session_id"] == report.session_id for session in inspect_before.transcript_sessions)
    assert any(session["session_id"] == report.session_id for session in inspect_before.child_run_sessions)
    assert inspect_before.memory_root == layout.workspace_root / ".weavert" / "memory"

    reset_demo_state(layout=layout)
    inspect_after = inspect_demo(layout=layout)

    assert inspect_after.workspace_exists is True
    assert inspect_after.transcript_sessions == ()
    assert inspect_after.child_run_sessions == ()
    assert inspect_after.task_lists == ()
