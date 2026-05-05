from __future__ import annotations

from pathlib import Path

import pytest

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import (
    reference_scenario_pack_shape,
    reference_scenario_runtime_pack_manifests,
    reference_shared_package_shape,
)


REFERENCE_MANIFESTS = reference_scenario_runtime_pack_manifests()
CODING_WORKSPACE_TOOLS = {"read", "glob", "grep", "edit", "write", "bash"}
CODING_PROFILE_AGENTS = {"plan", "verification", "planner", "coordinator", "worker"}
CODING_PROFILE_SKILLS = {"verify", "debug", "stuck", "batch", "simplify"}


def _assemble_reference_runtime(
    tmp_path: Path,
    package_name: str,
    *,
    include_recommended_packages: bool = True,
):
    shape = reference_scenario_pack_shape(package_name)
    runtime_root = tmp_path / shape.profile
    runtime_root.mkdir(parents=True)
    enabled_packages = (
        set(shape.recommended_first_party_packages)
        if include_recommended_packages
        else set()
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=runtime_root,
            distribution=shape.recommended_distribution,
            enabled_packages=enabled_packages,
            extra_package_manifests=REFERENCE_MANIFESTS,
            requested_packages={shape.package_name},
        )
    )
    return runtime, shape, runtime_root


def _tool_names(runtime) -> set[str]:
    return {name for name, _definition in runtime.kernel.tool_registry.items()}


def _agent_names(runtime) -> set[str]:
    return {name for name, _definition in runtime.kernel.agent_registry.items()}


def _skill_names(runtime) -> set[str]:
    return {name for name, _definition in runtime.kernel.skill_registry.items()}


@pytest.mark.parametrize(
    (
        "package_name",
        "expected_tools",
        "expected_agents",
        "expected_skills",
        "forbidden_tools",
        "forbidden_agents",
        "forbidden_skills",
    ),
    (
        (
            "weavert-scenario-coding",
            CODING_WORKSPACE_TOOLS,
            CODING_PROFILE_AGENTS,
            CODING_PROFILE_SKILLS,
            set(),
            set(),
            set(),
        ),
        (
            "weavert-scenario-chat",
            set(),
            set(),
            {"remember"},
            CODING_WORKSPACE_TOOLS,
            CODING_PROFILE_AGENTS,
            CODING_PROFILE_SKILLS,
        ),
        (
            "weavert-scenario-local-assistant",
            set(),
            set(),
            {"remember"},
            CODING_WORKSPACE_TOOLS,
            CODING_PROFILE_AGENTS,
            CODING_PROFILE_SKILLS,
        ),
    ),
)
def test_reference_scenario_pack_shapes_activate_through_existing_runtime_package_contract(
    tmp_path: Path,
    package_name: str,
    expected_tools: set[str],
    expected_agents: set[str],
    expected_skills: set[str],
    forbidden_tools: set[str],
    forbidden_agents: set[str],
    forbidden_skills: set[str],
) -> None:
    runtime, shape, _runtime_root = _assemble_reference_runtime(tmp_path, package_name)

    manifest_names = {manifest.name for manifest in runtime.kernel.package_manifests}
    assert shape.package_name in manifest_names
    assert set(shape.recommended_first_party_packages).issubset(manifest_names)
    assert set(shape.shared_package_dependencies).issubset(manifest_names)

    scenario_capability = runtime.services.require_capability(shape.capability_key)
    assert scenario_capability["profile"] == shape.profile
    assert scenario_capability["recommended_first_party_packages"] == list(
        shape.recommended_first_party_packages
    )
    assert scenario_capability["expected_agents"] == list(shape.expected_agents)
    assert scenario_capability["expected_skills"] == list(shape.expected_skills)
    assert scenario_capability["shared_package_dependencies"] == list(
        shape.shared_package_dependencies
    )

    for dependency_name in shape.shared_package_dependencies:
        shared_shape = reference_shared_package_shape(dependency_name)
        shared_capability = runtime.services.require_capability(shared_shape.capability_key)
        assert shared_capability["package_name"] == dependency_name
        assert shared_capability["intended_profiles"]

    tool_names = _tool_names(runtime)
    agent_names = _agent_names(runtime)
    skill_names = _skill_names(runtime)

    assert expected_tools <= tool_names
    assert expected_agents <= agent_names
    assert expected_skills <= skill_names
    assert tool_names.isdisjoint(forbidden_tools)
    assert agent_names.isdisjoint(forbidden_agents)
    assert skill_names.isdisjoint(forbidden_skills)


@pytest.mark.parametrize(
    "package_name",
    (
        "weavert-scenario-coding",
        "weavert-scenario-chat",
        "weavert-scenario-local-assistant",
    ),
)
def test_reference_scenario_pack_capabilities_publish_expected_profile_surfaces_without_claiming_package_local_contributions(
    tmp_path: Path,
    package_name: str,
) -> None:
    runtime, shape, _runtime_root = _assemble_reference_runtime(
        tmp_path,
        package_name,
        include_recommended_packages=False,
    )

    manifest_names = {manifest.name for manifest in runtime.kernel.package_manifests}
    assert manifest_names.isdisjoint(shape.recommended_first_party_packages)

    scenario_capability = runtime.services.require_capability(shape.capability_key)
    assert scenario_capability["expected_agents"] == list(shape.expected_agents)
    assert scenario_capability["expected_skills"] == list(shape.expected_skills)

    assert _agent_names(runtime).isdisjoint(shape.expected_agents)
    assert _skill_names(runtime).isdisjoint(shape.expected_skills)


def test_reference_scenario_pack_capabilities_preserve_distinct_default_boundaries(
    tmp_path: Path,
) -> None:
    coding_runtime, coding_shape, _ = _assemble_reference_runtime(tmp_path / "coding-case", "weavert-scenario-coding")
    chat_runtime, chat_shape, _ = _assemble_reference_runtime(tmp_path / "chat-case", "weavert-scenario-chat")
    assistant_runtime, assistant_shape, _ = _assemble_reference_runtime(
        tmp_path / "assistant-case",
        "weavert-scenario-local-assistant",
    )

    coding = coding_runtime.services.require_capability(coding_shape.capability_key)
    chat = chat_runtime.services.require_capability(chat_shape.capability_key)
    assistant = assistant_runtime.services.require_capability(assistant_shape.capability_key)

    assert any("workspace" in entry for entry in coding["default_boundaries"])
    assert any("shell" in entry for entry in coding["default_boundaries"])

    assert any("read-mostly" in entry for entry in chat["default_boundaries"])
    assert any("read-only" in entry or "approval-first" in entry for entry in chat["permission_policy_posture"])

    assert any("host-centric" in entry for entry in assistant["default_boundaries"])
    assert any("audit" in entry or "approval" in entry for entry in assistant["permission_policy_posture"])
    assert assistant["app_owned_wiring"][-1] == "final permission policy composition and audit sinks"
