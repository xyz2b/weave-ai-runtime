from __future__ import annotations

from functools import lru_cache
from typing import Any

from weavert.runtime_package_protocols import RuntimePackageManifest

from ._optional_compat import load_optional_module
from .scenario_runtime_pack_support import ReferenceScenarioPackShape, ReferenceSharedPackageShape

_SURFACE = "weavert.scenario_runtime_packs"
_DISTRIBUTIONS = (
    "weavert-kit-chat",
    "weavert-kit-coding",
    "weavert-kit-local-assistant",
    "weavert-kit-common-browser",
    "weavert-kit-common-git",
    "weavert-kit-common-local-os",
    "weavert-kit-common-pim",
    "weavert-kit-common-retrieval",
    "weavert-kit-common-web",
    "weavert-kit-common-workspace-intelligence",
)
_SOURCE_PATHS = (
    "packages/product-kits/chat",
    "packages/product-kits/coding",
    "packages/product-kits/local-assistant",
    "packages/product-kits/common/browser",
    "packages/product-kits/common/git",
    "packages/product-kits/common/local-os",
    "packages/product-kits/common/pim",
    "packages/product-kits/common/retrieval",
    "packages/product-kits/common/web",
    "packages/product-kits/common/workspace-intelligence",
)
_MISSING_ROOTS = (
    "weavert_kit_chat",
    "weavert_kit_coding",
    "weavert_kit_local_assistant",
    "weavert_kit_common_browser",
    "weavert_kit_common_git",
    "weavert_kit_common_local_os",
    "weavert_kit_common_pim",
    "weavert_kit_common_retrieval",
    "weavert_kit_common_web",
    "weavert_kit_common_workspace_intelligence",
)

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


def _load_product_kit_module(module_name: str):
    return load_optional_module(
        module_name,
        surface=_SURFACE,
        distribution_names=_DISTRIBUTIONS,
        source_paths=_SOURCE_PATHS,
        expected_missing_roots=_MISSING_ROOTS,
    )


@lru_cache(maxsize=1)
def _reference_registry() -> dict[str, Any]:
    retrieval = _load_product_kit_module("weavert_kit_common_retrieval")
    web = _load_product_kit_module("weavert_kit_common_web")
    browser = _load_product_kit_module("weavert_kit_common_browser")
    local_os = _load_product_kit_module("weavert_kit_common_local_os")
    pim = _load_product_kit_module("weavert_kit_common_pim")
    git = _load_product_kit_module("weavert_kit_common_git")
    workspace = _load_product_kit_module("weavert_kit_common_workspace_intelligence")
    coding = _load_product_kit_module("weavert_kit_coding")
    chat = _load_product_kit_module("weavert_kit_chat")
    local_assistant = _load_product_kit_module("weavert_kit_local_assistant")

    shared_shapes = (
        retrieval.REFERENCE_SHARED_PACKAGE_SHAPE,
        web.REFERENCE_SHARED_PACKAGE_SHAPE,
        browser.REFERENCE_SHARED_PACKAGE_SHAPE,
        local_os.REFERENCE_SHARED_PACKAGE_SHAPE,
        pim.REFERENCE_SHARED_PACKAGE_SHAPE,
        git.REFERENCE_SHARED_PACKAGE_SHAPE,
        workspace.REFERENCE_SHARED_PACKAGE_SHAPE,
    )
    scenario_shapes = (
        coding.REFERENCE_SCENARIO_PACK_SHAPE,
        chat.REFERENCE_SCENARIO_PACK_SHAPE,
        local_assistant.REFERENCE_SCENARIO_PACK_SHAPE,
    )
    return {
        "shared_shapes": shared_shapes,
        "scenario_shapes": scenario_shapes,
        "shared_manifest_builders": {
            retrieval.REFERENCE_SHARED_PACKAGE_SHAPE.package_name: retrieval.reference_shared_package_manifest,
            web.REFERENCE_SHARED_PACKAGE_SHAPE.package_name: web.reference_shared_package_manifest,
            browser.REFERENCE_SHARED_PACKAGE_SHAPE.package_name: browser.reference_shared_package_manifest,
            local_os.REFERENCE_SHARED_PACKAGE_SHAPE.package_name: local_os.reference_shared_package_manifest,
            pim.REFERENCE_SHARED_PACKAGE_SHAPE.package_name: pim.reference_shared_package_manifest,
            git.REFERENCE_SHARED_PACKAGE_SHAPE.package_name: git.reference_shared_package_manifest,
            workspace.REFERENCE_SHARED_PACKAGE_SHAPE.package_name: workspace.reference_shared_package_manifest,
        },
        "scenario_manifest_builders": {
            coding.REFERENCE_SCENARIO_PACK_SHAPE.package_name: coding.reference_scenario_pack_manifest,
            chat.REFERENCE_SCENARIO_PACK_SHAPE.package_name: chat.reference_scenario_pack_manifest,
            local_assistant.REFERENCE_SCENARIO_PACK_SHAPE.package_name: local_assistant.reference_scenario_pack_manifest,
        },
        "runtime_pack_manifest_factories": (
            coding.coding_scenario_runtime_pack_manifests,
            chat.chat_scenario_runtime_pack_manifests,
            local_assistant.local_assistant_scenario_runtime_pack_manifests,
        ),
    }


