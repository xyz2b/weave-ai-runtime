import asyncio
import os
from pathlib import Path

import pytest

from weavert.builtins import load_builtin_pack
from weavert.definitions import (
    AgentDefinition,
    PermissionBehavior,
    PermissionDecision,
    SkillDefinition,
)
from weavert_devtools.tool_impls import _GLOB_TOOL_MAX_MATCHES
from weavert.registries import AgentRegistry, SkillRegistry, ToolRegistry
from weavert.runtime_services import RuntimeServices
from weavert.tasking import TaskManager, TaskStatus
from weavert.tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler


class FakeHeaders:
    def get_content_type(self) -> str:
        return "text/html"


class FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self.status = status
        self.headers = FakeHeaders()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _build_runtime(tmp_path: Path) -> tuple[ToolRegistry, ToolScheduler, ToolContext]:
    tool_registry = ToolRegistry()
    for definition in load_builtin_pack(("weavert-core", "weavert-devtools")).tools:
        tool_registry.register(definition)

    agent_registry = AgentRegistry()
    skill_registry = SkillRegistry()
    task_manager = TaskManager()

    async def permission_handler(*args, **kwargs) -> PermissionDecision:
        _ = args, kwargs
        return PermissionDecision(PermissionBehavior.ALLOW)

    async def ask_user_handler(question: str, options: list[str] | None = None) -> str:
        _ = question, options
        return "yes"

    async def agent_runner(agent: str, prompt: str, context: ToolContext, *, background: bool = False) -> dict[str, object]:
        _ = context
        return {"agent": agent, "prompt": prompt, "background": background}

    async def skill_runner(skill: str, arguments: list[str], context: ToolContext) -> dict[str, object]:
        _ = context
        return {"skill": skill, "arguments": arguments}

    context = ToolContext(
        session_id="session",
        turn_id="turn",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        task_manager=task_manager,
        permission_handler=permission_handler,
        ask_user_handler=ask_user_handler,
        agent_runner=agent_runner,
        skill_runner=skill_runner,
    )
    return tool_registry, ToolScheduler(tool_registry), context


def test_builtin_file_tools(tmp_path: Path) -> None:
    _, scheduler, context = _build_runtime(tmp_path)

    results = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "write", {"file_path": "notes.txt", "content": "alpha\nbeta\ngamma\n"}),
                ToolCall("2", "read", {"file_path": "notes.txt", "offset": 1, "limit": 1}),
                ToolCall(
                    "3",
                    "edit",
                    {
                        "file_path": "notes.txt",
                        "old_string": "beta",
                        "new_string": "delta",
                    },
                ),
                ToolCall("4", "glob", {"pattern": "*.txt"}),
                ToolCall("5", "grep", {"pattern": "delta", "path": "."}),
            ],
            context,
        )
    )

    assert all(result.status == ToolCallStatus.SUCCESS for result in results)
    assert results[1].output["content"] == "beta"
    assert results[3].output["matches"] == [str((tmp_path / "notes.txt").resolve())]
    assert results[3].output["total_matches"] == 1
    assert results[3].output["returned_matches"] == 1
    assert results[3].output["truncated"] is False
    assert results[4].output["matches"][0]["line"] == "delta"


def test_builtin_glob_tool_truncates_large_match_sets(tmp_path: Path) -> None:
    _, scheduler, context = _build_runtime(tmp_path)
    for index in range(_GLOB_TOOL_MAX_MATCHES + 5):
        (tmp_path / f"file-{index:03}.txt").write_text("payload", encoding="utf-8")

    result = asyncio.run(
        scheduler.run([ToolCall("1", "glob", {"pattern": "**/*"})], context)
    )[0]

    assert result.status == ToolCallStatus.SUCCESS
    assert result.output["truncated"] is True
    assert result.output["total_matches"] == _GLOB_TOOL_MAX_MATCHES + 5
    assert result.output["returned_matches"] == _GLOB_TOOL_MAX_MATCHES
    assert len(result.output["matches"]) == _GLOB_TOOL_MAX_MATCHES
    assert str((tmp_path / "file-000.txt").resolve()) in result.output["matches"]
    assert str((tmp_path / f"file-{_GLOB_TOOL_MAX_MATCHES + 4:03}.txt").resolve()) not in result.output["matches"]


def test_builtin_glob_tool_keeps_workspace_symlink_paths(tmp_path: Path, tmp_path_factory) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are unavailable on this platform")

    _, scheduler, context = _build_runtime(tmp_path)
    external_root = tmp_path_factory.mktemp("glob-symlink-target")
    (external_root / "external.txt").write_text("payload", encoding="utf-8")
    symlink_path = tmp_path / "external-link.txt"
    try:
        symlink_path.symlink_to(external_root / "external.txt")
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    result = asyncio.run(
        scheduler.run([ToolCall("1", "glob", {"pattern": "**/*"})], context)
    )[0]

    assert result.status == ToolCallStatus.SUCCESS
    assert str(symlink_path.resolve()) not in result.output["matches"]
    assert str(symlink_path) in result.output["matches"]


