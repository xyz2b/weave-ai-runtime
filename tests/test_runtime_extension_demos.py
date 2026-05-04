from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import demos.projects.coding_workflow_demo as coding_workflow_demo
from demos._shared.common import run_async
from demos.projects.coding_workflow_demo import run_demo as run_coding_workflow_demo
from weavert.contracts import MessageRole, RuntimeMessage, TextBlock, ToolResultBlock, ToolUseBlock

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "demos" / "README.md"
GUIDE = ROOT / "docs" / "weavert-user-extension-guide.md"
FINDINGS_LEDGER = ROOT / "docs" / "weavert-demo-validation-findings.md"
PYTHON = sys.executable

DEMO_CASES = (
    (
        "demos.tools.file_backed_tool_demo",
        (
            "demo: file-backed tool",
            "available tools: report_status",
            "status: ok",
        ),
    ),
    (
        "demos.agents.file_backed_agent_demo",
        (
            "demo: file-backed agent",
            "agent: release-reviewer",
            "status: ok",
        ),
    ),
    (
        "demos.skills.file_backed_skill_demo",
        (
            "demo: file-backed skill",
            "mode: fork",
            "status: ok",
        ),
    ),
    (
        "demos.tools.guarded_tool_demo",
        (
            "demo: guarded tool",
            "schema validation: rejected invalid input",
            "input validation: rejected blank value",
            "permission path: denied",
            "permission path: allowed",
            "status: ok",
        ),
    ),
    (
        "demos.agents.scoped_agent_delegation_demo",
        (
            "demo: scoped agent delegation",
            "visible tools: collect_scope",
            "delegated agent: scoped-worker",
            "child summary: worker summary: scoped tools only",
            "status: ok",
        ),
    ),
    (
        "demos.skills.inline_vs_fork_skill_demo",
        (
            "demo: inline vs fork skill",
            "inline result: inline note for demo-user",
            "fork child summary: forked child wrote a scoped summary",
            "status: ok",
        ),
    ),
    (
        "demos.skills.inline_skill_hook_demo",
        (
            "demo: inline skill hooks",
            "first turn result: rewritten",
            "second turn result: original",
            "status: ok",
        ),
    ),
    (
        "demos.hooks.session_register_hook_demo",
        (
            "demo: session.register_hook",
            "hook activation: active",
            "status: ok",
        ),
    ),
    (
        "demos.hooks.runtime_config_hook_demo",
        (
            "demo: RuntimeConfig(hooks=...)",
            "hook source: runtime_config",
            "session one result: runtime-default",
            "session two result: runtime-default",
            "status: ok",
        ),
    ),
    (
        "demos.hooks.host_registered_hook_demo",
        (
            "demo: host.register_hook",
            "hook source: host",
            "hook activation: active",
            "dispatch traces: 1",
            "status: ok",
        ),
    ),
    (
        "demos.packages.provider_only_package_demo",
        (
            "demo: provider-only package",
            "visible invocations: package-release-check",
            "status: ok",
        ),
    ),
    (
        "demos.packages.package_activation_demo",
        (
            "demo: package activation",
            "inactive visible invocations: none",
            "active visible invocations: package-release-check",
            "status: ok",
        ),
    ),
    (
        "demos.packages.general_package_demo",
        (
            "demo: general RuntimePackageManifest",
            "package context: release-freeze is active",
            "status: ok",
        ),
    ),
    (
        "demos.projects.release_workflow_demo",
        (
            "demo: release workflow",
            "workspace: release-fixture",
            "changed services: payments, notifications",
            "qa status: passed",
            "freeze status: active",
            "release summary: release-fixture is ready",
            "release verdict: approve",
            "status: ok",
        ),
    ),
    (
        "demos.projects.coding_workflow_demo",
        (
            "demo: coding workflow",
            "workspace: coding-workflow-fixture",
            "mode: offline",
            "host customization: none",
            "builtin replacements: none",
            "verification: passed",
            "review: pass",
            "status: ok",
        ),
    ),
    (
        "demos.hosts.minimal_host_bound_demo",
        (
            "demo: minimal host-bound",
            "host lifecycle: startup, ready, shutdown",
            "turn terminal observed: true",
            "status: ok",
        ),
    ),
    (
        "demos.runtime.stream_report_session_demo",
        (
            "demo: stream/report session",
            "helper-owned report: completed",
            "session reusable: true",
            "status: ok",
        ),
    ),
    (
        "demos.runtime.assembly_diagnostics_demo",
        (
            "demo: assembly diagnostics",
            "assembly preset: headless-live",
            "visible invocations: diagnostic-note",
            "failure class: missing_env",
            "status: ok",
        ),
    ),
    (
        "demos.runtime.durable_resume_demo",
        (
            "demo: durable resume",
            "turn one persisted: true",
            "session resumed: true",
            "status: ok",
        ),
    ),
)

