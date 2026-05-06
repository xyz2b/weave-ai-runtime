from __future__ import annotations

from weavert.runtime_package_protocols import RuntimePackageManifest
from weavert_kit_chat import (
    REFERENCE_SCENARIO_PACK_SHAPE as CHAT_SCENARIO_PACK_SHAPE,
    chat_scenario_runtime_pack_manifests,
    reference_scenario_pack_manifest as chat_scenario_pack_manifest,
)
from weavert_kit_coding import (
    REFERENCE_SCENARIO_PACK_SHAPE as CODING_SCENARIO_PACK_SHAPE,
    coding_scenario_runtime_pack_manifests,
    reference_scenario_pack_manifest as coding_scenario_pack_manifest,
)
from weavert_kit_common_browser import (
    REFERENCE_SHARED_PACKAGE_SHAPE as BROWSER_SHARED_PACKAGE_SHAPE,
    reference_shared_package_manifest as browser_shared_package_manifest,
)
from weavert_kit_common_git import (
    REFERENCE_SHARED_PACKAGE_SHAPE as GIT_SHARED_PACKAGE_SHAPE,
    reference_shared_package_manifest as git_shared_package_manifest,
)
from weavert_kit_common_local_os import (
    REFERENCE_SHARED_PACKAGE_SHAPE as LOCAL_OS_SHARED_PACKAGE_SHAPE,
    reference_shared_package_manifest as local_os_shared_package_manifest,
)
from weavert_kit_common_pim import (
    REFERENCE_SHARED_PACKAGE_SHAPE as PIM_SHARED_PACKAGE_SHAPE,
    reference_shared_package_manifest as pim_shared_package_manifest,
)
from weavert_kit_common_retrieval import (
    REFERENCE_SHARED_PACKAGE_SHAPE as RETRIEVAL_SHARED_PACKAGE_SHAPE,
    reference_shared_package_manifest as retrieval_shared_package_manifest,
)
from weavert_kit_common_web import (
    REFERENCE_SHARED_PACKAGE_SHAPE as WEB_SHARED_PACKAGE_SHAPE,
    reference_shared_package_manifest as web_shared_package_manifest,
)
from weavert_kit_common_workspace_intelligence import (
    REFERENCE_SHARED_PACKAGE_SHAPE as WORKSPACE_SHARED_PACKAGE_SHAPE,
    reference_shared_package_manifest as workspace_shared_package_manifest,
)
from weavert_kit_local_assistant import (
    REFERENCE_SCENARIO_PACK_SHAPE as LOCAL_ASSISTANT_SCENARIO_PACK_SHAPE,
    local_assistant_scenario_runtime_pack_manifests,
    reference_scenario_pack_manifest as local_assistant_scenario_pack_manifest,
)

from .scenario_runtime_pack_support import ReferenceScenarioPackShape, ReferenceSharedPackageShape

REFERENCE_SHARED_PACKAGE_SHAPES: tuple[ReferenceSharedPackageShape, ...] = (
    RETRIEVAL_SHARED_PACKAGE_SHAPE,
    WEB_SHARED_PACKAGE_SHAPE,
    BROWSER_SHARED_PACKAGE_SHAPE,
    LOCAL_OS_SHARED_PACKAGE_SHAPE,
    PIM_SHARED_PACKAGE_SHAPE,
    GIT_SHARED_PACKAGE_SHAPE,
    WORKSPACE_SHARED_PACKAGE_SHAPE,
)

REFERENCE_SCENARIO_PACK_SHAPES: tuple[ReferenceScenarioPackShape, ...] = (
    CODING_SCENARIO_PACK_SHAPE,
    CHAT_SCENARIO_PACK_SHAPE,
    LOCAL_ASSISTANT_SCENARIO_PACK_SHAPE,
)


def reference_shared_package_shapes() -> tuple[ReferenceSharedPackageShape, ...]:
    return REFERENCE_SHARED_PACKAGE_SHAPES


