from __future__ import annotations

from weavert.package_system.protocols import RuntimePackageManifest
from weavert.extension_contracts.scenario_runtime_packs import (
    ReferenceSharedPackageShape,
    build_reference_shared_package_manifest,
)

from ._builtins import shared_workspace_intelligence_builtin_tools

CODING_SHARED_WORKSPACE_TOOLS = (
    "workspace_symbols",
    "workspace_references",
    "workspace_outline",
    "workspace_test_targets",
)

REFERENCE_SHARED_PACKAGE_SHAPE = ReferenceSharedPackageShape(
    package_name="weavert-shared-workspace-intelligence",
    capability_key="weavert.reference.shared.workspace_intelligence",
    description="Reference shared package for workspace-intelligence surfaces in coding products.",
    shared_surface_family="workspace-intelligence",
    intended_profiles=("coding",),
    surfaces=(
        "symbol lookup",
        "reference search",
        "file outline inspection",
        "test-target discovery",
    ),
    tool_ids=CODING_SHARED_WORKSPACE_TOOLS,
    notes=(
        "Start with lightweight symbol and test-target discovery before deeper indexing or IDE integration.",
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
    raise KeyError(f"Unknown workspace-intelligence shared package shape: {name}")


def reference_shared_package_manifest() -> RuntimePackageManifest:
    return build_reference_shared_package_manifest(
        REFERENCE_SHARED_PACKAGE_SHAPE,
        builtin_tools=shared_workspace_intelligence_builtin_tools,
    )


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_shared_package_manifest(),)


__all__ = [
    "CODING_SHARED_WORKSPACE_TOOLS",
    "REFERENCE_SHARED_PACKAGE_SHAPE",
    "reference_shared_package_manifest",
    "reference_shared_package_manifests",
    "reference_shared_package_shape",
    "reference_shared_package_shapes",
]
