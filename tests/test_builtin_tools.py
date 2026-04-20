import asyncio
from pathlib import Path

from runtime.builtins.tools import builtin_tools
from runtime.definitions import (
    AgentDefinition,
    PermissionBehavior,
    PermissionDecision,
    SkillDefinition,
)
from runtime.registries import AgentRegistry, SkillRegistry, ToolRegistry
from runtime.tasking import TaskManager
from runtime.tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler


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
    for definition in builtin_tools():
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
    assert results[4].output["matches"][0]["line"] == "delta"


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

    monkeypatch.setattr("runtime.builtins.tool_impls.urllib.request.urlopen", fake_urlopen)

    results = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "bash", {"command": "printf hi"}),
                ToolCall("2", "web_fetch", {"url": "https://example.com/resource"}),
                ToolCall("3", "web_search", {"query": "example"}),
                ToolCall("4", "agent", {"agent": "verification", "prompt": "run checks", "background": True}),
                ToolCall("5", "skill", {"skill": "verify", "arguments": ["src/app.py"]}),
                ToolCall("6", "task_create", {"task_id": "t1", "title": "test task"}),
                ToolCall("7", "task_update", {"task_id": "t1", "status": "running"}),
                ToolCall("8", "task_get", {"task_id": "t1"}),
                ToolCall("9", "task_list", {}),
                ToolCall("10", "task_stop", {"task_id": "t1"}),
                ToolCall("11", "ask_user", {"question": "continue?", "options": ["yes", "no"]}),
                ToolCall("12", "sleep", {"seconds": 0.01}),
            ],
            context,
        )
    )

    assert all(result.status == ToolCallStatus.SUCCESS for result in results)
    assert results[0].output["stdout"] == "hi"
    assert results[1].output["content"] == "fetch body"
    assert results[2].output["results"][0]["title"] == "Example Result"
    assert results[3].output["background"] is True
    assert results[4].output["arguments"] == ["src/app.py"]
    assert results[7].output["status"] == "running"
    assert results[8].output["tasks"][0]["task_id"] == "t1"
    assert results[9].output["status"] == "stopped"
    assert results[10].output["response"] == "yes"
    assert results[11].output["slept_seconds"] == 0.01