def test_builtin_external_orchestration_and_task_tools(tmp_path: Path, monkeypatch) -> None:
    _, scheduler, context = _build_runtime(tmp_path)
    context.agent_registry.register(
        AgentDefinition(name="verification", description="verify", prompt="verify")
    )
    context.skill_registry.register(
        SkillDefinition(name="verify", description="verify", content="verify")
    )

    def fake_urlopen(request, timeout=10):
        url = request.full_url if hasattr(request, "full_url") else request
        if "duckduckgo.com" in url:
            return FakeResponse(
                '<a class="result__a" href="https://example.com/result">Example Result</a>'
            )
        return FakeResponse("fetch body")

    monkeypatch.setattr("weavert.builtins.tool_impls.urllib.request.urlopen", fake_urlopen)
    context.task_manager.create(
        "job-1",
        title="background-check",
        metadata={"session_id": context.session_id, "kind": "background_agent"},
    )
    context.task_manager.register_stop_handler(
        "job-1",
        lambda task: context.task_manager.update(task.task_id, status=TaskStatus.STOPPED),
    )
    context.task_manager.update("job-1", status=TaskStatus.RUNNING)

    primary = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "bash", {"command": "printf hi"}),
                ToolCall("2", "web_fetch", {"url": "https://example.com/resource"}),
                ToolCall("3", "web_search", {"query": "example"}),
                ToolCall("4", "agent", {"agent": "verification", "prompt": "run checks", "background": True}),
                ToolCall("5", "skill", {"skill": "verify", "arguments": ["src/app.py"]}),
                ToolCall("6", "task_create", {"subject": "test task"}),
                ToolCall("7", "job_get", {"job_id": "job-1"}),
                ToolCall("8", "job_list", {}),
                ToolCall("9", "job_stop", {"job_id": "job-1"}),
                ToolCall("10", "ask_user", {"question": "continue?", "options": ["yes", "no"]}),
                ToolCall("11", "sleep", {"seconds": 0.01}),
            ],
            context,
        )
    )

    created_task_id = primary[5].output["task"]["task_id"]
    follow_up = asyncio.run(
        scheduler.run(
            [
                ToolCall("12", "task_update", {"task_id": created_task_id, "status": "in_progress"}),
                ToolCall("13", "task_get", {"task_id": created_task_id}),
                ToolCall("14", "task_list", {}),
            ],
            context,
        )
    )

    assert all(result.status == ToolCallStatus.SUCCESS for result in primary)
    assert all(result.status == ToolCallStatus.SUCCESS for result in follow_up)
    assert primary[0].output["stdout"] == "hi"
    assert primary[1].output["content"] == "fetch body"
    assert primary[2].output["results"][0]["title"] == "Example Result"
    assert primary[3].output["background"] is True
    assert primary[4].output["arguments"] == ["src/app.py"]
    assert primary[5].output["task"]["subject"] == "test task"
    assert primary[6].output["job"]["job_id"] == "job-1"
    assert primary[7].output["jobs"][0]["job_id"] == "job-1"
    assert primary[8].output["job"]["status"] == "stopped"
    assert primary[9].output["response"] == "yes"
    assert primary[10].output["slept_seconds"] == 0.01
    assert follow_up[0].output["task"]["status"] == "in_progress"
    assert follow_up[1].output["task"]["task_id"] == created_task_id
    assert follow_up[2].output["tasks"][0]["task_id"] == created_task_id


def test_builtin_job_tools_use_job_service_without_materializing_task_manager(tmp_path: Path) -> None:
    tool_registry = ToolRegistry()
    for definition in load_builtin_pack(("weavert-core",)).tools:
        tool_registry.register(definition)
    services = RuntimeServices()
    services.job_service.create_or_update_compat(
        "job-1",
        "background-check",
        metadata={"session_id": "session"},
    )
    context = ToolContext(
        session_id="session",
        turn_id="turn",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=tool_registry,
        runtime_services=services,
    )
    scheduler = ToolScheduler(tool_registry)

    results = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "job_list", {}),
                ToolCall("2", "job_get", {"job_id": "job-1"}),
            ],
            context,
        )
    )

    assert all(result.status == ToolCallStatus.SUCCESS for result in results)
    assert results[0].output["jobs"][0]["job_id"] == "job-1"
    assert results[1].output["job"]["job_id"] == "job-1"
    assert services.tasks.manager is None
