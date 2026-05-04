from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from weavert import (
    RuntimeAssemblyPresetName,
    generate_starter_scaffold,
    official_starter_scaffold_catalog,
)
from weavert.starter_scaffolds import main as starter_main

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PYTHON = sys.executable


def _script_env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = str(SRC)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = pythonpath if not existing else f"{pythonpath}{os.pathsep}{existing}"
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENAI_MODEL", None)
    env.pop("OPENAI_BASE_URL", None)
    return env


def _run_generated_entrypoint(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, str(path)],
        cwd=path.parent,
        check=False,
        capture_output=True,
        text=True,
        env=_script_env(),
    )


@pytest.mark.parametrize(
    ("shape", "preset", "entrypoint"),
    (
        ("minimal-project", RuntimeAssemblyPresetName.ORDINARY_WORKFLOW, "app.py"),
        ("headless-workflow", RuntimeAssemblyPresetName.ORDINARY_WORKFLOW, "workflow_runner.py"),
        ("live-smoke", RuntimeAssemblyPresetName.HEADLESS_LIVE, "live_smoke.py"),
    ),
)
def test_official_starter_scaffold_catalog_covers_expected_shapes(
    shape: str,
    preset: RuntimeAssemblyPresetName,
    entrypoint: str,
) -> None:
    catalog = official_starter_scaffold_catalog()

    assert set(catalog) == {"minimal-project", "headless-workflow", "live-smoke"}
    assert catalog[shape].assembly_preset == preset
    assert catalog[shape].entrypoint == entrypoint
    assert catalog[shape].summary


@pytest.mark.parametrize("shape", ("minimal-project", "headless-workflow", "live-smoke"))
def test_generate_starter_scaffold_uses_canonical_layout_and_public_imports(tmp_path: Path, shape: str) -> None:
    result = generate_starter_scaffold(shape, tmp_path / shape)

    assert result.entrypoint_path.exists()
    assert (result.destination / ".weavert").is_dir()
    assert (result.destination / "README.md").is_file()
    assert (result.destination / "pyproject.toml").is_file()

    python_files = sorted(result.destination.rglob("*.py"))
    assert python_files
    for source_file in python_files:
        contents = source_file.read_text(encoding="utf-8")
        assert "demos." not in contents
        assert "demos/" not in contents
        assert "from weavert" in contents


def test_starter_scaffold_cli_lists_the_official_catalog(capsys: pytest.CaptureFixture[str]) -> None:
    assert starter_main(["list"]) == 0

    output = capsys.readouterr().out
    assert "minimal-project" in output
    assert "headless-workflow" in output
    assert "live-smoke" in output


@pytest.mark.parametrize(
    ("shape", "expected_lines"),
    (
        (
            "minimal-project",
            (
                "preset: ordinary-workflow",
                "workspace root: .weavert",
                "status: ok",
            ),
        ),
        (
            "headless-workflow",
            (
                "preset: ordinary-workflow",
                "ready checks: canonical weavert imports, project-local agent discovery, report-oriented workflow execution",
                "status: ok",
            ),
        ),
    ),
)
def test_generated_offline_starters_run_successfully(
    tmp_path: Path,
    shape: str,
    expected_lines: tuple[str, ...],
) -> None:
    result = generate_starter_scaffold(shape, tmp_path / shape)

    completed = _run_generated_entrypoint(result.entrypoint_path)

    assert completed.returncode == 0, completed.stderr
    for line in expected_lines:
        assert line in completed.stdout



def test_generated_live_smoke_starter_requires_preflight_and_skips_offline_fallback(tmp_path: Path) -> None:
    result = generate_starter_scaffold("live-smoke", tmp_path / "live-smoke")
    entrypoint_source = result.entrypoint_path.read_text(encoding="utf-8")

    assert "ScriptedModelClient" not in entrypoint_source
    assert "preflight_default_model_route" in entrypoint_source

    completed = _run_generated_entrypoint(result.entrypoint_path)

    assert completed.returncode == 1
    assert "preset: headless-live" in completed.stdout
    assert '"ready": false' in completed.stdout
    assert '"failure_class": "missing_env"' in completed.stdout
