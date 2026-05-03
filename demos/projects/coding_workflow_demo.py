from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from demos._shared.common import (
    AllowAllPermissionService,
    demo_workspace,
    discovery_source,
    run_async,
    temporary_workspace,
)
from demos._shared.scripted_model import ScriptedModelClient, text_batch, tool_call_batch

from weavert.contracts import MessageRole, RuntimeMessage, ToolResultBlock, ToolUseBlock
from weavert.runtime_kernel import RuntimeConfig, RuntimeDistribution, assemble_runtime

FIXTURE_ROOT = demo_workspace("projects", "workspaces", "coding_workflow")
WORKSPACE_LABEL = "coding-workflow-fixture"
SESSION_ID_OFFLINE = "coding-workflow-offline"
SESSION_ID_LIVE = "coding-workflow-live"
TARGET_FILE = "src/demo_service/greeting.py"
VERIFICATION_COMMAND = "python3 -m unittest discover -s tests"
DEFAULT_PROMPT = """Work in the current fixture workspace.

Goal:
1. Apply the `coding-loop` skill first.
2. Inspect the greeting bug before editing.
3. Update the default greeting so `format_greeting()` returns `Hello, WeaveRT.` by changing only the minimal source line.
4. Run `python3 -m unittest discover -s tests`.
5. Run the `review-change` skill to review the final change.
6. Finish with a concise summary naming the changed file, the verification outcome, and the review outcome.
"""


@dataclass(frozen=True, slots=True)
class DemoReport:
    mode: str
    workspace_root: Path
    workspace_label: str
    prompt: str
    verification_command: str
    messages: tuple[RuntimeMessage, ...]
    terminal_stop_reason: str | None
    terminal_metadata: dict[str, Any]
    final_text: str
    review_result: dict[str, Any] | None
    verification_result: dict[str, Any] | None
    host_customization: str
    builtin_replacements: str
    ok: bool
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PromptOutcome:
    messages: tuple[RuntimeMessage, ...]
    terminal_stop_reason: str | None
    terminal_metadata: dict[str, Any]


def _assert_parent_request(request) -> None:
    assert request.agent is not None
    assert request.agent.name == "coding-assistant"
    assert set(request.turn_context.available_tools) == {"bash", "edit", "glob", "grep", "read", "skill"}
    assert set(request.turn_context.available_skills) == {"coding-loop", "review-change"}


def _assert_reviewer_request(request) -> None:
    assert request.agent is not None
    assert request.agent.name == "reviewer"
    assert set(request.turn_context.available_tools) == {"glob", "grep", "read"}


def _offline_client() -> ScriptedModelClient:
    def _coding_loop_batch(request):
        _assert_parent_request(request)
        return tool_call_batch(
            request_id="req-coding-workflow-1",
            tool_name="skill",
            tool_input={"skill": "coding-loop"},
            call_id="call-coding-loop",
        )

    def _inspect_batch(request):
        _assert_parent_request(request)
        return tool_call_batch(
            request_id="req-coding-workflow-2",
            tool_name="grep",
            tool_input={"pattern": "DEFAULT_NAME", "path": "src/demo_service"},
            call_id="call-inspect-grep",
        )

    def _edit_batch(request):
        _assert_parent_request(request)
        return tool_call_batch(
            request_id="req-coding-workflow-3",
            tool_name="edit",
            tool_input={
                "file_path": TARGET_FILE,
                "old_string": 'DEFAULT_NAME = "runtime"',
                "new_string": 'DEFAULT_NAME = "WeaveRT"',
            },
            call_id="call-edit-greeting",
        )

    def _verify_batch(request):
        _assert_parent_request(request)
        return tool_call_batch(
            request_id="req-coding-workflow-4",
            tool_name="bash",
            tool_input={
                "command": VERIFICATION_COMMAND,
            },
            call_id="call-run-tests",
        )

    def _review_skill_batch(request):
        _assert_parent_request(request)
        return tool_call_batch(
            request_id="req-coding-workflow-5",
            tool_name="skill",
            tool_input={
                "skill": "review-change",
                "arguments": [
                    "changed file: src/demo_service/greeting.py",
                    "verification: python3 -m unittest discover -s tests",
                ],
            },
            call_id="call-review-skill",
        )

    def _reviewer_read_batch(request):
        _assert_reviewer_request(request)
        return tool_call_batch(
            request_id="req-coding-workflow-6",
            tool_name="read",
            tool_input={"file_path": TARGET_FILE},
            call_id="call-review-read",
        )

    def _reviewer_summary_batch(request):
        _assert_reviewer_request(request)
        return text_batch(
            request_id="req-coding-workflow-7",
            text="review: pass",
        )

    def _final_batch(request):
        _assert_parent_request(request)
        return text_batch(
            request_id="req-coding-workflow-8",
            text=(
                "updated src/demo_service/greeting.py; "
                "verification: passed; "
                "review: pass"
            ),
        )

    return ScriptedModelClient(
        [
            _coding_loop_batch,
            _inspect_batch,
            _edit_batch,
            _verify_batch,
            _review_skill_batch,
            _reviewer_read_batch,
            _reviewer_summary_batch,
            _final_batch,
        ]
    )


async def _run_prompt(*, runtime, workspace: Path) -> PromptOutcome:
    report = await runtime.run_prompt_report(
        DEFAULT_PROMPT,
        session_id=SESSION_ID_LIVE if runtime.kernel.config.model_client is None else SESSION_ID_OFFLINE,
        agent_name="coding-assistant",
        cwd=workspace,
        wait_for_finalization=True,
    )
    terminal_stop_reason = report.terminal.stop_reason if report.terminal is not None else None
    terminal_metadata = dict(report.terminal.metadata) if report.terminal is not None else {}
    return PromptOutcome(
        messages=report.messages,
        terminal_stop_reason=terminal_stop_reason,
        terminal_metadata=terminal_metadata,
    )


