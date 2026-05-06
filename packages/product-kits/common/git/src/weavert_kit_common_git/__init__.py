from __future__ import annotations

from weavert.runtime_package_protocols import RuntimePackageManifest
from weavert.scenario_runtime_pack_support import (
    ReferenceSharedPackageShape,
    build_reference_shared_package_manifest,
)

from ._builtins import shared_git_builtin_tools

CODING_SHARED_GIT_TOOLS = (
    "git_status",
    "git_diff",
    "git_history",
)

REFERENCE_SHARED_PACKAGE_SHAPE = ReferenceSharedPackageShape(
    package_name="weavert-shared-git",
    capability_key="weavert.reference.shared.git",
    description="Reference shared package for read-mostly git inspection in coding products.",
    shared_surface_family="git",
    intended_profiles=("coding",),
    surfaces=(
        "workspace git status inspection",
        "focused diff inspection",
        "recent history inspection",
    ),
    tool_ids=CODING_SHARED_GIT_TOOLS,
    notes=(
        "Keep git inspection reusable so coding products do not need shell-only conventions for common repo state checks.",
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
    raise KeyError(f"Unknown git shared package shape: {name}")


def reference_shared_package_manifest() -> RuntimePackageManifest:
    return build_reference_shared_package_manifest(
        REFERENCE_SHARED_PACKAGE_SHAPE,
        builtin_tools=shared_git_builtin_tools,
    )


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_shared_package_manifest(),)


__all__ = [
    "CODING_SHARED_GIT_TOOLS",
    "REFERENCE_SHARED_PACKAGE_SHAPE",
    "reference_shared_package_manifest",
    "reference_shared_package_manifests",
    "reference_shared_package_shape",
    "reference_shared_package_shapes",
]
