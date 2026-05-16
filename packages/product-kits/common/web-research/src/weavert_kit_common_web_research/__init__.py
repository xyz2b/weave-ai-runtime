from __future__ import annotations

from weavert.package_system.protocols import RuntimePackageManifest
from weavert.extension_contracts.scenario_runtime_packs import (
    ReferenceSharedPackageShape,
    build_reference_shared_package_manifest,
)

from ._builtins import CODING_WEB_RESEARCH_TOOLS, shared_coding_web_research_builtin_tools
from ._tool_impls import (
    technical_web_fetch_tool,
    technical_web_find_tool,
    technical_web_search_tool,
    validate_technical_web_fetch,
    validate_technical_web_find,
    validate_technical_web_search,
)

REFERENCE_SHARED_PACKAGE_SHAPE = ReferenceSharedPackageShape(
    package_name="weavert-shared-web-research",
    capability_key="weavert.reference.shared.web_research",
    description="Reference shared package for coding-oriented technical web research surfaces.",
    shared_surface_family="coding-web-research",
    intended_profiles=("coding",),
    surfaces=(
        "domain-scoped technical web search",
        "version-aware inspected-page retrieval",
        "page-local exact evidence finding",
    ),
    tool_ids=CODING_WEB_RESEARCH_TOOLS,
    notes=(
        "Keep coding-oriented external reference lookup reusable so coding products do not rely on app-local-only helpers.",
        "The coding web package stays distinct from the chat-facing web adapter and from browser staging packages.",
    ),
)


def reference_shared_package_shapes() -> tuple[ReferenceSharedPackageShape, ...]:
    return (REFERENCE_SHARED_PACKAGE_SHAPE,)


def reference_shared_package_shape(name: str | None = None) -> ReferenceSharedPackageShape:
    normalized = REFERENCE_SHARED_PACKAGE_SHAPE.package_name if name is None else str(name)
    if normalized in {
        REFERENCE_SHARED_PACKAGE_SHAPE.package_name,
        REFERENCE_SHARED_PACKAGE_SHAPE.capability_key,
    }:
        return REFERENCE_SHARED_PACKAGE_SHAPE
    raise KeyError(f"Unknown coding web shared package shape: {name}")


def reference_shared_package_manifest() -> RuntimePackageManifest:
    return build_reference_shared_package_manifest(
        REFERENCE_SHARED_PACKAGE_SHAPE,
        builtin_tools=shared_coding_web_research_builtin_tools,
    )


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_shared_package_manifest(),)


__all__ = [
    "CODING_WEB_RESEARCH_TOOLS",
    "REFERENCE_SHARED_PACKAGE_SHAPE",
    "reference_shared_package_manifest",
    "reference_shared_package_manifests",
    "reference_shared_package_shape",
    "reference_shared_package_shapes",
    "shared_coding_web_research_builtin_tools",
    "technical_web_fetch_tool",
    "technical_web_find_tool",
    "technical_web_search_tool",
    "validate_technical_web_fetch",
    "validate_technical_web_find",
    "validate_technical_web_search",
]
