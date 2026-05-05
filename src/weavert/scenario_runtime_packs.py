from __future__ import annotations

from dataclasses import dataclass

from .runtime_package_protocols import (
    CapabilityBinding,
    CapabilityPackageBindingSpec,
    PackageAssemblyStage,
    PackageContribution,
    RuntimePackageManifest,
    build_capability_only_package_manifest,
)


@dataclass(frozen=True, slots=True)
class ReferenceSharedPackageShape:
    package_name: str
    capability_key: str
    description: str
    intended_profiles: tuple[str, ...]
    surfaces: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceScenarioPackShape:
    package_name: str
    profile: str
    display_name: str
    description: str
    recommended_distribution: str
    recommended_first_party_packages: tuple[str, ...]
    shared_package_dependencies: tuple[str, ...]
    contributed_agents: tuple[str, ...]
    contributed_skills: tuple[str, ...]
    default_boundaries: tuple[str, ...]
    app_owned_wiring: tuple[str, ...]
    host_assumptions: tuple[str, ...]
    permission_policy_posture: tuple[str, ...]
    staged_scope_boundaries: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def capability_key(self) -> str:
        return f"weavert.reference.scenario.{self.profile}"


REFERENCE_SHARED_PACKAGE_SHAPES: tuple[ReferenceSharedPackageShape, ...] = (
    ReferenceSharedPackageShape(
        package_name="weavert-shared-retrieval",
        capability_key="weavert.reference.shared.retrieval",
        description="Reference retrieval-oriented shared package for chat and assistant scenario packs.",
        intended_profiles=("chat", "local_assistant"),
        surfaces=(
            "retrieval context contributors",
            "search-oriented memory adapters",
            "grounding helpers",
        ),
        notes=(
            "Keep retrieval adapters reusable so multiple scenario packs can compose them.",
            "Do not treat retrieval ownership as a coding-only concern.",
        ),
    ),
    ReferenceSharedPackageShape(
        package_name="weavert-bridge-web",
        capability_key="weavert.reference.bridge.web",
        description="Reference shared package shape for web and HTTP capability surfaces.",
        intended_profiles=("chat", "local_assistant"),
        surfaces=("web fetch bridge", "remote content access", "HTTP-aware grounding helpers"),
        notes=(
            "Scenario packs should consume this bridge instead of duplicating web adapters.",
        ),
    ),
    ReferenceSharedPackageShape(
        package_name="weavert-bridge-browser",
        capability_key="weavert.reference.bridge.browser",
        description="Reference shared package shape for browser automation capability surfaces.",
        intended_profiles=("local_assistant",),
        surfaces=("browser bridge", "tab/session mediation", "navigation helpers"),
        notes=(
            "Keep browser bindings reusable and host-mediated instead of embedding them into each scenario pack.",
        ),
    ),
    ReferenceSharedPackageShape(
        package_name="weavert-bridge-local-os",
        capability_key="weavert.reference.bridge.local_os",
        description="Reference shared package shape for local OS capability surfaces.",
        intended_profiles=("local_assistant",),
        surfaces=("filesystem adapter", "process launch mediation", "desktop integration hooks"),
        notes=(
            "Local OS surfaces need stronger permission posture than read-mostly chat scenarios.",
        ),
    ),
    ReferenceSharedPackageShape(
        package_name="weavert-bridge-pim",
        capability_key="weavert.reference.bridge.pim",
        description="Reference shared package shape for personal information manager capability surfaces.",
        intended_profiles=("local_assistant",),
        surfaces=("calendar adapter", "contacts/tasks adapter", "notification handoff hooks"),
        notes=(
            "PIM adapters remain shared integrations even when a local assistant scenario pack recommends them.",
        ),
    ),
)


