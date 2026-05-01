from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

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


def test_runtime_extension_readme_lists_project_and_live_app_demo_layers() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "## Seam basics" in readme
    assert "## Semantic demos" in readme
    assert "## Project demos" in readme
    assert "## Live app demos" in readme
    assert "multiple stable extension seams into a single project-shaped workflow" in readme
    assert "python3 -B -m demos.projects.release_workflow_demo" in readme
    assert "python3 -B -m demos.apps.code_assistant shell" in readme
    assert "host-bound AI coding shell" in readme
