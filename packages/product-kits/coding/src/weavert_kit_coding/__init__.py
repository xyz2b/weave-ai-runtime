from __future__ import annotations

from weavert.runtime_package_protocols import RuntimePackageManifest
from weavert.scenario_runtime_pack_support import (
    ReferenceScenarioPackShape,
    build_reference_scenario_pack_manifest,
)
from weavert_kit_common_git import (
    CODING_SHARED_GIT_TOOLS,
    reference_shared_package_manifest as git_package_manifest,
)
from weavert_kit_common_workspace_intelligence import (
    CODING_SHARED_WORKSPACE_TOOLS,
    reference_shared_package_manifest as workspace_intelligence_package_manifest,
)

from ._builtins import coding_scenario_builtin_agents, coding_scenario_builtin_skills

CODING_WORKFLOW_CONTROL_TOOLS = (
    "agent",
    "skill",
    "task_archive",
    "task_assign_next",
    "task_block",
    "task_claim",
    "task_create",
    "task_delete",
    "task_get",
    "task_list",
    "task_release",
    "task_unarchive",
    "task_unblock",
    "task_update",
    "job_get",
    "job_list",
    "job_stop",
)
CODING_SCENARIO_AGENTS = (
    "coding-planner",
    "reviewer",
    "verifier",
)
CODING_GENERIC_AGENTS = (
    "plan",
    "verification",
    "planner",
    "coordinator",
    "worker",
)
CODING_SCENARIO_SKILLS = (
    "coding-loop",
    "review-change",
    "verify-change",
    "task-discipline",
    "repo-onboard",
)
CODING_GENERIC_SKILLS = (
    "verify",
    "debug",
    "stuck",
    "batch",
    "simplify",
)

REFERENCE_SCENARIO_PACK_SHAPE = ReferenceScenarioPackShape(
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
    shared_package_dependencies=(
        "weavert-shared-git",
        "weavert-shared-workspace-intelligence",
    ),
    expected_tools=(
        "read",
        "glob",
        "grep",
        "edit",
        "write",
        "bash",
        *CODING_WORKFLOW_CONTROL_TOOLS,
        *CODING_SHARED_GIT_TOOLS,
        *CODING_SHARED_WORKSPACE_TOOLS,
    ),
    expected_agents=(*CODING_SCENARIO_AGENTS, *CODING_GENERIC_AGENTS),
    expected_skills=(*CODING_SCENARIO_SKILLS, *CODING_GENERIC_SKILLS),
    workflow_agent_ids=CODING_SCENARIO_AGENTS,
    workflow_skill_ids=CODING_SCENARIO_SKILLS,
    default_boundaries=(
        "workspace-oriented by default",
        "shell and file mutation surfaces are expected",
        "verification and review loops stay visible",
    ),
    app_owned_wiring=(
        "model provider selection",
        "transcript and child-run store selection",
        "host binding for terminal or IDE shells",
        "app-owned main shell agent and enhanced shell tool replacements",
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
        "The scenario pack publishes product-role workflow agents without replacing the generic first-party planning layer.",
        "The coding workflow layer remains additive to app-owned shells and shared coding packages.",
    ),
)


def reference_scenario_pack_shapes() -> tuple[ReferenceScenarioPackShape, ...]:
    return (REFERENCE_SCENARIO_PACK_SHAPE,)


def reference_scenario_pack_shape(name: str | None = None) -> ReferenceScenarioPackShape:
    normalized = REFERENCE_SCENARIO_PACK_SHAPE.package_name if name is None else str(name)
    if normalized in {
        REFERENCE_SCENARIO_PACK_SHAPE.package_name,
        REFERENCE_SCENARIO_PACK_SHAPE.profile,
        REFERENCE_SCENARIO_PACK_SHAPE.display_name,
    }:
        return REFERENCE_SCENARIO_PACK_SHAPE
    raise KeyError(f"Unknown coding scenario pack shape: {name}")


def reference_scenario_pack_manifest() -> RuntimePackageManifest:
    return build_reference_scenario_pack_manifest(
        REFERENCE_SCENARIO_PACK_SHAPE,
        builtin_agents=coding_scenario_builtin_agents,
        builtin_skills=coding_scenario_builtin_skills,
    )


def reference_scenario_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_scenario_pack_manifest(),)


def coding_scenario_runtime_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (
        git_package_manifest(),
        workspace_intelligence_package_manifest(),
        reference_scenario_pack_manifest(),
    )


__all__ = [
    "CODING_GENERIC_AGENTS",
    "CODING_GENERIC_SKILLS",
    "CODING_SCENARIO_AGENTS",
    "CODING_SCENARIO_SKILLS",
    "CODING_WORKFLOW_CONTROL_TOOLS",
    "REFERENCE_SCENARIO_PACK_SHAPE",
    "coding_scenario_runtime_pack_manifests",
    "reference_scenario_pack_manifest",
    "reference_scenario_pack_manifests",
    "reference_scenario_pack_shape",
    "reference_scenario_pack_shapes",
]
