from __future__ import annotations

from weavert.package_system.protocols import RuntimePackageManifest
from weavert.extension_contracts.scenario_runtime_packs import (
    ReferenceSharedPackageShape,
    build_reference_shared_package_manifest,
)

from ._builtins import (
    CHAT_WEB_TOOLS,
    WEB_RESEARCH_WORKER_AGENTS,
    chat_web_grounding_builtin_tools,
    web_research_worker_builtin_agents,
)
from ._tool_impls import (
    grounding_web_fetch_tool,
    grounding_web_find_tool,
    grounding_web_search_tool,
    validate_grounding_web_fetch,
    validate_grounding_web_find,
    validate_grounding_web_search,
    validate_web_research,
    validate_web_research_fetch_many,
    web_research_fetch_many_tool,
    web_research_tool,
)

REFERENCE_SHARED_PACKAGE_SHAPE = ReferenceSharedPackageShape(
    package_name="weavert-bridge-web",
    capability_key="weavert.reference.bridge.web",
    description="Reference shared package for AI-first web_research plus low-level read-only web primitives.",
    shared_surface_family="web-bridge",
    intended_profiles=("chat", "local_assistant"),
    surfaces=(
        "AI-first bounded web_research entrypoint",
        "read-only web search",
        "bounded remote fetch",
        "page-local grounding evidence finding",
        "bounded concurrent research page inspection",
        "HTTP-aware grounding helpers",
    ),
    tool_ids=CHAT_WEB_TOOLS,
    agent_ids=WEB_RESEARCH_WORKER_AGENTS,
    notes=(
        "Scenario packs should recommend web_research as the public web research entrypoint.",
        "Low-level primitives remain available for explicit search, fetch, and page-local find flows.",
        "web-searcher is a package-owned delegated worker behind web_research, not the recommended public path.",
        "The default posture stays read-only and chat-safe even when external grounding is enabled.",
        "Browser navigation or interaction still requires a separate browser bridge package.",
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
        builtin_agents=web_research_worker_builtin_agents,
    )


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_shared_package_manifest(),)


__all__ = [
    "CHAT_WEB_TOOLS",
    "REFERENCE_SHARED_PACKAGE_SHAPE",
    "WEB_RESEARCH_WORKER_AGENTS",
    "grounding_web_fetch_tool",
    "grounding_web_find_tool",
    "grounding_web_search_tool",
    "reference_shared_package_manifest",
    "reference_shared_package_manifests",
    "reference_shared_package_shape",
    "reference_shared_package_shapes",
    "validate_grounding_web_fetch",
    "validate_grounding_web_find",
    "validate_grounding_web_search",
    "validate_web_research",
    "validate_web_research_fetch_many",
    "web_research_fetch_many_tool",
    "web_research_tool",
    "web_research_worker_builtin_agents",
]
