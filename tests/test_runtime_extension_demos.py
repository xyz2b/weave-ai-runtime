from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from demos._shared.common import run_async
from demos.projects.coding_workflow_demo import run_demo as run_coding_workflow_demo

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "demos" / "README.md"
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
    assert report.terminal_metadata["failure_class"] == "auth_error"
    assert "OPENAI_API_KEY" in str(report.error_message)
    assert report.verification_result is None
    assert report.review_result is None


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
