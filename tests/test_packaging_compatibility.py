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
        [PYTHON, "-m", "venv", str(virtualenv)],
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


def test_core_package_surface_stays_core_only_without_optional_packages_installed(tmp_path: Path) -> None:
    venv_python = _create_virtualenv(tmp_path)
    _pip_install(venv_python, ROOT / "packages" / "framework-core")

    completed = _run_python(
        venv_python,
        """
        import importlib

        import weavert
        import weavert.compaction as compaction
        import weavert.extension_contracts as extension_contracts
        import weavert.isolation as isolation
        import weavert.memory as memory
        import weavert.package_system as package_system

        print("imports-ok")
        print("canonical-import-root", extension_contracts.CANONICAL_IMPORT_ROOT)
        print("package-manifest-type", package_system.RuntimePackageManifest.__name__)
        print("core-memory-model", memory.MemoryTurnResult().__class__.__name__)
        print("core-isolation-worktree", isolation.IsolationManager().describe_modes()["worktree"]["status"])
        assert compaction.CompactionPolicy().enabled is True
        assert weavert.RuntimePackageManifest is package_system.RuntimePackageManifest

        removed_modules = (
            "weavert.compaction.manager",
            "weavert.compaction.package",
            "weavert.memory.manager",
            "weavert.memory.package",
            "weavert.openai_client",
            "weavert.openai_package",
            "weavert.stores_file",
            "weavert.hosts.reference",
            "weavert.hosts.package",
            "weavert.team.assembly",
            "weavert.team.builtins",
            "weavert.team.tool_impls",
            "weavert.devtools.builtins",
            "weavert.devtools.tool_impls",
            "weavert.planning.builtins",
            "weavert.builtin_workflows.builtins",
            "weavert.testing",
            "weavert.starter_scaffolds",
            "weavert.scenario_runtime_packs",
            "weavert.reference_chat_builtins",
            "weavert.reference_chat_tool_impls",
            "weavert.reference_coding_builtins",
            "weavert.reference_coding_tool_impls",
            "weavert.reference_local_assistant_builtins",
            "weavert.isolation_package",
        )
        for module_name in removed_modules:
            try:
                importlib.import_module(module_name)
            except ModuleNotFoundError:
                print("missing", module_name)
            else:
                raise SystemExit(f"{module_name} should not be available from weavert-core")

        trimmed_attrs = (
            ("weavert.compaction", "CompactionManager"),
            ("weavert.memory", "MemoryManager"),
            ("weavert.isolation", "WorktreeIsolationAdapter"),
            ("weavert.hosts", "SdkHostRuntime"),
        )
        for module_name, attr_name in trimmed_attrs:
            module = importlib.import_module(module_name)
            if hasattr(module, attr_name):
                raise SystemExit(f"{module_name}.{attr_name} should not be exposed by weavert-core")
            print("trimmed", f"{module_name}.{attr_name}")
        """,
    )

    assert completed.returncode == 0, completed.stderr
    assert "imports-ok" in completed.stdout
    assert "canonical-import-root weavert" in completed.stdout
    assert "package-manifest-type RuntimePackageManifest" in completed.stdout
    assert "core-memory-model MemoryTurnResult" in completed.stdout
    assert "core-isolation-worktree not_available" in completed.stdout
    assert "missing weavert.openai_client" in completed.stdout
    assert "trimmed weavert.compaction.CompactionManager" in completed.stdout


def test_toolchain_scripts_package_installs_editably_and_exposes_modules(tmp_path: Path) -> None:
    venv_python = _create_virtualenv(tmp_path)
    _pip_install(venv_python, ROOT / "packages" / "framework-core")
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
