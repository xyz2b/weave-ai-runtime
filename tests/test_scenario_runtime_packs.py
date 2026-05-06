from __future__ import annotations

import asyncio
from email.message import Message
from pathlib import Path
import socket
import subprocess
from typing import Any

import pytest

from weavert.contracts import MessageRole
from weavert.definitions import ToolRiskLevel
from weavert.memory.models import MemoryEntry
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.runtime_package_protocols import HostFacetBinding, PackageOwnership
from weavert.runtime_package_resolution import PACKAGE_CANDIDATE_METADATA_KEY
from weavert.tool_runtime import ToolContext
from weavert_testing import ScriptedModelClient, text_batch, tool_call_batch
import weavert_kit_common_web._tool_impls as reference_chat_tool_impls
from weavert_kit_chat import (
    CHAT_RETRIEVAL_TOOLS,
    CHAT_SCENARIO_AGENTS as CHAT_SCENARIO_AGENT_NAMES,
    CHAT_SCENARIO_SKILLS as CHAT_SCENARIO_SKILL_NAMES,
    chat_scenario_runtime_pack_manifests,
    reference_scenario_pack_manifest as chat_scenario_pack_manifest,
    reference_scenario_pack_shape as chat_scenario_pack_shape,
    reference_scenario_pack_shapes as chat_scenario_pack_shapes,
)
from weavert_kit_coding import (
    coding_scenario_runtime_pack_manifests,
    reference_scenario_pack_manifest as coding_scenario_pack_manifest,
    reference_scenario_pack_shape as coding_scenario_pack_shape,
    reference_scenario_pack_shapes as coding_scenario_pack_shapes,
)
from weavert_kit_common_browser import (
    LOCAL_ASSISTANT_BROWSER_HOST_FACET,
    LOCAL_ASSISTANT_BROWSER_TOOLS,
    reference_shared_package_manifest as browser_shared_package_manifest,
    reference_shared_package_shape as browser_shared_package_shape,
    reference_shared_package_shapes as browser_shared_package_shapes,
)
from weavert_kit_common_git import (
    reference_shared_package_manifest as git_shared_package_manifest,
    reference_shared_package_shape as git_shared_package_shape,
    reference_shared_package_shapes as git_shared_package_shapes,
)
from weavert_kit_common_local_os import (
    LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
    LOCAL_ASSISTANT_LOCAL_OS_TOOLS,
    reference_shared_package_manifest as local_os_shared_package_manifest,
    reference_shared_package_shape as local_os_shared_package_shape,
    reference_shared_package_shapes as local_os_shared_package_shapes,
)
from weavert_kit_common_pim import (
    LOCAL_ASSISTANT_PIM_HOST_FACET,
    LOCAL_ASSISTANT_PIM_TOOLS,
    reference_shared_package_manifest as pim_shared_package_manifest,
    reference_shared_package_shape as pim_shared_package_shape,
    reference_shared_package_shapes as pim_shared_package_shapes,
)
from weavert_kit_common_retrieval import (
    reference_shared_package_manifest as retrieval_shared_package_manifest,
    reference_shared_package_shape as retrieval_shared_package_shape,
    reference_shared_package_shapes as retrieval_shared_package_shapes,
)
from weavert_kit_common_web import (
    CHAT_WEB_TOOLS,
    reference_shared_package_manifest as web_shared_package_manifest,
    reference_shared_package_shape as web_shared_package_shape,
    reference_shared_package_shapes as web_shared_package_shapes,
    validate_grounding_web_fetch,
)
from weavert_kit_common_workspace_intelligence import (
    reference_shared_package_manifest as workspace_shared_package_manifest,
    reference_shared_package_shape as workspace_shared_package_shape,
    reference_shared_package_shapes as workspace_shared_package_shapes,
)
from weavert_kit_local_assistant import (
    LOCAL_ASSISTANT_SCENARIO_AGENTS as LOCAL_ASSISTANT_SCENARIO_AGENT_NAMES,
    LOCAL_ASSISTANT_SCENARIO_SKILLS as LOCAL_ASSISTANT_SCENARIO_SKILL_NAMES,
    local_assistant_scenario_runtime_pack_manifests,
    reference_scenario_pack_manifest as local_assistant_scenario_pack_manifest,
    reference_scenario_pack_shape as local_assistant_scenario_pack_shape,
    reference_scenario_pack_shapes as local_assistant_scenario_pack_shapes,
)