async def run_demo(*, live: bool = False) -> DemoReport:
    mode = "live" if live else "offline"
    model_client = None if live else _offline_client()

    with temporary_workspace(FIXTURE_ROOT) as workspace:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=workspace,
                distribution=RuntimeDistribution.FULL,
                model_client=model_client,
                discovery_sources=(discovery_source(workspace),),
            )
        )
        runtime.services.permissions = AllowAllPermissionService()
        outcome = await _run_prompt(runtime=runtime, workspace=workspace)

        review_result = _review_result(outcome.messages)
        verification_result = _verification_result(outcome.messages)

        final_text = _last_assistant_text(outcome.messages)
        error_message = str(outcome.terminal_metadata.get("error") or "").strip() or None
        verification_exit_code = (
            int(verification_result.get("exit_code", 1))
            if isinstance(verification_result, dict)
            else 1
        )
        verification_passed = verification_exit_code == 0
        review_passed = bool(
            review_result
            and isinstance(review_result.get("agent_result"), dict)
            and str(review_result["agent_result"].get("summary") or "").strip() == "review: pass"
        )
        file_text = (workspace / TARGET_FILE).read_text(encoding="utf-8")
        ok = (
            error_message is None
            and terminal_stop_reason_is_success(outcome.terminal_stop_reason)
            and "DEFAULT_NAME = \"WeaveRT\"" in file_text
            and verification_passed
            and review_passed
            and bool(final_text)
        )
        return DemoReport(
            mode=mode,
            workspace_root=workspace,
            workspace_label=WORKSPACE_LABEL,
            prompt=DEFAULT_PROMPT,
            verification_command=VERIFICATION_COMMAND,
            messages=outcome.messages,
            terminal_stop_reason=outcome.terminal_stop_reason,
            terminal_metadata=outcome.terminal_metadata,
            final_text=final_text,
            review_result=review_result,
            verification_result=verification_result,
            host_customization="none",
            builtin_replacements="none",
            ok=ok,
            error_message=error_message,
        )


def terminal_stop_reason_is_success(stop_reason: str | None) -> bool:
    return stop_reason in {None, "completed", "end_turn"}


def _last_assistant_text(messages: tuple[RuntimeMessage, ...]) -> str:
    for message in reversed(messages):
        if message.role == MessageRole.ASSISTANT and message.text:
            return message.text
    return ""


def _find_tool_result(
    messages: tuple[RuntimeMessage, ...],
    *,
    tool_name: str,
    matcher,
) -> dict[str, Any] | None:
    tool_uses: dict[str, ToolUseBlock] = {}
    latest_match: dict[str, Any] | None = None
    for message in messages:
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                tool_uses[block.tool_use_id] = block
                continue
            if not isinstance(block, ToolResultBlock):
                continue
            tool_use = tool_uses.get(block.tool_use_id)
            if tool_use is None or tool_use.name != tool_name:
                continue
            tool_input = tool_use.input if isinstance(tool_use.input, dict) else {}
            tool_result = block.content if isinstance(block.content, dict) else None
            if tool_result is None:
                continue
            if matcher(tool_input, tool_result):
                latest_match = tool_result
    return latest_match


def _verification_result(messages: tuple[RuntimeMessage, ...]) -> dict[str, Any] | None:
    expected_command = VERIFICATION_COMMAND.strip()
    return _find_tool_result(
        messages,
        tool_name="bash",
        matcher=lambda tool_input, tool_result: (
            str(tool_input.get("command") or tool_result.get("command") or "").strip() == expected_command
        ),
    )


def _review_result(messages: tuple[RuntimeMessage, ...]) -> dict[str, Any] | None:
    return _find_tool_result(
        messages,
        tool_name="skill",
        matcher=lambda tool_input, tool_result: (
            str(tool_input.get("skill") or tool_result.get("skill") or "").strip() == "review-change"
        ),
    )


def render_report(report: DemoReport) -> None:
    print("demo: coding workflow")
    print(f"workspace: {report.workspace_label}")
    print(f"mode: {report.mode}")
    print(f"host customization: {report.host_customization}")
    print(f"builtin replacements: {report.builtin_replacements}")
    if report.ok:
        print("verification: passed")
        print("review: pass")
        print(f"summary: {report.final_text}")
        print("status: ok")
        return
    verification_label = (
        "passed"
        if isinstance(report.verification_result, dict) and int(report.verification_result.get("exit_code", 1)) == 0
        else "not-run"
    )
    review_label = "pass" if report.review_result and isinstance(report.review_result.get("agent_result"), dict) and str(report.review_result["agent_result"].get("summary") or "").strip() == "review: pass" else "not-run"
    print(f"verification: {verification_label}")
    print(f"review: {review_label}")
    if report.error_message is not None:
        print(f"error: {report.error_message}")
    elif report.terminal_stop_reason is not None:
        print(f"error: terminal stop reason {report.terminal_stop_reason}")
    else:
        print("error: workflow validation did not reach the expected success criteria")
    print("status: error")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the layered coding workflow project demo.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the same coding workflow against the bundled live provider route.",
    )
    args = parser.parse_args(argv)

    report = run_async(run_demo(live=args.live))
    render_report(report)
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
