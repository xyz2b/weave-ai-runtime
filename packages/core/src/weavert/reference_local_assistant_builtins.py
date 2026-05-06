from __future__ import annotations

from typing import Any

from ._optional_compat import load_optional_attr

_SURFACE = "weavert.reference_local_assistant_builtins"
_DISTRIBUTIONS = (
    "weavert-kit-local-assistant",
    "weavert-kit-common-browser",
    "weavert-kit-common-local-os",
    "weavert-kit-common-pim",
)
_SOURCE_PATHS = (
    "packages/product-kits/local-assistant",
    "packages/product-kits/common/browser",
    "packages/product-kits/common/local-os",
    "packages/product-kits/common/pim",
)
_MISSING_ROOTS = (
    "weavert_kit_local_assistant",
    "weavert_kit_common_browser",
    "weavert_kit_common_local_os",
    "weavert_kit_common_pim",
)

_MODULE_BY_EXPORT = {
    "LOCAL_ASSISTANT_BROWSER_HOST_FACET": "weavert_kit_common_browser",
    "LOCAL_ASSISTANT_BROWSER_TOOLS": "weavert_kit_common_browser",
    "local_assistant_browser_bridge_builtin_tools": "weavert_kit_common_browser._builtins",
    "LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET": "weavert_kit_common_local_os",
    "LOCAL_ASSISTANT_LOCAL_OS_TOOLS": "weavert_kit_common_local_os",
    "local_assistant_local_os_bridge_builtin_tools": "weavert_kit_common_local_os._builtins",
    "LOCAL_ASSISTANT_PIM_HOST_FACET": "weavert_kit_common_pim",
    "LOCAL_ASSISTANT_PIM_TOOLS": "weavert_kit_common_pim",
    "local_assistant_pim_bridge_builtin_tools": "weavert_kit_common_pim._builtins",
    "LOCAL_ASSISTANT_SCENARIO_AGENTS": "weavert_kit_local_assistant._builtins",
    "LOCAL_ASSISTANT_SCENARIO_SKILLS": "weavert_kit_local_assistant._builtins",
    "local_assistant_scenario_builtin_agents": "weavert_kit_local_assistant._builtins",
    "local_assistant_scenario_builtin_skills": "weavert_kit_local_assistant._builtins",
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
