from __future__ import annotations

from typing import Any

from ._optional_compat import load_optional_attr

_SURFACE = "weavert.reference_coding_tool_impls"
_DISTRIBUTIONS = (
    "weavert-kit-common-git",
    "weavert-kit-common-workspace-intelligence",
)
_SOURCE_PATHS = (
    "packages/product-kits/common/git",
    "packages/product-kits/common/workspace-intelligence",
)
_MISSING_ROOTS = (
    "weavert_kit_common_git",
    "weavert_kit_common_workspace_intelligence",
)
_OPTIONAL_MODULES = (
    "weavert_kit_common_git._tool_impls",
    "weavert_kit_common_workspace_intelligence._tool_impls",
)

__all__ = [
    "git_diff_tool",
    "git_history_tool",
    "git_status_tool",
    "validate_git_path_tool",
    "validate_workspace_outline_tool",
    "validate_workspace_query_tool",
    "validate_workspace_symbol_tool",
    "validate_workspace_test_targets_tool",
    "workspace_outline_tool",
    "workspace_references_tool",
    "workspace_symbols_tool",
    "workspace_test_targets_tool",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    for module_name in _OPTIONAL_MODULES:
        try:
            return load_optional_attr(
                module_name,
                name,
                surface=_SURFACE,
                distribution_names=_DISTRIBUTIONS,
                source_paths=_SOURCE_PATHS,
                expected_missing_roots=_MISSING_ROOTS,
            )
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