def reference_scenario_pack_shapes() -> tuple[ReferenceScenarioPackShape, ...]:
    return REFERENCE_SCENARIO_PACK_SHAPES


def reference_shared_package_shape(name: str) -> ReferenceSharedPackageShape:
    normalized = str(name)
    for shape in REFERENCE_SHARED_PACKAGE_SHAPES:
        if normalized in {shape.package_name, shape.capability_key}:
            return shape
    raise KeyError(f"Unknown reference shared package shape: {name}")


def reference_scenario_pack_shape(name: str) -> ReferenceScenarioPackShape:
    normalized = str(name)
    for shape in REFERENCE_SCENARIO_PACK_SHAPES:
        if normalized in {shape.package_name, shape.profile, shape.display_name}:
            return shape
    raise KeyError(f"Unknown reference scenario pack shape: {name}")


def build_reference_shared_package_manifest(name: str) -> RuntimePackageManifest:
    package_name = reference_shared_package_shape(name).package_name
    if package_name == RETRIEVAL_SHARED_PACKAGE_SHAPE.package_name:
        return retrieval_shared_package_manifest()
    if package_name == WEB_SHARED_PACKAGE_SHAPE.package_name:
        return web_shared_package_manifest()
    if package_name == BROWSER_SHARED_PACKAGE_SHAPE.package_name:
        return browser_shared_package_manifest()
    if package_name == LOCAL_OS_SHARED_PACKAGE_SHAPE.package_name:
        return local_os_shared_package_manifest()
    if package_name == PIM_SHARED_PACKAGE_SHAPE.package_name:
        return pim_shared_package_manifest()
    if package_name == GIT_SHARED_PACKAGE_SHAPE.package_name:
        return git_shared_package_manifest()
    if package_name == WORKSPACE_SHARED_PACKAGE_SHAPE.package_name:
        return workspace_shared_package_manifest()
    raise KeyError(f"Unknown reference shared package manifest: {name}")


def build_reference_scenario_pack_manifest(name: str) -> RuntimePackageManifest:
    package_name = reference_scenario_pack_shape(name).package_name
    if package_name == CODING_SCENARIO_PACK_SHAPE.package_name:
        return coding_scenario_pack_manifest()
    if package_name == CHAT_SCENARIO_PACK_SHAPE.package_name:
        return chat_scenario_pack_manifest()
    if package_name == LOCAL_ASSISTANT_SCENARIO_PACK_SHAPE.package_name:
        return local_assistant_scenario_pack_manifest()
    raise KeyError(f"Unknown reference scenario pack manifest: {name}")


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return tuple(
        build_reference_shared_package_manifest(shape.package_name)
        for shape in REFERENCE_SHARED_PACKAGE_SHAPES
    )


def reference_scenario_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    return tuple(
        build_reference_scenario_pack_manifest(shape.package_name)
        for shape in REFERENCE_SCENARIO_PACK_SHAPES
    )


def reference_scenario_runtime_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    manifests: list[RuntimePackageManifest] = []
    seen: set[str] = set()
    for manifest in (
        *coding_scenario_runtime_pack_manifests(),
        *chat_scenario_runtime_pack_manifests(),
        *local_assistant_scenario_runtime_pack_manifests(),
    ):
        if manifest.name in seen:
            continue
        manifests.append(manifest)
        seen.add(manifest.name)
    return tuple(manifests)


__all__ = [
    "REFERENCE_SCENARIO_PACK_SHAPES",
    "REFERENCE_SHARED_PACKAGE_SHAPES",
    "ReferenceScenarioPackShape",
    "ReferenceSharedPackageShape",
    "build_reference_scenario_pack_manifest",
    "build_reference_shared_package_manifest",
    "reference_scenario_pack_manifests",
    "reference_scenario_pack_shape",
    "reference_scenario_pack_shapes",
    "reference_scenario_runtime_pack_manifests",
    "reference_shared_package_manifests",
    "reference_shared_package_shape",
    "reference_shared_package_shapes",
]
