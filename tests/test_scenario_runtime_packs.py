from __future__ import annotations

import asyncio
from email.message import Message
import json
import os
from pathlib import Path
import socket
import subprocess
import tarfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import pytest

from weavert.contracts import MessageRole
from weavert.definitions import ToolRiskLevel
from weavert.memory.models import MemoryEntry
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.package_system.protocols import HostFacetBinding, PackageOwnership
from weavert.package_system.resolution import PACKAGE_CANDIDATE_METADATA_KEY
from weavert.tool_runtime import ToolContext
from weavert_testing import ScriptedModelClient, text_batch, tool_call_batch
import weavert_kit_common_web_research._tool_impls as reference_web_tool_impls
import weavert_web_research.core as reference_web_research_core
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
from weavert_kit_common_web_research import (
    WEB_RESEARCH_TOOLS,
    reference_shared_package_manifest as web_research_shared_package_manifest,
    reference_shared_package_shape as web_research_shared_package_shape,
    reference_shared_package_shapes as web_research_shared_package_shapes,
    validate_web_fetch,
    validate_web_find,
)
from weavert_devtools.tool_impls import validate_web_fetch as validate_devtools_web_fetch
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


def _read_web_artifact_text(path: Path, member: str) -> str:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return archive.read(member).decode()
    with tarfile.open(path) as archive:
        package_prefix = path.name.removesuffix(".tar.gz")
        extracted = archive.extractfile(f"{package_prefix}/src/{member}")
        assert extracted is not None
        return extracted.read().decode()


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
CODING_SHARED_WEB_TOOLS = set(WEB_RESEARCH_TOOLS)
CODING_EXCLUSIVE_SPECIALIZED_TOOLS = (
    CODING_WORKSPACE_TOOLS
    | CODING_SHARED_GIT_TOOLS
    | CODING_SHARED_WORKSPACE_TOOLS
)
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
CODING_SPECIALIZED_TOOLS = (
    CODING_WORKSPACE_TOOLS
    | CODING_SHARED_GIT_TOOLS
    | CODING_SHARED_WEB_TOOLS
    | CODING_SHARED_WORKSPACE_TOOLS
)
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
CHAT_WEB_TOOL_SET = set(WEB_RESEARCH_TOOLS)
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
    | CHAT_WEB_TOOL_SET
    | LOCAL_ASSISTANT_WORKFLOW_CONTROL_TOOLS
    | LOCAL_ASSISTANT_BRIDGE_TOOL_SET
)
LOCAL_ASSISTANT_SCENARIO_AGENTS = set(LOCAL_ASSISTANT_SCENARIO_AGENT_NAMES)
LOCAL_ASSISTANT_SCENARIO_SKILLS = set(LOCAL_ASSISTANT_SCENARIO_SKILL_NAMES)
PUBLIC_BATCH_FETCH_FIELDS = {"urls", "sources", "max_concurrent_fetches"}
PUBLIC_BATCH_FETCH_TOOL_NAMES = {
    "grounding_web_search",
    "grounding_web_fetch",
    "grounding_web_find",
    "web_research_fetch_many",
    "_web_research_fetch_many",
    "web_fetch_many",
    "fetch_many",
}
LOCAL_ASSISTANT_PROFILE_SKILLS = LOCAL_ASSISTANT_SCENARIO_SKILLS | {"remember"}

REFERENCE_SHARED_SHAPES = (
    *retrieval_shared_package_shapes(),
    *web_research_shared_package_shapes(),
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
        web_research_shared_package_shape,
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
        web_research_shared_package_manifest(),
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


def _assemble_shared_reference_runtime(tmp_path: Path, package_name: str, *, model_client=None):
    shape = reference_shared_package_shape(package_name)
    runtime_root = tmp_path / shape.package_name
    runtime_root.mkdir(parents=True)
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=runtime_root,
            distribution="weavert-core",
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


def _tool_context(runtime, cwd: Path) -> ToolContext:
    return ToolContext(
        session_id="reference-shared-tool",
        turn_id="turn-1",
        agent_name="tester",
        cwd=cwd,
        tool_registry=runtime.kernel.tool_registry,
        agent_registry=runtime.kernel.agent_registry,
        tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
        runtime_services=runtime.services,
        agent_runner=runtime.services.agent_runner,
    )


def _assert_public_web_fetch_schema_is_single_page(schema: dict[str, Any]) -> None:
    properties = schema["properties"]
    assert {"url", "source"} <= set(properties)
    assert PUBLIC_BATCH_FETCH_FIELDS.isdisjoint(properties)
    assert all("batch" not in field and "concurrent" not in field for field in properties)
    assert schema["additionalProperties"] is False
    assert schema["oneOf"] == [{"required": ["url"]}, {"required": ["source"]}]


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


def _web_urlopen(request, timeout=10):  # pragma: no cover - exercised through tool calls
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
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    monkeypatch.setattr(
        reference_web_tool_impls,
        "web_urlopen",
        lambda request, timeout=10, **_kwargs: _web_urlopen(request, timeout=timeout),
    )
    monkeypatch.setattr(reference_web_research_core, "web_urlopen", _web_urlopen)

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

    web_runtime, web_shape, web_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    web_tool_names = _tool_names(web_runtime)
    assert CHAT_WEB_TOOL_SET <= web_tool_names
    assert web_runtime.kernel.agent_registry.get("web-searcher").metadata["builtin_owner"] == web_shape.package_name
    assert all(
        web_runtime.kernel.tool_registry.get(tool_name).metadata["builtin_owner"] == web_shape.package_name
        for tool_name in CHAT_WEB_TOOL_SET
    )
    assert all(
        web_runtime.kernel.tool_registry.get(tool_name).traits.read_only
        for tool_name in CHAT_WEB_TOOL_SET
    )

    delegated_calls = []

    async def agent_runner(agent: str, prompt: str, context: ToolContext, **kwargs: Any) -> dict[str, Any]:
        delegated_calls.append((agent, prompt, kwargs, context))
        raise AssertionError("normal web_research execution should use the package-owned loop")

    web_research_context = ToolContext(
        session_id="reference-shared-tool",
        turn_id="turn-1",
        agent_name="tester",
        cwd=web_root,
        tool_registry=web_runtime.kernel.tool_registry,
        agent_registry=web_runtime.kernel.agent_registry,
        tool_pool=tuple(web_runtime.kernel.tool_registry.definitions()),
        runtime_services=web_runtime.services,
        agent_runner=agent_runner,
    )
    web_research_tool_def = web_runtime.kernel.tool_registry.get("web_research")
    web_research_result = asyncio.run(
        web_research_tool_def.execute(
            {
                "objective": "What is the refund policy?",
                "domains": ["grounding.example.test"],
                "blocked_domains": ["blocked.example.test"],
                "freshness_days": 14,
                "search_budget": 2,
                "fetch_budget": 1,
                "find_budget": 1,
                "desired_source_count": 1,
            },
            web_research_context,
        )
    )
    assert delegated_calls == []
    assert web_research_result["policy"] == {
        "domains": ["grounding.example.test"],
        "blocked_domains": ["blocked.example.test"],
        "freshness_days": 14,
    }
    assert web_research_result["budget"]["fetch_budget"] == 1
    assert web_research_result["budget"]["used"] == {"searches": 1, "fetches": 1, "finds": 0}
    assert web_research_result["sources"][0]["url"] == "https://grounding.example.test/refund-policy"
    assert web_research_result["sources"][0]["title"] == "Refund policy"
    assert "Refunds stay available" in web_research_result["evidence"][0]["excerpt"]
    assert "Refunds stay available" in web_research_result["answer"]
    assert web_research_result["stop_reason"] == "freshness_unsupported"
    assert web_research_result["child_run"]["agent"] == "web_research_loop"

    search_tool = web_runtime.kernel.tool_registry.get("web_search")
    search_result = asyncio.run(
        search_tool.execute({"query": "refund policy", "limit": 3}, _tool_context(web_runtime, web_root))
    )
    assert search_result["results"] == [
        {
            "id": search_result["results"][0]["id"],
            "title": "Refund policy",
            "excerpt": "",
            "content": "",
            "url": "https://grounding.example.test/refund-policy",
            "source_kind": "external",
            "metadata": search_result["results"][0]["metadata"],
            "rank": 1,
            "source_handle": search_result["results"][0]["source_handle"],
            "page_handle": search_result["results"][0]["page_handle"],
            "source": search_result["results"][0]["source"],
            "browser_handoff": search_result["results"][0]["browser_handoff"],
        }
    ]
    assert search_result["results"][0]["source_handle"].startswith("source::")
    assert search_result["results"][0]["page_handle"].startswith("page::")

    fetch_tool = web_runtime.kernel.tool_registry.get("web_fetch")
    fetch_result = asyncio.run(
        fetch_tool.execute(
            {"source": search_result["results"][0]},
            _tool_context(web_runtime, web_root),
        )
    )
    assert fetch_result["title"] == "Refund policy"
    assert "30 days" in fetch_result["content"]
    assert fetch_result["source_handle"] == search_result["results"][0]["source_handle"]

    find_tool = web_runtime.kernel.tool_registry.get("web_find")
    find_result = asyncio.run(
        find_tool.execute(
            {"page": fetch_result, "pattern": "30 days"},
            _tool_context(web_runtime, web_root),
        )
    )
    assert find_result["matches"][0]["exact_excerpt"] == "30 days"
    assert find_result["matches"][0]["source_handle"] == fetch_result["source_handle"]

    coding_tool_names = _tool_names(web_runtime)
    assert CODING_SHARED_WEB_TOOLS <= coding_tool_names
    assert all(
        web_runtime.kernel.tool_registry.get(tool_name).metadata["builtin_owner"] == web_shape.package_name
        for tool_name in CODING_SHARED_WEB_TOOLS
    )

    async def coding_agent_runner(agent: str, _prompt: str, context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        await context.tool_registry.get("web_fetch").execute(
            {"url": "https://grounding.example.test/refund-policy"},
            context,
        )
        return {
            "agent": agent,
            "status": "completed",
            "summary": "The API remains available in v2.",
            "terminal_metadata": {
                "web_research": {
                    "answer": "The API remains available in v2.",
                    "stop_reason": "sufficient_evidence",
                    "version_scope": {"requested": "v2", "status": "satisfied"},
                    "api_names": ["refunds.create"],
                    "compatibility_notes": ["Compatible with v2."],
                    "breaking_changes": [],
                }
            },
        }

    async def _request_coding_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_coding_fallback)
    coding_result = asyncio.run(
        web_research_tool_def.execute(
            {
                "objective": "Check whether refunds.create is still available in v2.",
                "profile": "coding",
                "domains": ["grounding.example.test"],
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            ToolContext(
                session_id="coding-web-research",
                turn_id="turn-1",
                agent_name="tester",
                cwd=web_root,
                tool_registry=web_runtime.kernel.tool_registry,
                agent_registry=web_runtime.kernel.agent_registry,
                tool_pool=tuple(web_runtime.kernel.tool_registry.definitions()),
                runtime_services=web_runtime.services,
                agent_runner=coding_agent_runner,
            ),
        )
    )
    assert coding_result["research_trace"]["profile"] == "coding"
    assert coding_result["facets"]["coding"]["version_scope"] == {"requested": "v2", "status": "satisfied"}
    assert coding_result["facets"]["coding"]["api_names"] == ["refunds.create"]


def test_common_web_generated_artifacts_match_public_research_surfaces() -> None:
    package_root = Path("packages/product-kits/common/web-research")
    required_snippets = {
        "__init__.py": (
            "web_research_tool",
            "web_fetch_tool",
            "validate_web_fetch",
            "bounded multi-page inspection behind web_research",
        ),
        "_builtins.py": (
            "web_research",
            "web-searcher",
            "web_fetch",
            '"mode"',
            '"hard_policy"',
            '"preferences"',
            '"max_concurrent_fetches"',
        ),
        "_tool_impls.py": (
            "WebResearchLoopState",
            "web_fetch_tool",
            "_effective_web_tool_input",
            "budget_profile",
            "preferred_domains",
        ),
    }
    artifact_sources = [
        package_root / "build/lib/weavert_kit_common_web_research",
        package_root / "dist/weavert_kit_common_web_research-0.1.0-py3-none-any.whl",
        package_root / "dist/weavert_kit_common_web_research-0.1.0.tar.gz",
    ]

    for artifact in artifact_sources:
        assert artifact.exists(), artifact
        for filename, snippets in required_snippets.items():
            member = f"weavert_kit_common_web_research/{filename}"
            if artifact.is_dir():
                text = (artifact / filename).read_text()
            else:
                text = _read_web_artifact_text(artifact, member)
            for snippet in snippets:
                assert snippet in text, (artifact, filename, snippet)


def test_public_web_fetch_schema_is_single_page_only(tmp_path: Path) -> None:
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    schema = runtime.kernel.tool_registry.get("web_fetch").input_schema

    _assert_public_web_fetch_schema_is_single_page(schema)

    context = _tool_context(runtime, runtime_root)
    url = validate_web_fetch({"url": "https://docs.example.test/page"}, context)
    source = validate_web_fetch(
        {"source": {"url": "https://docs.example.test/page", "title": "Docs"}},
        context,
    )
    both = validate_web_fetch(
        {"url": "https://docs.example.test/page", "source": {"url": "https://docs.example.test/other"}},
        context,
    )

    assert url.valid is True
    assert source.valid is True
    assert both.valid is False
    assert both.message == "web_fetch accepts either url or source, not both"


def test_public_web_fetch_rejects_batch_fields_standalone_and_inside_web_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    context = _tool_context(runtime, runtime_root)

    for field, value in {
        "urls": ["https://docs.example.test/a", "https://docs.example.test/b"],
        "sources": [{"url": "https://docs.example.test/a"}],
        "max_concurrent_fetches": 2,
    }.items():
        outcome = validate_web_fetch({field: value}, context)
        assert outcome.valid is False
        assert "batch fetch fields are not public" in outcome.message
        assert field in outcome.message

    async def agent_runner(agent: str, _prompt: str, active_context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        with pytest.raises(ValueError, match="batch fetch fields are not public"):
            await active_context.tool_registry.get("web_fetch").execute(
                {"urls": ["https://docs.example.test/a", "https://docs.example.test/b"]},
                active_context,
            )
        return {"agent": agent, "status": "completed", "summary": "Batch fetch was rejected."}

    async def _request_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_fallback)
    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {"objective": "Reject public batch fetch.", "max_turns": 1},
            ToolContext(
                session_id="batch-fetch-rejection",
                turn_id="turn-1",
                agent_name="tester",
                cwd=runtime_root,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                runtime_services=runtime.services,
                agent_runner=agent_runner,
            ),
        )
    )

    assert result["sources"] == []
    assert result["budget"]["rejections"]["policy"] == 1
    assert result["trace_summary"][0]["event"] == "rejected"
    assert result["stop_reason"] == "policy_blocked"
    assert result["gaps"][0]["kind"] == "policy_blocked"


