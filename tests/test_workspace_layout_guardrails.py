from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packages" / "toolchain" / "scripts" / "check_workspace_layout.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_workspace_layout", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unknown_top_level_code_root_is_flagged() -> None:
    module = _load_module()

    visible = (
        "packages/core/src/weavert/__init__.py",
        "docs/README.md",
        "rogue-addon/src/rogue_addon/__init__.py",
    )

    assert module._unexpected_top_level_code_roots(visible) == ("rogue-addon",)


def test_unknown_doc_only_root_is_not_flagged() -> None:
    module = _load_module()

    visible = (
        "docs/README.md",
        "future-notes/README.md",
    )

    assert module._unexpected_top_level_code_roots(visible) == ()


def test_root_level_code_file_is_flagged() -> None:
    module = _load_module()

    visible = (
        "plugin.py",
        "pyproject.toml",
    )

    assert module._unexpected_top_level_code_roots(visible) == ("plugin.py",)
