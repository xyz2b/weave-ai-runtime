from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from weavert_testing import ScriptedModelClient, extract_tool_result, text_batch, tool_call_batch
import examples.apps.code_assistant.__main__ as code_assistant_main
from examples.apps.code_assistant.app import (
    CODE_ASSISTANT_STATE_ROOT_ENV,
    _inspection_outcome,
    _print_task_list,
    _tool_result_events,
    _workflow_validation_result,
    RunReport,
    WorkflowLedger,
    assemble_demo_runtime,
    default_layout,
    inspect_demo,
    reset_demo_state,
    run_demo,
    shell_demo,
)
from examples.apps.code_assistant.builtin_overrides import _classify_command
from examples.apps.code_assistant.host import ApprovalRecord
from weavert.agent_execution import AgentRunRecord, AgentRunStatus, SpawnMode
from weavert_openai.openai_client import OPENAI_ROUTE_NAME
from weavert.contracts import MessageRole, RuntimeMessage, ToolResultBlock
from weavert.runtime_kernel import RuntimeDistribution
from weavert.tool_runtime import ToolContext

PYTHON = sys.executable
ROOT = Path(__file__).resolve().parents[1]
CODE_ASSISTANT_README = ROOT / "examples" / "apps" / "code_assistant" / "README.md"
OFFICIAL_SHARED_GIT_TOOLS = {"git_status", "git_diff", "git_history"}
OFFICIAL_SHARED_WORKSPACE_TOOLS = {
    "workspace_symbols",
    "workspace_references",
    "workspace_outline",
    "workspace_test_targets",
}
OFFICIAL_CODE_ASSISTANT_SKILLS = {
    "coding-loop",
    "task-discipline",
    "repo-conventions",
    "bugfix",
    "review-change",
    "verify-change",
    "repo-onboard",
}


def _layout(tmp_path: Path):
    return default_layout(state_root=tmp_path / "state")


def _cli_env(
    tmp_path: Path,
    *,
    openai_api_key: str | None = None,
    openai_model: str | None = None,
    openai_base_url: str | None = None,
) -> dict[str, str]:
    env = dict(os.environ)
    env[CODE_ASSISTANT_STATE_ROOT_ENV] = str(tmp_path / "cli-state")
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        env.pop(name, None)
    if openai_api_key is not None:
        env["OPENAI_API_KEY"] = openai_api_key
    if openai_model is not None:
        env["OPENAI_MODEL"] = openai_model
    if openai_base_url is not None:
        env["OPENAI_BASE_URL"] = openai_base_url
    return env


def _run_code_assistant_cli(
    *args: str,
    env: dict[str, str],
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-B", "-m", "examples.apps.code_assistant", *args],
        cwd=ROOT,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
    )


def _scripted_run_report(tmp_path: Path):
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    report = asyncio.run(
        run_demo(
            prompt="Use the default coding workflow.",
            auto_approve=True,
            layout=layout,
            deterministic=True,
            output_writer=lambda _line: None,
        )
    )
    return report, layout


def _run_scripted_demo(tmp_path: Path, scripted_batches: list[object]):
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    client = ScriptedModelClient(scripted_batches)
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


def _assert_code_assistant_request(request) -> None:
    assert request.agent is not None
    assert request.agent.name == "code-assistant"
    assert {"read", "glob", "grep", "edit", "write", "bash", "git_status", "workspace_symbols", "agent", "skill"}.issubset(
        set(request.turn_context.available_tools)
    )
    assert {"coding-loop", "review-change", "verify-change", "task-discipline", "repo-onboard"}.issubset(
        set(request.turn_context.available_skills)
    )


def _assert_planner_request(request) -> None:
    assert request.agent is not None
    assert request.agent.name == "coding-planner"
    assert {"read", "glob", "grep", "workspace_symbols", "workspace_test_targets", "task_create", "task_list"}.issubset(
        set(request.turn_context.available_tools)
    )


def _iter_input(lines: list[str]):
    iterator = iter(lines)

    def _reader(_prompt: str) -> str:
        return next(iterator)

    return _reader