def test_web_research_policy_blocked_when_fallback_fetch_violates_hard_domain_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    async def agent_runner(agent: str, _prompt: str, active_context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        with pytest.raises(ValueError, match="outside the allowed domains"):
            await active_context.tool_registry.get("web_fetch").execute(
                {"url": "https://outside.example.test/leak"},
                active_context,
            )
        return {"agent": agent, "status": "completed", "summary": "Domain policy blocked fetch."}

    async def _request_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_fallback)
    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Reject outside-domain fallback fetch.",
                "domains": ["grounding.example.test"],
                "max_turns": 1,
            },
            ToolContext(
                session_id="policy-blocked-domain",
                turn_id="turn-1",
                agent_name="tester",
                cwd=runtime_root,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                runtime_services=runtime.services,
                agent_runner=agent_runner,
            ),
        )
    )

    assert result["sources"] == []
    assert result["evidence"] == []
    assert result["stop_reason"] == "policy_blocked"
    assert result["budget"]["rejections"]["policy"] == 1
    rejected = [event for event in result["trace_summary"] if event["event"] == "rejected"]
    assert rejected == [
        {
            "event": "rejected",
            "tool": "web_fetch",
            "error": "Grounding fetch is outside the allowed domains",
            "url": "https://outside.example.test/leak",
        }
    ]


