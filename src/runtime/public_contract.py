from __future__ import annotations

import shutil
from pathlib import Path

CANONICAL_PRODUCT_NAME = "WeaveRT"
CANONICAL_INSTALL_NAME = "weavert"
LEGACY_INSTALL_NAME = "ai-agent-runtime"
CANONICAL_IMPORT_ROOT = "weavert"
LEGACY_IMPORT_ROOT = "runtime"
CANONICAL_WORKSPACE_ROOT = ".weavert"
LEGACY_WORKSPACE_ROOT = ".runtime"
CANONICAL_NAMESPACE_PREFIX = "weavert."
LEGACY_NAMESPACE_PREFIX = "runtime."

_FIRST_PARTY_NAME_MAP = {
    "weavert-core": "weavert-core",
    "weavert-default": "weavert-default",
    "weavert-full": "weavert-full",
    "weavert-memory": "weavert-memory",
    "weavert-team": "weavert-team",
    "weavert-compaction": "weavert-compaction",
    "weavert-isolation": "weavert-isolation",
    "weavert-openai": "weavert-openai",
    "weavert-hosts-reference": "weavert-hosts-reference",
    "weavert-stores-file": "weavert-stores-file",
    "weavert-builtin-workflows": "weavert-builtin-workflows",
    "weavert-planning": "weavert-planning",
    "weavert-devtools": "weavert-devtools",
}


def canonical_first_party_name(name: str) -> str:
    return _FIRST_PARTY_NAME_MAP.get(str(name), str(name))


def canonical_distribution_name(name: str) -> str:
    return canonical_first_party_name(name)


def canonical_public_namespace(value: str) -> str:
    text = str(value)
    if text.startswith(LEGACY_NAMESPACE_PREFIX):
        return CANONICAL_NAMESPACE_PREFIX + text[len(LEGACY_NAMESPACE_PREFIX) :]
    return text


def canonical_workspace_root(parent: str | Path) -> Path:
    return Path(parent).resolve() / CANONICAL_WORKSPACE_ROOT


def legacy_workspace_root(parent: str | Path) -> Path:
    return Path(parent).resolve() / LEGACY_WORKSPACE_ROOT


def ensure_canonical_workspace_root(
    parent: str | Path,
    *,
    migrate_legacy: bool = True,
) -> Path:
    canonical = canonical_workspace_root(parent)
    legacy = legacy_workspace_root(parent)
    if migrate_legacy and legacy.exists():
        _merge_missing_legacy_workspace_entries(legacy, canonical)
    return canonical


def _merge_missing_legacy_workspace_entries(legacy: Path, canonical: Path) -> None:
    if not canonical.exists():
        shutil.copytree(legacy, canonical)
        return
    for entry in legacy.rglob("*"):
        destination = canonical / entry.relative_to(legacy)
        if entry.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry, destination)


def workspace_root_candidates(parent: str | Path) -> tuple[Path, ...]:
    canonical = canonical_workspace_root(parent)
    legacy = legacy_workspace_root(parent)
    candidates = [canonical]
    if legacy.exists():
        candidates.append(legacy)
    return tuple(candidates)


def workspace_skill_root_candidates(parent: str | Path) -> tuple[Path, ...]:
    return tuple(root / "skills" for root in workspace_root_candidates(parent))


__all__ = [
    "CANONICAL_IMPORT_ROOT",
    "CANONICAL_INSTALL_NAME",
    "CANONICAL_NAMESPACE_PREFIX",
    "CANONICAL_PRODUCT_NAME",
    "CANONICAL_WORKSPACE_ROOT",
    "LEGACY_IMPORT_ROOT",
    "LEGACY_INSTALL_NAME",
    "LEGACY_NAMESPACE_PREFIX",
    "LEGACY_WORKSPACE_ROOT",
    "canonical_distribution_name",
    "canonical_first_party_name",
    "canonical_public_namespace",
    "canonical_workspace_root",
    "ensure_canonical_workspace_root",
    "legacy_workspace_root",
    "workspace_root_candidates",
    "workspace_skill_root_candidates",
]