def _iter_input_then_eof(lines: list[str]):
    iterator = iter(lines)

    def _reader(_prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise EOFError from exc

    return _reader


def _result_payload(result: object) -> dict[str, object]:
    payload = getattr(result, "value", result)
    assert isinstance(payload, dict)
    return payload


def _latest_shell_session_id(request) -> str:
    for message in reversed(request.messages):
        for block in message.content:
            if not isinstance(block, ToolResultBlock) or not isinstance(block.content, dict):
                continue
            shell_session_id = str(block.content.get("shell_session_id") or "").strip()
            if shell_session_id:
                return shell_session_id
    raise AssertionError("Missing shell_session_id in prior tool results")


def test_reset_demo_state_keeps_only_app_owned_shell_definitions(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    workspace = reset_demo_state(layout=layout)
    assistant_definition = (workspace / ".weavert" / "agents" / "code-assistant.md").read_text(encoding="utf-8")

    assert workspace == layout.workspace_root
    assert (workspace / ".weavert" / "agents" / "code-assistant.md").exists()
    assert not (workspace / ".weavert" / "agents" / "coding-planner.md").exists()
    assert not (workspace / ".weavert" / "agents" / "reviewer.md").exists()
    assert not (workspace / ".weavert" / "agents" / "verifier.md").exists()
    assert not (workspace / ".weavert" / "skills" / "coding-loop" / "SKILL.md").exists()
    assert not (workspace / ".weavert" / "skills" / "review-change" / "SKILL.md").exists()
    assert (workspace / ".weavert" / "skills" / "bugfix" / "SKILL.md").exists()
    assert (workspace / ".weavert" / "skills" / "repo-conventions" / "SKILL.md").exists()
    assert (workspace / "src" / "demo_service" / "greeting.py").exists()
    assert not (layout.fixture_root / ".weavert" / "transcripts").exists()
    assert "`max_turns: 8`" in assistant_definition
    assert "visible shared plan" in assistant_definition
    assert "git_*" in assistant_definition
    assert "workspace_*" in assistant_definition


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
    coding_loop = runtime.kernel.skill_registry.get("coding-loop")
    review_change = runtime.kernel.skill_registry.get("review-change")
    verify_change = runtime.kernel.skill_registry.get("verify-change")
    task_discipline = runtime.kernel.skill_registry.get("task-discipline")
    repo_onboard = runtime.kernel.skill_registry.get("repo-onboard")
    package_manifests = {manifest.name for manifest in runtime.kernel.package_manifests}

    assert runtime.kernel.distribution == RuntimeDistribution.FULL.value
    assert runtime.kernel.config.default_model_route == OPENAI_ROUTE_NAME
    assert profile["profile_name"] == RuntimeDistribution.FULL.value
    assert profile["surfaces"]["transcript"]["durability"] == "durable"
    assert profile["surfaces"]["child_runs"]["durability"] == "durable"
    assert profile["surfaces"]["task_lists"]["durability"] == "durable"
    assert {"weavert-scenario-coding", "weavert-shared-git", "weavert-shared-workspace-intelligence"} <= package_manifests
    assert bash_tool is not None
    assert "action" in bash_tool.input_schema["properties"]
    assert "description" in bash_tool.input_schema["properties"]
    assert "run_in_background" in bash_tool.input_schema["properties"]
    assert "shell_session_id" in bash_tool.input_schema["properties"]
    assert bash_tool.metadata["builtin_owner"] == "weavert-devtools"
    assert code_assistant is not None
    assert planner is not None
    assert reviewer is not None
    assert verifier is not None
    assert coding_loop is not None
    assert review_change is not None
    assert verify_change is not None
    assert task_discipline is not None
    assert repo_onboard is not None
    assert code_assistant.max_turns == 16
    assert planner.max_turns == 8
    assert reviewer.max_turns == 4
    assert verifier.max_turns == 4
    assert {"read", "glob", "grep", "edit", "write", "bash", "git_*", "workspace_*", "agent", "skill", "task_*", "job_*"} == set(
        code_assistant.tools
    )
    assert {"read", "glob", "grep", "workspace_*", "task_*"} == set(planner.tools)
    assert {"read", "glob", "grep", "git_status", "git_diff", "task_list"} == set(reviewer.tools)
    assert {"read", "glob", "grep", "bash", "git_status", "git_diff", "workspace_test_targets", "task_list", "job_*"} == set(
        verifier.tools
    )
    assert OFFICIAL_CODE_ASSISTANT_SKILLS == set(code_assistant.skills)
    assert planner.metadata["builtin_owner"] == "weavert-scenario-coding"
    assert reviewer.metadata["builtin_owner"] == "weavert-scenario-coding"
    assert verifier.metadata["builtin_owner"] == "weavert-scenario-coding"
    assert coding_loop.metadata["builtin_owner"] == "weavert-scenario-coding"
    assert review_change.metadata["builtin_owner"] == "weavert-scenario-coding"
    assert verify_change.metadata["builtin_owner"] == "weavert-scenario-coding"
    assert task_discipline.metadata["builtin_owner"] == "weavert-scenario-coding"
    assert repo_onboard.metadata["builtin_owner"] == "weavert-scenario-coding"
    assert runtime.kernel.agent_registry.get("planner").metadata["builtin_owner"] == "weavert-planning"
    assert runtime.kernel.agent_registry.get("verification").metadata["builtin_owner"] == "weavert-devtools"


def test_run_demo_with_scripted_model_exercises_shell_agents_tools_and_child_runs(tmp_path: Path) -> None:
    report, layout = _scripted_run_report(tmp_path)

    assert report.ok is True
    assert report.mode == "deterministic"
    assert report.workflow_gaps == ()
    assert report.workflow_advisories == ()
    assert report.workflow_ledger.current_state == "ready_to_summarize"
    assert report.workflow_ledger.change_revision == 2
    assert report.workflow_ledger.verified_revision == 2
    assert report.workflow_ledger.reviewed_revision == 2
    assert report.workflow_warnings == ()
    assert report.final_text == "completed coding shell workflow"
    assert [approval.name for approval in report.approvals] == ["edit", "write", "bash"]
    assert all(approval.approved for approval in report.approvals)
    assert [child["agent"] for child in report.child_runs] == ["coding-planner", "reviewer", "verifier"]
    assert report.task_list_id.startswith("session:")
    assert len(report.task_list["tasks"]) == 2
    assert report.transcript_path.exists()
    assert report.child_run_index_path.exists()
    assert report.memory_root == layout.workspace_root / ".weavert" / "memory"
    assert report.assembly_anchors is not None
    assert report.assembly_anchors.package_manifests == (
        "weavert-scenario-coding",
        "weavert-shared-git",
        "weavert-shared-workspace-intelligence",
    )
    assert dict(report.assembly_anchors.tool_family_owners) == {
        "git_*": "weavert-shared-git",
        "workspace_*": "weavert-shared-workspace-intelligence",
    }
    assert dict(report.assembly_anchors.definition_owners)["code-assistant"] == "app"
    assert dict(report.assembly_anchors.definition_owners)["coding-planner"] == "weavert-scenario-coding"
    assert dict(report.assembly_anchors.definition_owners)["reviewer"] == "weavert-scenario-coding"
    assert dict(report.assembly_anchors.definition_owners)["verifier"] == "weavert-scenario-coding"
    assert dict(report.assembly_anchors.definition_owners)["coding-loop"] == "weavert-scenario-coding"
    assert dict(report.assembly_anchors.definition_owners)["bash"] == "weavert-devtools"
    assert report.assembly_anchors.bash_builtin_owner == "weavert-devtools"
    assert report.assembly_anchors.bash_replacement_active is True
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


def test_run_demo_accepts_planner_side_inspection_without_parent_read_or_grep(tmp_path: Path) -> None:
    report, _layout = _scripted_run_report(tmp_path)
    parent_tool_names = [
        str(entry.get("tool_name") or "")
        for message in report.messages
        for entry in message.metadata.get("tool_results", ())
        if isinstance(message.metadata.get("tool_results"), list) and isinstance(entry, dict)
    ]

    assert report.ok is True
    assert report.workflow_gaps == ()
    assert "grep" not in parent_tool_names
    assert "read" not in parent_tool_names


def test_run_demo_surfaces_degraded_planner_as_advisory_when_shared_tasks_exist(tmp_path: Path) -> None:
    def _coding_loop_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-1",
            tool_name="skill",
            tool_input={"skill": "coding-loop"},
            call_id="call-skill",
        )

    def _planner_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-2",
            tool_name="agent",
            tool_input={
                "agent": "coding-planner",
                "max_turns": 8,
                "prompt": "Inspect only the necessary files, leave shared tasks, and summarize the plan.",
            },
            call_id="call-planner",
        )

    def _planner_task_list_one(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-1",
            tool_name="task_list",
            tool_input={},
            call_id="call-planner-task-list-1",
        )

    def _planner_grep_one(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-2",
            tool_name="grep",
            tool_input={"pattern": "DEFAULT_NAME", "path": "src"},
            call_id="call-planner-grep-1",
        )

    def _planner_task_create_one(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-3",
            tool_name="task_create",
            tool_input={"subject": "Inspect the greeting implementation"},
            call_id="call-planner-task-create-1",
        )

    def _planner_task_create_two(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-4",
            tool_name="task_create",
            tool_input={"subject": "Update the greeting and add the live note"},
            call_id="call-planner-task-create-2",
        )

    def _planner_task_list_two(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-5",
            tool_name="task_list",
            tool_input={},
            call_id="call-planner-task-list-2",
        )

    def _planner_grep_two(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-6",
            tool_name="grep",
            tool_input={"pattern": "Hello", "path": "tests"},
            call_id="call-planner-grep-2",
        )

    def _planner_task_list_three(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-7",
            tool_name="task_list",
            tool_input={},
            call_id="call-planner-task-list-3",
        )

    def _planner_grep_three(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-8",
            tool_name="grep",
            tool_input={"pattern": "greet", "path": "src/demo_service"},
            call_id="call-planner-grep-3",
        )

    def _task_list_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-3",
            tool_name="task_list",
            tool_input={},
            call_id="call-task-list",
        )

    def _edit_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-4",
            tool_name="edit",
            tool_input={
                "file_path": "src/demo_service/greeting.py",
                "old_string": 'DEFAULT_NAME = "runtime"',
                "new_string": 'DEFAULT_NAME = "WeaveRT"',
            },
            call_id="call-edit",
        )

    def _write_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-5",
            tool_name="write",
            tool_input={"file_path": "notes/live_demo.md", "content": "Degraded planning still left a usable plan.\n"},
            call_id="call-write",
        )

    def _bash_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-6",
            tool_name="bash",
            tool_input={"command": "python3 -m unittest discover -s tests", "description": "Run unit tests"},
            call_id="call-bash",
        )

    def _reviewer_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-7",
            tool_name="agent",
            tool_input={"agent": "reviewer", "prompt": "Review the final workspace."},
            call_id="call-reviewer",
        )

    def _reviewer_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "reviewer"
        return text_batch(request_id="req-reviewer-1", text="review: pass")

    def _verifier_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-8",
            tool_name="agent",
            tool_input={"agent": "verifier", "prompt": "Confirm the verification result."},
            call_id="call-verifier",
        )

    def _verifier_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "verifier"
        return text_batch(request_id="req-verifier-1", text="verification: pass")

    def _final_batch(request):
        _assert_code_assistant_request(request)
        return text_batch(request_id="req-code-9", text="completed despite planner degradation")

    report, _layout = _run_scripted_demo(
        tmp_path,
        [
            _coding_loop_batch,
            _planner_batch,
            _planner_task_list_one,
            _planner_grep_one,
            _planner_task_create_one,
            _planner_task_create_two,
            _planner_task_list_two,
            _planner_grep_two,
            _planner_task_list_three,
            _planner_grep_three,
            _task_list_batch,
            _edit_batch,
            _write_batch,
            _bash_batch,
            _reviewer_batch,
            _reviewer_child_batch,
            _verifier_batch,
            _verifier_child_batch,
            _final_batch,
        ],
    )

    assert report.ok is True
    assert report.workflow_gaps == ()
    assert report.child_runs[0]["agent"] == "coding-planner"
    assert report.child_runs[0]["status"] == "max_turns"
    assert len(report.workflow_advisories) == 1
    assert "planner degraded" in report.workflow_advisories[0]