@pytest.mark.parametrize(
    "package_name",
    ("weavert-scenario-chat", "weavert-scenario-coding", "weavert-scenario-local-assistant"),
)
def test_scenario_web_inventories_reject_public_batch_fetch_surfaces(tmp_path: Path, package_name: str) -> None:
    runtime, _shape, _runtime_root = _assemble_reference_runtime(tmp_path, package_name)
    tool_names = _tool_names(runtime)

    assert "web_fetch" in tool_names
    assert PUBLIC_BATCH_FETCH_TOOL_NAMES.isdisjoint(tool_names)
    for tool_name in tool_names:
        assert "fetch_many" not in tool_name

    for tool_name, tool_definition in runtime.kernel.tool_registry.items():
        assert tool_name not in PUBLIC_BATCH_FETCH_TOOL_NAMES
        if tool_name == "web_fetch":
            _assert_public_web_fetch_schema_is_single_page(tool_definition.input_schema)
        else:
            assert "web_research_fetch_many" not in str(tool_definition.input_schema)


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
                CODING_EXCLUSIVE_SPECIALIZED_TOOLS,
                CODING_PROFILE_AGENTS,
                CODING_PROFILE_SKILLS,
            ),
        (
            "weavert-scenario-local-assistant",
                LOCAL_ASSISTANT_PROFILE_TOOLS,
                LOCAL_ASSISTANT_SCENARIO_AGENTS,
                LOCAL_ASSISTANT_PROFILE_SKILLS,
                CODING_EXCLUSIVE_SPECIALIZED_TOOLS,
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
def test_web_fetch_validation_rejects_non_public_hosts(url: str) -> None:
    outcome = validate_web_fetch(
        {"url": url},
        ToolContext(session_id="grounding-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd()),
    )

    assert outcome.valid is False
    assert outcome.message == "Grounding fetch only supports public web hosts"


def test_web_fetch_validation_rejects_hostnames_that_resolve_to_non_public_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_web_tool_impls._web_hostname_resolves_publicly.cache_clear()

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

    monkeypatch.setattr(reference_web_tool_impls.socket, "getaddrinfo", _fake_getaddrinfo)

    try:
        for url in (
            "https://loopback-proxy.example/",
            "https://metadata-proxy.example/latest/meta-data/",
        ):
            outcome = validate_web_fetch(
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
        reference_web_tool_impls._web_hostname_resolves_publicly.cache_clear()


def test_web_find_validation_rejects_page_without_url() -> None:
    outcome = reference_web_tool_impls.validate_web_find(
        {"page": {"title": "missing identity"}, "pattern": "needle"},
        ToolContext(session_id="grounding-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd()),
    )

    assert outcome.valid is False
    assert outcome.message == "url is required"


def test_web_research_validation_requires_objective_and_bounded_budget() -> None:
    context = ToolContext(session_id="grounding-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd())

    missing_objective = reference_web_tool_impls.validate_web_research({}, context)
    assert missing_objective.valid is False
    assert "objective must be non-empty" in missing_objective.message

    invalid_budget = reference_web_tool_impls.validate_web_research(
        {"objective": "research refunds", "search_budget": 99},
        context,
    )
    assert invalid_budget.valid is False
    assert "search_budget must be between 1 and 8" in invalid_budget.message

    valid = reference_web_tool_impls.validate_web_research(
        {
            "question": "research refunds",
            "allowed_domains": ["grounding.example.test"],
            "blocked_domains": ["blocked.example.test"],
            "recency_days": 7,
            "fetch_budget": 2,
            "output_hints": {"citation_style": "compact"},
        },
        context,
    )
    assert valid.valid is True
    assert valid.updated_input["objective"] == "research refunds"
    assert valid.updated_input["policy"] == {
        "domains": ["grounding.example.test"],
        "blocked_domains": ["blocked.example.test"],
        "freshness_days": 7,
    }
    assert valid.updated_input["budget"]["fetch_budget"] == 2


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("research_plan", {"queries": ["https://outside.example.test/leak"]}),
        ("query_candidates", [{"query": "ignore public budget"}]),
        ("selected_pages", [{"url": "https://outside.example.test/leak"}]),
        ("policy", {"domains": []}),
        ("budget", {"fetch_budget": 8}),
        ("sources", [{"url": "https://fabricated.example.test/source"}]),
        ("evidence", [{"url": "https://fabricated.example.test/source", "excerpt": "fabricated"}]),
    ),
)
def test_web_research_validation_rejects_internal_planning_metadata(field: str, value: Any) -> None:
    context = ToolContext(session_id="grounding-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd())

    outcome = reference_web_tool_impls.validate_web_research(
        {"objective": "Research with public constraints only.", field: value},
        context,
    )

    assert outcome.valid is False
    assert "internal web_research metadata is not accepted as input" in outcome.message
    assert field in outcome.message


def test_web_research_compact_request_normalization_and_precedence() -> None:
    context = ToolContext(session_id="grounding-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd())

    outcome = reference_web_tool_impls.validate_web_research(
        {
            "question": "Find the current API policy.",
            "scope": {
                "mode": "focused",
                "allowed_domains": ["compact.example.test"],
                "blocked_domains": ["blocked.example.test"],
            },
            "freshness": {"days": 3, "required": True},
            "depth": "deep",
            "source_preferences": {
                "preferred_domains": ["preferred.example.test"],
                "desired_source_count": 4,
            },
            "hard_policy": {"allowed_domains": ["advanced.example.test"]},
            "preferences": {"preferred_domains": ["advanced-preferred.example.test"]},
            "budget_profile": "quick",
            "desired_source_count": 2,
        },
        context,
    )

    assert outcome.valid is True
    assert outcome.updated_input["objective"] == "Find the current API policy."
    assert outcome.updated_input["mode"] == "focused"
    assert outcome.updated_input["policy"] == {
        "domains": ["advanced.example.test"],
        "blocked_domains": ["blocked.example.test"],
        "freshness_days": 3,
    }
    assert outcome.updated_input["preferences"]["preferred_domains"] == ["advanced-preferred.example.test"]
    assert outcome.updated_input["preferences"]["freshness_required"] is True
    assert outcome.updated_input["budget_profile"] == "quick"
    assert outcome.updated_input["budget"]["search_budget"] == 2
    assert outcome.updated_input["budget"]["desired_source_count"] == 2


@pytest.mark.parametrize(
    ("profile", "expected_priorities", "freshness_required"),
    (
        ("general", ["official", "authoritative", "news", "reference"], False),
        ("coding", ["official_docs", "release_notes", "changelog", "source_repository", "issue_tracker"], False),
        ("business", ["official_company", "filings", "announcements", "news", "reviews"], False),
        ("academic", ["papers", "publishers", "institutions", "preprints"], False),
        ("legal_compliance", ["statutes", "regulations", "standards", "official_guidance"], True),
        ("product_shopping", ["official_specs", "prices", "reviews", "alternatives", "risk_notes"], True),
    ),
)
def test_web_research_profile_defaults_source_priorities_and_freshness(
    profile: str,
    expected_priorities: list[str],
    freshness_required: bool,
) -> None:
    context = ToolContext(session_id="profile-defaults", turn_id="turn-1", agent_name="tester", cwd=Path.cwd())

    outcome = reference_web_tool_impls.validate_web_research(
        {"objective": "Profile-specific research.", "profile": profile},
        context,
    )

    assert outcome.valid is True
    assert outcome.updated_input["profile"] == profile
    assert outcome.updated_input["preferences"]["source_priorities"] == expected_priorities
    assert outcome.updated_input["preferences"]["freshness_required"] is freshness_required
    assert outcome.updated_input["freshness_required"] is freshness_required


def test_web_research_strategy_validation_accepts_pro_and_rejects_unknown() -> None:
    context = ToolContext(session_id="pro-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd())

    accepted = reference_web_tool_impls.validate_web_research(
        {"objective": "Research with Pro planning.", "strategy": "pro"},
        context,
    )
    rejected = reference_web_tool_impls.validate_web_research(
        {"objective": "Research with unknown strategy.", "strategy": "magic"},
        context,
    )

    assert accepted.valid is True
    assert accepted.updated_input["strategy"] == "pro"
    assert rejected.valid is False
    assert rejected.message == "strategy must be deterministic or pro"


def test_pro_web_research_planner_search_fetch_and_evidence_bound_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = "refund policy"
    url = "https://grounding.example.test/refund-policy"
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={query: [{"title": "Refund policy", "url": url}]},
    )
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    context = _tool_context(runtime, runtime_root)
    def _synthesis_response(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert kind == "synthesizer"
        evidence_id = payload["evidence"][0]["id"]
        return {
            "answer": "Refunds stay available for 30 days after purchase.",
            "claims": [{"claim": "Refunds stay available for 30 days.", "evidence_ids": [evidence_id]}],
            "confidence": "high",
        }

    context.metadata[reference_web_tool_impls._WEB_RESEARCH_MODEL_RESPONSE_METADATA_KEY] = [
        {"actions": [{"type": "search", "query": query}], "rationale": "Find candidates."},
        {"actions": [{"type": "fetch", "source_handle": url}], "stop_intent": "sufficient_evidence"},
        _synthesis_response,
    ]

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {"objective": "What is the refund window?", "strategy": "pro", "search_budget": 1, "fetch_budget": 1, "desired_source_count": 1},
            context,
        )
    )

    assert result["strategy"] == "pro"
    assert result["child_run"]["agent"] == "web_research_pro_loop"
    assert result["stop_reason"] == "sufficient_evidence"
    assert result["sources"][0]["url"] == url
    assert result["claims"][0]["evidence_id"]
    assert any(event["event"] == "planner_decision" for event in result["trace_summary"])
    assert any(event["event"] == "synthesis_validated" for event in result["trace_summary"])


def test_pro_web_research_rejects_fabricated_source_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = reference_web_research_core.FixtureWebResearchProvider()
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    context = _tool_context(runtime, runtime_root)
    context.metadata[reference_web_tool_impls._WEB_RESEARCH_MODEL_RESPONSE_METADATA_KEY] = [
        {"actions": [{"type": "fetch", "source_handle": "fabricated-source"}], "stop_intent": "sufficient_evidence"},
        {"answer": "Unsupported.", "claims": [{"claim": "Unsupported.", "evidence_ids": ["fabricated-source"]}]},
        {"answer": "", "claims": []},
    ]

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {"objective": "Reject fabricated source.", "strategy": "pro", "search_budget": 1, "fetch_budget": 1, "desired_source_count": 1},
            context,
        )
    )

    assert result["sources"] == []
    assert result["claims"] == []
    assert result["stop_reason"] in {"policy_blocked", "partial_result", "remaining_gaps"}
    assert any(event["event"] == "planner_action_rejected" for event in result["trace_summary"])


def test_pro_web_research_rejects_policy_violating_direct_url_before_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_urls: list[str] = []

    def _urlopen(request, timeout=10, **_kwargs):
        _ = timeout
        opened_urls.append(request.full_url if hasattr(request, "full_url") else str(request))
        return _FakeUrlopenResponse("<html><body>blocked</body></html>")

    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    context = _tool_context(runtime, runtime_root)
    context.metadata[reference_web_tool_impls._WEB_RESEARCH_MODEL_RESPONSE_METADATA_KEY] = [
        {"actions": [{"type": "direct_url_fetch", "url": "https://blocked.example.test/page"}]},
        {"answer": "", "claims": []},
    ]

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Reject blocked direct URL.",
                "strategy": "pro",
                "allowed_domains": ["grounding.example.test"],
                "search_budget": 1,
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            context,
        )
    )

    assert opened_urls == []
    assert result["sources"] == []
    assert result["stop_reason"] == "policy_blocked"
    assert any(event["event"] == "planner_action_rejected" for event in result["trace_summary"])


def test_pro_web_research_traces_valid_direct_url_and_keeps_source_coverage_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    context = _tool_context(runtime, runtime_root)
    context.metadata[reference_web_tool_impls._WEB_RESEARCH_MODEL_RESPONSE_METADATA_KEY] = [
        {"actions": [{"type": "direct_url_fetch", "url": "https://grounding.example.test/refund-policy"}], "stop_intent": "sufficient_evidence"},
        {"answer": "Refunds stay available.", "claims": []},
    ]

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Inspect one direct URL.",
                "strategy": "pro",
                "allowed_domains": ["grounding.example.test"],
                "search_budget": 1,
                "fetch_budget": 1,
                "desired_source_count": 2,
            },
            context,
        )
    )

    assert result["sources"][0]["url"] == "https://grounding.example.test/refund-policy"
    assert result["stop_reason"] == "remaining_gaps"
    assert any(event["event"] == "direct_url_fetch" and event["provenance"] == "direct_url" for event in result["trace_summary"])