README_USER_CENTRIC_SNIPPETS = (
    (
        "demos.tools.guarded_tool_demo",
        "How do I validate custom input guards, schema errors, permission denial, and a successful guarded tool path before I wire the tool into a larger workflow?",
        (
            "demo: guarded tool",
            "schema validation: rejected invalid input",
            "input validation: rejected blank value",
            "permission path: denied",
            "permission path: allowed",
            "status: ok",
        ),
        "It isolates the tool contract before the same behavior is hidden inside a multi-step agent loop.",
    ),
    (
        "demos.agents.scoped_agent_delegation_demo",
        "What actually changes when I delegate to a child agent with a narrower tool pool?",
        (
            "demo: scoped agent delegation",
            "visible tools:",
            "delegated agent:",
            "child summary:",
            "status: ok",
        ),
        "It proves tool scoping and child summaries before delegation is mixed into a project workflow.",
    ),
    (
        "demos.skills.inline_vs_fork_skill_demo",
        "When should I keep a skill inline versus forking it to a child agent?",
        (
            "demo: inline vs fork skill",
            "inline result:",
            "fork child summary:",
            "status: ok",
        ),
        "It makes the execution-mode tradeoff visible before skills become one step in a larger composition.",
    ),
    (
        "demos.hooks.host_registered_hook_demo",
        "How do I attach a hook from host-owned integration code, confirm that it materialized as an active session hook, and prove that it actually fired?",
        (
            "demo: host.register_hook",
            "hook source: host",
            "hook activation: active",
            "dispatch traces:",
            "status: ok",
        ),
        "It keeps host-owned hook attachment smaller than a full product shell.",
    ),
    (
        "demos.hosts.minimal_host_bound_demo",
        "What is the smallest stable `RuntimeAssembly.bind_host()` path that still shows lifecycle and turn events?",
        (
            "demo: minimal host-bound",
            "host lifecycle: startup, ready, shutdown",
            "turn terminal observed: true",
            "status: ok",
        ),
        "It proves the host seam without immediately pulling in approvals, durable state, or builtin replacement.",
    ),
    (
        "demos.runtime.stream_report_session_demo",
        "Which helper owns the session, and how do I prove a caller-owned session remains reusable?",
        (
            "demo: stream/report session",
            "helper-owned report: completed",
            "session reusable: true",
            "status: ok",
        ),
        "It answers helper-lifecycle questions directly instead of burying them in workflow orchestration.",
    ),
    (
        "demos.runtime.assembly_diagnostics_demo",
        "How do I inspect assembly posture, visible invocations, and a predictable model-route failure without product UX?",
        (
            "demo: assembly diagnostics",
            "assembly preset:",
            "visible invocations:",
            "failure class:",
            "status: ok",
        ),
        "It keeps assembly and route diagnostics below host binding and app-specific presentation.",
    ),
    (
        "demos.runtime.durable_resume_demo",
        "What does the minimum durable transcript and resume proof look like before I build custom product UX around it?",
        (
            "demo: durable resume",
            "turn one persisted: true",
            "session resumed: true",
            "status: ok",
        ),
        "It validates persistence expectations directly, without requiring the advanced app shell.",
    ),
)

USER_CENTRIC_FINDINGS_ENTRIES = (
    "guarded_tool_demo",
    "scoped_agent_delegation_demo",
    "inline_vs_fork_skill_demo",
    "host_registered_hook_demo",
    "minimal_host_bound_demo",
    "stream_report_session_demo",
    "assembly_diagnostics_demo",
    "durable_resume_demo",
)


