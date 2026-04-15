from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..definitions import PermissionBehavior, PermissionDecision, ValidationOutcome
from ..tasking import TaskManager, TaskStatus
from ..tool_runtime import ToolCallResult, ToolCallStatus, ToolContext


async def read_file_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    path = _resolve_path(context.cwd, tool_input["file_path"])
    offset = tool_input.get("offset", 0)
    limit = tool_input.get("limit")
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    selected = lines[offset : offset + limit if limit is not None else None]
    return {
        "file_path": str(path),
        "content": "\n".join(selected),
        "start_line": offset + 1 if lines else 0,
        "line_count": len(selected),
    }


async def glob_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    root = _resolve_path(context.cwd, tool_input.get("root", "."))
    pattern = tool_input["pattern"]
    matches = sorted(str(path) for path in root.glob(pattern))
    return {"root": str(root), "pattern": pattern, "matches": matches}


async def grep_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    root = _resolve_path(context.cwd, tool_input.get("path", "."))
    pattern = re.compile(
        tool_input["pattern"],
        0 if tool_input.get("case_sensitive", False) else re.IGNORECASE,
    )
    results: list[dict[str, Any]] = []
    for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
        try:
            for line_number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line):
                    results.append(
                        {
                            "file_path": str(file_path),
                            "line_number": line_number,
                            "line": line,
                        }
                    )
        except UnicodeDecodeError:
            continue
    return {"pattern": tool_input["pattern"], "matches": results}


def validate_read_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    path = _resolve_path(context.cwd, tool_input["file_path"])
    if not path.exists():
        return ValidationOutcome(False, f"File does not exist: {path}")
    if not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    return ValidationOutcome(True)


def validate_edit_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    path = _resolve_path(context.cwd, tool_input["file_path"])
    if not path.exists() and tool_input["old_string"] != "":
        return ValidationOutcome(False, f"File does not exist: {path}")
    if path.exists() and not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    if tool_input["old_string"] == tool_input["new_string"]:
        return ValidationOutcome(False, "old_string and new_string must differ")
    return ValidationOutcome(True)


def validate_write_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    path = _resolve_path(context.cwd, tool_input["file_path"])
    if path.exists() and not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    return ValidationOutcome(True)


def ask_permission(_: dict[str, Any], __: ToolContext) -> PermissionDecision:
    return PermissionDecision(
        behavior=PermissionBehavior.ASK,
        message="This tool requires explicit permission before execution.",
    )