def test_pro_web_research_unsupported_synthesis_gets_one_repair_then_drops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    context = _tool_context(runtime, runtime_root)

    def _bad_synthesis(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert kind == "synthesizer"
        assert payload["evidence"]
        return {"answer": "Unsupported answer.", "claims": [{"claim": "Unsupported claim.", "evidence_ids": ["missing-evidence"]}]}

    context.metadata[reference_web_tool_impls._WEB_RESEARCH_MODEL_RESPONSE_METADATA_KEY] = [
        {"actions": [{"type": "direct_url_fetch", "url": "https://grounding.example.test/refund-policy"}], "stop_intent": "sufficient_evidence"},
        _bad_synthesis,
        {"answer": "Still unsupported.", "claims": [{"claim": "Still unsupported.", "evidence_ids": ["still-missing"]}]},
    ]

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Drop unsupported synthesis.",
                "strategy": "pro",
                "allowed_domains": ["grounding.example.test"],
                "search_budget": 1,
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            context,
        )
    )

    assert result["claims"] == []
    assert result["stop_reason"] == "remaining_gaps"
    assert any(event["event"] == "synthesis_repair_attempt" for event in result["trace_summary"])
    assert any(event["event"] == "unsupported_synthesis_dropped" for event in result["trace_summary"])


def test_web_research_pro_unavailable_falls_back_to_deterministic_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={"What is the refund window?": [{"title": "Refund policy", "url": "https://grounding.example.test/refund-policy"}]},
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {"objective": "What is the refund window?", "strategy": "pro", "search_budget": 1, "fetch_budget": 1, "desired_source_count": 1},
            _tool_context(runtime, runtime_root),
        )
    )

    assert result["strategy"] == "deterministic"
    assert result["requested_strategy"] == "pro"
    assert result["research_trace"]["strategy_fallback_reason"] == "pro_model_unavailable"
    assert result["child_run"]["agent"] == "web_research_loop"


def test_web_research_runtime_projects_ledger_evidence_without_terminal_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)

    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(
        tmp_path,
        "weavert-shared-web-research",
    )

    tool = runtime.kernel.tool_registry.get("web_research")
    result = asyncio.run(
        tool.execute(
            {
                "objective": "What is the refund window?",
                "domains": ["grounding.example.test"],
                "search_budget": 1,
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert result["answer"] == "Refunds stay available for 30 days after purchase."
    assert result["sources"][0]["url"] == "https://grounding.example.test/refund-policy"
    assert result["evidence"][0]["url"] == "https://grounding.example.test/refund-policy"
    assert "30 days" in result["evidence"][0]["excerpt"]
    assert result["budget"]["used"] == {"searches": 1, "fetches": 1, "finds": 0}
    assert result["stop_reason"] == "sufficient_evidence"
    assert result["child_run"]["agent"] == "web_research_loop"
    assert result["research_trace"]["queries"] == ["What is the refund window?"]
    trace_events = [event["event"] for event in result["trace_summary"]]
    assert "research_plan" in trace_events
    assert "searched" in trace_events
    assert "page_selected" in trace_events
    assert "fetched" in trace_events
    assert "loop_decision" in trace_events
    assert "terminal_decision" in trace_events


def test_web_research_public_result_envelope_matches_registered_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    tool = runtime.kernel.tool_registry.get("web_research")

    result = asyncio.run(
        tool.execute(
            {
                "objective": "What is the refund window?",
                "domains": ["grounding.example.test"],
                "search_budget": 1,
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    required = set(tool.output_schema["required"])
    properties = set(tool.output_schema["properties"])
    assert tool.output_schema["additionalProperties"] is False
    assert set(result) == required
    assert set(result) <= properties
    assert set(result["budget"]) == {
        "search_budget",
        "fetch_budget",
        "find_budget",
        "desired_source_count",
        "max_turns",
        "max_concurrent_fetches",
        "used",
        "rejections",
        "operation_failures",
    }
    assert set(result["budget"]["used"]) == {"searches", "fetches", "finds"}
    assert set(result["budget"]["rejections"]) == {"policy", "budget"}
    assert set(result["freshness"]) == {"requested_days", "required", "status"}
    assert set(result["research_trace"]) == {"profile", "strategy", "queries", "pages_read", "iterations", "trace_summary"}
    assert result["research_trace"]["trace_summary"] == result["trace_summary"]
    assert all(isinstance(result[field], list) for field in ("sources", "evidence", "conflicts", "gaps", "claims", "trace_summary"))
    assert isinstance(result["auxiliary_signals"], dict)
    assert {"id", "title", "url", "source_handle", "page_handle"} <= set(result["sources"][0])
    assert {"id", "title", "url", "excerpt", "source_handle", "page_handle"} <= set(result["evidence"][0])


def test_web_research_runtime_preserves_provider_and_freshness_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    provider = reference_web_research_core.FixtureWebResearchProvider(
        provider_id="fresh-fixture",
        supports_freshness=True,
        search_results={
            "refund policy": [
                {"title": "Refund policy", "url": "https://grounding.example.test/refund-policy"}
            ]
        },
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )

    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(
        tmp_path,
        "weavert-shared-web-research",
    )

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "question": "What is the current refund policy?",
                "scope": {"allowed_domains": ["grounding.example.test"]},
                "freshness": {"days": 7, "required": True},
                "depth": "quick",
                "desired_source_count": 1,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert result["provider"]["id"] == "fresh-fixture"
    assert result["provider_selection"]["selected"] == "fresh-fixture"
    assert result["freshness_scope"] == {"requested_days": 7, "status": "enforced"}
    assert result["stop_reason"] == "sufficient_evidence"
    assert result["sources"][0]["provider"]["id"] == "fresh-fixture"


def test_web_research_runtime_classifies_provider_fallback_as_freshness_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    failing_provider = reference_web_research_core.FixtureWebResearchProvider(
        provider_id="fresh-fixture",
        supports_freshness=True,
        fail_search=True,
    )
    fallback_provider = reference_web_research_core.FixtureWebResearchProvider(
        provider_id="legacy-fixture",
        supports_freshness=False,
        search_results={
            "refund policy": [
                {"title": "Refund policy", "url": "https://grounding.example.test/refund-policy"}
            ]
        },
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((failing_provider, fallback_provider)),
    )

    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(
        tmp_path,
        "weavert-shared-web-research",
    )

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "question": "What is the current refund policy?",
                "scope": {"allowed_domains": ["grounding.example.test"]},
                "freshness": {"days": 7, "required": True},
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert result["provider"]["id"] == "legacy-fixture"
    assert result["provider_selection"]["status"] == "fallback"
    assert result["provider_fallback"]["used"] is True
    assert result["freshness_scope"] == {"requested_days": 7, "status": "unsupported"}
    assert result["stop_reason"] == "freshness_unsupported"


def test_web_research_runtime_enforces_policy_and_budget_in_package_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_urls: list[str] = []

    def _urlopen(request, timeout=10, **_kwargs):
        _ = timeout
        url = request.full_url if hasattr(request, "full_url") else str(request)
        opened_urls.append(url)
        return _FakeUrlopenResponse(
            f"<html><head><title>{url}</title></head><body>Evidence from {url}</body></html>"
        )

    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _urlopen)
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={
            "Only inspect the grounding domain.": [
                {"title": "Outside", "url": "https://outside.example.test/leak"},
                {"title": "Allowed one", "url": "https://grounding.example.test/one"},
                {"title": "Allowed two", "url": "https://grounding.example.test/two"},
            ]
        },
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )

    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(
        tmp_path,
        "weavert-shared-web-research",
    )

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Only inspect the grounding domain.",
                "domains": ["grounding.example.test"],
                "fetch_budget": 1,
                "desired_source_count": 1,
                "max_turns": 4,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert opened_urls == ["https://grounding.example.test/one"]
    assert result["budget"]["used"]["fetches"] == 1
    assert result["budget"]["rejections"] == {"policy": 0, "budget": 0}
    assert result["stop_reason"] == "sufficient_evidence"
    assert result["child_run"]["agent"] == "web_research_loop"


def test_web_research_open_mode_repeated_fetch_uses_preferences_and_deterministic_partial_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_urls: list[str] = []

    def _urlopen(request, timeout=10, **_kwargs):
        _ = timeout
        url = request.full_url if hasattr(request, "full_url") else str(request)
        opened_urls.append(url)
        return _FakeUrlopenResponse(
            f"<html><head><title>{url}</title></head><body>Evidence from {url}</body></html>"
        )

    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _urlopen)
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={
            "Explore public sources.": [
                {"title": "Preferred", "url": "https://preferred.example.test/a"},
                {"title": "Unsafe internal", "url": "http://127.0.0.1:8000/admin"},
                {"title": "Outside", "url": "https://outside.example.test/c"},
            ]
        },
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )

    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(
        tmp_path,
        "weavert-shared-web-research",
    )

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Explore public sources.",
                "mode": "open",
                "domains": ["preferred.example.test"],
                "fetch_budget": 3,
                "desired_source_count": 2,
                "max_turns": 4,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert opened_urls == ["https://preferred.example.test/a", "https://outside.example.test/c"]
    assert result["policy"]["domains"] == []
    assert result["preferences"]["preferred_domains"] == ["preferred.example.test"]
    assert [source["url"] for source in result["sources"]] == [
        "https://preferred.example.test/a",
        "https://outside.example.test/c",
    ]
    assert result["budget"]["used"]["fetches"] == 2
    assert result["budget"]["rejections"]["policy"] == 0
    assert result["stop_reason"] == "sufficient_evidence"


def test_web_research_runtime_drops_fabricated_child_metadata_without_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    delegated_calls: list[str] = []

    async def _request_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    async def agent_runner(agent: str, _prompt: str, _context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        delegated_calls.append(agent)
        return {
            "agent": agent,
            "status": "completed",
            "summary": "Child claimed evidence without using web tools.",
            "terminal_metadata": {
                "web_research": {
                    "sources": [
                        {
                            "url": "https://fabricated.example.test/source",
                            "title": "Fabricated source",
                        }
                    ],
                    "evidence": [
                        {
                            "url": "https://fabricated.example.test/source",
                            "excerpt": "Fabricated evidence.",
                        }
                    ],
                    "stop_reason": "sufficient_evidence",
                }
            },
        }

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_fallback)
    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {"objective": "Verify fabricated child metadata.", "desired_source_count": 1},
            ToolContext(
                session_id="fabricated-child-metadata",
                turn_id="turn-1",
                agent_name="tester",
                cwd=runtime_root,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                runtime_services=runtime.services,
                agent_runner=agent_runner,
            ),
        )
    )

    assert result["sources"] == []
    assert result["evidence"] == []
    assert result["answer"] == ""
    assert result["stop_reason"] == "partial_result"
    assert result["budget"]["used"] == {"searches": 0, "fetches": 0, "finds": 0}
    assert delegated_calls == ["web-searcher"]
    dropped = [event for event in result["trace_summary"] if event["event"] == "unverified_child_metadata_dropped"]
    assert {event["kind"] for event in dropped} == {"source", "evidence"}
    assert any(event["event"] == "unverified_child_answer_dropped" for event in result["trace_summary"])


