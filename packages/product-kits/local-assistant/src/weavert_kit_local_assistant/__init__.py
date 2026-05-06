from __future__ import annotations

from weavert.package_system.protocols import RuntimePackageManifest
from weavert.extension_contracts.scenario_runtime_packs import (
    ReferenceScenarioPackShape,
    build_reference_scenario_pack_manifest,
)
from weavert_kit_common_browser import (
    LOCAL_ASSISTANT_BROWSER_HOST_FACET,
    LOCAL_ASSISTANT_BROWSER_TOOLS,
    reference_shared_package_manifest as browser_package_manifest,
)
from weavert_kit_common_local_os import (
    LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
    LOCAL_ASSISTANT_LOCAL_OS_TOOLS,
    reference_shared_package_manifest as local_os_package_manifest,
)
from weavert_kit_common_pim import (
    LOCAL_ASSISTANT_PIM_HOST_FACET,
    LOCAL_ASSISTANT_PIM_TOOLS,
    reference_shared_package_manifest as pim_package_manifest,
)
from weavert_kit_common_retrieval import (
    CHAT_RETRIEVAL_TOOLS,
    reference_shared_package_manifest as retrieval_package_manifest,
)

from ._builtins import (
    LOCAL_ASSISTANT_SCENARIO_AGENTS,
    LOCAL_ASSISTANT_SCENARIO_SKILLS,
    local_assistant_scenario_builtin_agents,
    local_assistant_scenario_builtin_skills,
)

LOCAL_ASSISTANT_WORKFLOW_CONTROL_TOOLS = ("ask_user", "skill")

REFERENCE_SCENARIO_PACK_SHAPE = ReferenceScenarioPackShape(
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
    expected_tools=(
        *CHAT_RETRIEVAL_TOOLS,
        *LOCAL_ASSISTANT_WORKFLOW_CONTROL_TOOLS,
        *LOCAL_ASSISTANT_BROWSER_TOOLS,
        *LOCAL_ASSISTANT_LOCAL_OS_TOOLS,
        *LOCAL_ASSISTANT_PIM_TOOLS,
    ),
    expected_agents=LOCAL_ASSISTANT_SCENARIO_AGENTS,
    expected_skills=("remember", *LOCAL_ASSISTANT_SCENARIO_SKILLS),
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
    workflow_agent_ids=LOCAL_ASSISTANT_SCENARIO_AGENTS,
    workflow_skill_ids=LOCAL_ASSISTANT_SCENARIO_SKILLS,
    staged_scope_boundaries=(
        "start with retrieval and approval-mediated bridge composition before full automation",
        "treat richer automation bundles as later follow-up work",
    ),
    notes=(
        "Local assistant remains a staged bridge reference, not a full product shell.",
        "Final host mediation, final allowlists, and final audit sinks stay outside the scenario pack.",
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
    raise KeyError(f"Unknown local-assistant scenario pack shape: {name}")


def reference_scenario_pack_manifest() -> RuntimePackageManifest:
    return build_reference_scenario_pack_manifest(
        REFERENCE_SCENARIO_PACK_SHAPE,
        builtin_agents=local_assistant_scenario_builtin_agents,
        builtin_skills=local_assistant_scenario_builtin_skills,
    )


def reference_scenario_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_scenario_pack_manifest(),)


def local_assistant_scenario_runtime_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (
        retrieval_package_manifest(),
        browser_package_manifest(),
        local_os_package_manifest(),
        pim_package_manifest(),
        reference_scenario_pack_manifest(),
    )


__all__ = [
    "LOCAL_ASSISTANT_BROWSER_HOST_FACET",
    "LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET",
    "LOCAL_ASSISTANT_PIM_HOST_FACET",
    "LOCAL_ASSISTANT_SCENARIO_AGENTS",
    "LOCAL_ASSISTANT_SCENARIO_SKILLS",
    "LOCAL_ASSISTANT_WORKFLOW_CONTROL_TOOLS",
    "REFERENCE_SCENARIO_PACK_SHAPE",
    "local_assistant_scenario_runtime_pack_manifests",
    "reference_scenario_pack_manifest",
    "reference_scenario_pack_manifests",
    "reference_scenario_pack_shape",
    "reference_scenario_pack_shapes",
]
