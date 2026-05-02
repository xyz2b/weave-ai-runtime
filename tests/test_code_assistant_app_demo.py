from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from demos._shared.common import extract_tool_result
from demos._shared.scripted_model import ScriptedModelClient, text_batch, tool_call_batch
from demos.apps.code_assistant.app import (
    CODE_ASSISTANT_STATE_ROOT_ENV,
    _print_task_list,
    assemble_demo_runtime,
    default_layout,
    inspect_demo,
    reset_demo_state,
    run_demo,
    shell_demo,
)
from demos.apps.code_assistant.builtin_overrides import _classify_command
from weavert.openai_client import OPENAI_ROUTE_NAME
from weavert.contracts import ToolResultBlock
from weavert.runtime_kernel import RuntimeDistribution
from weavert.tool_runtime import ToolContext

PYTHON = sys.executable
ROOT = Path(__file__).resolve().parents[1]


def _layout(tmp_path: Path):
    return default_layout(state_root=tmp_path / "state")


def _cli_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env[CODE_ASSISTANT_STATE_ROOT_ENV] = str(tmp_path / "cli-state")
    return env


def _run_code_assistant_cli(
    *args: str,
    env: dict[str, str],
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-B", "-m", "demos.apps.code_assistant", *args],
        cwd=ROOT,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
    )


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
    assert "action" in bash_tool.input_schema["properties"]
    assert "description" in bash_tool.input_schema["properties"]
    assert "run_in_background" in bash_tool.input_schema["properties"]
    assert "shell_session_id" in bash_tool.input_schema["properties"]
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
    assert start["session_status"] == "running"
    assert start["session_output_complete"] is False
    assert send["action"] == "send"
    assert "hello from session" in str(read["session_output"])
    assert read["shell_session_id"] == start["shell_session_id"]
    assert stop_payload["status"] in {"stopped", "completed", "failed"}
    assert interrupt["action"] == "interrupt"
    assert interrupt["shell_session_id"] == interrupt_stop_payload["shell_session_id"]
    assert interrupt_stop_payload["status"] in {"stopped", "completed", "failed"}
    assert unsupported_payload["status"] == "unsupported"
    assert unsupported_payload["unsupported_shell"] is True
    assert "line-oriented" in str(unsupported_payload["unsupported_reason"])
    assert any(job["metadata"].get("shell_session_id") == start["shell_session_id"] for job in jobs)


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
    assert inline_payload["status"] == "blocked"
    assert "inline interpreter command" in str(inline_payload["stderr"])
    assert not outside_path.exists()


def test_replacement_bash_classifies_common_test_commands() -> None:
    assert _classify_command("python3 -m pytest -q").name == "test"
    assert _classify_command("make test").name == "test"
    assert _classify_command("cargo test").name == "test"
    assert _classify_command("go test ./...").name == "test"


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
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

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
    assert "current transcript: cli-shell" in shell.stdout
    assert "current task list: session:cli-shell" in shell.stdout
    assert "jobs: 0" in shell.stdout


def test_code_assistant_cli_run_surfaces_auth_failure_in_subprocess(tmp_path: Path) -> None:
    env = _cli_env(tmp_path)
    env.pop("OPENAI_API_KEY", None)

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