def test_web_research_runtime_merges_child_annotations_without_overriding_ledger_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    async def _request_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    async def agent_runner(agent: str, _prompt: str, context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        fetched = await context.tool_registry.get("web_fetch").execute(
            {"url": "https://grounding.example.test/refund-policy"},
            context,
        )
        return {
            "agent": agent,
            "status": "completed",
            "summary": "Refunds stay available for 30 days.",
            "terminal_metadata": {
                "web_research": {
                    "sources": [
                        {
                            "url": "https://fabricated.example.test/refund-policy",
                            "title": "Fabricated title",
                            "source_handle": fetched["source_handle"],
                            "relevance": "high",
                        }
                    ],
                    "evidence": [
                        {
                            "url": "https://fabricated.example.test/refund-policy",
                            "source_handle": fetched["source_handle"],
                            "excerpt": "Fabricated child excerpt.",
                            "claim": "Refunds remain available for 30 days.",
                        }
                    ],
                }
            },
        }

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_fallback)
    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Annotate verified refund evidence.",
                "domains": ["grounding.example.test"],
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            ToolContext(
                session_id="matching-child-metadata",
                turn_id="turn-1",
                agent_name="tester",
                cwd=runtime_root,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                runtime_services=runtime.services,
                agent_runner=agent_runner,
            ),
        )
    )

    assert result["sources"][0]["url"] == "https://grounding.example.test/refund-policy"
    assert result["sources"][0]["title"] == "Refund policy"
    assert result["sources"][0]["relevance"] == "high"
    assert result["evidence"][0]["url"] == "https://grounding.example.test/refund-policy"
    assert "Refunds stay available" in result["evidence"][0]["excerpt"]
    assert result["evidence"][0]["claim"] == "Refunds remain available for 30 days."
    assert result["answer"] == "Refunds stay available for 30 days after purchase."
    assert result["stop_reason"] == "sufficient_evidence"


def test_web_research_records_search_provider_failure_as_structured_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = reference_web_research_core.FixtureWebResearchProvider(fail_search=True)
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Search provider outage.",
                "search_budget": 1,
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert result["sources"] == []
    assert result["evidence"] == []
    assert result["answer"] == ""
    assert result["budget"]["used"] == {"searches": 1, "fetches": 0, "finds": 0}
    assert result["budget"]["operation_failures"] == 1
    assert result["stop_reason"] in {"partial_result", "remaining_gaps", "budget_exhausted"}
    assert result["child_run"]["agent"] == "web_research_loop"
    failure_events = [event for event in result["trace_summary"] if event["event"] == "operation_failed"]
    assert failure_events[0]["tool"] == "web_search"
    assert "fixture search failure" in failure_events[0]["error"]


def test_web_research_profile_source_scoring_is_traceable_and_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_urls: list[str] = []

    def _urlopen(request, timeout=10, **_kwargs):
        _ = timeout
        url = request.full_url if hasattr(request, "full_url") else str(request)
        opened_urls.append(url)
        return _FakeUrlopenResponse(
            f"<html><head><title>{url}</title></head><body>API v2 compatibility evidence from {url}</body></html>"
        )

    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _urlopen)
    query = "Widget API v2 documentation changelog"
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={
            query: [
                {"title": "Blog copy", "url": "https://blog.example.test/widget-api-v2"},
                {"title": "Widget API reference documentation", "url": "https://docs.example.test/widget-api-v2"},
                {"title": "Widget changelog", "url": "https://docs.example.test/widget-api-v2/changelog"},
            ]
        }
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Widget API v2",
                "profile": "coding",
                "search_budget": 1,
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert opened_urls == ["https://docs.example.test/widget-api-v2"]
    selected_source = next(source for source in result["sources"] if source["url"] == "https://docs.example.test/widget-api-v2")
    assert selected_source["source_class"] == "official_docs"
    assert "profile_priority:official_docs" in selected_source["quality"]["signals"]
    inspected_evidence = next(item for item in result["evidence"] if item["url"] == "https://docs.example.test/widget-api-v2")
    assert inspected_evidence["source_class"] == "official_docs"
    assert "profile_priority:official_docs" in inspected_evidence["quality"]["signals"]
    assert "inspection_success" in inspected_evidence["quality"]["signals"]
    assert inspected_evidence["quality"]["diagnostic_only"] is True
    selected = [event for event in result["trace_summary"] if event["event"] == "page_selected"]
    assert selected
    assert "profile_priority:official_docs" in selected[0]["rationale"]


def test_web_research_accepts_only_ledger_bound_claims_and_projects_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _urlopen(request, timeout=10):
        _ = timeout
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url == "https://grounding.example.test/refund-policy-conflict":
            return _FakeUrlopenResponse(
                "<html><head><title>Refund conflict</title></head><body>"
                "<p>Refunds are not available after purchase in this older notice from 2020.</p>"
                "</body></html>"
            )
        return _web_urlopen(request, timeout=timeout)

    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    async def _request_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    async def agent_runner(agent: str, _prompt: str, context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        first = await context.tool_registry.get("web_fetch").execute(
            {"url": "https://grounding.example.test/refund-policy"},
            context,
        )
        second = await context.tool_registry.get("web_fetch").execute(
            {"url": "https://grounding.example.test/refund-policy-conflict"},
            context,
        )
        return {
            "agent": agent,
            "status": "completed",
            "terminal_metadata": {
                "web_research": {
                    "claims": [
                        {
                            "claim": "Refunds are available for 30 days.",
                            "claim_key": "refund_window",
                            "stance": "supports",
                            "source_handle": first["source_handle"],
                        },
                        {
                            "claim": "Refunds are not available after purchase.",
                            "claim_key": "refund_window",
                            "stance": "disputes",
                            "source_handle": second["source_handle"],
                        },
                        {"claim": "Unbound claim.", "claim_key": "refund_window", "stance": "supports"},
                    ],
                    "stop_reason": "sufficient_evidence",
                }
            },
        }

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_fallback)
    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Check refund conflicts.",
                "domains": ["grounding.example.test"],
                "fetch_budget": 2,
                "desired_source_count": 2,
            },
            ToolContext(
                session_id="claim-conflict",
                turn_id="turn-1",
                agent_name="tester",
                cwd=runtime_root,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                runtime_services=runtime.services,
                agent_runner=agent_runner,
            ),
        )
    )

    assert len(result["claims"]) == 2
    assert all(claim.get("source_handle") for claim in result["claims"])
    assert result["conflicts"][0]["claim_key"] == "refund_window"
    assert result["conflicts"][0]["resolved"] is False
    assert result["stop_reason"] == "unresolved_conflict"
    assert any(event["event"] == "unverified_child_metadata_dropped" and event["kind"] == "claim" for event in result["trace_summary"])
    assert result["auxiliary_signals"]["numbers"]


def test_web_research_unresolved_child_conflict_overrides_partial_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    async def _request_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    async def agent_runner(agent: str, _prompt: str, context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        fetched = await context.tool_registry.get("web_fetch").execute(
            {"url": "https://grounding.example.test/refund-policy"},
            context,
        )
        return {
            "agent": agent,
            "status": "completed",
            "terminal_metadata": {
                "web_research": {
                    "claims": [
                        {
                            "id": "claim-refund",
                            "claim": "Refunds are available for 30 days.",
                            "claim_key": "refund_window",
                            "source_handle": fetched["source_handle"],
                        }
                    ],
                    "conflicts": [
                        {
                            "kind": "claim_conflict",
                            "claim_key": "refund_window",
                            "claim_ids": ["claim-refund"],
                            "source_handles": [fetched["source_handle"]],
                            "resolved": False,
                        }
                    ],
                    "stop_reason": "partial_result",
                }
            },
        }

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_fallback)
    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Check partial conflict evidence.",
                "domains": ["grounding.example.test"],
                "fetch_budget": 1,
                "desired_source_count": 2,
            },
            ToolContext(
                session_id="partial-conflict",
                turn_id="turn-1",
                agent_name="tester",
                cwd=runtime_root,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                runtime_services=runtime.services,
                agent_runner=agent_runner,
            ),
        )
    )

    assert result["conflicts"][0]["claim_key"] == "refund_window"
    assert result["stop_reason"] == "unresolved_conflict"