def _dedupe_manifests(*groups):
    manifests = []
    seen = set()
    for group in groups:
        for manifest in group:
            if manifest.name in seen:
                continue
            manifests.append(manifest)
            seen.add(manifest.name)
    return tuple(manifests)


REFERENCE_MANIFESTS = _dedupe_manifests(
    coding_scenario_runtime_pack_manifests(),
    chat_scenario_runtime_pack_manifests(),
    local_assistant_scenario_runtime_pack_manifests(),
)
REFERENCE_PACKAGE_VERSION = "1.0.0"
CODING_WORKSPACE_TOOLS = {"read", "glob", "grep", "edit", "write", "bash"}
CODING_SHARED_GIT_TOOLS = {"git_status", "git_diff", "git_history"}
CODING_SHARED_WORKSPACE_TOOLS = {
    "workspace_symbols",
    "workspace_references",
    "workspace_outline",
    "workspace_test_targets",
}
CODING_WORKFLOW_CONTROL_TOOLS = {
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
}
CODING_SPECIALIZED_TOOLS = CODING_WORKSPACE_TOOLS | CODING_SHARED_GIT_TOOLS | CODING_SHARED_WORKSPACE_TOOLS
CODING_PROFILE_TOOLS = (
    CODING_SPECIALIZED_TOOLS
    | CODING_WORKFLOW_CONTROL_TOOLS
)
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
CHAT_RETRIEVAL_TOOL_SET = set(CHAT_RETRIEVAL_TOOLS)
CHAT_WEB_TOOL_SET = set(CHAT_WEB_TOOLS)
CHAT_WORKFLOW_CONTROL_TOOLS = {"ask_user"}
CHAT_PROFILE_TOOLS = CHAT_RETRIEVAL_TOOL_SET | CHAT_WEB_TOOL_SET | CHAT_WORKFLOW_CONTROL_TOOLS
CHAT_SCENARIO_AGENTS = set(CHAT_SCENARIO_AGENT_NAMES)
CHAT_SCENARIO_SKILLS = set(CHAT_SCENARIO_SKILL_NAMES)
CHAT_PROFILE_SKILLS = CHAT_SCENARIO_SKILLS | {"remember"}
LOCAL_ASSISTANT_BRIDGE_TOOL_SET = (
    set(LOCAL_ASSISTANT_BROWSER_TOOLS)
    | set(LOCAL_ASSISTANT_LOCAL_OS_TOOLS)
    | set(LOCAL_ASSISTANT_PIM_TOOLS)
)
LOCAL_ASSISTANT_WORKFLOW_CONTROL_TOOLS = {"ask_user", "skill"}
LOCAL_ASSISTANT_PROFILE_TOOLS = (
    CHAT_RETRIEVAL_TOOL_SET
    | LOCAL_ASSISTANT_WORKFLOW_CONTROL_TOOLS
    | LOCAL_ASSISTANT_BRIDGE_TOOL_SET
)
LOCAL_ASSISTANT_SCENARIO_AGENTS = set(LOCAL_ASSISTANT_SCENARIO_AGENT_NAMES)
LOCAL_ASSISTANT_SCENARIO_SKILLS = set(LOCAL_ASSISTANT_SCENARIO_SKILL_NAMES)
LOCAL_ASSISTANT_PROFILE_SKILLS = LOCAL_ASSISTANT_SCENARIO_SKILLS | {"remember"}

REFERENCE_SHARED_SHAPES = (
    *retrieval_shared_package_shapes(),
    *web_shared_package_shapes(),
    *browser_shared_package_shapes(),
    *local_os_shared_package_shapes(),
    *pim_shared_package_shapes(),
    *git_shared_package_shapes(),
    *workspace_shared_package_shapes(),
)
REFERENCE_SCENARIO_SHAPES = (
    *coding_scenario_pack_shapes(),
    *chat_scenario_pack_shapes(),
    *local_assistant_scenario_pack_shapes(),
)


def reference_shared_package_shapes():
    return REFERENCE_SHARED_SHAPES


def reference_scenario_pack_shapes():
    return REFERENCE_SCENARIO_SHAPES


def reference_shared_package_shape(name: str):
    for resolver in (
        retrieval_shared_package_shape,
        web_shared_package_shape,
        browser_shared_package_shape,
        local_os_shared_package_shape,
        pim_shared_package_shape,
        git_shared_package_shape,
        workspace_shared_package_shape,
    ):
        try:
            return resolver(name)
        except KeyError:
            continue
    raise KeyError(name)


