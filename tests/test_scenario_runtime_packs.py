from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess

import pytest

from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.runtime_package_resolution import PACKAGE_CANDIDATE_METADATA_KEY
from weavert.scenario_runtime_packs import (
    reference_scenario_pack_manifests,
    reference_scenario_pack_shape,
    reference_scenario_pack_shapes,
    reference_scenario_runtime_pack_manifests,
    reference_shared_package_manifests,
    reference_shared_package_shape,
    reference_shared_package_shapes,
)
from weavert.testing import ScriptedModelClient, text_batch
from weavert.tool_runtime import ToolContext


REFERENCE_MANIFESTS = reference_scenario_runtime_pack_manifests()
REFERENCE_PACKAGE_VERSION = "1.0.0"
CODING_WORKSPACE_TOOLS = {"read", "glob", "grep", "edit", "write", "bash"}
CODING_SHARED_GIT_TOOLS = {"git_status", "git_diff", "git_history"}
CODING_SHARED_WORKSPACE_TOOLS = {
    "workspace_symbols",
    "workspace_references",
    "workspace_outline",
    "workspace_test_targets",
}
CODING_PROFILE_TOOLS = CODING_WORKSPACE_TOOLS | CODING_SHARED_GIT_TOOLS | CODING_SHARED_WORKSPACE_TOOLS
CODING_SCENARIO_AGENTS = {"coding-planner", "reviewer", "verifier"}
CODING_GENERIC_AGENTS = {"plan", "verification", "planner", "coordinator", "worker"}
CODING_PROFILE_AGENTS = CODING_SCENARIO_AGENTS | CODING_GENERIC_AGENTS
CODING_SCENARIO_SKILLS = {
    "coding-loop",
    "review-change",
    "verify-change",
    "task-discipline",
    "repo-onboard",
}
CODING_GENERIC_SKILLS = {"verify", "debug", "stuck", "batch", "simplify"}
CODING_PROFILE_SKILLS = CODING_SCENARIO_SKILLS | CODING_GENERIC_SKILLS


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


def _assemble_shared_reference_runtime(tmp_path: Path, package_name: str):
    shape = reference_shared_package_shape(package_name)
    runtime_root = tmp_path / shape.package_name
    runtime_root.mkdir(parents=True)
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=runtime_root,
            distribution="weavert-core",
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


def _diagnostic_codes(runtime) -> set[str]:
    return {diagnostic.code for diagnostic in runtime.kernel.diagnostics}


def _tool_context(runtime, cwd: Path) -> ToolContext:
    return ToolContext(
        session_id="reference-shared-tool",
        turn_id="turn-1",
        agent_name="tester",
        cwd=cwd,
        tool_registry=runtime.kernel.tool_registry,
        runtime_services=runtime.services,
    )


@pytest.mark.parametrize(
    ("package_name", "expected_tools"),
    (
        ("weavert-shared-git", CODING_SHARED_GIT_TOOLS),
        ("weavert-shared-workspace-intelligence", CODING_SHARED_WORKSPACE_TOOLS),
    ),
)
def test_reference_shared_coding_packages_can_be_admitted_selected_and_executed(
    tmp_path: Path,
    package_name: str,
    expected_tools: set[str],
) -> None:
    runtime, shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, package_name)

    manifest_names = {manifest.name for manifest in runtime.kernel.package_manifests}
    assert shape.package_name in manifest_names
    assert expected_tools <= _tool_names(runtime)

    for tool_name in expected_tools:
        assert runtime.kernel.tool_registry.get(tool_name).metadata["builtin_owner"] == shape.package_name

    capability = runtime.services.require_capability(shape.capability_key)
    assert capability["package_name"] == shape.package_name
    assert capability["tool_ids"] == list(shape.tool_ids)

    if package_name == "weavert-shared-git":
        tracked_file = runtime_root / "module.py"
        tracked_file.write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=runtime_root, check=True, capture_output=True, text=True)
        tool = runtime.kernel.tool_registry.get("git_status")
        result = asyncio.run(tool.execute({}, _tool_context(runtime, runtime_root)))
        assert result["is_git_repo"] is True
        assert result["repo_root"] == str(runtime_root)
        assert any(entry["path"] == "module.py" for entry in result["entries"])
    else:
        source_file = runtime_root / "service.py"
        source_file.write_text(
            "class GreetingService:\n    def render(self):\n        return 'hi'\n",
            encoding="utf-8",
        )
        tool = runtime.kernel.tool_registry.get("workspace_symbols")
        result = asyncio.run(
            tool.execute({"query": "Greeting"}, _tool_context(runtime, runtime_root))
        )
        assert any(match["name"] == "GreetingService" for match in result["matches"])