def test_web_research_resolved_child_conflict_preserves_rationale_without_unresolved_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    async def _request_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    async def agent_runner(agent: str, _prompt: str, context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        fetched = await context.tool_registry.get("web_fetch").execute(
            {"url": "https://grounding.example.test/refund-policy"},
            context,
        )
        return {
            "agent": agent,
            "status": "completed",
            "terminal_metadata": {
                "web_research": {
                    "claims": [
                        {
                            "id": "claim-refund",
                            "claim": "Refunds are available for 30 days.",
                            "claim_key": "refund_window",
                            "source_handle": fetched["source_handle"],
                        }
                    ],
                    "conflicts": [
                        {
                            "kind": "claim_conflict",
                            "claim_key": "refund_window",
                            "claim_ids": ["claim-refund"],
                            "source_handles": [fetched["source_handle"]],
                            "resolved": True,
                            "resolution_rationale": "Current policy supersedes the older notice.",
                        }
                    ],
                    "stop_reason": "sufficient_evidence",
                }
            },
        }

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_fallback)
    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Check resolved refund evidence.",
                "domains": ["grounding.example.test"],
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            ToolContext(
                session_id="resolved-conflict",
                turn_id="turn-1",
                agent_name="tester",
                cwd=runtime_root,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                runtime_services=runtime.services,
                agent_runner=agent_runner,
            ),
        )
    )

    assert result["conflicts"][0]["resolved"] is True
    assert result["conflicts"][0]["resolution_rationale"] == "Current policy supersedes the older notice."
    assert result["stop_reason"] == "sufficient_evidence"


def test_web_research_compatible_same_key_claims_are_not_text_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    async def _request_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    async def agent_runner(agent: str, _prompt: str, context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        first = await context.tool_registry.get("web_fetch").execute(
            {"url": "https://grounding.example.test/refund-policy"},
            context,
        )
        second = await context.tool_registry.get("web_fetch").execute(
            {"url": "https://grounding.example.test/refund-policy"},
            context,
        )
        return {
            "agent": agent,
            "status": "completed",
            "terminal_metadata": {
                "web_research": {
                    "claims": [
                        {
                            "claim": "Refunds are available for 30 days.",
                            "claim_key": "refund_window",
                            "stance": "supports",
                            "source_handle": first["source_handle"],
                        },
                        {
                            "claim": "Customers may request refunds within thirty days.",
                            "claim_key": "refund_window",
                            "stance": "supports",
                            "source_handle": second["source_handle"],
                        },
                    ],
                    "stop_reason": "sufficient_evidence",
                }
            },
        }

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_fallback)
    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Check compatible refund claims.",
                "domains": ["grounding.example.test"],
                "fetch_budget": 2,
                "desired_source_count": 1,
            },
            ToolContext(
                session_id="compatible-claims",
                turn_id="turn-1",
                agent_name="tester",
                cwd=runtime_root,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                runtime_services=runtime.services,
                agent_runner=agent_runner,
            ),
        )
    )

    assert len(result["claims"]) == 2
    assert result["conflicts"] == []
    assert result["stop_reason"] != "unresolved_conflict"


def test_web_research_drops_unbound_child_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    async def _request_fallback(_request, _context, _state):
        raise reference_web_tool_impls._DelegatedWebResearchFallbackRequested("test fallback before web budget")

    async def agent_runner(agent: str, _prompt: str, context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        await context.tool_registry.get("web_fetch").execute(
            {"url": "https://grounding.example.test/refund-policy"},
            context,
        )
        return {
            "agent": agent,
            "status": "completed",
            "terminal_metadata": {
                "web_research": {
                    "conflicts": [
                        {
                            "kind": "claim_conflict",
                            "claim_key": "fabricated",
                            "source_handles": ["missing-source"],
                            "resolved": False,
                        }
                    ],
                    "stop_reason": "sufficient_evidence",
                }
            },
        }

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _request_fallback)
    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Drop fabricated conflicts.",
                "domains": ["grounding.example.test"],
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            ToolContext(
                session_id="unbound-conflict",
                turn_id="turn-1",
                agent_name="tester",
                cwd=runtime_root,
                tool_registry=runtime.kernel.tool_registry,
                agent_registry=runtime.kernel.agent_registry,
                tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                runtime_services=runtime.services,
                agent_runner=agent_runner,
            ),
        )
    )

    assert result["conflicts"] == []
    assert result["stop_reason"] == "sufficient_evidence"
    assert any(event["event"] == "unverified_child_metadata_dropped" and event["kind"] == "conflict" for event in result["trace_summary"])


def test_web_research_single_search_can_fetch_multiple_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_urls: list[str] = []

    def _urlopen(request, timeout=10, **_kwargs):
        _ = timeout
        url = request.full_url if hasattr(request, "full_url") else str(request)
        opened_urls.append(url)
        return _FakeUrlopenResponse(
            f"<html><head><title>{url}</title></head><body>Refund evidence from {url}.</body></html>"
        )

    class _CapturingProvider(reference_web_research_core.FixtureWebResearchProvider):
        def __init__(self) -> None:
            super().__init__(
                search_results={
                    "refund policy": [
                        {"title": "Refund source one", "url": "https://grounding.example.test/one"},
                        {"title": "Refund source two", "url": "https://grounding.example.test/two"},
                        {"title": "Refund source three", "url": "https://grounding.example.test/three"},
                    ]
                }
            )
            self.search_limits: list[int] = []

        def search(self, query: str, *, limit: int, policy=None):
            self.search_limits.append(limit)
            return super().search(query, limit=limit, policy=policy)

    provider = _CapturingProvider()
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _urlopen)
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Compare refund policy sources.",
                "domains": ["grounding.example.test"],
                "search_budget": 1,
                "fetch_budget": 3,
                "desired_source_count": 3,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert provider.search_limits == [3]
    assert opened_urls == [
        "https://grounding.example.test/one",
        "https://grounding.example.test/two",
        "https://grounding.example.test/three",
    ]
    assert result["budget"]["used"] == {"searches": 1, "fetches": 3, "finds": 0}
    assert [source["url"] for source in result["sources"]] == opened_urls
    assert result["stop_reason"] == "sufficient_evidence"


def test_web_research_budget_exhausted_when_fetch_budget_prevents_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={
            "refund policy": [
                {"title": "Refund policy", "url": "https://grounding.example.test/refund-policy"}
            ]
        },
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "What is the refund policy?",
                "domains": ["grounding.example.test"],
                "search_budget": 1,
                "fetch_budget": 0,
                "desired_source_count": 1,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert result["budget"]["used"] == {"searches": 1, "fetches": 0, "finds": 0}
    assert result["sources"][0]["url"] == "https://grounding.example.test/refund-policy"
    assert result["evidence"] == []
    assert result["stop_reason"] == "budget_exhausted"
    assert result["gaps"][0]["kind"] == "budget_exhausted"
    assert result["research_trace"]["pages_read"] == []


def test_web_research_low_yield_replans_once_then_stops_with_remaining_gaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={
            "refund policy": [],
            "Low yield refund policy official source": [],
        },
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Low yield refund policy",
                "search_budget": 2,
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert result["budget"]["used"] == {"searches": 2, "fetches": 0, "finds": 0}
    assert result["stop_reason"] == "remaining_gaps"
    events = [event["event"] for event in result["trace_summary"]]
    assert events.count("replanned") == 1
    assert events.count("low_yield_search") == 2


def test_web_research_low_yield_after_replan_stops_with_partial_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={
            "refund policy": [
                {"title": "Refund policy", "url": "https://grounding.example.test/refund-policy"}
            ],
            "Partial refund policy official source": [],
        },
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Partial refund policy",
                "domains": ["grounding.example.test"],
                "search_budget": 2,
                "fetch_budget": 2,
                "desired_source_count": 2,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert len(result["evidence"]) == 1
    assert result["budget"]["used"] == {"searches": 2, "fetches": 1, "finds": 0}
    assert result["stop_reason"] == "partial_result"
    events = [event["event"] for event in result["trace_summary"]]
    assert events.count("replanned") == 1
    assert "low_yield_search" in events


def test_web_research_internal_invariant_failure_is_not_projected_as_partial_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")
    delegated_calls: list[str] = []

    async def _raise_invariant(_request, _context, _state):
        raise AssertionError("loop invariant failed")

    async def agent_runner(agent: str, _prompt: str, _context: ToolContext, **_kwargs: Any) -> dict[str, Any]:
        delegated_calls.append(agent)
        return {"agent": agent, "status": "completed", "summary": "fallback should not run"}

    monkeypatch.setattr(reference_web_tool_impls, "_run_goal_driven_web_research_loop", _raise_invariant)

    with pytest.raises(AssertionError, match="loop invariant failed"):
        asyncio.run(
            runtime.kernel.tool_registry.get("web_research").execute(
                {"objective": "Trigger invariant failure."},
                ToolContext(
                    session_id="invariant-failure",
                    turn_id="turn-1",
                    agent_name="tester",
                    cwd=runtime_root,
                    tool_registry=runtime.kernel.tool_registry,
                    agent_registry=runtime.kernel.agent_registry,
                    tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
                    runtime_services=runtime.services,
                    agent_runner=agent_runner,
                ),
            )
        )

    assert delegated_calls == []


