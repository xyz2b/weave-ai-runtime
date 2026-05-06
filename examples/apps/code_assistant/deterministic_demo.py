from __future__ import annotations

from examples._shared.scripted_model import ScriptedModelClient, text_batch, tool_call_batch


def _assert_code_assistant_request(request) -> None:
    assert request.agent is not None
    assert request.agent.name == "code-assistant"
    assert {
        "read",
        "glob",
        "grep",
        "edit",
        "write",
        "bash",
        "git_status",
        "workspace_symbols",
        "agent",
        "skill",
    }.issubset(set(request.turn_context.available_tools))
    assert {
        "coding-loop",
        "review-change",
        "verify-change",
        "task-discipline",
        "repo-onboard",
    }.issubset(set(request.turn_context.available_skills))


def _assert_planner_request(request) -> None:
    assert request.agent is not None
    assert request.agent.name == "coding-planner"
    assert {
        "read",
        "glob",
        "grep",
        "workspace_symbols",
        "workspace_test_targets",
        "task_create",
        "task_list",
    }.issubset(set(request.turn_context.available_tools))


def _assert_reviewer_request(request) -> None:
    assert request.agent is not None
    assert request.agent.name == "reviewer"
    assert {"read", "glob", "grep", "git_status", "git_diff", "task_list"} == set(
        request.turn_context.available_tools
    )


def _assert_verifier_request(request) -> None:
    assert request.agent is not None
    assert request.agent.name == "verifier"
    assert {
        "read",
        "glob",
        "grep",
        "bash",
        "git_status",
        "git_diff",
        "workspace_test_targets",
        "task_list",
        "job_get",
        "job_list",
        "job_stop",
    } == set(request.turn_context.available_tools)


def build_deterministic_model_client() -> ScriptedModelClient:
    # Keep the scripted validation path in example-owned code so the CLI, docs, and tests
    # all replay the same workflow contract.
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
                "prompt": (
                    "Inspect the current task list plus only the test and source files needed for this task. "
                    "Leave a short shared task plan and return a concise planning summary."
                ),
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

    def _planner_grep_batch(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-2",
            tool_name="grep",
            tool_input={"pattern": "DEFAULT_NAME", "path": "src"},
            call_id="call-planner-grep",
        )

    def _planner_task_one_batch(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-3",
            tool_name="task_create",
            tool_input={"subject": "Inspect the failing greeting flow"},
            call_id="call-planner-task-one",
        )

    def _planner_task_two_batch(request):
        _assert_planner_request(request)
        return tool_call_batch(
            request_id="req-planner-4",
            tool_name="task_create",
            tool_input={"subject": "Fix greeting and add live note"},
            call_id="call-planner-task-two",
        )

    def _planner_summary_batch(request):
        _assert_planner_request(request)
        return text_batch(
            request_id="req-planner-5",
            text=(
                "plan: inspect the greeting flow, update the default name, "
                "add the note, then verify"
            ),
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
            tool_input={
                "file_path": "notes/live_demo.md",
                "content": "The coding shell MVP updated the greeting fixture.\n",
            },
            call_id="call-write",
        )

    def _bash_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-6",
            tool_name="bash",
            tool_input={
                "command": "python3 -m unittest discover -s tests",
                "description": "Run unit tests",
            },
            call_id="call-bash",
        )

    def _reviewer_batch(request):
        _assert_code_assistant_request(request)
        return tool_call_batch(
            request_id="req-code-7",
            tool_name="agent",
            tool_input={"agent": "reviewer", "prompt": "Review the greeting change and note."},
            call_id="call-reviewer",
        )

    def _reviewer_child_batch(request):
        _assert_reviewer_request(request)
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
        _assert_verifier_request(request)
        return text_batch(request_id="req-verifier-1", text="verification: pass")

    def _final_batch(request):
        _assert_code_assistant_request(request)
        return text_batch(request_id="req-code-9", text="completed coding shell workflow")

    return ScriptedModelClient(
        [
            _coding_loop_batch,
            _planner_batch,
            _planner_task_list_batch,
            _planner_grep_batch,
            _planner_task_one_batch,
            _planner_task_two_batch,
            _planner_summary_batch,
            _task_list_batch,
            _edit_batch,
            _write_batch,
            _bash_batch,
            _reviewer_batch,
            _reviewer_child_batch,
            _verifier_batch,
            _verifier_child_batch,
            _final_batch,
        ]
    )


__all__ = ["build_deterministic_model_client"]
