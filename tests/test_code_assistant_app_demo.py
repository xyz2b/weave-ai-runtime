from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from demos._shared.common import extract_tool_result
from demos._shared.scripted_model import ScriptedModelClient, text_batch, tool_call_batch
from demos.apps.code_assistant.app import (
    assemble_demo_runtime,
    default_layout,
    inspect_demo,
    reset_demo_state,
    run_demo,
    shell_demo,
)
from weavert.openai_client import OPENAI_ROUTE_NAME
from weavert.runtime_kernel import RuntimeDistribution
from weavert.tool_runtime import ToolContext

PYTHON = sys.executable


def _layout(tmp_path: Path):
    return default_layout(state_root=tmp_path / "state")


def _scripted_run_report(tmp_path: Path):
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)

    def _assert_main_request(request) -> None:
        assert request.agent is not None
        assert request.agent.name == "code-assistant"
        assert {"read", "glob", "grep", "edit", "write", "bash", "agent", "skill"}.issubset(
            set(request.turn_context.available_tools)
        )
        assert {"coding-loop", "review-change", "verify-change"}.issubset(
            set(request.turn_context.available_skills)
        )

    def _coding_loop_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-1",
            tool_name="skill",
            tool_input={"skill": "coding-loop"},
            call_id="call-skill",
        )

    def _planner_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-2",
            tool_name="agent",
            tool_input={"agent": "coding-planner", "prompt": "Plan the work and create shared tasks."},
            call_id="call-planner",
        )

    def _planner_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "coding-planner"
        assert {"read", "glob", "grep", "task_create", "task_list"}.issubset(
            set(request.turn_context.available_tools)
        )
        return text_batch(request_id="req-planner-1", text="plan: inspect, fix, verify")

    def _task_one_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-3",
            tool_name="task_create",
            tool_input={"subject": "Inspect the failing greeting flow"},
            call_id="call-task-one",
        )

    def _task_two_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-4",
            tool_name="task_create",
            tool_input={"subject": "Fix greeting and add live note"},
            call_id="call-task-two",
        )

    def _grep_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-5",
            tool_name="grep",
            tool_input={"pattern": "WeaveRT", "path": "tests"},
            call_id="call-grep",
        )

    def _read_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-6",
            tool_name="read",
            tool_input={"file_path": "src/demo_service/greeting.py"},
            call_id="call-read",
        )

    def _edit_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-7",
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
            request_id="req-code-8",
            tool_name="write",
            tool_input={
                "file_path": "notes/live_demo.md",
                "content": "The coding shell MVP updated the greeting fixture.\n",
            },
            call_id="call-write",
        )

    def _bash_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-9",
            tool_name="bash",
            tool_input={
                "command": "python3 -m unittest discover -s tests",
                "description": "Run unit tests",
            },
            call_id="call-bash",
        )

    def _reviewer_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-10",
            tool_name="agent",
            tool_input={"agent": "reviewer", "prompt": "Review the greeting change and note."},
            call_id="call-reviewer",
        )

    def _reviewer_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "reviewer"
        assert {"read", "glob", "grep", "task_list"} == set(request.turn_context.available_tools)
        return text_batch(request_id="req-reviewer-1", text="review: no issues found")

    def _verifier_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-11",
            tool_name="agent",
            tool_input={"agent": "verifier", "prompt": "Confirm the verification result."},
            call_id="call-verifier",
        )

    def _verifier_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "verifier"
        assert {"read", "glob", "grep", "bash", "task_list", "job_get", "job_list", "job_stop"} == set(
            request.turn_context.available_tools
        )
        return text_batch(request_id="req-verifier-1", text="verification: tests passed")

    def _task_list_batch(request):
        _assert_main_request(request)
        return tool_call_batch(
            request_id="req-code-12",
            tool_name="task_list",
            tool_input={},
            call_id="call-task-list",
        )

    def _final_batch(request):
        _assert_main_request(request)
        return text_batch(request_id="req-code-13", text="completed coding shell workflow")

    client = ScriptedModelClient(
        [
            _coding_loop_batch,
            _planner_batch,
            _planner_child_batch,
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


def _iter_input(lines: list[str]):
    iterator = iter(lines)

    def _reader(_prompt: str) -> str:
        return next(iterator)

    return _reader


def test_reset_demo_state_materializes_shell_agents_and_skills(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    workspace = reset_demo_state(layout=layout)

    assert workspace == layout.workspace_root
    assert (workspace / ".weavert" / "agents" / "code-assistant.md").exists()
    assert (workspace / ".weavert" / "agents" / "coding-planner.md").exists()
    assert (workspace / ".weavert" / "agents" / "reviewer.md").exists()
    assert (workspace / ".weavert" / "agents" / "verifier.md").exists()
    assert (workspace / ".weavert" / "skills" / "coding-loop" / "SKILL.md").exists()
    assert (workspace / ".weavert" / "skills" / "review-change" / "SKILL.md").exists()
    assert (workspace / "src" / "demo_service" / "greeting.py").exists()
    assert not (layout.fixture_root / ".weavert" / "transcripts").exists()


def test_demo_runtime_defaults_to_full_distribution_and_replaces_only_bash(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)

    runtime = assemble_demo_runtime(layout=layout)
    profile = runtime.query_persistence_profile()
    bash_tool = runtime.kernel.tool_registry.get("bash")
    code_assistant = runtime.kernel.agent_registry.get("code-assistant")
    planner = runtime.kernel.agent_registry.get("coding-planner")
    reviewer = runtime.kernel.agent_registry.get("reviewer")
    verifier = runtime.kernel.agent_registry.get("verifier")

    assert runtime.kernel.distribution == RuntimeDistribution.FULL.value
    assert runtime.kernel.config.default_model_route == OPENAI_ROUTE_NAME
    assert profile["profile_name"] == RuntimeDistribution.FULL.value
    assert profile["surfaces"]["transcript"]["durability"] == "durable"
    assert profile["surfaces"]["child_runs"]["durability"] == "durable"
    assert profile["surfaces"]["task_lists"]["durability"] == "durable"
    assert bash_tool is not None
    assert "description" in bash_tool.input_schema["properties"]
    assert "run_in_background" in bash_tool.input_schema["properties"]
    assert bash_tool.metadata["builtin_owner"] == "weavert-devtools"
    assert code_assistant is not None
    assert planner is not None
    assert reviewer is not None
    assert verifier is not None
    assert {"read", "glob", "grep", "edit", "write", "bash", "agent", "skill", "task_*", "job_*"} == set(
        code_assistant.tools
    )
    assert {"read", "glob", "grep", "task_*"} == set(planner.tools)
    assert {"read", "glob", "grep", "task_list"} == set(reviewer.tools)
    assert {"read", "glob", "grep", "bash", "task_list", "job_*"} == set(verifier.tools)
    assert {"coding-loop", "task-discipline", "repo-conventions", "bugfix", "review-change", "verify-change", "repo-onboard"} == set(
        code_assistant.skills
    )


def test_run_demo_with_scripted_model_exercises_shell_agents_tools_and_child_runs(tmp_path: Path) -> None:
    report, layout = _scripted_run_report(tmp_path)

    assert report.ok is True
    assert report.workflow_gaps == ()
    assert report.final_text == "completed coding shell workflow"
    assert [approval.name for approval in report.approvals] == ["edit", "write", "bash"]
    assert all(approval.approved for approval in report.approvals)
    assert [child["agent"] for child in report.child_runs] == ["coding-planner", "reviewer", "verifier"]
    assert report.task_list_id.startswith("session:")
    assert len(report.task_list["tasks"]) == 2
    assert report.transcript_path.exists()
    assert report.child_run_index_path.exists()
    assert report.memory_root == layout.workspace_root / ".weavert" / "memory"
    assert (layout.workspace_root / "notes" / "live_demo.md").read_text(encoding="utf-8").strip() == (
        "The coding shell MVP updated the greeting fixture."
    )
    assert 'DEFAULT_NAME = "WeaveRT"' in (layout.workspace_root / "src" / "demo_service" / "greeting.py").read_text(
        encoding="utf-8"
    )

    skill_result = extract_tool_result(report.messages, "call-skill")
    planner_result = extract_tool_result(report.messages, "call-planner")
    bash_result = extract_tool_result(report.messages, "call-bash")
    reviewer_result = extract_tool_result(report.messages, "call-reviewer")
    verifier_result = extract_tool_result(report.messages, "call-verifier")

    assert skill_result["skill"] == "coding-loop"
    assert skill_result["mode"] == "inline"
    assert planner_result["agent"] == "coding-planner"
    assert planner_result["status"] == "completed"
    assert bash_result["classification"] == "test"
    assert bash_result["exit_code"] == 0
    assert bash_result["stdout_preview"]
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


def test_shell_demo_reuses_a_session_and_keeps_local_commands_host_owned(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    output_lines: list[str] = []
    client = ScriptedModelClient(
        [
            tool_call_batch(
                request_id="req-shell-1",
                tool_name="bash",
                tool_input={
                    "command": "python3 -c \"print('bg ok')\"",
                    "description": "Run a background check",
                    "run_in_background": True,
                },
                call_id="call-shell-bash",
            ),
            text_batch(request_id="req-shell-2", text="background check started"),
            text_batch(request_id="req-shell-3", text="session state summarized"),
        ]
    )

    report = asyncio.run(
        shell_demo(
            auto_approve=True,
            layout=layout,
            model_client=client,
            input_reader=_iter_input(
                [
                    "/help",
                    "Start the background check.",
                    "/jobs",
                    "Summarize the running state.",
                    "/exit",
                ]
            ),
            output_writer=output_lines.append,
        )
    )

    assert report.ok is True
    assert report.prompt_count == 2
    assert report.local_commands == ("help", "jobs", "exit")
    assert report.transcript_path.exists()
    assert len(client.requests) == 3
    assert [approval.name for approval in report.approvals] == ["bash"]
    assert any("local commands:" in line for line in output_lines)
    assert any("[bash:running]" in line for line in output_lines)
    assert any("jobs:" in line for line in output_lines)
    assert any("assistant: background check started" in line for line in output_lines)
    assert any("assistant: session state summarized" in line for line in output_lines)


def test_shell_resume_lists_sessions_and_reattaches_without_model_turn(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    seed_client = ScriptedModelClient(
        [text_batch(request_id="req-seed-1", text="seeded transcript")]
    )
    asyncio.run(
        run_demo(
            prompt="Seed a resumable session.",
            session_id="resume-target",
            auto_approve=True,
            validate_workflow=False,
            layout=layout,
            model_client=seed_client,
            output_writer=lambda _line: None,
        )
    )

    output_lines: list[str] = []
    idle_client = ScriptedModelClient([])
    report = asyncio.run(
        shell_demo(
            session_id="scratch-shell",
            auto_approve=True,
            layout=layout,
            model_client=idle_client,
            input_reader=_iter_input(["/resume", "/resume resume-target", "/exit"]),
            output_writer=output_lines.append,
        )
    )

    assert report.session_id == "resume-target"
    assert len(idle_client.requests) == 0
    assert any("resumable sessions:" in line for line in output_lines)
    assert any("reattached session: resume-target" in line for line in output_lines)


def test_replacement_bash_returns_structured_results_and_background_jobs(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    runtime = assemble_demo_runtime(layout=layout)
    bash_tool = runtime.kernel.tool_registry.get("bash")
    assert bash_tool is not None

    context = ToolContext(
        session_id="shell-test",
        turn_id="turn-1",
        agent_name="code-assistant",
        cwd=layout.workspace_root,
        tool_registry=runtime.kernel.tool_registry,
        runtime_services=runtime.services,
    )

    async def scenario():
        foreground_result = await bash_tool.execute(
            {"command": "printf hi", "description": "Emit hi"},
            context,
        )
        background_result = await bash_tool.execute(
            {
                "command": "python3 -c \"import time; time.sleep(30)\"",
                "description": "Sleep in background",
                "run_in_background": True,
            },
            context,
        )
        jobs_result = await runtime.list_jobs(session_id="shell-test")
        stopped_result = await runtime.stop_job(background_result["job_id"], session_id="shell-test")
        return foreground_result, background_result, jobs_result, stopped_result

    foreground, background, jobs, stopped = asyncio.run(scenario())

    assert foreground["classification"] == "other"
    assert foreground["status"] == "completed"
    assert foreground["stdout"] == "hi"
    assert foreground["stdout_preview"] == "hi"
    assert foreground["output_summary"] == "hi"

    assert background["status"] == "running"
    assert background["job_id"] is not None
    assert background["background_reason"] == "requested"

    assert any(job["job_id"] == background["job_id"] for job in jobs)
    assert stopped["status"] == "stopped"
    assert stopped["result"]["status"] == "stopped"


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


def test_run_demo_fails_when_required_workflow_surfaces_do_not_execute(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    client = ScriptedModelClient(
        [
            text_batch(
                request_id="req-code-1",
                text="I inspected mentally and I am done.",
            )
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

    assert report.ok is False
    assert "Workflow validation failed" in str(report.error_message)
    assert "the workspace-local coding-loop skill was not applied" in report.workflow_gaps
    assert "the coding-planner child run never executed" in report.workflow_gaps
    assert "the workflow never used bash verification" in report.workflow_gaps


def test_inspect_demo_reports_durable_state_and_reset_clears_generated_outputs(tmp_path: Path) -> None:
    report, layout = _scripted_run_report(tmp_path)

    inspect_before = inspect_demo(layout=layout)

    assert inspect_before.workspace_exists is True
    assert inspect_before.distribution == RuntimeDistribution.FULL.value
    assert inspect_before.default_model_route == OPENAI_ROUTE_NAME
    assert inspect_before.persistence_profile["surfaces"]["memory"]["durability"] == "durable"
    assert any(session["session_id"] == report.session_id for session in inspect_before.transcript_sessions)
    assert any(session["session_id"] == report.session_id for session in inspect_before.child_run_sessions)
    assert {record["agent"] for record in inspect_before.child_run_records} == {
        "coding-planner",
        "reviewer",
        "verifier",
    }
    assert any(record["summary"] == "review: no issues found" for record in inspect_before.child_run_records)
    assert inspect_before.task_lists[0]["tasks"][0]["subject"] == "Inspect the failing greeting flow"
    assert inspect_before.memory_root == layout.workspace_root / ".weavert" / "memory"

    reset_demo_state(layout=layout)
    inspect_after = inspect_demo(layout=layout)

    assert inspect_after.workspace_exists is True
    assert inspect_after.transcript_sessions == ()
    assert inspect_after.child_run_sessions == ()
    assert inspect_after.child_run_records == ()
    assert inspect_after.task_lists == ()