def reference_shared_package_shapes() -> tuple[ReferenceSharedPackageShape, ...]:
    return _reference_registry()["shared_shapes"]


def reference_scenario_pack_shapes() -> tuple[ReferenceScenarioPackShape, ...]:
    return _reference_registry()["scenario_shapes"]


def reference_shared_package_shape(name: str) -> ReferenceSharedPackageShape:
    normalized = str(name)
    for shape in reference_shared_package_shapes():
        if normalized in {shape.package_name, shape.capability_key}:
            return shape
    raise KeyError(f"Unknown reference shared package shape: {name}")


def reference_scenario_pack_shape(name: str) -> ReferenceScenarioPackShape:
    normalized = str(name)
    for shape in reference_scenario_pack_shapes():
        if normalized in {shape.package_name, shape.profile, shape.display_name}:
            return shape
    raise KeyError(f"Unknown reference scenario pack shape: {name}")


def build_reference_shared_package_manifest(name: str) -> RuntimePackageManifest:
    package_name = reference_shared_package_shape(name).package_name
    try:
        factory = _reference_registry()["shared_manifest_builders"][package_name]
    except KeyError as exc:
        raise KeyError(f"Unknown reference shared package manifest: {name}") from exc
    return factory()


def build_reference_scenario_pack_manifest(name: str) -> RuntimePackageManifest:
    package_name = reference_scenario_pack_shape(name).package_name
    try:
        factory = _reference_registry()["scenario_manifest_builders"][package_name]
    except KeyError as exc:
        raise KeyError(f"Unknown reference scenario pack manifest: {name}") from exc
    return factory()


def reference_shared_package_manifests() -> tuple[RuntimePackageManifest, ...]:
    return tuple(
        build_reference_shared_package_manifest(shape.package_name)
        for shape in reference_shared_package_shapes()
    )


def reference_scenario_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    return tuple(
        build_reference_scenario_pack_manifest(shape.package_name)
        for shape in reference_scenario_pack_shapes()
    )


def reference_scenario_runtime_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    manifests: list[RuntimePackageManifest] = []
    seen: set[str] = set()
    for factory in _reference_registry()["runtime_pack_manifest_factories"]:
        for manifest in factory():
            if manifest.name in seen:
                continue
            manifests.append(manifest)
            seen.add(manifest.name)
    return tuple(manifests)


def __getattr__(name: str) -> Any:
    if name == "REFERENCE_SHARED_PACKAGE_SHAPES":
        return reference_shared_package_shapes()
    if name == "REFERENCE_SCENARIO_PACK_SHAPES":
        return reference_scenario_pack_shapes()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