def test_run_demo_rejects_late_inspection_after_the_first_material_edit(tmp_path: Path) -> None:
    def _coding_loop_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-1",
            tool_name="skill",
            tool_input={"skill": "coding-loop"},
            call_id="call-skill",
        )

    def _planner_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-2",
            tool_name="agent",
            tool_input={
                "agent": "coding-planner",
                "max_turns": 8,
                "prompt": "Create a short shared task plan before editing.",
            },
            call_id="call-planner",
        )

    def _planner_task_list_batch(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-1",
            tool_name="task_list",
            tool_input={},
            call_id="call-planner-task-list",
        )

    def _planner_task_create_batch(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-2",
            tool_name="task_create",
            tool_input={"subject": "Fix the greeting and note file"},
            call_id="call-planner-task-create",
        )

    def _planner_summary_batch(request):
        _assert_planner_request(request)
        return text_batch(request_id="req-planner-3", text="plan: make the greeting change, add the note, then verify")

    def _edit_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-3",
            tool_name="edit",
            tool_input={
                "file_path": "src/demo_service/greeting.py",
                "old_string": 'DEFAULT_NAME = "runtime"',
                "new_string": 'DEFAULT_NAME = "WeaveRT"',
            },
            call_id="call-edit",
        )

    def _read_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-4",
            tool_name="read",
            tool_input={"file_path": "src/demo_service/greeting.py"},
            call_id="call-read",
        )

    def _write_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-5",
            tool_name="write",
            tool_input={"file_path": "notes/live_demo.md", "content": "Late inspection should not pass validation.\n"},
            call_id="call-write",
        )

    def _bash_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-6",
            tool_name="bash",
            tool_input={"command": "python3 -m unittest discover -s tests", "description": "Run unit tests"},
            call_id="call-bash",
        )

    def _reviewer_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-7",
            tool_name="agent",
            tool_input={"agent": "reviewer", "prompt": "Review the final workspace."},
            call_id="call-reviewer",
        )

    def _reviewer_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "reviewer"
        return text_batch(request_id="req-reviewer-1", text="review: pass")

    def _verifier_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-8",
            tool_name="agent",
            tool_input={"agent": "verifier", "prompt": "Confirm the verification result."},
            call_id="call-verifier",
        )

    def _verifier_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "verifier"
        return text_batch(request_id="req-verifier-1", text="verification: pass")

    def _final_batch(request):
        _assert_code_assistant_request(request)
        return text_batch(request_id="req-code-9", text="completed with late inspection")

    report, _layout = _run_scripted_demo(
        tmp_path,
        [
            _coding_loop_batch,
            _planner_batch,
            _planner_task_list_batch,
            _planner_task_create_batch,
            _planner_summary_batch,
            _edit_batch,
            _read_batch,
            _write_batch,
            _bash_batch,
            _reviewer_batch,
            _reviewer_child_batch,
            _verifier_batch,
            _verifier_child_batch,
            _final_batch,
        ],
    )

    assert report.ok is False
    assert "repository inspection only happened after the first material edit" in report.workflow_gaps
    assert report.workflow_advisories == ()


def test_run_demo_does_not_let_parent_created_tasks_mask_planner_failure(tmp_path: Path) -> None:
    def _coding_loop_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-1",
            tool_name="skill",
            tool_input={"skill": "coding-loop"},
            call_id="call-skill",
        )

    def _planner_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-2",
            tool_name="agent",
            tool_input={
                "agent": "coding-planner",
                "max_turns": 8,
                "prompt": "Inspect briefly, then leave a visible shared plan before editing.",
            },
            call_id="call-planner",
        )

    def _planner_task_list_one(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-1",
            tool_name="task_list",
            tool_input={},
            call_id="call-planner-task-list-1",
        )

    def _planner_grep_one(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-2",
            tool_name="grep",
            tool_input={"pattern": "DEFAULT_NAME", "path": "src"},
            call_id="call-planner-grep-1",
        )

    def _planner_task_list_two(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-3",
            tool_name="task_list",
            tool_input={},
            call_id="call-planner-task-list-2",
        )

    def _planner_grep_two(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-4",
            tool_name="grep",
            tool_input={"pattern": "Hello", "path": "tests"},
            call_id="call-planner-grep-2",
        )

    def _planner_task_list_three(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-5",
            tool_name="task_list",
            tool_input={},
            call_id="call-planner-task-list-3",
        )

    def _planner_grep_three(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-6",
            tool_name="grep",
            tool_input={"pattern": "greet", "path": "src/demo_service"},
            call_id="call-planner-grep-3",
        )

    def _planner_task_list_four(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-7",
            tool_name="task_list",
            tool_input={},
            call_id="call-planner-task-list-4",
        )

    def _planner_grep_four(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-8",
            tool_name="grep",
            tool_input={"pattern": "notes", "path": "."},
            call_id="call-planner-grep-4",
        )

    def _task_create_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-3",
            tool_name="task_create",
            tool_input={"subject": "Parent-created fallback task"},
            call_id="call-parent-task-create",
        )

    def _grep_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-4",
            tool_name="grep",
            tool_input={"pattern": "DEFAULT_NAME", "path": "src"},
            call_id="call-parent-grep",
        )

    def _edit_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-5",
            tool_name="edit",
            tool_input={
                "file_path": "src/demo_service/greeting.py",
                "old_string": 'DEFAULT_NAME = "runtime"',
                "new_string": 'DEFAULT_NAME = "WeaveRT"',
            },
            call_id="call-edit",
        )

    def _write_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-6",
            tool_name="write",
            tool_input={"file_path": "notes/live_demo.md", "content": "Parent-created tasks should not hide planner failure.\n"},
            call_id="call-write",
        )

    def _bash_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-7",
            tool_name="bash",
            tool_input={"command": "python3 -m unittest discover -s tests", "description": "Run unit tests"},
            call_id="call-bash",
        )

    def _reviewer_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-8",
            tool_name="agent",
            tool_input={"agent": "reviewer", "prompt": "Review the final workspace."},
            call_id="call-reviewer",
        )

    def _reviewer_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "reviewer"
        return text_batch(request_id="req-reviewer-1", text="review: pass")

    def _verifier_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-9",
            tool_name="agent",
            tool_input={"agent": "verifier", "prompt": "Confirm the verification result."},
            call_id="call-verifier",
        )

    def _verifier_child_batch(request):
        assert request.agent is not None
        assert request.agent.name == "verifier"
        return text_batch(request_id="req-verifier-1", text="verification: pass")

    def _final_batch(request):
        _assert_code_assistant_request(request)
        return text_batch(request_id="req-code-10", text="completed with parent-created fallback tasks")

    report, _layout = _run_scripted_demo(
        tmp_path,
        [
            _coding_loop_batch,
            _planner_batch,
            _planner_task_list_one,
            _planner_grep_one,
            _planner_task_list_two,
            _planner_grep_two,
            _planner_task_list_three,
            _planner_grep_three,
            _planner_task_list_four,
            _planner_grep_four,
            _task_create_batch,
            _grep_batch,
            _edit_batch,
            _write_batch,
            _bash_batch,
            _reviewer_batch,
            _reviewer_child_batch,
            _verifier_batch,
            _verifier_child_batch,
            _final_batch,
        ],
    )

    assert report.ok is False
    assert report.child_runs[0]["status"] == "max_turns"
    assert (
        "the coding-planner child run ended with status 'max_turns' without leaving a planner-authored shared plan outcome"
        in report.workflow_gaps
    )
    assert report.workflow_advisories == ()


