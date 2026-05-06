from __future__ import annotations

from typing import Any

from ._optional_compat import load_optional_attr

_SURFACE = "weavert.reference_coding_builtins"
_DISTRIBUTIONS = (
    "weavert-kit-coding",
    "weavert-kit-common-git",
    "weavert-kit-common-workspace-intelligence",
)
_SOURCE_PATHS = (
    "packages/product-kits/coding",
    "packages/product-kits/common/git",
    "packages/product-kits/common/workspace-intelligence",
)
_MISSING_ROOTS = (
    "weavert_kit_coding",
    "weavert_kit_common_git",
    "weavert_kit_common_workspace_intelligence",
)

_MODULE_BY_EXPORT = {
    "coding_scenario_builtin_agents": "weavert_kit_coding._builtins",
    "coding_scenario_builtin_skills": "weavert_kit_coding._builtins",
    "shared_git_builtin_tools": "weavert_kit_common_git._builtins",
    "shared_workspace_intelligence_builtin_tools": "weavert_kit_common_workspace_intelligence._builtins",
}

__all__ = list(_MODULE_BY_EXPORT)


def __getattr__(name: str) -> Any:
    module_name = _MODULE_BY_EXPORT.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return load_optional_attr(
        module_name,
        name,
        surface=_SURFACE,
        distribution_names=_DISTRIBUTIONS,
        source_paths=_SOURCE_PATHS,
        expected_missing_roots=_MISSING_ROOTS,
    )


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