def reference_scenario_pack_shape(name: str):
    for resolver in (
        coding_scenario_pack_shape,
        chat_scenario_pack_shape,
        local_assistant_scenario_pack_shape,
    ):
        try:
            return resolver(name)
        except KeyError:
            continue
    raise KeyError(name)


def reference_shared_package_manifests():
    return (
        retrieval_shared_package_manifest(),
        web_shared_package_manifest(),
        browser_shared_package_manifest(),
        local_os_shared_package_manifest(),
        pim_shared_package_manifest(),
        git_shared_package_manifest(),
        workspace_shared_package_manifest(),
    )


def reference_scenario_pack_manifests():
    return (
        coding_scenario_pack_manifest(),
        chat_scenario_pack_manifest(),
        local_assistant_scenario_pack_manifest(),
    )


def _assemble_reference_runtime(
    tmp_path: Path,
    package_name: str,
    *,
    include_recommended_packages: bool = True,
    extra_enabled_packages: set[str] | None = None,
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
    if extra_enabled_packages:
        enabled_packages.update(extra_enabled_packages)
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


class _FakeUrlopenResponse:
    def __init__(self, body: str, *, content_type: str = "text/html", status: int = 200) -> None:
        self.status = status
        self._body = body.encode("utf-8")
        self.headers = Message()
        self.headers.add_header("Content-Type", content_type)

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            return self._body
        return self._body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _ = exc_type, exc, tb
        return False


def _grounding_urlopen(request, timeout=10):  # pragma: no cover - exercised through tool calls
    _ = timeout
    url = request.full_url if hasattr(request, "full_url") else str(request)
    if "duckduckgo.com" in url:
        return _FakeUrlopenResponse(
            (
                '<html><body><a class="result__a" '
                'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgrounding.example.test%2Frefund-policy">'
                "Refund policy</a>"
                '<a class="result__a" href="http://127.0.0.1:8000/admin">Unsafe internal page</a>'
                "</body></html>"
            )
        )
    if url == "https://grounding.example.test/refund-policy":
        return _FakeUrlopenResponse(
            (
                "<html><head><title>Refund policy</title></head><body>"
                "<article><h1>Refund policy</h1><p>Refunds stay available for 30 days after purchase.</p>"
                "<p>Support can cite this window directly.</p></article></body></html>"
            )
        )
    raise AssertionError(f"Unexpected URL requested during test: {url}")


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


def test_grounded_reference_shared_packages_can_be_admitted_selected_and_executed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_chat_tool_impls, "_grounding_urlopen", _grounding_urlopen)

    retrieval_runtime, retrieval_shape, retrieval_root = _assemble_shared_reference_runtime(
        tmp_path,
        "weavert-shared-retrieval",
    )
    retrieval_tool_names = _tool_names(retrieval_runtime)
    assert CHAT_RETRIEVAL_TOOL_SET <= retrieval_tool_names
    assert all(
        retrieval_runtime.kernel.tool_registry.get(tool_name).metadata["builtin_owner"]
        == retrieval_shape.package_name
        for tool_name in CHAT_RETRIEVAL_TOOL_SET
    )
    assert all(
        retrieval_runtime.kernel.tool_registry.get(tool_name).traits.read_only
        for tool_name in CHAT_RETRIEVAL_TOOL_SET
    )

    retrieve_tool = retrieval_runtime.kernel.tool_registry.get("retrieve_context")
    retrieval_result = asyncio.run(
        retrieve_tool.execute(
            {
                "query": "refund window",
                "items": [
                    {
                        "id": "support-doc",
                        "title": "Refund window",
                        "content": "Customers can request a refund within 30 days after purchase.",
                        "url": "https://grounding.example.test/refund-policy",
                    },
                    {
                        "id": "shipping-doc",
                        "title": "Shipping times",
                        "content": "Physical orders usually arrive in 7 days.",
                    },
                ],
            },
            _tool_context(retrieval_runtime, retrieval_root),
        )
    )
    assert [item["id"] for item in retrieval_result["results"]] == ["support-doc"]

    citations_tool = retrieval_runtime.kernel.tool_registry.get("prepare_citations")
    citations_result = asyncio.run(
        citations_tool.execute({"items": retrieval_result["results"]}, _tool_context(retrieval_runtime, retrieval_root))
    )
    assert citations_result["citations"][0]["label"] == "[1]"
    assert "Refund window" in citations_result["citation_block"]

    web_runtime, web_shape, web_root = _assemble_shared_reference_runtime(tmp_path, "weavert-bridge-web")
    web_tool_names = _tool_names(web_runtime)
    assert CHAT_WEB_TOOL_SET <= web_tool_names
    assert all(
        web_runtime.kernel.tool_registry.get(tool_name).metadata["builtin_owner"] == web_shape.package_name
        for tool_name in CHAT_WEB_TOOL_SET
    )
    assert all(
        web_runtime.kernel.tool_registry.get(tool_name).traits.read_only
        for tool_name in CHAT_WEB_TOOL_SET
    )

    search_tool = web_runtime.kernel.tool_registry.get("grounding_web_search")
    search_result = asyncio.run(
        search_tool.execute({"query": "refund policy", "limit": 3}, _tool_context(web_runtime, web_root))
    )
    assert search_result["results"] == [
        {
            "title": "Refund policy",
            "url": "https://grounding.example.test/refund-policy",
        }
    ]

    fetch_tool = web_runtime.kernel.tool_registry.get("grounding_web_fetch")
    fetch_result = asyncio.run(
        fetch_tool.execute(
            {"url": "https://grounding.example.test/refund-policy"},
            _tool_context(web_runtime, web_root),
        )
    )
    assert fetch_result["title"] == "Refund policy"
    assert "30 days" in fetch_result["content"]