def test_inspection_outcome_accepts_same_message_read_before_edit() -> None:
    created_at = datetime(2026, 5, 2, tzinfo=timezone.utc)
    message = RuntimeMessage(
        message_id="same-message-inspection",
        role=MessageRole.USER,
        created_at=created_at,
        content=(
            ToolResultBlock(
                tool_use_id="call-read",
                content={"file_path": "src/demo_service/greeting.py"},
            ),
            ToolResultBlock(
                tool_use_id="call-edit",
                content={"updated": True},
            ),
        ),
        metadata={
            "tool_results": [
                {"tool_use_id": "call-read", "tool_name": "read", "status": "success"},
                {"tool_use_id": "call-edit", "tool_name": "edit", "status": "success"},
            ]
        },
    )

    outcome = _inspection_outcome(_tool_result_events([message], scope="parent"))

    assert outcome.satisfied is True
    assert outcome.late_only is False


def test_workflow_validation_ignores_previous_turn_planner_evidence() -> None:
    base = datetime(2026, 5, 2, tzinfo=timezone.utc)
    old_planner_record = AgentRunRecord(
        run_id="planner-old",
        parent_run_id="parent-old",
        session_id="shared-session",
        parent_turn_id="turn-old",
        turn_id="planner-turn-old",
        agent_name="coding-planner",
        spawn_mode=SpawnMode.SYNC,
        status=AgentRunStatus.COMPLETED,
        messages=(
            RuntimeMessage(
                message_id="planner-old-tools",
                role=MessageRole.USER,
                created_at=base,
                content=(
                    ToolResultBlock(tool_use_id="old-task-list", content={"tasks": []}),
                    ToolResultBlock(tool_use_id="old-grep", content={"matches": []}),
                    ToolResultBlock(
                        tool_use_id="old-task-create",
                        content={"task": {"task_id": "task-old"}},
                    ),
                ),
                metadata={
                    "tool_results": [
                        {
                            "tool_use_id": "old-task-list",
                            "tool_name": "task_list",
                            "status": "success",
                        },
                        {
                            "tool_use_id": "old-grep",
                            "tool_name": "grep",
                            "status": "success",
                        },
                        {
                            "tool_use_id": "old-task-create",
                            "tool_name": "task_create",
                            "status": "success",
                        },
                    ]
                },
            ),
            RuntimeMessage(
                message_id="planner-old-summary",
                role=MessageRole.ASSISTANT,
                created_at=base + timedelta(seconds=1),
                content="plan: inspect, edit, verify",
            ),
        ),
    )
    reviewer_record = AgentRunRecord(
        run_id="reviewer-current",
        parent_run_id="parent-current",
        session_id="shared-session",
        parent_turn_id="turn-current",
        turn_id="reviewer-turn-current",
        agent_name="reviewer",
        spawn_mode=SpawnMode.SYNC,
        status=AgentRunStatus.COMPLETED,
    )
    verifier_record = AgentRunRecord(
        run_id="verifier-current",
        parent_run_id="parent-current",
        session_id="shared-session",
        parent_turn_id="turn-current",
        turn_id="verifier-turn-current",
        agent_name="verifier",
        spawn_mode=SpawnMode.SYNC,
        status=AgentRunStatus.COMPLETED,
    )
    messages = [
        RuntimeMessage(
            message_id="skill",
            role=MessageRole.USER,
            created_at=base + timedelta(minutes=10),
            content=(
                ToolResultBlock(
                    tool_use_id="call-skill",
                    content={"skill": "coding-loop", "mode": "inline"},
                ),
            ),
            metadata={
                "tool_results": [
                    {"tool_use_id": "call-skill", "tool_name": "skill", "status": "success"},
                ]
            },
        ),
        RuntimeMessage(
            message_id="edit",
            role=MessageRole.USER,
            created_at=base + timedelta(minutes=11),
            content=(ToolResultBlock(tool_use_id="call-edit", content={"updated": True}),),
            metadata={
                "tool_results": [
                    {"tool_use_id": "call-edit", "tool_name": "edit", "status": "success"},
                ]
            },
        ),
        RuntimeMessage(
            message_id="write",
            role=MessageRole.USER,
            created_at=base + timedelta(minutes=12),
            content=(ToolResultBlock(tool_use_id="call-write", content={"changed": True}),),
            metadata={
                "tool_results": [
                    {"tool_use_id": "call-write", "tool_name": "write", "status": "success"},
                ]
            },
        ),
        RuntimeMessage(
            message_id="bash",
            role=MessageRole.USER,
            created_at=base + timedelta(minutes=13),
            content=(
                ToolResultBlock(
                    tool_use_id="call-bash",
                    content={
                        "classification": "test",
                        "status": "completed",
                        "exit_code": 0,
                    },
                ),
            ),
            metadata={
                "tool_results": [
                    {"tool_use_id": "call-bash", "tool_name": "bash", "status": "success"},
                ]
            },
        ),
        RuntimeMessage(
            message_id="final",
            role=MessageRole.ASSISTANT,
            created_at=base + timedelta(minutes=14),
            content="done",
        ),
    ]

    validation = _workflow_validation_result(
        messages=messages,
        approvals=[
            ApprovalRecord(
                session_id="shared-session",
                target="edit",
                name="edit",
                approved=True,
                summary="ok",
                payload={},
            ),
            ApprovalRecord(
                session_id="shared-session",
                target="write",
                name="write",
                approved=True,
                summary="ok",
                payload={},
            ),
            ApprovalRecord(
                session_id="shared-session",
                target="bash",
                name="bash",
                approved=True,
                summary="ok",
                payload={},
            ),
        ],
        child_run_records=[old_planner_record, reviewer_record, verifier_record],
        task_list={"tasks": [{"task_id": "task-old", "subject": "Previous planner task"}]},
        final_text="done",
        workflow_ledger=WorkflowLedger(
            change_revision=2,
            verified_revision=2,
            reviewed_revision=2,
            current_state="ready_to_summarize",
        ),
        current_turn_id="turn-current",
    )

    assert validation.workflow_gaps == (
        "the shared task list was never inspected",
        "the coding-planner child run never executed",
        "the workflow never used glob, grep, or read before the first material edit",
    )
    assert validation.workflow_advisories == ()


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
                    "command": "sleep 30",
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
    assert report.workflow_ledger.current_state == "clean"
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


