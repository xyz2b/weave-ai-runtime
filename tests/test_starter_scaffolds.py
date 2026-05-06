from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from weavert.runtime_kernel import RuntimeAssemblyPresetName
from weavert_starter import generate_starter_scaffold, main as starter_main, official_starter_scaffold_catalog

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = tuple(sorted(ROOT.glob("packages/**/src")))
PYTHON = sys.executable


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENAI_MODEL", None)
    env.pop("OPENAI_BASE_URL", None)
    return env


def _script_env() -> dict[str, str]:
    env = _clean_env()
    pythonpath = os.pathsep.join(str(path) for path in SRC_ROOTS)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = pythonpath if not existing else f"{pythonpath}{os.pathsep}{existing}"
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
    assert (result.destination / ".weavert" / "starter-scaffold-manifest.json").is_file()

    readme = (result.destination / "README.md").read_text(encoding="utf-8")
    assert "python3 -m venv .venv" in readme
    assert "python -m pip install -e /path/to/weave-ai-runtime/packages/core" in readme
    if shape != "live-smoke":
        assert "python -m pip install -e /path/to/weave-ai-runtime/packages/toolchain/testing" in readme

    python_files = sorted(result.destination.rglob("*.py"))
    assert python_files
    for source_file in python_files:
        contents = source_file.read_text(encoding="utf-8")
        assert "examples." not in contents
        assert "examples/" not in contents
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


def test_generate_starter_scaffold_force_replaces_previous_generated_shape_without_leaving_stale_files(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "starter"
    generate_starter_scaffold("minimal-project", destination)
    (destination / ".weavert" / "starter-scaffold-manifest.json").unlink()
    preserved_file = destination / "notes.txt"
    preserved_file.write_text("keep me", encoding="utf-8")

    result = generate_starter_scaffold("live-smoke", destination, force=True)

    assert result.definition.name.value == "live-smoke"
    assert (destination / "live_smoke.py").is_file()
    assert (destination / ".weavert" / "agents" / "live-smoke-runner.md").is_file()
    assert not (destination / "app.py").exists()
    assert not (destination / ".weavert" / "agents" / "starter-guide.md").exists()
    assert not (destination / ".weavert" / "tools" / "project_snapshot.py").exists()
    assert (destination / ".weavert" / "starter-scaffold-manifest.json").is_file()
    assert preserved_file.read_text(encoding="utf-8") == "keep me"


def test_generated_minimal_starter_runs_in_a_fresh_virtualenv_after_installing_local_runtime(tmp_path: Path) -> None:
    result = generate_starter_scaffold("minimal-project", tmp_path / "minimal-project")
    virtualenv = tmp_path / "venv"

    create_env = subprocess.run(
        [PYTHON, "-m", "venv", "--system-site-packages", str(virtualenv)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert create_env.returncode == 0, create_env.stderr

    venv_python = virtualenv / "bin" / "python"
    install_runtime = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-q", "-e", str(ROOT / "packages" / "core")],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert install_runtime.returncode == 0, install_runtime.stderr

    install_testing = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-q", "-e", str(ROOT / "packages" / "toolchain" / "testing")],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert install_testing.returncode == 0, install_testing.stderr

    install_project = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-q", "-e", str(result.destination)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert install_project.returncode == 0, install_project.stderr

    completed = subprocess.run(
        [str(venv_python), str(result.entrypoint_path)],
        cwd=result.destination,
        check=False,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )

    assert completed.returncode == 0, completed.stderr
    assert "preset: ordinary-workflow" in completed.stdout
    assert "status: ok" in completed.stdout
