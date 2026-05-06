from __future__ import annotations

from weavert.package_system.protocols import RuntimePackageManifest
from weavert.extension_contracts.scenario_runtime_packs import (
    ReferenceSharedPackageShape,
    build_reference_shared_package_manifest,
)

from ._builtins import (
    LOCAL_ASSISTANT_BROWSER_HOST_FACET,
    LOCAL_ASSISTANT_BROWSER_TOOLS,
    local_assistant_browser_bridge_builtin_tools,
)

REFERENCE_SHARED_PACKAGE_SHAPE = ReferenceSharedPackageShape(
    package_name="weavert-bridge-browser",
    capability_key="weavert.reference.bridge.browser",
    description="Reference shared package shape for browser automation capability surfaces.",
    shared_surface_family="browser-bridge",
    intended_profiles=("local_assistant",),
    surfaces=("browser bridge", "tab/session mediation", "navigation helpers"),
    tool_ids=LOCAL_ASSISTANT_BROWSER_TOOLS,
    notes=(
        "Keep browser bindings reusable and host-mediated instead of embedding them into each scenario pack.",
        "Expose staged browser inspection and action receipts without taking final host ownership.",
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
    raise KeyError(f"Unknown browser shared package shape: {name}")


def reference_shared_package_manifest() -> RuntimePackageManifest:
    return build_reference_shared_package_manifest(
        REFERENCE_SHARED_PACKAGE_SHAPE,
        builtin_tools=local_assistant_browser_bridge_builtin_tools,
    )


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_shared_package_manifest(),)


__all__ = [
    "LOCAL_ASSISTANT_BROWSER_HOST_FACET",
    "LOCAL_ASSISTANT_BROWSER_TOOLS",
    "REFERENCE_SHARED_PACKAGE_SHAPE",
    "reference_shared_package_manifest",
    "reference_shared_package_manifests",
    "reference_shared_package_shape",
    "reference_shared_package_shapes",
]
