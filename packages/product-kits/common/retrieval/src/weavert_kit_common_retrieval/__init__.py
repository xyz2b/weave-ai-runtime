from __future__ import annotations

from weavert.package_system.protocols import RuntimePackageManifest
from weavert.extension_contracts.scenario_runtime_packs import (
    ReferenceSharedPackageShape,
    build_reference_shared_package_manifest,
)

from ._builtins import CHAT_RETRIEVAL_TOOLS, chat_shared_retrieval_builtin_tools

REFERENCE_SHARED_PACKAGE_SHAPE = ReferenceSharedPackageShape(
    package_name="weavert-shared-retrieval",
    capability_key="weavert.reference.shared.retrieval",
    description="Reference retrieval-oriented shared package for grounded chat and assistant scenario packs.",
    shared_surface_family="retrieval",
    intended_profiles=("chat", "local_assistant"),
    surfaces=(
        "grounding context retrieval",
        "memory-backed evidence ranking",
        "citation preparation helpers",
    ),
    tool_ids=CHAT_RETRIEVAL_TOOLS,
    notes=(
        "Keep retrieval adapters reusable so multiple scenario packs can compose them without copying prompt logic.",
        "Local-assistant stacks can reuse the same retrieval surface without inheriting coding-oriented mutation tools.",
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
    raise KeyError(f"Unknown retrieval shared package shape: {name}")


def reference_shared_package_manifest() -> RuntimePackageManifest:
    return build_reference_shared_package_manifest(
        REFERENCE_SHARED_PACKAGE_SHAPE,
        builtin_tools=chat_shared_retrieval_builtin_tools,
    )


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_shared_package_manifest(),)


__all__ = [
    "CHAT_RETRIEVAL_TOOLS",
    "REFERENCE_SHARED_PACKAGE_SHAPE",
    "reference_shared_package_manifest",
    "reference_shared_package_manifests",
    "reference_shared_package_shape",
    "reference_shared_package_shapes",
]