@pytest.mark.parametrize(
    (
        "package_name",
        "expected_tools",
        "sample_tool_name",
        "sample_input",
        "expected_status",
    ),
    (
        (
            "weavert-bridge-browser",
            set(LOCAL_ASSISTANT_BROWSER_TOOLS),
            "browser_stage_navigation",
            {"url": "https://assistant.example.test/briefing"},
            "staged",
        ),
        (
            "weavert-bridge-local-os",
            set(LOCAL_ASSISTANT_LOCAL_OS_TOOLS),
            "local_os_snapshot",
            {"topics": ["files"]},
            "host_bridge_required",
        ),
        (
            "weavert-bridge-pim",
            set(LOCAL_ASSISTANT_PIM_TOOLS),
            "pim_stage_task",
            {"title": "Send weekly update"},
            "staged",
        ),
    ),
)
def test_local_assistant_reference_shared_bridge_packages_can_be_admitted_selected_and_executed(
    tmp_path: Path,
    package_name: str,
    expected_tools: set[str],
    sample_tool_name: str,
    sample_input: dict[str, Any],
    expected_status: str,
) -> None:
    runtime, shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, package_name)

    manifest_names = {manifest.name for manifest in runtime.kernel.package_manifests}
    assert shape.package_name in manifest_names
    assert expected_tools <= _tool_names(runtime)
    assert all(runtime.kernel.tool_registry.get(tool_name).metadata["builtin_owner"] == shape.package_name for tool_name in expected_tools)

    capability = runtime.services.require_capability(shape.capability_key)
    assert capability["package_name"] == shape.package_name
    assert capability["tool_ids"] == list(shape.tool_ids)

    tool = runtime.kernel.tool_registry.get(sample_tool_name)
    result = asyncio.run(tool.execute(sample_input, _tool_context(runtime, runtime_root)))
    assert result["status"] == expected_status
    assert result["host_binding_owner"] == "app"
    assert result["allowlist_owner"] == "app"
    assert result["audit_sink_owner"] == "app"


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
            CHAT_PROFILE_TOOLS,
            CHAT_SCENARIO_AGENTS,
            CHAT_PROFILE_SKILLS,
            CODING_SPECIALIZED_TOOLS,
            CODING_PROFILE_AGENTS,
            CODING_PROFILE_SKILLS,
        ),
        (
            "weavert-scenario-local-assistant",
            LOCAL_ASSISTANT_PROFILE_TOOLS,
            LOCAL_ASSISTANT_SCENARIO_AGENTS,
            LOCAL_ASSISTANT_PROFILE_SKILLS,
            CODING_SPECIALIZED_TOOLS,
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
    (
        "package_name",
        "materialized_tools",
        "materialized_agents",
        "materialized_skills",
        "withheld_tools",
        "withheld_agents",
        "withheld_skills",
    ),
    (
        (
            "weavert-scenario-coding",
            CODING_WORKFLOW_CONTROL_TOOLS | CODING_SHARED_GIT_TOOLS | CODING_SHARED_WORKSPACE_TOOLS,
            CODING_SCENARIO_AGENTS,
            CODING_SCENARIO_SKILLS,
            CODING_WORKSPACE_TOOLS,
            CODING_GENERIC_AGENTS,
            CODING_GENERIC_SKILLS,
        ),
        (
            "weavert-scenario-chat",
            CHAT_PROFILE_TOOLS,
            CHAT_SCENARIO_AGENTS,
            CHAT_SCENARIO_SKILLS,
            set(),
            set(),
            {"remember"},
        ),
        (
            "weavert-scenario-local-assistant",
            LOCAL_ASSISTANT_PROFILE_TOOLS,
            LOCAL_ASSISTANT_SCENARIO_AGENTS,
            LOCAL_ASSISTANT_SCENARIO_SKILLS,
            set(),
            set(),
            {"remember"},
        ),
    ),
)
def test_reference_scenario_pack_capabilities_publish_expected_profile_surfaces_and_warn_on_missing_recommended_packages(
    tmp_path: Path,
    package_name: str,
    materialized_tools: set[str],
    materialized_agents: set[str],
    materialized_skills: set[str],
    withheld_tools: set[str],
    withheld_agents: set[str],
    withheld_skills: set[str],
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
    tool_names = _tool_names(runtime)
    agent_names = _agent_names(runtime)
    skill_names = _skill_names(runtime)

    assert materialized_tools <= tool_names
    assert materialized_agents <= agent_names
    assert materialized_skills <= skill_names
    assert tool_names.isdisjoint(withheld_tools)
    assert agent_names.isdisjoint(withheld_agents)
    assert skill_names.isdisjoint(withheld_skills)
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


@pytest.mark.parametrize(
    "package_name",
    (
        "weavert-scenario-chat",
        "weavert-scenario-local-assistant",
    ),
)
def test_non_coding_reference_scenario_packs_warn_when_coding_surfaces_are_enabled(
    tmp_path: Path,
    package_name: str,
) -> None:
    runtime, _shape, _runtime_root = _assemble_reference_runtime(
        tmp_path,
        package_name,
        extra_enabled_packages={"weavert-devtools", "weavert-planning"},
    )

    diagnostic_codes = _diagnostic_codes(runtime)
    assert "scenario_pack_non_coding_profile_admits_coding_surfaces" in diagnostic_codes
    assert "scenario_pack_default_profile_omits_coding_surfaces" not in diagnostic_codes
    assert runtime.kernel.tool_registry.get("bash") is not None
    assert runtime.kernel.tool_registry.get("edit") is not None


@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1:8000/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "https://metadata.google.internal/computeMetadata/v1/",
    ),
)
def test_grounding_web_fetch_validation_rejects_non_public_hosts(url: str) -> None:
    outcome = validate_grounding_web_fetch(
        {"url": url},
        ToolContext(session_id="grounding-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd()),
    )

    assert outcome.valid is False
    assert outcome.message == "Grounding fetch only supports public web hosts"


def test_grounding_web_fetch_validation_rejects_hostnames_that_resolve_to_non_public_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_chat_tool_impls._grounding_hostname_resolves_publicly.cache_clear()

    def _fake_getaddrinfo(hostname: str, *_args, **_kwargs):
        if hostname == "loopback-proxy.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))]
        if hostname == "metadata-proxy.example":
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("169.254.169.254", 443),
                )
            ]
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(reference_chat_tool_impls.socket, "getaddrinfo", _fake_getaddrinfo)

    try:
        for url in (
            "https://loopback-proxy.example/",
            "https://metadata-proxy.example/latest/meta-data/",
        ):
            outcome = validate_grounding_web_fetch(
                {"url": url},
                ToolContext(
                    session_id="grounding-validation",
                    turn_id="turn-1",
                    agent_name="tester",
                    cwd=Path.cwd(),
                ),
            )
            assert outcome.valid is False
            assert outcome.message == "Grounding fetch only supports public web hosts"
    finally:
        reference_chat_tool_impls._grounding_hostname_resolves_publicly.cache_clear()


