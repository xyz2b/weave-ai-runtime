from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import Diagnostic, DiagnosticSeverity
from .runtime_package_protocols import (
    CapabilityBinding,
    CapabilityPackageBindingSpec,
    ContextContributorBinding,
    ContextContributorStage,
    PackageAssemblyStage,
    PackageContribution,
    RuntimePackageManifest,
    build_capability_only_package_manifest,
    snapshot_runtime_value,
)


@dataclass(frozen=True, slots=True)
class ReferenceSharedPackageShape:
    package_name: str
    capability_key: str
    description: str
    shared_surface_family: str
    intended_profiles: tuple[str, ...]
    surfaces: tuple[str, ...]
    tool_ids: tuple[str, ...] = ()
    agent_ids: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()
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
    expected_tools: tuple[str, ...]
    expected_agents: tuple[str, ...]
    expected_skills: tuple[str, ...]
    default_boundaries: tuple[str, ...]
    app_owned_wiring: tuple[str, ...]
    host_assumptions: tuple[str, ...]
    permission_policy_posture: tuple[str, ...]
    profile_prompt_fragments: tuple[str, ...]
    staged_scope_boundaries: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def capability_key(self) -> str:
        return f"weavert.reference.scenario.{self.profile}"


@dataclass(frozen=True, slots=True)
class _ScenarioPackProfileContributor:
    prompt_fragments: tuple[str, ...]

    async def collect(self, **_kwargs):
        return self.prompt_fragments


def _reference_package_candidate_metadata(package_name: str) -> dict[str, dict[str, str]]:
    return {
        "package_candidate": {
            "candidate_id": f"reference::{package_name}",
            "version": "1.0.0",
        }
    }


def _surface_inventory(values: tuple[str, ...]) -> list[str]:
    return list(_stable_unique_names(values))


def _shared_package_surface_contract(shape: ReferenceSharedPackageShape) -> dict[str, object]:
    return {
        **_reference_package_candidate_metadata(shape.package_name),
        "reference_kind": "shared-package",
        "shared_surface_family": shape.shared_surface_family,
        "intended_profiles": list(shape.intended_profiles),
        "shared_surfaces": list(shape.surfaces),
        "tool_ids": _surface_inventory(shape.tool_ids),
        "agent_ids": _surface_inventory(shape.agent_ids),
        "skill_ids": _surface_inventory(shape.skill_ids),
        "notes": list(shape.notes),
    }


def _scenario_pack_surface_contract(shape: ReferenceScenarioPackShape) -> dict[str, object]:
    return {
        **_reference_package_candidate_metadata(shape.package_name),
        "reference_kind": "scenario-pack",
        "scenario_profile": shape.profile,
        "recommended_distribution": shape.recommended_distribution,
        "recommended_first_party_packages": list(shape.recommended_first_party_packages),
        "shared_package_dependencies": list(shape.shared_package_dependencies),
        "expected_tools": _surface_inventory(shape.expected_tools),
        "expected_agents": _surface_inventory(shape.expected_agents),
        "expected_skills": _surface_inventory(shape.expected_skills),
        "default_boundaries": list(shape.default_boundaries),
        "app_owned_wiring": list(shape.app_owned_wiring),
        "host_assumptions": list(shape.host_assumptions),
        "permission_policy_posture": list(shape.permission_policy_posture),
        "profile_prompt_fragments": list(shape.profile_prompt_fragments),
        "staged_scope_boundaries": list(shape.staged_scope_boundaries),
        "notes": list(shape.notes),
    }


