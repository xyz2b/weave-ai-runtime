#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ROOT_PYPROJECT = ROOT / "pyproject.toml"
CORE_PYPROJECT = ROOT / "packages" / "core" / "pyproject.toml"
CORE_PACKAGE = ROOT / "packages" / "core" / "src" / "weavert"
PLACEHOLDERS = (
    ROOT / "packages" / "framework-packs" / "README.md",
    ROOT / "packages" / "product-kits" / "README.md",
    ROOT / "packages" / "toolchain" / "README.md",
)
SUPPORT_ROOTS = (
    ROOT / "docs",
    ROOT / "tests",
    ROOT / "examples",
    ROOT / "upstreams",
    ROOT / ".local",
)
ALLOWED_TOP_LEVEL_DIRS = frozenset(
    {
        ".local",
        "docs",
        "examples",
        "openspec",
        "packages",
        "scripts",
        "tests",
        "upstreams",
    }
)
ALLOWED_TOP_LEVEL_FILES = frozenset(
    {
        ".gitignore",
        "LICENSE",
        "LICENSE.txt",
        "LICENSE.md",
        "pyproject.toml",
        "README.md",
        "uv.lock",
    }
)
CODELIKE_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".mjs",
        ".py",
        ".pyi",
        ".rb",
        ".rs",
        ".sh",
        ".swift",
        ".ts",
        ".tsx",
    }
)
CODELIKE_FILENAMES = frozenset(
    {
        "Cargo.toml",
        "go.mod",
        "package.json",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
    }
)
SOURCE_LIKE_SEGMENTS = frozenset({"src", "lib", "bin"})


def _load_toml(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _visible_paths() -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    visible: list[str] = []
    for line in result.stdout.splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        if (ROOT / normalized).exists():
            visible.append(normalized)
    return tuple(visible)


def _is_code_like_filename(name: str) -> bool:
    pure_name = PurePosixPath(name).name
    if pure_name in CODELIKE_FILENAMES:
        return True
    return PurePosixPath(pure_name).suffix in CODELIKE_EXTENSIONS


def _is_disallowed_top_level_code_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts:
        return False

    if len(parts) == 1:
        name = parts[0]
        if name in ALLOWED_TOP_LEVEL_FILES or name.startswith("."):
            return False
        return _is_code_like_filename(name)

    top_level = parts[0]
    if top_level in ALLOWED_TOP_LEVEL_DIRS:
        return False

    if any(segment in SOURCE_LIKE_SEGMENTS for segment in parts[1:-1]):
        return True
    return _is_code_like_filename(parts[-1])


def _unexpected_top_level_code_roots(visible_paths: tuple[str, ...]) -> tuple[str, ...]:
    unexpected: set[str] = set()
    for path in visible_paths:
        if not _is_disallowed_top_level_code_path(path):
            continue
        parts = PurePosixPath(path).parts
        unexpected.add(parts[0] if len(parts) > 1 else path)
    return tuple(sorted(unexpected))


def main() -> int:
    errors: list[str] = []

    root_data = _load_toml(ROOT_PYPROJECT)
    core_data = _load_toml(CORE_PYPROJECT)

    root_project = root_data.get("project", {})
    core_project = core_data.get("project", {})
    workspace_meta = root_data.get("tool", {}).get("weavert_workspace", {})

    if root_project.get("name") != "weavert-workspace":
        errors.append("root pyproject must identify the workspace coordinator")
    if root_project.get("scripts"):
        errors.append("root pyproject should not publish console entrypoints")
    if core_project.get("name") != "weavert":
        errors.append("packages/core must own the concrete weavert package metadata")
    if not isinstance(core_project.get("scripts"), dict) or "weavert-starter" not in core_project.get("scripts", {}):
        errors.append("packages/core must own the weavert-starter entrypoint")

    expected_concrete = ["packages/core"]
    if workspace_meta.get("concrete_package_roots") != expected_concrete:
        errors.append("workspace metadata must declare packages/core as the initial concrete package root")
    expected_placeholders = [
        "packages/framework-packs",
        "packages/product-kits",
        "packages/toolchain",
    ]
    if workspace_meta.get("family_placeholder_roots") != expected_placeholders:
        errors.append("workspace metadata must declare the placeholder package families")

    if not CORE_PACKAGE.is_dir():
        errors.append("packages/core/src/weavert is missing")
    for placeholder in PLACEHOLDERS:
        if not placeholder.is_file():
            errors.append(f"missing placeholder index: {placeholder.relative_to(ROOT)}")
    for support_root in SUPPORT_ROOTS:
        if not support_root.exists():
            errors.append(f"missing support root: {support_root.relative_to(ROOT)}")

    visible = _visible_paths()
    if any(path.startswith("src/weavert/") for path in visible):
        errors.append("tracked implementation files must not remain under src/weavert/")
    if any(path.startswith("demos/") for path in visible):
        errors.append("tracked runnable examples must not remain under demos/")
    unexpected_roots = _unexpected_top_level_code_roots(visible)
    if unexpected_roots:
        errors.append(
            "tracked top-level add-on code must stay within the workspace or support roots; "
            f"found: {', '.join(unexpected_roots)}"
        )

    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1

    print("workspace layout: ok")
    print("root package role: coordinator")
    print("core package role: concrete package metadata owner")
    print("placeholder families: framework-packs, product-kits, toolchain")
    print("support roots: docs, tests, examples, upstreams, .local")
    print("top-level code guardrail: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
