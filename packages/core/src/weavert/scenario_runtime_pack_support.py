from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .diagnostics import Diagnostic, DiagnosticSeverity
from .runtime_package_protocols import (
    CapabilityBinding,
    ContextContributorBinding,
    ContextContributorStage,
    PackageAssemblyStage,
    PackageContribution,
    RuntimePackageManifest,
    annotate_builtin_owner,
    snapshot_runtime_value,
)

BuiltinDefinitions = Callable[[], tuple] | Iterable


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
    workflow_tool_ids: tuple[str, ...] = ()
    workflow_agent_ids: tuple[str, ...] = ()
    workflow_skill_ids: tuple[str, ...] = ()
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


def build_reference_shared_package_manifest(
    shape: ReferenceSharedPackageShape,
    *,
    builtin_tools: BuiltinDefinitions = (),
    builtin_agents: BuiltinDefinitions = (),
    builtin_skills: BuiltinDefinitions = (),
) -> RuntimePackageManifest:
    surface_contract = _shared_package_surface_contract(shape)
    capability_surface_contract = snapshot_runtime_value(surface_contract)
    manifest_surface_contract = snapshot_runtime_value(surface_contract)
    resolved_builtin_tools = _resolve_builtin_definitions(builtin_tools)
    resolved_builtin_agents = _resolve_builtin_definitions(builtin_agents)
    resolved_builtin_skills = _resolve_builtin_definitions(builtin_skills)
    dependencies = ("weavert-core",)

    def _assemble(context) -> PackageContribution:
        if context.stage == PackageAssemblyStage.BUILTINS:
            return PackageContribution(
                builtin_tools=_annotated_builtin_definitions(
                    resolved_builtin_tools,
                    package_name=context.manifest.name,
                    package_role=context.manifest.role,
                    expected_names=shape.tool_ids,
                ),
                builtin_agents=_annotated_builtin_definitions(
                    resolved_builtin_agents,
                    package_name=context.manifest.name,
                    package_role=context.manifest.role,
                    expected_names=shape.agent_ids,
                ),
                builtin_skills=_annotated_builtin_definitions(
                    resolved_builtin_skills,
                    package_name=context.manifest.name,
                    package_role=context.manifest.role,
                    expected_names=shape.skill_ids,
                ),
            )
        if context.stage != PackageAssemblyStage.SERVICES:
            return PackageContribution()
        return PackageContribution(
            capabilities=(
                CapabilityBinding(
                    key=shape.capability_key,
                    value={
                        "kind": "shared-package",
                        "package_name": shape.package_name,
                        "capability_key": shape.capability_key,
                        "description": shape.description,
                        "surfaces": list(shape.surfaces),
                        **capability_surface_contract,
                    },
                    owner=context.ownership(
                        "capability",
                        capability_key=shape.capability_key,
                        package_pattern="shared-package",
                        shared_surface_family=shape.shared_surface_family,
                    ),
                    metadata={
                        "package_pattern": "shared-package",
                        "shared_surface_family": shape.shared_surface_family,
                    },
                ),
            ),
            metadata={
                "package_pattern": "shared-package",
                "registration_path": "PackageContribution.capabilities",
            },
        )

    return RuntimePackageManifest(
        name=shape.package_name,
        role="shared_package",
        description=shape.description,
        dependencies=dependencies,
        assembly_entrypoint=_assemble,
        metadata={
            "package_pattern": "shared-package",
            "baseline_dependencies": list(dependencies),
            "capabilities": [shape.capability_key],
            "capability_registration_path": "PackageContribution.capabilities",
            **manifest_surface_contract,
        },
    )


