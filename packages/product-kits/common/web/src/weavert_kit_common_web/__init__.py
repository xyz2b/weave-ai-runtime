from __future__ import annotations

from weavert.runtime_package_protocols import RuntimePackageManifest
from weavert.scenario_runtime_pack_support import (
    ReferenceSharedPackageShape,
    build_reference_shared_package_manifest,
)

from ._builtins import CHAT_WEB_TOOLS, chat_web_grounding_builtin_tools
from ._tool_impls import (
    grounding_web_fetch_tool,
    grounding_web_search_tool,
    validate_grounding_web_fetch,
    validate_grounding_web_search,
)

REFERENCE_SHARED_PACKAGE_SHAPE = ReferenceSharedPackageShape(
    package_name="weavert-bridge-web",
    capability_key="weavert.reference.bridge.web",
    description="Reference shared package for read-only web search and fetch grounding surfaces.",
    shared_surface_family="web-bridge",
    intended_profiles=("chat", "local_assistant"),
    surfaces=("read-only web search", "bounded remote fetch", "HTTP-aware grounding helpers"),
    tool_ids=CHAT_WEB_TOOLS,
    notes=(
        "Scenario packs should consume this bridge instead of duplicating web adapters.",
        "The default posture stays read-only and chat-safe even when external grounding is enabled.",
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
    raise KeyError(f"Unknown web shared package shape: {name}")


def reference_shared_package_manifest() -> RuntimePackageManifest:
    return build_reference_shared_package_manifest(
        REFERENCE_SHARED_PACKAGE_SHAPE,
        builtin_tools=chat_web_grounding_builtin_tools,
    )


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_shared_package_manifest(),)


__all__ = [
    "CHAT_WEB_TOOLS",
    "REFERENCE_SHARED_PACKAGE_SHAPE",
    "grounding_web_fetch_tool",
    "grounding_web_search_tool",
    "reference_shared_package_manifest",
    "reference_shared_package_manifests",
    "reference_shared_package_shape",
    "reference_shared_package_shapes",
    "validate_grounding_web_fetch",
    "validate_grounding_web_search",
]