def test_grounded_chat_reference_stack_exercises_retrieval_web_and_memory_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_chat_tool_impls, "_grounding_urlopen", _grounding_urlopen)

    runtime, shape, runtime_root = _assemble_reference_runtime(tmp_path, "weavert-scenario-chat")
    assert shape.expected_tools == CHAT_RETRIEVAL_TOOLS + CHAT_WEB_TOOLS + ("ask_user",)
    assert set(shape.workflow_agent_ids) == CHAT_SCENARIO_AGENTS
    assert set(shape.workflow_skill_ids) == CHAT_SCENARIO_SKILLS

    search_tool = runtime.kernel.tool_registry.get("grounding_web_search")
    search_result = asyncio.run(
        search_tool.execute({"query": "refund policy"}, _tool_context(runtime, runtime_root))
    )
    assert search_result["results"][0]["url"] == "https://grounding.example.test/refund-policy"

    fetch_tool = runtime.kernel.tool_registry.get("grounding_web_fetch")
    fetched = asyncio.run(
        fetch_tool.execute(
            {"url": search_result["results"][0]["url"]},
            _tool_context(runtime, runtime_root),
        )
    )
    assert "30 days" in fetched["content"]

    memory_service = runtime.services.resolve_memory_service()
    support_agent = runtime.kernel.agent_registry.get("support-agent")
    persisted = asyncio.run(
        memory_service.persist_entries(
            session_id="grounded-chat-stack",
            agent=support_agent,
            cwd=runtime_root,
            entries=(
                MemoryEntry(
                    title="Refund preference",
                    content="Support answers should mention the 30 day refund window when users ask about refunds.",
                    metadata={"tags": ["refunds", "policy"]},
                ),
            ),
        )
    )
    assert persisted

    retrieve_tool = runtime.kernel.tool_registry.get("retrieve_context")
    retrieval = asyncio.run(
        retrieve_tool.execute(
            {
                "query": "refund window",
                "items": [
                    {
                        "id": "web-refund-policy",
                        "title": fetched["title"],
                        "content": fetched["content"],
                        "url": fetched["url"],
                    }
                ],
            },
            _tool_context(runtime, runtime_root),
        )
    )
    assert len(retrieval["results"]) >= 2
    assert {"external", "memory"} <= {item["source_kind"] for item in retrieval["results"]}

    citations_tool = runtime.kernel.tool_registry.get("prepare_citations")
    citations = asyncio.run(
        citations_tool.execute({"items": retrieval["results"][:2]}, _tool_context(runtime, runtime_root))
    )
    assert citations["citations"][0]["label"] == "[1]"
    assert "Refund policy" in citations["citation_block"]
    assert "Refund preference" in citations["citation_block"]