def test_web_research_records_page_inspection_failure_as_partial_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _urlopen(request, timeout=10, **_kwargs):
        _ = timeout
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url == "https://grounding.example.test/good":
            return _FakeUrlopenResponse(
                "<html><head><title>Good source</title></head><body>Verified refund evidence.</body></html>"
            )
        if url == "https://grounding.example.test/fail":
            raise urllib.error.URLError("backend unavailable")
        raise AssertionError(f"Unexpected URL requested during test: {url}")

    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _urlopen)
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={
            "Inspect two candidate sources.": [
                {"title": "Good source", "url": "https://grounding.example.test/good"},
                {"title": "Failing source", "url": "https://grounding.example.test/fail"},
            ]
        },
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )

    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(
        tmp_path,
        "weavert-shared-web-research",
    )

    result = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Inspect two candidate sources.",
                "fetch_budget": 2,
                "desired_source_count": 2,
                "max_turns": 3,
            },
            _tool_context(runtime, runtime_root),
        )
    )

    assert [item["url"] for item in result["evidence"]] == ["https://grounding.example.test/good"]
    assert result["budget"]["used"]["fetches"] == 2
    assert result["budget"]["operation_failures"] == 1
    assert result["stop_reason"] == "partial_result"
    failure_events = [event for event in result["trace_summary"] if event["event"] == "operation_failed"]
    assert failure_events == [
        {
            "event": "operation_failed",
            "tool": "web_fetch",
            "error": "<urlopen error backend unavailable>",
            "url": "https://grounding.example.test/fail",
        }
    ]


def test_web_research_stop_reason_uses_desired_source_count_and_freshness_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)
    provider = reference_web_research_core.FixtureWebResearchProvider(
        search_results={
            "refund policy": [
                {"title": "Refund policy", "url": "https://grounding.example.test/refund-policy"}
            ]
        },
    )
    monkeypatch.setattr(
        reference_web_tool_impls,
        "_web_search_provider_registry",
        reference_web_research_core.WebSearchProviderRegistry((provider,)),
    )
    runtime, _shape, runtime_root = _assemble_shared_reference_runtime(tmp_path, "weavert-shared-web-research")

    unmet_count = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Collect two refund policy sources.",
                "domains": ["grounding.example.test"],
                "fetch_budget": 1,
                "desired_source_count": 2,
            },
            _tool_context(runtime, runtime_root),
        )
    )
    assert len(unmet_count["evidence"]) == 1
    assert unmet_count["stop_reason"] == "partial_result"

    freshness_limited = asyncio.run(
        runtime.kernel.tool_registry.get("web_research").execute(
            {
                "objective": "Collect fresh refund policy evidence.",
                "domains": ["grounding.example.test"],
                "freshness_days": 7,
                "fetch_budget": 1,
                "desired_source_count": 1,
            },
            _tool_context(runtime, runtime_root),
        )
    )
    assert len(freshness_limited["evidence"]) == 1
    assert freshness_limited["stop_reason"] == "freshness_unsupported"
    assert any(
        event == {"event": "freshness_unsupported", "requested_days": 7, "status": "unsupported"}
        for event in freshness_limited["trace_summary"]
    )


def test_web_fetch_validation_rejects_missing_url() -> None:
    outcome = validate_web_fetch(
        {"source": {"title": "missing url"}},
        ToolContext(session_id="coding-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd()),
    )

    assert outcome.valid is False
    assert outcome.message == "url is required"


def test_web_find_validation_rejects_page_without_url() -> None:
    outcome = validate_web_find(
        {"page": {"content": "text"}, "pattern": "needle", "domains": ["docs.example.test"]},
        ToolContext(session_id="coding-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd()),
    )

    assert outcome.valid is False
    assert outcome.message == "url is required"


def test_devtools_web_fetch_validation_rejects_domain_constrained_mismatch() -> None:
    outcome = validate_devtools_web_fetch(
        {"url": "https://example.com", "domains": ["allowed.example.test"]},
        ToolContext(session_id="devtools-validation", turn_id="turn-1", agent_name="tester", cwd=Path.cwd()),
    )

    assert outcome.valid is False
    assert outcome.message == "Grounding fetch is outside the allowed domains"


def test_shared_core_revalidates_final_fetch_url_and_sets_freshness_scope() -> None:
    backend = reference_web_research_core.DuckDuckGoHtmlBackend(
        urlopen=lambda request, *, timeout: _web_urlopen(request, timeout=timeout)
    )
    policy = reference_web_research_core.build_policy({"domains": ["grounding.example.test"], "freshness_days": 7})

    result = reference_web_research_core.search_web("refund policy", backend=backend, policy=policy)
    assert result["freshness_scope"] == {"requested_days": 7, "status": "unsupported"}

    class _RedirectingBackend:
        def search(self, query: str, *, limit: int):
            _ = query, limit
            return []

        def fetch(self, url: str, *, timeout: float, max_bytes: int):
            _ = url, timeout, max_bytes
            return reference_web_research_core.BackendFetchResult(
                url="https://redirected.example.test/out-of-scope",
                status=200,
                content_type="text/html",
                body="<html><title>Out of scope</title></html>",
                raw_bytes=32,
                title="Out of scope",
            )

        def find(self, page: dict[str, Any], pattern: str, *, limit: int, excerpt_chars: int):
            _ = page, pattern, limit, excerpt_chars
            return []

    with pytest.raises(ValueError, match="outside the allowed domains"):
        reference_web_research_core.inspect_page(
            {"url": "https://grounding.example.test/refund-policy"},
            backend=_RedirectingBackend(),
            policy=policy,
        )


def test_shared_core_provider_registry_reports_freshness_and_fallback() -> None:
    fresh_provider = reference_web_research_core.FixtureWebResearchProvider(
        provider_id="fresh-fixture",
        supports_freshness=True,
        search_results={
            "refund policy": [
                {"title": "Refund policy", "url": "https://grounding.example.test/refund-policy"},
                {"title": "Outside", "url": "https://outside.example.test/refund-policy"},
            ]
        },
    )
    legacy_provider = reference_web_research_core.FixtureWebResearchProvider(
        provider_id="legacy-fixture",
        supports_freshness=False,
        search_results={
            "refund policy": [
                {"title": "Refund policy", "url": "https://grounding.example.test/refund-policy"}
            ]
        },
    )
    policy = reference_web_research_core.build_policy(
        {"domains": ["grounding.example.test"], "freshness_days": 7, "limit": 3}
    )

    enforced = reference_web_research_core.search_web(
        "refund policy",
        registry=reference_web_research_core.WebSearchProviderRegistry((fresh_provider, legacy_provider)),
        policy=policy,
    )

    assert enforced["provider"]["id"] == "fresh-fixture"
    assert enforced["freshness_scope"] == {"requested_days": 7, "status": "enforced"}
    assert enforced["constraint_outcomes"]["allowed_domains"]["status"] == "enforced"
    assert [item["url"] for item in enforced["results"]] == ["https://grounding.example.test/refund-policy"]
    assert enforced["results"][0]["metadata"]["provider"]["id"] == "fresh-fixture"

    failing_fresh_provider = reference_web_research_core.FixtureWebResearchProvider(
        provider_id="fresh-fixture",
        supports_freshness=True,
        fail_search=True,
    )
    fallback = reference_web_research_core.search_web(
        "refund policy",
        registry=reference_web_research_core.WebSearchProviderRegistry((failing_fresh_provider, legacy_provider)),
        policy=policy,
    )

    assert fallback["provider"]["id"] == "legacy-fixture"
    assert fallback["provider_selection"]["status"] == "fallback"
    assert fallback["provider_fallback"]["used"] is True
    assert fallback["provider_fallback"]["from"] == "fresh-fixture"
    assert fallback["freshness_scope"] == {"requested_days": 7, "status": "unsupported"}


def test_brave_provider_maps_freshness_and_domain_filters() -> None:
    requested_urls: list[str] = []
    requested_tokens: list[str | None] = []

    def _brave_urlopen(request, timeout=10, **_kwargs):
        _ = timeout
        requested_urls.append(request.full_url)
        requested_tokens.append(request.get_header("X-subscription-token") or request.get_header("X-Subscription-Token"))
        return _FakeUrlopenResponse(
            (
                '{"web":{"results":['
                '{"title":"Fresh docs","url":"https://docs.example.test/current","description":"Fresh result"}'
                "]}}"
            ),
            content_type="application/json",
        )

    provider = reference_web_research_core.BraveSearchApiProvider(api_key="test-token", urlopen=_brave_urlopen)
    policy = reference_web_research_core.build_policy(
        {
            "domains": ["docs.example.test"],
            "blocked_domains": ["old.example.test"],
            "freshness_days": 7,
            "limit": 2,
        }
    )

    result = reference_web_research_core.search_web(
        "api reference",
        registry=reference_web_research_core.WebSearchProviderRegistry((provider,)),
        policy=policy,
    )

    parsed = urllib.parse.urlparse(requested_urls[0])
    query_params = urllib.parse.parse_qs(parsed.query)
    assert requested_tokens == ["test-token"]
    assert query_params["freshness"] == ["pw"]
    assert "site:docs.example.test" in query_params["q"][0]
    assert "-site:old.example.test" in query_params["q"][0]
    assert result["provider"]["id"] == "brave-search"
    assert result["freshness_scope"] == {"requested_days": 7, "status": "enforced"}


def test_google_provider_maps_query_parameters_and_normalizes_results() -> None:
    requested_urls: list[str] = []

    def _google_urlopen(request, timeout=10, **_kwargs):
        _ = timeout
        requested_urls.append(request.full_url)
        return _FakeUrlopenResponse(
            json.dumps(
                {
                    "items": [
                        {
                            "title": "Fresh docs",
                            "link": "https://docs.example.test/current",
                            "snippet": "Fresh Google result",
                            "displayLink": "docs.example.test",
                            "formattedUrl": "https://docs.example.test/current",
                        },
                        {
                            "title": "Outside",
                            "link": "https://outside.example.test/current",
                            "snippet": "Filtered by core",
                        },
                    ]
                }
            ),
            content_type="application/json",
        )

    provider = reference_web_research_core.GoogleSearchApiProvider(
        api_key="google-token",
        cx="search-engine-id",
        urlopen=_google_urlopen,
    )
    policy = reference_web_research_core.build_policy(
        {
            "domains": ["docs.example.test"],
            "blocked_domains": ["old.example.test"],
            "freshness_days": 7,
            "limit": 2,
        }
    )

    result = reference_web_research_core.search_web(
        "api reference",
        provider="google-search",
        registry=reference_web_research_core.WebSearchProviderRegistry((provider,)),
        policy=policy,
    )

    parsed = urllib.parse.urlparse(requested_urls[0])
    query_params = urllib.parse.parse_qs(parsed.query)
    assert query_params["key"] == ["google-token"]
    assert query_params["cx"] == ["search-engine-id"]
    assert query_params["num"] == ["2"]
    assert query_params["dateRestrict"] == ["d7"]
    assert "site:docs.example.test" in query_params["q"][0]
    assert "-site:old.example.test" in query_params["q"][0]
    assert result["provider"]["id"] == "google-search"
    assert result["provider_selection"]["selected"] == "google-search"
    assert result["freshness_scope"] == {"requested_days": 7, "status": "enforced"}
    assert [item["url"] for item in result["results"]] == ["https://docs.example.test/current"]
    assert result["results"][0]["metadata"]["provider_result_metadata"]["displayLink"] == "docs.example.test"


def test_default_registry_includes_configured_google_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "google-token")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "search-engine-id")
    monkeypatch.setenv("WEAVERT_WEB_SEARCH_PROVIDER", "google-search")
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("WEAVERT_BRAVE_SEARCH_API_KEY", raising=False)
    registry = reference_web_research_core.default_web_search_provider_registry()

    assert [provider.provider_metadata.provider_id for provider in registry.providers] == [
        "google-search",
        "duckduckgo-html",
    ]

    class _FailingGoogleProvider:
        provider_metadata = reference_web_research_core.GoogleSearchApiProvider(
            api_key="google-token",
            cx="search-engine-id",
        ).provider_metadata

        def search(self, query: str, *, limit: int, policy=None):
            _ = query, limit, policy
            raise ValueError("google unavailable")

        def fetch(self, url: str, *, timeout: float, max_bytes: int):
            _ = url, timeout, max_bytes
            raise NotImplementedError

        def find(self, page: dict[str, Any], pattern: str, *, limit: int, excerpt_chars: int):
            _ = page, pattern, limit, excerpt_chars
            raise NotImplementedError

    fallback_provider = reference_web_research_core.FixtureWebResearchProvider(
        provider_id="legacy-fixture",
        search_results={"refund policy": [{"title": "Refund policy", "url": "https://grounding.example.test/refund"}]},
    )
    fallback = reference_web_research_core.search_web(
        "refund policy",
        provider="google-search",
        registry=reference_web_research_core.WebSearchProviderRegistry((_FailingGoogleProvider(), fallback_provider)),
        policy=reference_web_research_core.build_policy({"domains": ["grounding.example.test"], "limit": 1}),
    )

    assert fallback["provider"]["id"] == "legacy-fixture"
    assert fallback["provider_selection"]["status"] == "fallback"
    assert fallback["provider_fallback"]["from"] == "google-search"