REFERENCE_SCENARIO_PACK_SHAPES: tuple[ReferenceScenarioPackShape, ...] = (
    ReferenceScenarioPackShape(
        package_name="weavert-scenario-coding",
        profile="coding",
        display_name="AI coding",
        description="Reference scenario pack for workspace-oriented coding experiences.",
        recommended_distribution="weavert-core",
        recommended_first_party_packages=(
            "weavert-devtools",
            "weavert-planning",
            "weavert-builtin-workflows",
        ),
        shared_package_dependencies=(),
        contributed_agents=("plan", "verification", "planner", "coordinator", "worker"),
        contributed_skills=("verify", "debug", "stuck", "batch", "simplify"),
        default_boundaries=(
            "workspace-oriented by default",
            "shell and file mutation surfaces are expected",
            "verification and review loops stay visible",
        ),
        app_owned_wiring=(
            "model provider selection",
            "transcript and child-run store selection",
            "host binding for terminal or IDE shells",
            "final permission policy composition",
        ),
        host_assumptions=(
            "CLI or IDE hosts may expose workspace context and terminal rendering",
        ),
        permission_policy_posture=(
            "start from coding-grade read/write or approval-mediated execution policies",
            "keep deployment-specific allowlists in app-owned policy layers",
        ),
        notes=(
            "The scenario pack proves profile selection without inventing a new package protocol.",
        ),
    ),
    ReferenceScenarioPackShape(
        package_name="weavert-scenario-chat",
        profile="chat",
        display_name="AI chat",
        description="Reference scenario pack for read-mostly chat experiences.",
        recommended_distribution="weavert-core",
        recommended_first_party_packages=("weavert-memory",),
        shared_package_dependencies=(
            "weavert-shared-retrieval",
            "weavert-bridge-web",
        ),
        contributed_agents=(),
        contributed_skills=("remember",),
        default_boundaries=(
            "read-mostly by default",
            "no implicit workspace mutation or shell execution surfaces",
            "grounding and retrieval are shared-package concerns",
        ),
        app_owned_wiring=(
            "model provider selection",
            "session/transcript store selection",
            "host binding for web, mobile, or support surfaces",
            "final permission policy composition",
        ),
        host_assumptions=(
            "host remains lightweight and may only expose notifications or approval prompts",
        ),
        permission_policy_posture=(
            "default to read-only or approval-first policies",
            "treat any write-capable bridge as an app-owned escalation decision",
        ),
        notes=(
            "Chat inherits memory and retrieval posture without inheriting coding defaults.",
        ),
    ),
    ReferenceScenarioPackShape(
        package_name="weavert-scenario-local-assistant",
        profile="local_assistant",
        display_name="local assistant",
        description="Reference scenario pack for host-centric local assistant experiences.",
        recommended_distribution="weavert-core",
        recommended_first_party_packages=("weavert-memory",),
        shared_package_dependencies=(
            "weavert-shared-retrieval",
            "weavert-bridge-browser",
            "weavert-bridge-local-os",
            "weavert-bridge-pim",
        ),
        contributed_agents=(),
        contributed_skills=("remember",),
        default_boundaries=(
            "host-centric by default",
            "stronger permission, audit, and approval expectations than chat",
            "bridge-heavy composition without implicit coding surfaces",
        ),
        app_owned_wiring=(
            "model provider selection",
            "durable store selection for transcripts, jobs, and memory",
            "desktop or device host binding",
            "final permission policy composition and audit sinks",
        ),
        host_assumptions=(
            "host owns desktop or device mediation and can expose bridge-specific approval UX",
            "host decides which browser, OS, or PIM bridges are actually bound",
        ),
        permission_policy_posture=(
            "compose staged approval layers for browser, OS, and PIM actions",
            "keep final high-risk allowlists outside the scenario pack",
        ),
        staged_scope_boundaries=(
            "start with retrieval and approval-mediated bridge composition before full automation",
            "treat richer automation bundles as later follow-up work",
        ),
        notes=(
            "Local assistant remains a boundary reference first, not a full product shell.",
        ),
    ),
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
    shape = reference_shared_package_shape(name)
    return build_capability_only_package_manifest(
        name=shape.package_name,
        role="shared_capability",
        description=shape.description,
        capabilities=(
            CapabilityPackageBindingSpec(
                key=shape.capability_key,
                value={
                    "kind": "shared-package",
                    "package_name": shape.package_name,
                    "capability_key": shape.capability_key,
                    "description": shape.description,
                    "intended_profiles": list(shape.intended_profiles),
                    "surfaces": list(shape.surfaces),
                    "notes": list(shape.notes),
                },
                metadata={
                    "reference_kind": "shared-package",
                    "intended_profiles": list(shape.intended_profiles),
                },
            ),
        ),
        manifest_metadata={
            "reference_kind": "shared-package",
            "intended_profiles": list(shape.intended_profiles),
            "shared_surfaces": list(shape.surfaces),
        },
    )


def build_reference_scenario_pack_manifest(name: str) -> RuntimePackageManifest:
    shape = reference_scenario_pack_shape(name)
    dependencies = _stable_unique_names(("weavert-core", *shape.shared_package_dependencies))

    def _assemble(context) -> PackageContribution:
        if context.stage != PackageAssemblyStage.SERVICES:
            return PackageContribution()
        return PackageContribution(
            capabilities=(
                CapabilityBinding(
                    key=shape.capability_key,
                    value={
                        "kind": "scenario-pack",
                        "package_name": shape.package_name,
                        "profile": shape.profile,
                        "display_name": shape.display_name,
                        "recommended_distribution": shape.recommended_distribution,
                        "recommended_first_party_packages": list(
                            shape.recommended_first_party_packages
                        ),
                        "shared_package_dependencies": list(shape.shared_package_dependencies),
                        "contributed_agents": list(shape.contributed_agents),
                        "contributed_skills": list(shape.contributed_skills),
                        "default_boundaries": list(shape.default_boundaries),
                        "app_owned_wiring": list(shape.app_owned_wiring),
                        "host_assumptions": list(shape.host_assumptions),
                        "permission_policy_posture": list(shape.permission_policy_posture),
                        "staged_scope_boundaries": list(shape.staged_scope_boundaries),
                        "notes": list(shape.notes),
                    },
                    owner=context.ownership(
                        "capability",
                        capability_key=shape.capability_key,
                        package_pattern="scenario-pack",
                        scenario_profile=shape.profile,
                    ),
                    metadata={
                        "package_pattern": "scenario-pack",
                        "scenario_profile": shape.profile,
                    },
                ),
            ),
            metadata={
                "package_pattern": "scenario-pack",
                "registration_path": "PackageContribution.capabilities",
                "scenario_profile": shape.profile,
            },
        )

    return RuntimePackageManifest(
        name=shape.package_name,
        role="scenario_pack",
        description=shape.description,
        dependencies=dependencies,
        assembly_entrypoint=_assemble,
        metadata={
            "package_pattern": "scenario-pack",
            "baseline_dependencies": list(dependencies),
            "capabilities": [shape.capability_key],
            "capability_registration_path": "PackageContribution.capabilities",
            "reference_kind": "scenario-pack",
            "scenario_profile": shape.profile,
            "recommended_distribution": shape.recommended_distribution,
            "recommended_first_party_packages": list(shape.recommended_first_party_packages),
            "shared_package_dependencies": list(shape.shared_package_dependencies),
            "contributed_agents": list(shape.contributed_agents),
            "contributed_skills": list(shape.contributed_skills),
            "default_boundaries": list(shape.default_boundaries),
            "app_owned_wiring": list(shape.app_owned_wiring),
            "host_assumptions": list(shape.host_assumptions),
            "permission_policy_posture": list(shape.permission_policy_posture),
            "staged_scope_boundaries": list(shape.staged_scope_boundaries),
            "notes": list(shape.notes),
        },
    )


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
    return (*reference_shared_package_manifests(), *reference_scenario_pack_manifests())


def _stable_unique_names(names: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        ordered.append(name)
        seen.add(name)
    return tuple(ordered)


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