def test_shared_git_tools_respect_file_path_focus(tmp_path: Path) -> None:
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-git")

    focused_file = runtime_root / "a.py"
    other_file = runtime_root / "b.py"
    focused_file.write_text("VALUE = 1\n", encoding="utf-8")
    other_file.write_text("OTHER = 2\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=runtime_root, check=True, capture_output=True, text=True)

    tool = runtime.kernel.tool_registry.get("git_status")
    result = asyncio.run(tool.execute({"path": "a.py"}, _tool_context(runtime, runtime_root)))

    assert [entry["path"] for entry in result["entries"]] == ["a.py"]


def test_workspace_intelligence_tools_respect_file_path_focus_and_tolerate_broken_python(
    tmp_path: Path,
) -> None:
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(
        tmp_path,
        "weavert-shared-workspace-intelligence",
    )
    focused_file = runtime_root / "a.py"
    other_file = runtime_root / "b.py"
    broken_file = runtime_root / "broken.py"
    focused_file.write_text("def target():\n    pass\n\ntarget()\n", encoding="utf-8")
    other_file.write_text("def target_two():\n    target()\n", encoding="utf-8")
    broken_file.write_text("def broken(:\n    pass\n", encoding="utf-8")

    symbols_tool = runtime.kernel.tool_registry.get("workspace_symbols")
    symbols_result = asyncio.run(
        symbols_tool.execute({"query": "target", "path": "a.py"}, _tool_context(runtime, runtime_root))
    )
    assert {Path(match["file_path"]).name for match in symbols_result["matches"]} == {"a.py"}
    assert any(match["name"] == "target" for match in symbols_result["matches"])

    references_tool = runtime.kernel.tool_registry.get("workspace_references")
    references_result = asyncio.run(
        references_tool.execute({"symbol": "target", "path": "a.py"}, _tool_context(runtime, runtime_root))
    )
    assert {Path(match["file_path"]).name for match in references_result["matches"]} == {"a.py"}

    broken_result = asyncio.run(
        symbols_tool.execute({"query": "broken", "path": "broken.py"}, _tool_context(runtime, runtime_root))
    )
    assert any(match["name"] == "broken" for match in broken_result["matches"])
    assert {Path(match["file_path"]).name for match in broken_result["matches"]} == {"broken.py"}


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
            CODING_PROFILE_TOOLS,
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
    assert scenario_capability["scenario_profile"] == shape.profile
    assert scenario_capability["recommended_first_party_packages"] == list(
        shape.recommended_first_party_packages
    )
    assert scenario_capability["expected_tools"] == list(shape.expected_tools)
    assert scenario_capability["expected_agents"] == list(shape.expected_agents)
    assert scenario_capability["expected_skills"] == list(shape.expected_skills)
    assert scenario_capability["workflow_tool_ids"] == list(shape.workflow_tool_ids)
    assert scenario_capability["workflow_agent_ids"] == list(shape.workflow_agent_ids)
    assert scenario_capability["workflow_skill_ids"] == list(shape.workflow_skill_ids)
    assert scenario_capability["shared_package_dependencies"] == list(
        shape.shared_package_dependencies
    )
    assert scenario_capability["profile_prompt_fragments"] == list(shape.profile_prompt_fragments)

    for dependency_name in shape.shared_package_dependencies:
        shared_shape = reference_shared_package_shape(dependency_name)
        shared_capability = runtime.services.require_capability(shared_shape.capability_key)
        assert shared_capability["package_name"] == dependency_name
        assert shared_capability["intended_profiles"]
        assert shared_capability["shared_surface_family"] == shared_shape.shared_surface_family

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
    assert all(isinstance(tool_name, str) for tool_name in scenario_capability["expected_tools"])
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
    assert scenario_capability["expected_tools"] == list(shape.expected_tools)
    assert scenario_capability["expected_agents"] == list(shape.expected_agents)
    assert scenario_capability["expected_skills"] == list(shape.expected_skills)
    assert scenario_capability["workflow_agent_ids"] == list(shape.workflow_agent_ids)
    assert scenario_capability["workflow_skill_ids"] == list(shape.workflow_skill_ids)
    assert all(isinstance(tool_name, str) for tool_name in scenario_capability["expected_tools"])

    execution_plan = runtime.services.context_contributor_execution_plan()
    assert any(
        entry.binding.owner.package_name == shape.package_name
        and entry.binding.name == f"{shape.package_name}.profile_guidance"
        for entry in execution_plan
    )
    if package_name == "weavert-scenario-coding":
        assert set(shape.workflow_agent_ids) <= _agent_names(runtime)
        assert _agent_names(runtime).isdisjoint(CODING_GENERIC_AGENTS)
        assert set(shape.workflow_skill_ids) <= _skill_names(runtime)
        assert _skill_names(runtime).isdisjoint(CODING_GENERIC_SKILLS)
    else:
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


@pytest.mark.parametrize("distribution", (None, "weavert-core", "weavert-default", "weavert-full"))
def test_reference_scenario_runtime_packs_are_not_part_of_default_distribution_baselines(
    tmp_path: Path,
    distribution: str | None,
) -> None:
    runtime_root = tmp_path / (distribution or "runtime-default")
    runtime_root.mkdir(parents=True)
    config_kwargs = {"working_directory": runtime_root}
    if distribution is not None:
        config_kwargs["distribution"] = distribution
    runtime = assemble_runtime(RuntimeConfig(**config_kwargs))

    reference_package_names = {
        *(shape.package_name for shape in reference_shared_package_shapes()),
        *(shape.package_name for shape in reference_scenario_pack_shapes()),
    }
    projected_manifest_names = set(runtime.services.metadata["package_manifests"])
    active_manifest_names = {manifest.name for manifest in runtime.kernel.package_manifests}

    assert active_manifest_names.isdisjoint(reference_package_names)
    assert projected_manifest_names.isdisjoint(reference_package_names)

    for shape in reference_shared_package_shapes():
        with pytest.raises(KeyError):
            runtime.services.require_capability(shape.capability_key)
    for shape in reference_scenario_pack_shapes():
        with pytest.raises(KeyError):
            runtime.services.require_capability(shape.capability_key)


def test_reference_package_manifest_metadata_follows_family_specific_surface_contracts() -> None:
    for manifest, shape in zip(reference_shared_package_manifests(), reference_shared_package_shapes()):
        metadata = manifest.metadata
        candidate = metadata[PACKAGE_CANDIDATE_METADATA_KEY]
        assert manifest.name == shape.package_name
        assert metadata["package_pattern"] == "shared-package"
        assert metadata["reference_kind"] == "shared-package"
        assert candidate["candidate_id"] == f"reference::{shape.package_name}"
        assert candidate["version"] == REFERENCE_PACKAGE_VERSION
        assert metadata["shared_surface_family"] == shape.shared_surface_family
        assert metadata["intended_profiles"] == list(shape.intended_profiles)
        assert metadata["shared_surfaces"] == list(shape.surfaces)
        assert metadata["tool_ids"] == list(shape.tool_ids)
        assert metadata["agent_ids"] == list(shape.agent_ids)
        assert metadata["skill_ids"] == list(shape.skill_ids)
        assert "scenario_profile" not in metadata

    for manifest, shape in zip(reference_scenario_pack_manifests(), reference_scenario_pack_shapes()):
        metadata = manifest.metadata
        candidate = metadata[PACKAGE_CANDIDATE_METADATA_KEY]
        assert manifest.name == shape.package_name
        assert metadata["package_pattern"] == "scenario-pack"
        assert metadata["reference_kind"] == "scenario-pack"
        assert candidate["candidate_id"] == f"reference::{shape.package_name}"
        assert candidate["version"] == REFERENCE_PACKAGE_VERSION
        assert metadata["scenario_profile"] == shape.profile
        assert metadata["recommended_distribution"] == shape.recommended_distribution
        assert metadata["recommended_first_party_packages"] == list(
            shape.recommended_first_party_packages
        )
        assert metadata["shared_package_dependencies"] == list(shape.shared_package_dependencies)
        assert metadata["expected_tools"] == list(shape.expected_tools)
        assert metadata["expected_agents"] == list(shape.expected_agents)
        assert metadata["expected_skills"] == list(shape.expected_skills)
        assert metadata["workflow_tool_ids"] == list(shape.workflow_tool_ids)
        assert metadata["workflow_agent_ids"] == list(shape.workflow_agent_ids)
        assert metadata["workflow_skill_ids"] == list(shape.workflow_skill_ids)
        assert "shared_surface_family" not in metadata


def test_runtime_metadata_projects_reference_package_surface_contracts_for_safe_inspection(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution="weavert-core",
            enabled_packages={
                "weavert-devtools",
                "weavert-planning",
                "weavert-builtin-workflows",
                "weavert-memory",
            },
            extra_package_manifests=REFERENCE_MANIFESTS,
            requested_packages={
                "weavert-scenario-coding",
                "weavert-scenario-chat",
                "weavert-scenario-local-assistant",
            },
        )
    )

    manifests = runtime.services.metadata["package_manifests"]

    shared_shape = reference_shared_package_shape("weavert-shared-retrieval")
    shared_manifest = manifests[shared_shape.package_name]
    assert shared_manifest["package_candidate"] == {
        "candidate_id": f"reference::{shared_shape.package_name}",
        "version": REFERENCE_PACKAGE_VERSION,
    }
    assert shared_manifest["shared_surface_family"] == shared_shape.shared_surface_family
    assert shared_manifest["intended_profiles"] == list(shared_shape.intended_profiles)
    assert shared_manifest["tool_ids"] == list(shared_shape.tool_ids)
    assert shared_manifest["skill_ids"] == list(shared_shape.skill_ids)

    coding_shape = reference_scenario_pack_shape("weavert-scenario-coding")
    coding_manifest = manifests[coding_shape.package_name]
    coding_capability = runtime.services.require_capability(coding_shape.capability_key)
    registration_manifest = next(
        entry["manifest"]
        for entry in runtime.services.metadata["package_registration"]["accepted"]
        if entry["package_name"] == coding_shape.package_name
    )
    resolved_manifest = runtime.services.metadata["package_resolution"]["resolved_graph"]["packages"][
        coding_shape.package_name
    ]["manifest"]
    assert coding_manifest["package_candidate"] == {
        "candidate_id": f"reference::{coding_shape.package_name}",
        "version": REFERENCE_PACKAGE_VERSION,
    }
    assert coding_manifest["scenario_profile"] == coding_shape.profile
    assert coding_manifest["recommended_first_party_packages"] == list(
        coding_shape.recommended_first_party_packages
    )
    assert coding_manifest["shared_package_dependencies"] == list(
        coding_shape.shared_package_dependencies
    )
    assert coding_manifest["expected_tools"] == list(coding_shape.expected_tools)
    assert coding_manifest["expected_agents"] == list(coding_shape.expected_agents)
    assert coding_manifest["expected_skills"] == list(coding_shape.expected_skills)
    assert coding_manifest["workflow_agent_ids"] == list(coding_shape.workflow_agent_ids)
    assert coding_manifest["workflow_skill_ids"] == list(coding_shape.workflow_skill_ids)
    assert coding_capability["package_candidate"] == coding_manifest["package_candidate"]
    assert coding_capability["scenario_profile"] == coding_manifest["scenario_profile"]
    assert coding_capability["expected_tools"] == coding_manifest["expected_tools"]
    assert coding_capability["expected_agents"] == coding_manifest["expected_agents"]
    assert coding_capability["expected_skills"] == coding_manifest["expected_skills"]
    assert coding_capability["workflow_agent_ids"] == coding_manifest["workflow_agent_ids"]
    assert coding_capability["workflow_skill_ids"] == coding_manifest["workflow_skill_ids"]
    assert registration_manifest["package_candidate"] == coding_manifest["package_candidate"]
    assert registration_manifest["scenario_profile"] == coding_manifest["scenario_profile"]
    assert registration_manifest["expected_tools"] == coding_manifest["expected_tools"]
    assert registration_manifest["expected_agents"] == coding_manifest["expected_agents"]
    assert registration_manifest["expected_skills"] == coding_manifest["expected_skills"]
    assert registration_manifest["workflow_agent_ids"] == coding_manifest["workflow_agent_ids"]
    assert registration_manifest["workflow_skill_ids"] == coding_manifest["workflow_skill_ids"]
    assert resolved_manifest["package_candidate"] == coding_manifest["package_candidate"]
    assert resolved_manifest["scenario_profile"] == coding_manifest["scenario_profile"]
    assert resolved_manifest["expected_tools"] == coding_manifest["expected_tools"]
    assert resolved_manifest["expected_agents"] == coding_manifest["expected_agents"]
    assert resolved_manifest["expected_skills"] == coding_manifest["expected_skills"]
    assert resolved_manifest["workflow_agent_ids"] == coding_manifest["workflow_agent_ids"]
    assert resolved_manifest["workflow_skill_ids"] == coding_manifest["workflow_skill_ids"]


def test_reference_scenario_pack_capabilities_return_defensive_snapshots(
    tmp_path: Path,
) -> None:
    runtime, shape, _runtime_root = _assemble_reference_runtime(tmp_path, "weavert-scenario-coding")

    capability = runtime.services.require_capability(shape.capability_key)
    capability["expected_tools"].append("mutated-tool")
    capability["package_candidate"]["version"] = "9.9.9"

    fresh_capability = runtime.services.require_capability(shape.capability_key)
    projected_manifest = runtime.services.metadata["package_manifests"][shape.package_name]
    raw_manifest = next(
        manifest for manifest in runtime.kernel.package_manifests if manifest.name == shape.package_name
    )

    assert fresh_capability["expected_tools"] == list(shape.expected_tools)
    assert fresh_capability["package_candidate"] == {
        "candidate_id": f"reference::{shape.package_name}",
        "version": REFERENCE_PACKAGE_VERSION,
    }
    assert projected_manifest["expected_tools"] == list(shape.expected_tools)
    assert projected_manifest["package_candidate"] == fresh_capability["package_candidate"]
    assert raw_manifest.metadata["expected_tools"] == list(shape.expected_tools)
    assert raw_manifest.metadata["package_candidate"] == fresh_capability["package_candidate"]