def test_shell_inspect_highlights_live_current_session_over_persisted_history(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    seed_client = ScriptedModelClient([text_batch(request_id="req-seed-1", text="seeded transcript")])
    asyncio.run(
        run_demo(
            prompt="Seed a persisted transcript.",
            session_id="persisted-session",
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
            session_id="live-shell",
            auto_approve=True,
            layout=layout,
            model_client=idle_client,
            input_reader=_iter_input(["/inspect", "/exit"]),
            output_writer=output_lines.append,
        )
    )

    assert report.ok is True
    assert any("transcript sessions: 2" in line for line in output_lines)
    assert any("current transcript: live-shell" in line for line in output_lines)
    assert not any("latest transcript:" in line for line in output_lines)
    assert any("workflow: clean" in line for line in output_lines)


def test_shell_inspect_tasks_and_jobs_are_host_owned(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    output_lines: list[str] = []
    idle_client = ScriptedModelClient([])

    report = asyncio.run(
        shell_demo(
            auto_approve=True,
            layout=layout,
            model_client=idle_client,
            input_reader=_iter_input(["/inspect", "/tasks", "/jobs", "/exit"]),
            output_writer=output_lines.append,
        )
    )

    assert report.ok is True
    assert report.prompt_count == 0
    assert report.local_commands == ("inspect", "tasks", "jobs", "exit")
    assert len(idle_client.requests) == 0
    assert any("code assistant inspect" in line for line in output_lines)
    assert any("transcript sessions: 1" in line for line in output_lines)
    assert any(f"current transcript: {report.session_id}" in line for line in output_lines)
    assert any("task lists: 1" in line for line in output_lines)
    assert f"current task list: session:{report.session_id}" in output_lines
    assert f"task list: session:{report.session_id}" in output_lines
    assert any("jobs: 0" in line for line in output_lines)


def test_print_task_list_prefers_list_id_and_falls_back_to_task_list_id() -> None:
    output_lines: list[str] = []

    _print_task_list(
        task_list={
            "list_id": "session:preferred",
            "task_list_id": "session:legacy",
            "tasks": [],
        },
        output_writer=output_lines.append,
    )
    _print_task_list(
        task_list={
            "task_list_id": "session:fallback",
            "tasks": [],
        },
        output_writer=output_lines.append,
    )

    assert output_lines == [
        "task list: session:preferred",
        "no shared tasks yet",
        "task list: session:fallback",
        "no shared tasks yet",
    ]


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
                "command": "sleep 30",
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
    assert foreground["command_policy"] == "requires_high_risk_approval"
    assert foreground["status"] == "completed"
    assert foreground["stdout"] == "hi"
    assert foreground["stdout_preview"] == "hi"
    assert foreground["output_summary"] == "hi"

    assert background["status"] == "running"
    assert background["job_id"] is not None
    assert background["background_reason"] == "requested"
    assert background["session_profile"] == "background"
    assert background["recovery_state"] == "attached"
    assert background["sidecar_dir"]

    assert any(job["job_id"] == background["job_id"] for job in jobs)
    assert stopped["status"] == "stopped"
    assert stopped["result"]["status"] == "stopped"


def test_replacement_bash_v2_session_lifecycle_and_unsupported_tui(tmp_path: Path) -> None:
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
        start = await bash_tool.execute(
            {"action": "start", "command": "cat", "description": "Start an echo session"},
            context,
        )
        shell_session_id = start["shell_session_id"]
        assert isinstance(shell_session_id, str) and shell_session_id
        send = await bash_tool.execute(
            {
                "action": "send",
                "shell_session_id": shell_session_id,
                "stdin": "hello from session\n",
            },
            context,
        )
        await asyncio.sleep(0.1)
        read = await bash_tool.execute(
            {"action": "read", "shell_session_id": shell_session_id},
            context,
        )
        stop = await bash_tool.execute(
            {"action": "stop", "shell_session_id": shell_session_id},
            context,
        )
        interrupt_start = await bash_tool.execute(
            {"action": "start", "command": "cat", "description": "Start an interruptible session"},
            context,
        )
        interrupt_session_id = interrupt_start["shell_session_id"]
        interrupt = await bash_tool.execute(
            {"action": "interrupt", "shell_session_id": interrupt_session_id},
            context,
        )
        await asyncio.sleep(0.05)
        interrupt_stop = await bash_tool.execute(
            {"action": "stop", "shell_session_id": interrupt_session_id},
            context,
        )
        unsupported = await bash_tool.execute(
            {"action": "start", "command": "vim src/demo_service/greeting.py"},
            context,
        )
        jobs_result = await runtime.list_jobs(session_id="shell-test")
        return start, send, read, stop, interrupt, interrupt_stop, unsupported, jobs_result

    start, send, read, stop, interrupt, interrupt_stop, unsupported, jobs = asyncio.run(scenario())
    stop_payload = _result_payload(stop)
    interrupt_stop_payload = _result_payload(interrupt_stop)
    unsupported_payload = _result_payload(unsupported)

    assert start["action"] == "start"
    assert start["session_mode"] == "session"
    assert start["session_profile"] == "line_session"
    assert start["session_status"] == "running"
    assert start["recovery_state"] == "attached"
    assert start["sidecar_dir"]
    assert start["session_output_complete"] is False
    assert send["action"] == "send"
    assert "hello from session" in str(read["session_output"])
    assert read["shell_session_id"] == start["shell_session_id"]
    assert stop_payload["status"] in {"stopped", "completed", "command_failed"}
    assert interrupt["action"] == "interrupt"
    assert interrupt["shell_session_id"] == interrupt_stop_payload["shell_session_id"]
    assert interrupt_stop_payload["status"] in {"stopped", "completed", "command_failed"}
    assert unsupported_payload["status"] == "unsupported"
    assert unsupported_payload["unsupported_shell"] is True
    assert "intentionally unsupported" in str(unsupported_payload["unsupported_reason"])
    assert any(job["metadata"].get("shell_session_id") == start["shell_session_id"] for job in jobs)


def test_replacement_bash_session_stop_falls_back_to_kill_when_term_is_ignored(tmp_path: Path) -> None:
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
        start = await bash_tool.execute(
            {"action": "start", "command": "trap '' TERM; while true; do sleep 1; done"},
            context,
        )
        stop = await asyncio.wait_for(
            bash_tool.execute(
                {"action": "stop", "shell_session_id": start["shell_session_id"]},
                context,
            ),
            timeout=2,
        )
        return _result_payload(stop)

    stop_payload = asyncio.run(scenario())

    assert stop_payload["status"] == "stopped"
    assert stop_payload["session_status"] == "stopped"


def test_replacement_bash_interrupt_projects_as_stopped_job(tmp_path: Path) -> None:
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
        start = await bash_tool.execute(
            {"action": "start", "command": "cat", "description": "Interruptible session"},
            context,
        )
        shell_session_id = start["shell_session_id"]
        await bash_tool.execute(
            {"action": "interrupt", "shell_session_id": shell_session_id},
            context,
        )
        await asyncio.sleep(0.2)
        read = await bash_tool.execute(
            {"action": "read", "shell_session_id": shell_session_id},
            context,
        )
        jobs = await runtime.list_jobs(session_id="shell-test")
        return read, jobs

    read, jobs = asyncio.run(scenario())

    assert read["status"] == "interrupted"
    assert read["session_output_complete"] is True
    assert "is interrupted" in read["output_summary"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "stopped"
    assert jobs[0]["error"] is None
    assert jobs[0]["result"]["status"] == "interrupted"


def test_replacement_bash_background_stop_falls_back_to_kill_when_term_is_ignored(tmp_path: Path) -> None:
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
        background = await bash_tool.execute(
            {
                "command": "trap '' TERM; while true; do sleep 1; done",
                "run_in_background": True,
            },
            context,
        )
        stopped = await asyncio.wait_for(
            runtime.stop_job(background["job_id"], session_id="shell-test"),
            timeout=2,
        )
        return stopped

    stopped = asyncio.run(scenario())

    assert stopped["status"] == "stopped"
    assert stopped["result"]["status"] == "stopped"


def test_replacement_bash_blocks_workspace_escapes(tmp_path: Path) -> None:
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
    outside_path = tmp_path / "outside-proof.txt"

    async def scenario():
        absolute_read = await bash_tool.execute(
            {"command": "cat /etc/hosts", "description": "Read outside workspace"},
            context,
        )
        inline_write = await bash_tool.execute(
            {
                "command": (
                    "python3 -c \"from pathlib import Path; "
                    f"Path('{outside_path}').write_text('outside proof', encoding='utf-8')\""
                ),
                "description": "Write outside workspace",
            },
            context,
        )
        return absolute_read, inline_write

    absolute_read, inline_write = asyncio.run(scenario())
    absolute_payload = _result_payload(absolute_read)
    inline_payload = _result_payload(inline_write)

    assert absolute_payload["status"] == "blocked"
    assert "outside the workspace" in str(absolute_payload["stderr"])
    assert inline_payload["status"] == "not_confinable"
    assert inline_payload["command_policy"] == "not_confinable"
    assert "inline interpreter command" in str(inline_payload["stderr"])
    assert not outside_path.exists()


def test_replacement_bash_classifies_common_test_commands() -> None:
    assert _classify_command("python3 -m pytest -q").name == "test"
    assert _classify_command("uv run pytest -q").name == "test"
    assert _classify_command("poetry run pytest -q").name == "test"
    assert _classify_command("npm run build").name == "build"
    assert _classify_command("pnpm run lint").name == "lint"
    assert _classify_command("make test").name == "test"
    assert _classify_command("cargo test").name == "test"
    assert _classify_command("go test ./...").name == "test"


def test_replacement_bash_reports_command_failed_without_hiding_payload(tmp_path: Path) -> None:
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
        return await bash_tool.execute(
            {"command": "ls definitely-missing"},
            context,
        )

    result = asyncio.run(scenario())
    payload = _result_payload(result)

    assert payload["status"] == "command_failed"
    assert payload["error_kind"] == "command_failed"
    assert payload["exit_code"] != 0
    assert "definitely-missing" in payload["stderr"]


def test_replacement_bash_reconnects_to_broker_backed_session_after_runtime_restart(tmp_path: Path) -> None:
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
        start = await bash_tool.execute(
            {"action": "start", "command": "cat", "description": "Restart-aware session"},
            context,
        )
        await bash_tool.execute(
            {
                "action": "send",
                "shell_session_id": start["shell_session_id"],
                "stdin": "after restart\n",
            },
            context,
        )
        await asyncio.sleep(0.1)
        restarted_runtime = assemble_demo_runtime(layout=layout)
        restarted_tool = restarted_runtime.kernel.tool_registry.get("bash")
        restarted_context = ToolContext(
            session_id="shell-test",
            turn_id="turn-2",
            agent_name="code-assistant",
            cwd=layout.workspace_root,
            tool_registry=restarted_runtime.kernel.tool_registry,
            runtime_services=restarted_runtime.services,
        )
        read = await restarted_tool.execute(
            {"action": "read", "shell_session_id": start["shell_session_id"]},
            restarted_context,
        )
        stop = await restarted_tool.execute(
            {"action": "stop", "shell_session_id": start["shell_session_id"]},
            restarted_context,
        )
        return start, read, stop

    start, read, stop = asyncio.run(scenario())
    stop_payload = _result_payload(stop)

    assert start["recovery_state"] == "attached"
    assert "after restart" in str(read["session_output"])
    assert read["session_profile"] == "line_session"
    assert stop_payload["status"] in {"stopped", "completed", "command_failed"}


def test_replacement_bash_sync_restart_reconciles_running_background_shell(tmp_path: Path) -> None:
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
        background = await bash_tool.execute(
            {
                "command": "sleep 30",
                "description": "Restart-aware background shell",
                "run_in_background": True,
            },
            context,
        )
        return background["job_id"]

    job_id = asyncio.run(scenario())

    restarted_runtime = assemble_demo_runtime(layout=layout)
    record = restarted_runtime.services.job_service.get_sync(job_id)

    assert record is not None
    assert record.status.value == "running"
    assert record.metadata["recovery_state"] == "reattached"
    assert restarted_runtime.services.job_service.compat_stop_handler(job_id) is not None

    async def stop_after_restart():
        return await restarted_runtime.stop_job(job_id, session_id="shell-test")

    stopped = asyncio.run(stop_after_restart())

    assert stopped["status"] == "stopped"
    assert stopped["result"]["status"] == "stopped"


def test_replacement_bash_marks_background_shell_orphaned_when_broker_dies_before_restart(tmp_path: Path) -> None:
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
        background = await bash_tool.execute(
            {
                "command": "sleep 30",
                "description": "Broker-loss background shell",
                "run_in_background": True,
            },
            context,
        )
        record = runtime.services.job_service.get_sync(background["job_id"])
        assert record is not None
        return background["job_id"], int(background["broker_pid"]), int(record.metadata["pid"])

    job_id, broker_pid, process_pid = asyncio.run(scenario())
    os.kill(process_pid, 0)
    os.kill(broker_pid, signal.SIGKILL)
    asyncio.run(asyncio.sleep(0.1))

    restarted_runtime = assemble_demo_runtime(layout=layout)
    record = restarted_runtime.services.job_service.get_sync(job_id)

    assert record is not None
    assert record.status.value == "failed"
    assert record.result["status"] == "orphaned"
    assert record.result["recovery_state"] == "orphaned"
    assert "reconciled explicitly after runtime restart" in str(record.error)


def test_inspect_demo_reports_shell_sidecars_and_reset_clears_them(tmp_path: Path) -> None:
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
        start = await bash_tool.execute({"action": "start", "command": "cat"}, context)
        await bash_tool.execute(
            {"action": "stop", "shell_session_id": start["shell_session_id"]},
            context,
        )
        return start

    start = asyncio.run(scenario())
    inspect_before = inspect_demo(layout=layout)

    assert inspect_before.shell_sidecars
    assert any(sidecar.get("shell_session_id") == start["shell_session_id"] for sidecar in inspect_before.shell_sidecars)

    reset_demo_state(layout=layout)
    inspect_after = inspect_demo(layout=layout)

    assert inspect_after.shell_sidecars == ()


def test_shell_demo_renders_reactive_session_and_watcher_updates(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    output_lines: list[str] = []

    def _start_batch(_request):
        return tool_call_batch(
            request_id="req-shell-v2-1",
            tool_name="bash",
            tool_input={
                "action": "start",
                "command": "cat",
                "description": "Start a reactive shell session",
            },
            call_id="call-shell-start",
        )

    client = ScriptedModelClient(
        [
            _start_batch,
            text_batch(request_id="req-shell-v2-2", text="session output captured"),
        ]
    )

    report = asyncio.run(
        shell_demo(
            auto_approve=True,
            layout=layout,
            model_client=client,
            input_reader=_iter_input(
                [
                    "Start a live shell session.",
                    "/jobs",
                    "/exit",
                ]
            ),
            output_writer=output_lines.append,
        )
    )

    assert report.ok is True
    assert report.job_watch_events
    assert report.task_watch_events
    assert report.workflow_events
    assert any(event["metadata"].get("shell_session_id") for event in report.job_watch_events)
    assert any("[job:running]" in line for line in output_lines)


def test_shell_demo_warns_on_exit_when_latest_change_is_pending_verification(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    output_lines: list[str] = []
    client = ScriptedModelClient(
        [
            tool_call_batch(
                request_id="req-workflow-1",
                tool_name="edit",
                tool_input={
                    "file_path": "src/demo_service/greeting.py",
                    "old_string": 'DEFAULT_NAME = "runtime"',
                    "new_string": 'DEFAULT_NAME = "WeaveRT"',
                },
                call_id="call-workflow-edit",
            ),
            text_batch(request_id="req-workflow-2", text="edited the greeting"),
        ]
    )

    report = asyncio.run(
        shell_demo(
            auto_approve=True,
            layout=layout,
            model_client=client,
            input_reader=_iter_input(["Change the greeting.", "/exit"]),
            output_writer=output_lines.append,
        )
    )

    assert report.ok is True
    assert report.workflow_ledger.current_state == "pending_verification"
    assert any("pending_verification" in warning for warning in report.workflow_warnings)
    assert any("[workflow:warning]" in line for line in output_lines)


def test_shell_demo_warns_when_assistant_response_leaves_pending_verification(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    output_lines: list[str] = []
    client = ScriptedModelClient(
        [
            tool_call_batch(
                request_id="req-workflow-1",
                tool_name="edit",
                tool_input={
                    "file_path": "src/demo_service/greeting.py",
                    "old_string": 'DEFAULT_NAME = "runtime"',
                    "new_string": 'DEFAULT_NAME = "WeaveRT"',
                },
                call_id="call-workflow-edit",
            ),
            text_batch(request_id="req-workflow-2", text="Done. Updated the greeting."),
        ]
    )

    report = asyncio.run(
        shell_demo(
            auto_approve=True,
            layout=layout,
            model_client=client,
            input_reader=_iter_input_then_eof(["Change the greeting."]),
            output_writer=output_lines.append,
        )
    )

    assert report.ok is True
    assert report.workflow_ledger.current_state == "pending_verification"
    assert any("pending_verification" in warning for warning in report.workflow_warnings)
    assert any("Assistant response" in warning for warning in report.workflow_warnings)
    assert any("[workflow:warning]" in line for line in output_lines)


def test_shell_demo_ignores_noop_write_when_computing_workflow_revisions(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    output_lines: list[str] = []
    content = (layout.workspace_root / "src" / "demo_service" / "greeting.py").read_text(encoding="utf-8")
    client = ScriptedModelClient(
        [
            tool_call_batch(
                request_id="req-write-1",
                tool_name="write",
                tool_input={
                    "file_path": "src/demo_service/greeting.py",
                    "content": content,
                },
                call_id="call-write-same",
            ),
            text_batch(request_id="req-write-2", text="Rewrote the greeting file."),
        ]
    )

    report = asyncio.run(
        shell_demo(
            auto_approve=True,
            layout=layout,
            model_client=client,
            input_reader=_iter_input_then_eof(["Rewrite the greeting file."]),
            output_writer=output_lines.append,
        )
    )

    assert report.ok is True
    assert report.workflow_ledger.current_state == "clean"
    assert report.workflow_ledger.change_revision == 0
    assert report.workflow_warnings == ()


def test_run_demo_surfaces_missing_live_credentials_without_fallback(tmp_path: Path, monkeypatch) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    monkeypatch.setenv("OPENAI_MODEL", "ambient-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.invalid/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

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


def test_run_demo_succeeds_through_bundled_openai_route_when_stream_is_stubbed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    layout = _layout(tmp_path)
    reset_demo_state(layout=layout)

    def fake_post_json_stream(_url: str, _payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        return iter(
            [
                {"type": "response.created", "response": {"id": "resp-code-assistant-live"}},
                {"type": "response.output_text.delta", "delta": "Hello "},
                {"type": "response.output_text.delta", "delta": "from live route"},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp-code-assistant-live",
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": "Hello from live route"}],
                            }
                        ],
                        "usage": {"input_tokens": 6, "output_tokens": 4},
                    },
                },
            ]
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert_openai.openai_client._post_json_stream", fake_post_json_stream)

    report = asyncio.run(
        run_demo(
            prompt="Say hello.",
            auto_approve=True,
            validate_workflow=False,
            layout=layout,
            output_writer=lambda _line: None,
        )
    )

    assert report.ok is True
    assert report.default_model_route == OPENAI_ROUTE_NAME
    assert report.final_text == "Hello from live route"
    assert report.task_list_id == f"session:{report.session_id}"
    assert report.transcript_path.exists()


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
    assert "the coding-loop skill was not applied" in report.workflow_gaps
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
    assert any(record["summary"] == "review: pass" for record in inspect_before.child_run_records)
    assert inspect_before.task_lists[0]["tasks"][0]["subject"] == "Inspect the failing greeting flow"
    assert inspect_before.memory_root == layout.workspace_root / ".weavert" / "memory"
    assert inspect_before.assembly_anchors is not None
    assert inspect_before.assembly_anchors.package_manifests == (
        "weavert-scenario-coding",
        "weavert-shared-git",
        "weavert-shared-workspace-intelligence",
    )
    assert dict(inspect_before.assembly_anchors.tool_family_owners) == {
        "git_*": "weavert-shared-git",
        "workspace_*": "weavert-shared-workspace-intelligence",
    }
    assert set(inspect_before.changed_files) == {
        "notes/live_demo.md",
        "src/demo_service/greeting.py",
    }
    assert not any(
        "__pycache__" in path or path.endswith((".pyc", ".pyo")) or path.startswith(".weavert/")
        for path in inspect_before.changed_files
    )

    reset_demo_state(layout=layout)
    inspect_after = inspect_demo(layout=layout)

    assert inspect_after.workspace_exists is True
    assert inspect_after.transcript_sessions == ()
    assert inspect_after.child_run_sessions == ()
    assert inspect_after.child_run_records == ()
    assert inspect_after.task_lists == ()


def test_code_assistant_cli_respects_state_root_override_and_runs_shell_commands(tmp_path: Path) -> None:
    env = _cli_env(tmp_path)
    state_root = tmp_path / "cli-state"

    reset = _run_code_assistant_cli("reset", env=env)
    assert reset.returncode == 0
    assert f"workspace: {state_root / 'mini_repo'}" in reset.stdout

    inspect = _run_code_assistant_cli("inspect", env=env)
    assert inspect.returncode == 0
    assert f"state root: {state_root}" in inspect.stdout
    assert f"workspace: {state_root / 'mini_repo'}" in inspect.stdout

    shell = _run_code_assistant_cli(
        "shell",
        "--session-id",
        "cli-shell",
        "--auto-approve",
        env=env,
        input_text="/inspect\n/tasks\n/jobs\n/exit\n",
    )
    assert shell.returncode == 0
    assert "code assistant demo shell" in shell.stdout
    assert "current transcript: cli-shell" in shell.stdout
    assert "current task list: session:cli-shell" in shell.stdout
    assert "jobs: 0" in shell.stdout
    assert "workflow: clean (change=0, verified=0, reviewed=0)" in shell.stdout
    assert f"transcript: {state_root / 'mini_repo' / '.weavert' / 'transcripts' / 'cli-shell.jsonl'}" in shell.stdout
    assert "status: ok" in shell.stdout


def test_code_assistant_cli_deterministic_run_succeeds_without_provider_credentials(tmp_path: Path) -> None:
    env = _cli_env(tmp_path)
    state_root = tmp_path / "cli-state"

    completed = _run_code_assistant_cli(
        "run",
        "--deterministic",
        "--session-id",
        "cli-deterministic",
        "--auto-approve",
        env=env,
    )

    assert completed.returncode == 0
    assert "code assistant demo run" in completed.stdout
    assert "mode: deterministic" in completed.stdout
    assert "task list: session:cli-deterministic" in completed.stdout
    assert "workflow: ready_to_summarize (change=2, verified=2, reviewed=2)" in completed.stdout
    assert (
        "package manifests: weavert-scenario-coding, weavert-shared-git, "
        "weavert-shared-workspace-intelligence"
    ) in completed.stdout
    assert "tool families: git_*=weavert-shared-git, workspace_*=weavert-shared-workspace-intelligence" in completed.stdout
    assert "definition owners: code-assistant=app" in completed.stdout
    assert "coding-planner=weavert-scenario-coding" in completed.stdout
    assert "reviewer=weavert-scenario-coding" in completed.stdout
    assert "verifier=weavert-scenario-coding" in completed.stdout
    assert "coding-loop=weavert-scenario-coding" in completed.stdout
    assert "bash replacement: app-configured v2 over weavert-devtools" in completed.stdout
    assert (
        f"transcript: {state_root / 'mini_repo' / '.weavert' / 'transcripts' / 'cli-deterministic.jsonl'}"
        in completed.stdout
    )
    assert (
        f"child run index: {state_root / 'mini_repo' / '.weavert' / 'child_runs' / 'sessions' / 'cli-deterministic.json'}"
        in completed.stdout
    )
    assert "status: ok" in completed.stdout


def test_code_assistant_cli_run_surfaces_auth_failure_in_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    monkeypatch.setenv("OPENAI_MODEL", "ambient-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.invalid/v1")
    env = _cli_env(tmp_path)
    assert "OPENAI_API_KEY" not in env
    assert "OPENAI_MODEL" not in env
    assert "OPENAI_BASE_URL" not in env

    completed = _run_code_assistant_cli(
        "run",
        "--session-id",
        "cli-run",
        "--auto-approve",
        "--prompt",
        "Say hello.",
        env=env,
    )

    assert completed.returncode == 2
    assert "code assistant demo run" in completed.stdout
    assert "default route: openai_default" in completed.stdout
    assert "error: Bundled OpenAI route 'openai_default' requires OPENAI_API_KEY" in completed.stdout


def test_code_assistant_cli_run_prints_workflow_advisories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = RunReport(
        session_id="cli-advisory",
        workspace_root=tmp_path / "workspace",
        fixture_root=tmp_path / "fixture",
        distribution=RuntimeDistribution.FULL.value,
        default_model_route=OPENAI_ROUTE_NAME,
        persistence_profile={},
        messages=(),
        final_text="completed coding shell workflow",
        approvals=(),
        child_runs=(
            {
                "agent": "coding-planner",
                "status": "max_turns",
                "summary": "planner stopped after leaving shared tasks",
            },
        ),
        task_list_id="session:cli-advisory",
        task_list={"tasks": []},
        transcript_path=tmp_path / "workspace" / "transcript.jsonl",
        child_run_index_path=tmp_path / "workspace" / "child-runs.json",
        memory_root=tmp_path / "workspace" / "memory",
        notification_texts=(),
        terminal_stop_reason=None,
        terminal_metadata={},
        workflow_ledger=WorkflowLedger(
            change_revision=2,
            verified_revision=2,
            reviewed_revision=2,
            current_state="ready_to_summarize",
        ),
        workflow_gaps=(),
        workflow_advisories=("planner degraded: the coding-planner child run ended with status 'max_turns'",),
        workflow_warnings=(),
        ok=True,
        error_message=None,
    )

    async def _fake_run_demo(**_kwargs):
        return report

    monkeypatch.setattr(code_assistant_main, "run_demo", _fake_run_demo)
    monkeypatch.setattr(sys, "argv", ["code_assistant", "run", "--auto-approve"])

    exit_code = code_assistant_main.main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "workflow advisories: 1" in output
    assert "planner degraded: the coding-planner child run ended with status 'max_turns'" in output


def test_code_assistant_readme_documents_live_deterministic_and_shell_smoke_paths() -> None:
    readme = CODE_ASSISTANT_README.read_text(encoding="utf-8")

    assert "## Split ownership model" in readme
    assert "python3 -B -m examples.apps.code_assistant run \\" in readme
    assert "--deterministic \\" in readme
    assert "python3 -B -m examples.apps.code_assistant shell --session-id local-shell --auto-approve" in readme
    assert "`mode: live` or `mode: deterministic`" in readme
    assert "package manifests: weavert-scenario-coding, weavert-shared-git, weavert-shared-workspace-intelligence" in readme
    assert "tool families: git_*=weavert-shared-git, workspace_*=weavert-shared-workspace-intelligence" in readme
    assert "bash replacement: app-configured v2 over weavert-devtools" in readme
    assert "durable shell sidecars under `.weavert/shell/`" in readme
    assert "wrapper-aware command policy" in readme
    assert "`command_failed`" in readme
