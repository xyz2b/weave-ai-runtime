from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENAI_MODEL", None)
    env.pop("OPENAI_BASE_URL", None)
    env.pop("PYTHONPATH", None)
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    return env


def _create_virtualenv(tmp_path: Path) -> Path:
    virtualenv = tmp_path / "venv"
    completed = subprocess.run(
        [PYTHON, "-m", "venv", "--system-site-packages", str(virtualenv)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert completed.returncode == 0, completed.stderr
    return virtualenv / "bin" / "python"


def _pip_install(venv_python: Path, package_root: Path) -> None:
    completed = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-q", "-e", str(package_root)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    assert completed.returncode == 0, completed.stderr


def _run_python(venv_python: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(venv_python), "-c", textwrap.dedent(script)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )


def test_core_compatibility_shims_import_without_optional_packages_installed(tmp_path: Path) -> None:
    venv_python = _create_virtualenv(tmp_path)
    _pip_install(venv_python, ROOT / "packages" / "core")

    completed = _run_python(
        venv_python,
        """
        import weavert.reference_chat_builtins
        import weavert.reference_chat_tool_impls
        import weavert.reference_coding_builtins
        import weavert.reference_coding_tool_impls
        import weavert.reference_local_assistant_builtins
        import weavert.scenario_runtime_packs as scenario_runtime_packs
        import weavert.starter_scaffolds as starter_scaffolds
        import weavert.testing as testing
        import weavert.testing.assertions
        import weavert.testing.fixtures
        import weavert.testing.harness
        import weavert.testing.scripted

        print("imports-ok")

        checks = {
            "scenario": lambda: scenario_runtime_packs.reference_scenario_pack_manifests(),
            "starter": lambda: starter_scaffolds.generate_starter_scaffold("minimal-project", "unused"),
            "testing": lambda: testing.run_workflow_test,
        }

        for name, thunk in checks.items():
            try:
                thunk()
            except ModuleNotFoundError as exc:
                print(name, str(exc))
            else:
                raise SystemExit(f"{name} should require an optional package")
        """,
    )

    assert completed.returncode == 0, completed.stderr
    assert "imports-ok" in completed.stdout
    assert "packages/product-kits/chat" in completed.stdout
    assert "packages/toolchain/starter" in completed.stdout
    assert "packages/toolchain/testing" in completed.stdout


def test_toolchain_scripts_package_installs_editably_and_exposes_modules(tmp_path: Path) -> None:
    venv_python = _create_virtualenv(tmp_path)
    _pip_install(venv_python, ROOT / "packages" / "core")
    _pip_install(venv_python, ROOT / "packages" / "toolchain" / "scripts")

    completed = _run_python(
        venv_python,
        """
        import check_workspace_layout
        import openai_responses_live_smoke

        print(check_workspace_layout.__file__)
        print(openai_responses_live_smoke.__file__)
        """,
    )

    assert completed.returncode == 0, completed.stderr
    assert "check_workspace_layout.py" in completed.stdout
    assert "openai_responses_live_smoke.py" in completed.stdout
