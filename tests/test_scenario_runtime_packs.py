from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.scenario_runtime_packs import (
    reference_scenario_pack_shape,
    reference_scenario_runtime_pack_manifests,
    reference_shared_package_shape,
)
from weavert.testing import ScriptedModelClient, text_batch


REFERENCE_MANIFESTS = reference_scenario_runtime_pack_manifests()
CODING_WORKSPACE_TOOLS = {"read", "glob", "grep", "edit", "write", "bash"}
CODING_PROFILE_AGENTS = {"plan", "verification", "planner", "coordinator", "worker"}
CODING_PROFILE_SKILLS = {"verify", "debug", "stuck", "batch", "simplify"}


def _assemble_reference_runtime(
    tmp_path: Path,
    package_name: str,
    *,
    include_recommended_packages: bool = True,
    model_client=None,
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
            model_client=model_client,
        )
    )
    return runtime, shape, runtime_root


def _tool_names(runtime) -> set[str]:
    return {name for name, _definition in runtime.kernel.tool_registry.items()}


def _agent_names(runtime) -> set[str]:
    return {name for name, _definition in runtime.kernel.agent_registry.items()}


def _skill_names(runtime) -> set[str]:
    return {name for name, _definition in runtime.kernel.skill_registry.items()}


def _diagnostic_codes(runtime) -> set[str]:
    return {diagnostic.code for diagnostic in runtime.kernel.diagnostics}


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
    assert scenario_capability["profile_prompt_fragments"] == list(shape.profile_prompt_fragments)

    for dependency_name in shape.shared_package_dependencies:
        shared_shape = reference_shared_package_shape(dependency_name)
        shared_capability = runtime.services.require_capability(shared_shape.capability_key)
        assert shared_capability["package_name"] == dependency_name
        assert shared_capability["intended_profiles"]

    execution_plan = runtime.services.context_contributor_execution_plan()
    profile_entry = next(
        entry
        for entry in execution_plan
        if entry.binding.owner.package_name == shape.package_name
        and entry.binding.name == f"{shape.package_name}.profile_guidance"
    )
    assert profile_entry.binding.stage.value == "hooks"
    assert profile_entry.binding.metadata["profile_prompt_fragments"] == list(
        shape.profile_prompt_fragments
    )

    tool_names = _tool_names(runtime)
    agent_names = _agent_names(runtime)
    skill_names = _skill_names(runtime)

    assert expected_tools <= tool_names
    assert expected_agents <= agent_names
    assert expected_skills <= skill_names
    assert tool_names.isdisjoint(forbidden_tools)
    assert agent_names.isdisjoint(forbidden_agents)
    assert skill_names.isdisjoint(forbidden_skills)
    assert "scenario_pack_recommended_first_party_packages_missing" not in _diagnostic_codes(runtime)


@pytest.mark.parametrize(
    "package_name",
    (
        "weavert-scenario-coding",
        "weavert-scenario-chat",
        "weavert-scenario-local-assistant",
    ),
)
def test_reference_scenario_pack_capabilities_publish_expected_profile_surfaces_and_warn_on_missing_recommended_packages(
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

    execution_plan = runtime.services.context_contributor_execution_plan()
    assert any(
        entry.binding.owner.package_name == shape.package_name
        and entry.binding.name == f"{shape.package_name}.profile_guidance"
        for entry in execution_plan
    )
    assert _agent_names(runtime).isdisjoint(shape.expected_agents)
    assert _skill_names(runtime).isdisjoint(shape.expected_skills)
    assert "scenario_pack_recommended_first_party_packages_missing" in _diagnostic_codes(runtime)


@pytest.mark.parametrize(
    "package_name",
    (
        "weavert-scenario-coding",
        "weavert-scenario-chat",
        "weavert-scenario-local-assistant",
    ),
)
def test_reference_scenario_pack_context_contributors_publish_profile_guidance_in_model_requests(
    tmp_path: Path,
    package_name: str,
) -> None:
    shape = reference_scenario_pack_shape(package_name)

    def _batch(request):
        for fragment in shape.profile_prompt_fragments:
            assert fragment in request.turn_context.hook_context
        return text_batch(
            request_id=f"req-{shape.profile}-1",
            text=f"{shape.profile} profile guidance observed",
        )

    client = ScriptedModelClient([_batch])
    runtime, _shape, _runtime_root = _assemble_reference_runtime(
        tmp_path,
        package_name,
        model_client=client,
    )

    messages = asyncio.run(
        runtime.run_prompt(
            f"Confirm the {shape.profile} scenario-pack guidance.",
            session_id=f"{shape.profile}-scenario-pack-guidance",
        )
    )

    assert messages[-1].text == f"{shape.profile} profile guidance observed"


@pytest.mark.parametrize(
    "package_name",
    (
        "weavert-scenario-chat",
        "weavert-scenario-local-assistant",
    ),
)
def test_non_coding_reference_scenario_packs_publish_contextual_boundary_diagnostics(
    tmp_path: Path,
    package_name: str,
) -> None:
    runtime, _shape, _runtime_root = _assemble_reference_runtime(tmp_path, package_name)

    assert "scenario_pack_default_profile_omits_coding_surfaces" in _diagnostic_codes(runtime)


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
