from __future__ import annotations

from weavert.package_system.protocols import RuntimePackageManifest
from weavert.extension_contracts.scenario_runtime_packs import (
    ReferenceScenarioPackShape,
    build_reference_scenario_pack_manifest,
)
from weavert_kit_common_retrieval import CHAT_RETRIEVAL_TOOLS, reference_shared_package_manifest as retrieval_package_manifest
from weavert_kit_common_web import CHAT_WEB_TOOLS, reference_shared_package_manifest as web_package_manifest

from ._builtins import (
    CHAT_SCENARIO_AGENTS,
    CHAT_SCENARIO_SKILLS,
    chat_scenario_builtin_agents,
    chat_scenario_builtin_skills,
)

CHAT_WORKFLOW_CONTROL_TOOLS = ("ask_user",)

REFERENCE_SCENARIO_PACK_SHAPE = ReferenceScenarioPackShape(
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
    expected_tools=(*CHAT_RETRIEVAL_TOOLS, *CHAT_WEB_TOOLS, *CHAT_WORKFLOW_CONTROL_TOOLS),
    expected_agents=CHAT_SCENARIO_AGENTS,
    expected_skills=("remember", *CHAT_SCENARIO_SKILLS),
    default_boundaries=(
        "read-mostly by default",
        "no implicit workspace mutation or shell execution surfaces",
        "retrieval and web grounding stay shared-package concerns while workflow roles stay scenario-pack owned",
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
    workflow_agent_ids=CHAT_SCENARIO_AGENTS,
    workflow_skill_ids=CHAT_SCENARIO_SKILLS,
    notes=(
        "Chat inherits memory and retrieval posture without inheriting coding defaults.",
        "The chat scenario pack owns workflow agents and skills, while shared retrieval/web packages own the grounding tools.",
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
    raise KeyError(f"Unknown chat scenario pack shape: {name}")


def reference_scenario_pack_manifest() -> RuntimePackageManifest:
    return build_reference_scenario_pack_manifest(
        REFERENCE_SCENARIO_PACK_SHAPE,
        builtin_agents=chat_scenario_builtin_agents,
        builtin_skills=chat_scenario_builtin_skills,
    )


def reference_scenario_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (reference_scenario_pack_manifest(),)


def chat_scenario_runtime_pack_manifests() -> tuple[RuntimePackageManifest, ...]:
    return (
        retrieval_package_manifest(),
        web_package_manifest(),
        reference_scenario_pack_manifest(),
    )


__all__ = [
    "CHAT_SCENARIO_AGENTS",
    "CHAT_SCENARIO_SKILLS",
    "CHAT_WORKFLOW_CONTROL_TOOLS",
    "REFERENCE_SCENARIO_PACK_SHAPE",
    "chat_scenario_runtime_pack_manifests",
    "reference_scenario_pack_manifest",
    "reference_scenario_pack_manifests",
    "reference_scenario_pack_shape",
    "reference_scenario_pack_shapes",
]
