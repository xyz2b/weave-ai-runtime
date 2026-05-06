from __future__ import annotations

from weavert.package_system.protocols import RuntimePackageManifest
from weavert.extension_contracts.scenario_runtime_packs import (
    ReferenceSharedPackageShape,
    build_reference_shared_package_manifest,
)

from ._builtins import (
    LOCAL_ASSISTANT_PIM_HOST_FACET,
    LOCAL_ASSISTANT_PIM_TOOLS,
    local_assistant_pim_bridge_builtin_tools,
)

REFERENCE_SHARED_PACKAGE_SHAPE = ReferenceSharedPackageShape(
    package_name="weavert-bridge-pim",
    capability_key="weavert.reference.bridge.pim",
    description="Reference shared package shape for personal information manager capability surfaces.",
    shared_surface_family="pim-bridge",
    intended_profiles=("local_assistant",),
    surfaces=("calendar adapter", "contacts/tasks adapter", "notification handoff hooks"),
    tool_ids=LOCAL_ASSISTANT_PIM_TOOLS,
    notes=(
        "PIM adapters remain shared integrations even when a local assistant scenario pack recommends them.",
        "Stage calendar, reminder, contact, and task requests without claiming final account binding.",
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
    raise KeyError(f"Unknown PIM shared package shape: {name}")


def reference_shared_package_manifest() -> RuntimePackageManifest:
    return build_reference_shared_package_manifest(
        REFERENCE_SHARED_PACKAGE_SHAPE,
        builtin_tools=local_assistant_pim_bridge_builtin_tools,
    )


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_shared_package_manifest(),)


__all__ = [
    "LOCAL_ASSISTANT_PIM_HOST_FACET",
    "LOCAL_ASSISTANT_PIM_TOOLS",
    "REFERENCE_SHARED_PACKAGE_SHAPE",
    "reference_shared_package_manifest",
    "reference_shared_package_manifests",
    "reference_shared_package_shape",
    "reference_shared_package_shapes",
]
