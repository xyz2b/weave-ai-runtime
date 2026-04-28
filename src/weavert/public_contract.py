from __future__ import annotations

from pathlib import Path

CANONICAL_PRODUCT_NAME = "WeaveRT"
CANONICAL_INSTALL_NAME = "weavert"
CANONICAL_IMPORT_ROOT = "weavert"
CANONICAL_WORKSPACE_ROOT = ".weavert"
CANONICAL_NAMESPACE_PREFIX = "weavert."

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
    return str(value)


def canonical_workspace_root(parent: str | Path) -> Path:
    return Path(parent).resolve() / CANONICAL_WORKSPACE_ROOT


def ensure_canonical_workspace_root(
    parent: str | Path,
) -> Path:
    return canonical_workspace_root(parent)


def workspace_root_candidates(parent: str | Path) -> tuple[Path, ...]:
    return (canonical_workspace_root(parent),)


def workspace_skill_root_candidates(parent: str | Path) -> tuple[Path, ...]:
    return tuple(root / "skills" for root in workspace_root_candidates(parent))


__all__ = [
    "CANONICAL_IMPORT_ROOT",
    "CANONICAL_INSTALL_NAME",
    "CANONICAL_NAMESPACE_PREFIX",
    "CANONICAL_PRODUCT_NAME",
    "CANONICAL_WORKSPACE_ROOT",
    "canonical_distribution_name",
    "canonical_first_party_name",
    "canonical_public_namespace",
    "canonical_workspace_root",
    "ensure_canonical_workspace_root",
    "workspace_root_candidates",
    "workspace_skill_root_candidates",
]