def build_reference_scenario_pack_manifest(
    shape: ReferenceScenarioPackShape,
    *,
    builtin_tools: BuiltinDefinitions = (),
    builtin_agents: BuiltinDefinitions = (),
    builtin_skills: BuiltinDefinitions = (),
) -> RuntimePackageManifest:
    dependencies = stable_unique_names(("weavert-core", *shape.shared_package_dependencies))
    surface_contract = _scenario_pack_surface_contract(shape)
    capability_surface_contract = snapshot_runtime_value(surface_contract)
    manifest_surface_contract = snapshot_runtime_value(surface_contract)
    resolved_builtin_tools = _resolve_builtin_definitions(builtin_tools)
    resolved_builtin_agents = _resolve_builtin_definitions(builtin_agents)
    resolved_builtin_skills = _resolve_builtin_definitions(builtin_skills)

    def _assemble(context) -> PackageContribution:
        if context.stage == PackageAssemblyStage.BUILTINS:
            return PackageContribution(
                builtin_tools=_annotated_builtin_definitions(
                    resolved_builtin_tools,
                    package_name=context.manifest.name,
                    package_role=context.manifest.role,
                    expected_names=shape.workflow_tool_ids,
                ),
                builtin_agents=_annotated_builtin_definitions(
                    resolved_builtin_agents,
                    package_name=context.manifest.name,
                    package_role=context.manifest.role,
                    expected_names=shape.workflow_agent_ids,
                ),
                builtin_skills=_annotated_builtin_definitions(
                    resolved_builtin_skills,
                    package_name=context.manifest.name,
                    package_role=context.manifest.role,
                    expected_names=shape.workflow_skill_ids,
                ),
            )
        if context.stage != PackageAssemblyStage.SERVICES:
            return PackageContribution()

        missing_recommended_packages = tuple(
            package_name
            for package_name in shape.recommended_first_party_packages
            if package_name not in context.selected_packages
        )
        admitted_coding_packages = tuple(
            package_name
            for package_name in ("weavert-devtools", "weavert-planning")
            if package_name in context.selected_packages
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
        if shape.profile != "coding" and admitted_coding_packages:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    code="scenario_pack_non_coding_profile_admits_coding_surfaces",
                    message=(
                        f"Scenario pack '{shape.package_name}' is a non-coding profile, but app-owned "
                        "wiring admitted coding-oriented devtools or planning surfaces: "
                        f"{', '.join(admitted_coding_packages)}"
                    ),
                    definition_type="runtime_package_manifest",
                    source="package",
                    location=shape.package_name,
                    details={
                        "scenario_profile": shape.profile,
                        "admitted_first_party_packages": list(admitted_coding_packages),
                        "selected_packages": list(context.selected_packages),
                    },
                )
            )
        elif shape.profile != "coding" and not missing_recommended_packages:
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


def stable_unique_names(names: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        ordered.append(name)
        seen.add(name)
    return tuple(ordered)


def _reference_package_candidate_metadata(package_name: str) -> dict[str, dict[str, str]]:
    return {
        "package_candidate": {
            "candidate_id": f"reference::{package_name}",
            "version": "1.0.0",
        }
    }


def _surface_inventory(values: tuple[str, ...]) -> list[str]:
    return list(stable_unique_names(values))


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
        "workflow_tool_ids": _surface_inventory(shape.workflow_tool_ids),
        "workflow_agent_ids": _surface_inventory(shape.workflow_agent_ids),
        "workflow_skill_ids": _surface_inventory(shape.workflow_skill_ids),
        "default_boundaries": list(shape.default_boundaries),
        "app_owned_wiring": list(shape.app_owned_wiring),
        "host_assumptions": list(shape.host_assumptions),
        "permission_policy_posture": list(shape.permission_policy_posture),
        "profile_prompt_fragments": list(shape.profile_prompt_fragments),
        "staged_scope_boundaries": list(shape.staged_scope_boundaries),
        "notes": list(shape.notes),
    }


def _annotated_builtin_definitions(
    definitions: tuple,
    *,
    package_name: str,
    package_role: str,
    expected_names: tuple[str, ...],
) -> tuple:
    actual_names = tuple(getattr(definition, "name", None) for definition in definitions)
    if actual_names != expected_names:
        raise ValueError(
            f"Builtin definitions for {package_name} do not match the published surface contract: "
            f"expected {expected_names}, got {actual_names}"
        )
    return tuple(
        annotate_builtin_owner(
            definition,
            package_name=package_name,
            package_role=package_role,
        )
        for definition in definitions
    )


def _resolve_builtin_definitions(definitions: BuiltinDefinitions) -> tuple:
    resolved = definitions() if callable(definitions) else definitions
    return tuple(resolved)


__all__ = [
    "ReferenceScenarioPackShape",
    "ReferenceSharedPackageShape",
    "build_reference_scenario_pack_manifest",
    "build_reference_shared_package_manifest",
    "stable_unique_names",
]