async def edit_file_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    path = _resolve_path(context.cwd, tool_input["file_path"])
    old_string = tool_input["old_string"]
    new_string = tool_input["new_string"]
    replace_all = tool_input.get("replace_all", False)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    if old_string not in original and old_string != "":
        raise ValueError("old_string not found in file")
    updated = (
        original.replace(old_string, new_string)
        if replace_all
        else original.replace(old_string, new_string, 1)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return {"file_path": str(path), "updated": True}


async def write_file_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    path = _resolve_path(context.cwd, tool_input["file_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tool_input["content"], encoding="utf-8")
    return {"file_path": str(path), "bytes_written": len(tool_input["content"].encode("utf-8"))}


def validate_bash_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not tool_input["command"].strip():
        return ValidationOutcome(False, "command must be non-empty")
    return ValidationOutcome(True)


async def bash_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    cwd = _resolve_path(context.cwd, tool_input.get("cwd", "."))
    timeout_ms = tool_input.get("timeout_ms", 30_000)
    process = await asyncio.create_subprocess_shell(
        tool_input["command"],
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_ms / 1000)
    except asyncio.TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        raise ValueError("Command timed out")
    except asyncio.CancelledError:
        process.kill()
        await process.communicate()
        raise
    return {
        "command": tool_input["command"],
        "exit_code": process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }


def validate_url_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    url = tool_input["url"]
    if not url.startswith(("http://", "https://")):
        return ValidationOutcome(False, "Only http:// and https:// URLs are supported")
    return ValidationOutcome(True)


async def web_fetch_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    timeout = tool_input.get("timeout_ms", 10_000) / 1000

    def fetch() -> dict[str, Any]:
        request = urllib.request.Request(tool_input["url"], headers={"User-Agent": "claude-agent-runtime/0.1"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "url": tool_input["url"],
                "status": response.status,
                "content_type": response.headers.get_content_type(),
                "content": body,
            }

    return await asyncio.to_thread(fetch)


def validate_web_search(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not tool_input["query"].strip():
        return ValidationOutcome(False, "query must be non-empty")
    return ValidationOutcome(True)


async def web_search_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    encoded = urllib.parse.urlencode({"q": tool_input["query"]})
    url = f"https://duckduckgo.com/html/?{encoded}"

    def search() -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "claude-agent-runtime/0.1"})
        with urllib.request.urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", errors="replace")
        results = []
        for match in re.finditer(
            r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            html,
        ):
            title = re.sub(r"<[^>]+>", "", match.group("title"))
            results.append({"title": title, "url": match.group("href")})
            if len(results) >= tool_input.get("limit", 5):
                break
        return {"query": tool_input["query"], "results": results}

    return await asyncio.to_thread(search)


def validate_agent_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    if context.tool_registry is None:
        return ValidationOutcome(True)
    return ValidationOutcome(True)


async def agent_tool(tool_input: dict[str, Any], context: ToolContext) -> Any:
    if context.agent_runner is None:
        raise ValueError("No agent runner is configured")
    return await context.agent_runner(
        tool_input["agent"],
        tool_input["prompt"],
        context,
        background=tool_input.get("background", False),
    )


async def skill_tool(tool_input: dict[str, Any], context: ToolContext) -> Any:
    if context.skill_runner is None:
        raise ValueError("No skill runner is configured")
    return await context.skill_runner(
        tool_input["skill"],
        tool_input.get("arguments", []),
        context,
    )


async def task_create_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    manager = _task_manager(context)
    task = manager.create(
        task_id=tool_input["task_id"],
        title=tool_input["title"],
        description=tool_input.get("description"),
        metadata=tool_input.get("metadata"),
    )
    return _task_to_dict(task)


async def task_get_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    manager = _task_manager(context)
    task = manager.get(tool_input["task_id"])
    if task is None:
        raise ValueError("Task not found")
    return _task_to_dict(task)


async def task_update_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    manager = _task_manager(context)
    task = manager.update(
        tool_input["task_id"],
        status=TaskStatus(tool_input["status"]) if tool_input.get("status") else None,
        result=tool_input.get("result"),
        error=tool_input.get("error"),
        metadata=tool_input.get("metadata"),
    )
    return _task_to_dict(task)


async def task_list_tool(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    manager = _task_manager(context)
    return {"tasks": [_task_to_dict(task) for task in manager.list()]}


async def task_stop_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    manager = _task_manager(context)
    task = manager.stop(tool_input["task_id"])
    return _task_to_dict(task)


async def ask_user_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if context.runtime_services is not None:
        response = await context.runtime_services.elicitation.request(
            ElicitationRequest(
                session_id=context.session_id,
                turn_id=context.turn_id,
                prompt=tool_input["question"],
                options=tuple(tool_input.get("options", ())),
                metadata={"tool": "ask_user"},
            ),
            runtime_context=context,
        )
        return {"question": tool_input["question"], "response": response.response}
    handler = context.ask_user_handler
    if handler is None:
        raise ValueError("No ask_user handler is configured")
    response = await handler(tool_input["question"], tool_input.get("options"))
    return {"question": tool_input["question"], "response": response}


def validate_sleep_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    seconds = float(tool_input["seconds"])
    if seconds < 0 or seconds > 300:
        return ValidationOutcome(False, "seconds must be between 0 and 300")
    return ValidationOutcome(True)


async def sleep_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    seconds = float(tool_input["seconds"])
    await context.emit_progress("sleep", f"Sleeping for {seconds} seconds")
    await asyncio.sleep(seconds)
    return {"slept_seconds": seconds}


def validate_agent_registry_entry(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    registry = context.agent_registry
    if registry is None or registry.get(tool_input["agent"]) is not None:
        return ValidationOutcome(True)
    return ValidationOutcome(False, f"Unknown agent: {tool_input['agent']}")


def validate_skill_registry_entry(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    registry = context.skill_registry
    if registry is None or registry.get(tool_input["skill"]) is not None:
        return ValidationOutcome(True)
    return ValidationOutcome(False, f"Unknown skill: {tool_input['skill']}")


def _resolve_path(cwd: Path, file_path: str) -> Path:
    path = Path(file_path)
    return path if path.is_absolute() else (cwd / path).resolve()


def _task_manager(context: ToolContext):
    if context.task_manager is None and context.runtime_services is not None:
        context.task_manager = context.runtime_services.task_manager
    if context.task_manager is None:
        context.task_manager = TaskManager()
    return context.task_manager


def _task_to_dict(task: Any) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "result": task.result,
        "error": task.error,
        "stop_requested": task.stop_requested,
        "metadata": task.metadata,
    }


def cancelled_result(call_id: str, tool_name: str, message: str) -> ToolCallResult:
    return ToolCallResult(call_id=call_id, tool_name=tool_name, status=ToolCallStatus.CANCELLED, error=message)


def json_output(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True)
from ..elicitation import ElicitationRequest
