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


def _assemble_reference_runtime(tmp_path: Path, package_name: str):
    shape = reference_scenario_pack_shape(package_name)
    runtime_root = tmp_path / shape.profile
    runtime_root.mkdir(parents=True)
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=runtime_root,
            distribution=shape.recommended_distribution,
            enabled_packages=set(shape.recommended_first_party_packages),
            extra_package_manifests=REFERENCE_MANIFESTS,
            requested_packages={shape.package_name},
        )
    )
    return runtime, shape, runtime_root


@pytest.mark.parametrize(
    (
        "package_name",
        "expected_tools",
        "expected_agents",
        "expected_skills",
        "forbidden_tools",
        "forbidden_agents",
    ),
    (
        (
            "weavert-scenario-coding",
            {"read", "bash"},
            {"plan", "verification"},
            set(),
            set(),
            set(),
        ),
        (
            "weavert-scenario-chat",
            set(),
            set(),
            {"remember"},
            {"read", "write", "bash"},
            {"plan", "verification"},
        ),
        (
            "weavert-scenario-local-assistant",
            set(),
            set(),
            {"remember"},
            {"read", "write", "bash"},
            {"plan", "verification"},
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
    assert scenario_capability["shared_package_dependencies"] == list(
        shape.shared_package_dependencies
    )

    for dependency_name in shape.shared_package_dependencies:
        shared_shape = reference_shared_package_shape(dependency_name)
        shared_capability = runtime.services.require_capability(shared_shape.capability_key)
        assert shared_capability["package_name"] == dependency_name
        assert shared_capability["intended_profiles"]

    tool_names = {name for name, _definition in runtime.kernel.tool_registry.items()}
    agent_names = {name for name, _definition in runtime.kernel.agent_registry.items()}
    skill_names = {name for name, _definition in runtime.kernel.skill_registry.items()}

    assert expected_tools <= tool_names
    assert expected_agents <= agent_names
    assert expected_skills <= skill_names
    assert tool_names.isdisjoint(forbidden_tools)
    assert agent_names.isdisjoint(forbidden_agents)


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