@pytest.mark.parametrize(
    (
        "tool_name",
        "tool_input",
        "expected_status",
        "expected_package_name",
        "expected_host_facet",
        "expected_risk_level",
        "expected_read_only",
    ),
    (
        (
            "browser_snapshot",
            {"include_recent_tabs": True},
            "host_bridge_required",
            "weavert-bridge-browser",
            LOCAL_ASSISTANT_BROWSER_HOST_FACET,
            ToolRiskLevel.READ,
            True,
        ),
        (
            "browser_stage_navigation",
            {"url": "https://assistant.example.test/agenda", "reason": "prepare morning briefing"},
            "staged",
            "weavert-bridge-browser",
            LOCAL_ASSISTANT_BROWSER_HOST_FACET,
            ToolRiskLevel.WRITE,
            False,
        ),
        (
            "local_os_snapshot",
            {"topics": ["clipboard", "notifications"]},
            "host_bridge_required",
            "weavert-bridge-local-os",
            LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ToolRiskLevel.READ,
            True,
        ),
        (
            "local_os_stage_process_launch",
            {"command": "open", "args": ["Calendar.app"], "reason": "open meeting details"},
            "staged",
            "weavert-bridge-local-os",
            LOCAL_ASSISTANT_LOCAL_OS_HOST_FACET,
            ToolRiskLevel.EXEC,
            False,
        ),
        (
            "pim_list_agenda",
            {"include_reminders": True},
            "host_bridge_required",
            "weavert-bridge-pim",
            LOCAL_ASSISTANT_PIM_HOST_FACET,
            ToolRiskLevel.READ,
            True,
        ),
        (
            "pim_stage_calendar_event",
            {"title": "Team sync", "start_time": "2026-05-06T09:00:00Z"},
            "staged",
            "weavert-bridge-pim",
            LOCAL_ASSISTANT_PIM_HOST_FACET,
            ToolRiskLevel.WRITE,
            False,
        ),
    ),
)
def test_local_assistant_bridge_tools_keep_host_mediation_allowlists_and_audit_app_owned(
    tmp_path: Path,
    tool_name: str,
    tool_input: dict[str, Any],
    expected_status: str,
    expected_package_name: str,
    expected_host_facet: str,
    expected_risk_level: ToolRiskLevel,
    expected_read_only: bool,
) -> None:
    runtime, shape, runtime_root = _assemble_reference_runtime(tmp_path, "weavert-scenario-local-assistant")

    assert shape.expected_tools == (
        CHAT_RETRIEVAL_TOOLS
        + ("ask_user", "skill")
        + LOCAL_ASSISTANT_BROWSER_TOOLS
        + LOCAL_ASSISTANT_LOCAL_OS_TOOLS
        + LOCAL_ASSISTANT_PIM_TOOLS
    )
    assert set(shape.workflow_agent_ids) == LOCAL_ASSISTANT_SCENARIO_AGENTS
    assert set(shape.workflow_skill_ids) == LOCAL_ASSISTANT_SCENARIO_SKILLS
    assert LOCAL_ASSISTANT_PROFILE_TOOLS <= _tool_names(runtime)

    host_resolution = runtime.services.resolve_host_facet(expected_host_facet)
    assert host_resolution.available is False
    assert host_resolution.code == "not_available"

    tool = runtime.kernel.tool_registry.get(tool_name)
    assert tool.metadata["builtin_owner"] == expected_package_name
    assert tool.metadata["expected_host_facet"] == expected_host_facet
    assert tool.metadata["host_binding_owner"] == "app"
    assert tool.metadata["allowlist_owner"] == "app"
    assert tool.metadata["audit_sink_owner"] == "app"
    assert tool.traits.read_only is expected_read_only

    classifier = tool.execution_semantics.to_classifier_input(tool_input, _tool_context(runtime, runtime_root))
    assert classifier.risk_level == expected_risk_level
    assert classifier.side_effects is (not expected_read_only)

    result = asyncio.run(tool.execute(tool_input, _tool_context(runtime, runtime_root)))
    assert result["status"] == expected_status
    assert result["expected_host_facet"] == expected_host_facet
    assert result["host_binding_owner"] == "app"
    assert result["allowlist_owner"] == "app"
    assert result["audit_sink_owner"] == "app"
    assert result["approval_required"] is (not expected_read_only)
    assert result["request"] == tool_input