REFERENCE_SHARED_PACKAGE_SHAPES: tuple[ReferenceSharedPackageShape, ...] = (
    ReferenceSharedPackageShape(
        package_name="weavert-shared-retrieval",
        capability_key="weavert.reference.shared.retrieval",
        description="Reference retrieval-oriented shared package for chat and assistant scenario packs.",
        shared_surface_family="retrieval",
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
        shared_surface_family="web-bridge",
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
        shared_surface_family="browser-bridge",
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
        shared_surface_family="local-os-bridge",
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
        shared_surface_family="pim-bridge",
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
        expected_tools=("read", "glob", "grep", "edit", "write", "bash"),
        expected_agents=("plan", "verification", "planner", "coordinator", "worker"),
        expected_skills=("verify", "debug", "stuck", "batch", "simplify"),
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
        profile_prompt_fragments=(
            "Scenario profile: AI coding.",
            "Keep workspace-oriented planning, verification, and review posture visible.",
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
        expected_tools=(),
        expected_agents=(),
        expected_skills=("remember",),
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
        profile_prompt_fragments=(
            "Scenario profile: AI chat.",
            "Preserve read-mostly defaults and avoid implicit workspace mutation or shell execution.",
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
        expected_tools=(),
        expected_agents=(),
        expected_skills=("remember",),
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
        profile_prompt_fragments=(
            "Scenario profile: local assistant.",
            "Preserve host-centric defaults and require explicit approval posture for bridge-heavy actions.",
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
    surface_contract = _shared_package_surface_contract(shape)
    capability_surface_contract = snapshot_runtime_value(surface_contract)
    manifest_surface_contract = snapshot_runtime_value(surface_contract)
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
                    "surfaces": list(shape.surfaces),
                    **capability_surface_contract,
                },
                metadata={
                    "reference_kind": "shared-package",
                    "shared_surface_family": shape.shared_surface_family,
                    "intended_profiles": list(shape.intended_profiles),
                    "tool_ids": _surface_inventory(shape.tool_ids),
                    "agent_ids": _surface_inventory(shape.agent_ids),
                    "skill_ids": _surface_inventory(shape.skill_ids),
                },
            ),
        ),
        manifest_metadata=manifest_surface_contract,
    )


def build_reference_scenario_pack_manifest(name: str) -> RuntimePackageManifest:
    shape = reference_scenario_pack_shape(name)
    dependencies = _stable_unique_names(("weavert-core", *shape.shared_package_dependencies))
    surface_contract = _scenario_pack_surface_contract(shape)
    capability_surface_contract = snapshot_runtime_value(surface_contract)
    manifest_surface_contract = snapshot_runtime_value(surface_contract)

    def _assemble(context) -> PackageContribution:
        if context.stage != PackageAssemblyStage.SERVICES:
            return PackageContribution()
        missing_recommended_packages = tuple(
            package_name
            for package_name in shape.recommended_first_party_packages
            if package_name not in context.selected_packages
        )
        diagnostics: list[Diagnostic] = []
        if missing_recommended_packages:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    code="scenario_pack_recommended_first_party_packages_missing",
                    message=(
                        f"Scenario pack '{shape.package_name}' expects app-owned wiring to also "
                        f"select recommended first-party package(s): "
                        f"{', '.join(missing_recommended_packages)}"
                    ),
                    definition_type="runtime_package_manifest",
                    source="package",
                    location=shape.package_name,
                    details={
                        "scenario_profile": shape.profile,
                        "recommended_first_party_packages": list(shape.recommended_first_party_packages),
                        "missing_first_party_packages": list(missing_recommended_packages),
                        "selected_packages": list(context.selected_packages),
                    },
                )
            )
        elif (
            shape.profile != "coding"
            and "weavert-devtools" not in context.selected_packages
            and "weavert-planning" not in context.selected_packages
        ):
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    code="scenario_pack_default_profile_omits_coding_surfaces",
                    message=(
                        f"Scenario pack '{shape.package_name}' intentionally omits coding-oriented "
                        "devtools and planning surfaces from its default profile; enable them "
                        "explicitly in app-owned wiring only when that escalation is intended."
                    ),
                    definition_type="runtime_package_manifest",
                    source="package",
                    location=shape.package_name,
                    details={
                        "scenario_profile": shape.profile,
                        "omitted_first_party_packages": ["weavert-devtools", "weavert-planning"],
                        "selected_packages": list(context.selected_packages),
                    },
                )
            )
        contributor_name = f"{shape.package_name}.profile_guidance"
        return PackageContribution(
            context_contributors=(
                ContextContributorBinding(
                    name=contributor_name,
                    stage=ContextContributorStage.HOOKS,
                    contributor=_ScenarioPackProfileContributor(shape.profile_prompt_fragments),
                    owner=context.ownership(
                        "context_contributor",
                        contributor_name=contributor_name,
                        contributor_stage=ContextContributorStage.HOOKS.value,
                        package_pattern="scenario-pack",
                        scenario_profile=shape.profile,
                    ),
                    order=50,
                    metadata={
                        "package_pattern": "scenario-pack",
                        "scenario_profile": shape.profile,
                        "profile_prompt_fragments": list(shape.profile_prompt_fragments),
                    },
                ),
            ),
            capabilities=(
                CapabilityBinding(
                    key=shape.capability_key,
                    value={
                        "kind": "scenario-pack",
                        "package_name": shape.package_name,
                        "profile": shape.profile,
                        "scenario_profile": shape.profile,
                        "display_name": shape.display_name,
                        "description": shape.description,
                        **capability_surface_contract,
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
                "context_contributors": [contributor_name],
            },
            diagnostics=tuple(diagnostics),
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
            **manifest_surface_contract,
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