@pytest.mark.skipif(
    not os.environ.get("WEAVERT_LIVE_WEB_PROVIDER_SMOKE"),
    reason="live web provider smoke validation is opt-in",
)
def test_live_brave_provider_smoke_validation_is_opt_in() -> None:
    if not (os.environ.get("BRAVE_SEARCH_API_KEY") or os.environ.get("WEAVERT_BRAVE_SEARCH_API_KEY")):
        pytest.skip("BRAVE_SEARCH_API_KEY or WEAVERT_BRAVE_SEARCH_API_KEY is required")

    result = reference_web_research_core.search_web(
        "WeaveRT runtime",
        registry=reference_web_research_core.WebSearchProviderRegistry(
            (reference_web_research_core.BraveSearchApiProvider(),)
        ),
        policy=reference_web_research_core.build_policy({"freshness_days": 31, "limit": 2}),
    )

    assert result["provider"]["id"] == "brave-search"
    assert result["freshness_scope"]["status"] == "enforced"
    assert result["results"]


@pytest.mark.skipif(
    not os.environ.get("WEAVERT_LIVE_GOOGLE_SEARCH_SMOKE"),
    reason="live Google provider smoke validation is opt-in",
)
def test_live_google_provider_smoke_validation_is_opt_in() -> None:
    if not (os.environ.get("GOOGLE_SEARCH_API_KEY") and os.environ.get("GOOGLE_SEARCH_CX")):
        pytest.skip("GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX are required")

    result = reference_web_research_core.search_web(
        "WeaveRT runtime",
        registry=reference_web_research_core.WebSearchProviderRegistry(
            (reference_web_research_core.GoogleSearchApiProvider(),)
        ),
        policy=reference_web_research_core.build_policy({"freshness_days": 31, "limit": 2}),
    )

    assert result["provider"]["id"] == "google-search"
    assert result["freshness_scope"]["status"] == "enforced"
    assert result["results"]


def test_shared_core_redirect_handler_rejects_out_of_scope_and_blocked_targets() -> None:
    request = urllib.request.Request("https://grounding.example.test/refund-policy")
    headers = Message()

    outside_handler = reference_web_research_core._SafeWebRedirectHandler(
        allowed_domains=("grounding.example.test",),
    )
    with pytest.raises(urllib.error.HTTPError, match="outside the allowed domains"):
        outside_handler.redirect_request(
            request,
            fp=None,
            code=302,
            msg="Found",
            headers=headers,
            newurl="https://redirected.example.test/out-of-scope",
        )

    blocked_handler = reference_web_research_core._SafeWebRedirectHandler(
        blocked_domains=("redirected.example.test",),
    )
    with pytest.raises(urllib.error.HTTPError, match="blocked for this domain"):
        blocked_handler.redirect_request(
            request,
            fp=None,
            code=302,
            msg="Found",
            headers=headers,
            newurl="https://redirected.example.test/blocked",
        )


def test_grounded_chat_reference_stack_exercises_retrieval_web_and_memory_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reference_web_tool_impls, "_web_urlopen", _web_urlopen)

    runtime, shape, runtime_root = _assemble_reference_runtime(tmp_path, "weavert-scenario-chat")
    assert shape.expected_tools == CHAT_RETRIEVAL_TOOLS + WEB_RESEARCH_TOOLS + ("ask_user",)
    assert set(shape.workflow_agent_ids) == CHAT_SCENARIO_AGENTS
    assert set(shape.workflow_skill_ids) == CHAT_SCENARIO_SKILLS

    search_tool = runtime.kernel.tool_registry.get("web_search")
    search_result = asyncio.run(
        search_tool.execute({"query": "refund policy"}, _tool_context(runtime, runtime_root))
    )
    assert search_result["results"][0]["url"] == "https://grounding.example.test/refund-policy"
    assert search_result["results"][0]["source_handle"].startswith("source::")

    fetch_tool = runtime.kernel.tool_registry.get("web_fetch")
    fetched = asyncio.run(
        fetch_tool.execute(
            {"source": search_result["results"][0]},
            _tool_context(runtime, runtime_root),
        )
    )
    assert "30 days" in fetched["content"]
    assert fetched["source_handle"] == search_result["results"][0]["source_handle"]

    find_tool = runtime.kernel.tool_registry.get("web_find")
    findings = asyncio.run(
        find_tool.execute(
            {"page": fetched, "pattern": "30 days"},
            _tool_context(runtime, runtime_root),
        )
    )
    assert findings["matches"][0]["exact_excerpt"] == "30 days"

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
                        "content": findings["matches"][0]["excerpt"],
                        "excerpt": findings["matches"][0]["excerpt"],
                        "url": fetched["url"],
                        "metadata": {"source_handle": fetched["source_handle"]},
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
        + WEB_RESEARCH_TOOLS
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
            assert request["web_handoff"]["source_handle"] == "source::demo"
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
            {
                "url": "https://assistant.example.test/briefing",
                "web_handoff": {
                    "kind": "web_page",
                    "title": "Briefing",
                    "url": "https://assistant.example.test/briefing",
                    "source_handle": "source::demo",
                    "page_handle": "page::demo",
                    "domain": "assistant.example.test",
                    "approval_owner": "app",
                    "allowlist_owner": "app",
                    "audit_sink_owner": "app",
                },
            },
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
    assert staged["request"]["web_handoff"]["source_handle"] == "source::demo"


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
        "web_research",
        "web_fetch",
        "web_find",
        "web_search",
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


def test_core_scenario_runtime_packs_module_is_removed_after_product_kit_extraction() -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "core"
        / "src"
        / "weavert"
        / "scenario_runtime_packs.py"
    )

    assert source_path.exists() is False


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