def test_local_assistant_bridge_tools_use_bound_host_facets_for_live_state_and_staged_receipts(
    tmp_path: Path,
) -> None:
    class BrowserHostFacet:
        async def browser_snapshot(self, *, request, context):
            assert request == {"include_recent_tabs": True}
            assert context.agent_name == "tester"
            return {
                "focused_url": "https://assistant.example.test/home",
                "recent_tabs": ["https://assistant.example.test/home"],
            }

        async def browser_stage_navigation(self, *, request, context):
            assert request["url"] == "https://assistant.example.test/briefing"
            assert context.agent_name == "tester"
            return {
                "receipt_id": "nav-1",
                "review_state": "pending",
                "target_url": request["url"],
            }

    runtime, _shape, runtime_root = _assemble_reference_runtime(tmp_path, "weavert-scenario-local-assistant")
    runtime.services.register_host_facet(
        HostFacetBinding(
            name=LOCAL_ASSISTANT_BROWSER_HOST_FACET,
            facet=BrowserHostFacet(),
            owner=PackageOwnership(
                package_name="assistant-host",
                package_role="host",
                surface="host_facet",
            ),
        )
    )

    snapshot_tool = runtime.kernel.tool_registry.get("browser_snapshot")
    snapshot = asyncio.run(
        snapshot_tool.execute(
            {"include_recent_tabs": True},
            _tool_context(runtime, runtime_root),
        )
    )
    assert snapshot["status"] == "available"
    assert snapshot["bound_host_facet"] is True
    assert snapshot["host_facet_operation_supported"] is True
    assert snapshot["approval_required"] is False
    assert snapshot["bridge_state"] == {
        "focused_url": "https://assistant.example.test/home",
        "recent_tabs": ["https://assistant.example.test/home"],
    }

    stage_tool = runtime.kernel.tool_registry.get("browser_stage_navigation")
    staged = asyncio.run(
        stage_tool.execute(
            {"url": "https://assistant.example.test/briefing"},
            _tool_context(runtime, runtime_root),
        )
    )
    assert staged["status"] == "staged"
    assert staged["bound_host_facet"] is True
    assert staged["host_facet_operation_supported"] is True
    assert staged["approval_required"] is True
    assert staged["receipt"] == {
        "receipt_id": "nav-1",
        "review_state": "pending",
        "target_url": "https://assistant.example.test/briefing",
    }


