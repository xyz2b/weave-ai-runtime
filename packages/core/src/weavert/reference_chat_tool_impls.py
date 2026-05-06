from __future__ import annotations

from typing import Any

from ._optional_compat import load_optional_attr

_SURFACE = "weavert.reference_chat_tool_impls"
_DISTRIBUTIONS = (
    "weavert-kit-common-retrieval",
    "weavert-kit-common-web",
)
_SOURCE_PATHS = (
    "packages/product-kits/common/retrieval",
    "packages/product-kits/common/web",
)
_MISSING_ROOTS = (
    "weavert_kit_common_retrieval",
    "weavert_kit_common_web",
)

_MODULE_BY_EXPORT = {
    "prepare_citations_tool": "weavert_kit_common_retrieval._tool_impls",
    "retrieve_context_tool": "weavert_kit_common_retrieval._tool_impls",
    "validate_prepare_citations_tool": "weavert_kit_common_retrieval._tool_impls",
    "validate_retrieve_context_tool": "weavert_kit_common_retrieval._tool_impls",
    "_grounding_hostname_resolves_publicly": "weavert_kit_common_web._tool_impls",
    "_grounding_urlopen": "weavert_kit_common_web._tool_impls",
    "grounding_web_fetch_tool": "weavert_kit_common_web._tool_impls",
    "grounding_web_search_tool": "weavert_kit_common_web._tool_impls",
    "validate_grounding_web_fetch": "weavert_kit_common_web._tool_impls",
    "validate_grounding_web_search": "weavert_kit_common_web._tool_impls",
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