@pytest.mark.parametrize(("module_name", "expected_lines"), DEMO_CASES)
def test_runtime_extension_demo_runs_from_repo_root(
    module_name: str,
    expected_lines: tuple[str, ...],
) -> None:
    if not PYTHON:
        pytest.skip("a Python interpreter is required to run the demo modules")

    completed = subprocess.run(
        [PYTHON, "-B", "-m", module_name],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    for line in expected_lines:
        assert line in completed.stdout


def test_demo_docs_expose_user_centric_validation_and_findings_ledger() -> None:
    contents = README.read_text(encoding="utf-8")

    assert "## User-centric validation" in contents
    assert "docs/weavert-demo-validation-findings.md" in contents
    for module_name, question, anchors, why in README_USER_CENTRIC_SNIPPETS:
        assert f"python3 -B -m {module_name}" in contents
        assert question in contents
        for anchor in anchors:
            assert anchor in contents
        assert why in contents


def test_user_extension_guide_links_the_demo_findings_ledger() -> None:
    contents = GUIDE.read_text(encoding="utf-8")

    assert "user-centric validation layer" in contents
    assert "docs/weavert-demo-validation-findings.md" in contents


def test_demo_findings_ledger_tracks_each_user_centric_demo() -> None:
    contents = FINDINGS_LEDGER.read_text(encoding="utf-8")

    assert "## Current entries" in contents
    for entry_name in USER_CENTRIC_FINDINGS_ENTRIES:
        assert f"### {entry_name}" in contents
        assert f"- demo: `{entry_name}`" in contents


def test_coding_workflow_demo_live_smoke_reports_auth_failure_without_fallback(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    monkeypatch.setenv("OPENAI_MODEL", "ambient-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.invalid/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    report = run_async(run_coding_workflow_demo(live=True))

    assert report.mode == "live"
    assert report.ok is False
    assert report.terminal_metadata["failure_class"] == "missing_env"
    assert report.terminal_stop_reason == "preflight_blocked"
    assert "OPENAI_API_KEY" in str(report.error_message)
    assert report.verification_result is None
    assert report.review_result is None


def test_coding_workflow_demo_live_mode_reuses_the_same_success_criteria(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def fake_run_prompt(*, runtime, workspace):
        _ = runtime
        (workspace / coding_workflow_demo.TARGET_FILE).write_text(
            'DEFAULT_NAME = "WeaveRT"\n\n\n'
            "def format_greeting(name: str | None = None) -> str:\n"
            "    selected = (name or DEFAULT_NAME).strip()\n"
            "    if not selected:\n"
            "        selected = DEFAULT_NAME\n"
            '    return f"Hello, {selected}."\n',
            encoding="utf-8",
        )
        return coding_workflow_demo.PromptOutcome(
            messages=(
                RuntimeMessage(
                    message_id="live-verify-use",
                    role=MessageRole.ASSISTANT,
                    content=(
                        ToolUseBlock(
                            tool_use_id="tool-live-verify",
                            name="bash",
                            input={"command": coding_workflow_demo.VERIFICATION_COMMAND},
                        ),
                    ),
                ),
                RuntimeMessage(
                    message_id="live-verify-result",
                    role=MessageRole.USER,
                    content=(
                        ToolResultBlock(
                            tool_use_id="tool-live-verify",
                            content={
                                "command": coding_workflow_demo.VERIFICATION_COMMAND,
                                "exit_code": 0,
                                "stdout": "",
                                "stderr": "OK\n",
                                "shell": "bash",
                            },
                        ),
                    ),
                ),
                RuntimeMessage(
                    message_id="live-review-use",
                    role=MessageRole.ASSISTANT,
                    content=(
                        ToolUseBlock(
                            tool_use_id="tool-live-review",
                            name="skill",
                            input={
                                "skill": "review-change",
                                "arguments": [
                                    f"changed file: {coding_workflow_demo.TARGET_FILE}",
                                    f"verification: {coding_workflow_demo.VERIFICATION_COMMAND}",
                                ],
                            },
                        ),
                    ),
                ),
                RuntimeMessage(
                    message_id="live-review-result",
                    role=MessageRole.USER,
                    content=(
                        ToolResultBlock(
                            tool_use_id="tool-live-review",
                            content={
                                "skill": "review-change",
                                "mode": "fork",
                                "agent_result": {"summary": "review: pass"},
                            },
                        ),
                    ),
                ),
                RuntimeMessage(
                    message_id="live-summary",
                    role=MessageRole.ASSISTANT,
                    content=(
                        TextBlock(
                            "updated src/demo_service/greeting.py; verification: passed; review: pass"
                        ),
                    ),
                ),
            ),
            terminal_stop_reason="completed",
            terminal_metadata={},
        )

    monkeypatch.setattr(coding_workflow_demo, "_run_prompt", fake_run_prompt)

    report = run_async(run_coding_workflow_demo(live=True))

    assert report.mode == "live"
    assert report.ok is True
    assert report.error_message is None
    assert report.verification_result is not None
    assert report.verification_result["exit_code"] == 0
    assert report.review_result is not None
    assert report.review_result["agent_result"]["summary"] == "review: pass"


def test_coding_workflow_demo_live_cli_documents_the_same_boundary_without_network() -> None:
    env = dict(os.environ)
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        env.pop(name, None)

    completed = subprocess.run(
        [PYTHON, "-B", "-m", "demos.projects.coding_workflow_demo", "--live"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "mode: live" in completed.stdout
    assert "host customization: none" in completed.stdout
    assert "builtin replacements: none" in completed.stdout
    assert "OPENAI_API_KEY" in completed.stdout
    assert "status: error" in completed.stdout


def test_runtime_extension_readme_lists_layered_validation_story() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "## Layered validation path" in readme
    assert "## Project demos" in readme
    assert "## Workflow-level live smoke" in readme
    assert "## Advanced live app demos" in readme
    assert "ordinary extension path" in readme
    assert "workflow-level live smoke fail" in readme
    assert "advanced integration sample" in readme
    assert "python3 -B -m demos.projects.coding_workflow_demo" in readme
    assert "python3 -B -m demos.projects.coding_workflow_demo --live" in readme
    assert "python3 -B -m demos.apps.code_assistant shell" in readme