def test_local_assistant_mapping_host_facets_only_satisfy_supported_read_only_operations(
    tmp_path: Path,
) -> None:
    runtime, _shape, runtime_root = _assemble_reference_runtime(tmp_path, "weavert-scenario-local-assistant")
    runtime.services.register_host_facet(
        HostFacetBinding(
            name=LOCAL_ASSISTANT_PIM_HOST_FACET,
            facet={"events": [{"title": "Team sync"}]},
            owner=PackageOwnership(
                package_name="assistant-host",
                package_role="host",
                surface="host_facet",
            ),
        )
    )

    agenda_tool = runtime.kernel.tool_registry.get("pim_list_agenda")
    agenda = asyncio.run(agenda_tool.execute({}, _tool_context(runtime, runtime_root)))
    assert agenda["status"] == "available"
    assert agenda["bound_host_facet"] is True
    assert agenda["host_facet_operation_supported"] is True
    assert agenda["bridge_state"] == {"events": [{"title": "Team sync"}]}

    contacts_tool = runtime.kernel.tool_registry.get("pim_lookup_contacts")
    contacts = asyncio.run(
        contacts_tool.execute({"query": "Alice"}, _tool_context(runtime, runtime_root))
    )
    assert contacts["status"] == "host_bridge_required"
    assert contacts["bound_host_facet"] is True
    assert contacts["host_facet_operation_supported"] is False
    assert "bridge_state" not in contacts


def test_local_assistant_daily_brief_skill_fork_exposes_skill_tool_to_assistant_agents(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _parent_request(request):
        return tool_call_batch(
            request_id="req-local-assistant-root-1",
            tool_name="skill",
            tool_input={"skill": "daily-brief"},
            call_id="call-daily-brief",
        )

    def _planner_request(request):
        captured["planner_tools"] = set(request.turn_context.available_tools)
        captured["planner_skills"] = set(request.turn_context.available_skills)
        assert request.agent is not None
        assert request.agent.name == "assistant-planner"
        return tool_call_batch(
            request_id="req-local-assistant-planner-1",
            tool_name="skill",
            tool_input={"skill": "safe-action-check"},
            call_id="call-safe-action-check",
        )

    def _planner_followup(request):
        captured["planner_inline_skill_applied"] = any(
            message.role == MessageRole.SYSTEM and message.metadata.get("skill") == "safe-action-check"
            for message in request.messages
        )
        return text_batch(
            request_id="req-local-assistant-planner-2",
            text="planner finished with safe check",
        )

    def _parent_followup(request):
        return text_batch(
            request_id="req-local-assistant-root-2",
            text="daily brief completed",
        )

    runtime, _shape, _runtime_root = _assemble_reference_runtime(
        tmp_path,
        "weavert-scenario-local-assistant",
        model_client=ScriptedModelClient(
            [_parent_request, _planner_request, _planner_followup, _parent_followup]
        ),
    )

    messages = asyncio.run(
        runtime.run_prompt(
            "Start the local assistant daily brief.",
            session_id="local-assistant-daily-brief",
        )
    )

    assert captured["planner_tools"] == {
        "ask_user",
        "browser_snapshot",
        "local_os_snapshot",
        "pim_list_agenda",
        "pim_lookup_contacts",
        "prepare_citations",
        "retrieve_context",
        "skill",
    }
    assert captured["planner_skills"] == {"remember", "safe-action-check"}
    assert captured["planner_inline_skill_applied"] is True
    assert messages[-1].text == "daily brief completed"


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


def test_core_scenario_runtime_packs_module_is_only_a_compatibility_shim() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "core"
        / "src"
        / "weavert"
        / "scenario_runtime_packs.py"
    ).read_text(encoding="utf-8")

    assert "ReferenceSharedPackageShape(" not in source
    assert "ReferenceScenarioPackShape(" not in source
    assert "weavert_kit_chat" in source
    assert "weavert_kit_coding" in source
    assert "weavert_kit_local_assistant" in source


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
