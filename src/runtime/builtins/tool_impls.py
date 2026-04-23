from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..contracts import ExecutionResult, ExecutionStatus
from ..agent_execution import SpawnMode
from ..definitions import (
    AgentDefinition,
    IsolationMode,
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    SkillShell,
    ValidationOutcome,
)
from ..tasking import TaskManager, TaskStatus
from ..task_lists import (
    DefaultTaskListService,
    TaskDisciplinePolicy,
    TaskListError,
    TaskListInvalidRequestError,
    task_list_entry_to_dict,
)
from ..tool_runtime import ToolCallResult, ToolCallStatus, ToolContext

_EPHEMERAL_TASK_LIST_SERVICES: dict[tuple[str, str], DefaultTaskListService] = {}


async def read_file_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
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
    root = _resolve_path(context.cwd, tool_input.get("root", "."), context=context)
    pattern = tool_input["pattern"]
    matches = sorted(
        str(path)
        for path in root.glob(pattern)
        if _path_allowed(path.resolve(), context)
    )
    return {"root": str(root), "pattern": pattern, "matches": matches}


async def grep_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    root = _resolve_path(context.cwd, tool_input.get("path", "."), context=context)
    pattern = re.compile(
        tool_input["pattern"],
        0 if tool_input.get("case_sensitive", False) else re.IGNORECASE,
    )
    results: list[dict[str, Any]] = []
    for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
        if not _path_allowed(file_path.resolve(), context):
            continue
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
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    if not path.exists():
        return ValidationOutcome(False, f"File does not exist: {path}")
    if not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    return ValidationOutcome(True)


def validate_edit_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    if not path.exists() and tool_input["old_string"] != "":
        return ValidationOutcome(False, f"File does not exist: {path}")
    if path.exists() and not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    if tool_input["old_string"] == tool_input["new_string"]:
        return ValidationOutcome(False, "old_string and new_string must differ")
    return ValidationOutcome(True)


def validate_write_tool(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    if path.exists() and not path.is_file():
        return ValidationOutcome(False, f"Path is not a file: {path}")
    return ValidationOutcome(True)


def ask_permission(_: dict[str, Any], __: ToolContext) -> PermissionDecision:
    return PermissionDecision(
        behavior=PermissionBehavior.ASK,
        message="This tool requires explicit permission before execution.",
    )


async def edit_file_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
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
    path = _resolve_path(context.cwd, tool_input["file_path"], context=context)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tool_input["content"], encoding="utf-8")
    return {"file_path": str(path), "bytes_written": len(tool_input["content"].encode("utf-8"))}


def validate_bash_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not tool_input["command"].strip():
        return ValidationOutcome(False, "command must be non-empty")
    shell = _normalize_optional_string(tool_input.get("shell"))
    if shell is not None and shell not in {SkillShell.BASH.value, SkillShell.POWERSHELL.value}:
        return ValidationOutcome(False, f"Unsupported shell: {shell}")
    return ValidationOutcome(True)


async def bash_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    cwd = _resolve_path(context.cwd, tool_input.get("cwd", "."), context=context)
    timeout_ms = tool_input.get("timeout_ms", 30_000)
    shell = _normalize_optional_string(tool_input.get("shell")) or SkillShell.BASH.value
    if shell == SkillShell.POWERSHELL.value:
        process = await asyncio.create_subprocess_exec(
            "pwsh",
            "-NoProfile",
            "-Command",
            tool_input["command"],
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
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
        "shell": shell,
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
        request = urllib.request.Request(tool_input["url"], headers={"User-Agent": "ai-agent-runtime/0.1"})
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
        request = urllib.request.Request(url, headers={"User-Agent": "ai-agent-runtime/0.1"})
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
    registry_outcome = validate_agent_registry_entry(tool_input, context)
    if not registry_outcome.valid:
        return registry_outcome

    normalized = dict(tool_input)
    spawn_mode = _normalize_optional_string(tool_input.get("spawn_mode"))
    if spawn_mode is not None:
        if spawn_mode not in {SpawnMode.SYNC.value, SpawnMode.BACKGROUND.value}:
            return ValidationOutcome(False, f"Invalid spawn_mode: {spawn_mode}")
        normalized["spawn_mode"] = spawn_mode
        normalized["background"] = spawn_mode == SpawnMode.BACKGROUND.value
    else:
        normalized["background"] = bool(tool_input.get("background", False))

    cwd = _normalize_optional_string(tool_input.get("cwd"))
    if cwd is not None:
        try:
            resolved_cwd = _resolve_path(context.cwd, cwd, context=context)
        except ValueError as exc:
            return ValidationOutcome(False, str(exc))
        if not resolved_cwd.exists():
            return ValidationOutcome(False, f"cwd does not exist: {resolved_cwd}")
        if not resolved_cwd.is_dir():
            return ValidationOutcome(False, f"cwd is not a directory: {resolved_cwd}")
        normalized["cwd"] = str(resolved_cwd)

    model = _normalize_optional_string(tool_input.get("model"))
    if model is not None:
        normalized["model"] = model

    model_route = _normalize_optional_string(tool_input.get("model_route"))
    if model_route is not None:
        normalized["model_route"] = model_route

    reason = _normalize_optional_string(tool_input.get("reason"))
    if reason is not None:
        normalized["reason"] = reason

    permission_mode = _normalize_optional_string(tool_input.get("permission_mode"))
    if permission_mode is not None:
        try:
            normalized["permission_mode"] = PermissionMode(permission_mode).value
        except ValueError:
            return ValidationOutcome(False, f"Invalid permission_mode: {permission_mode}")

    isolation = _normalize_optional_string(tool_input.get("isolation"))
    if isolation is not None:
        try:
            normalized["isolation"] = IsolationMode(isolation).value
        except ValueError:
            return ValidationOutcome(False, f"Invalid isolation: {isolation}")

    max_turns = tool_input.get("max_turns")
    if max_turns is not None:
        if not isinstance(max_turns, int) or max_turns < 1:
            return ValidationOutcome(False, "max_turns must be a positive integer")
        normalized["max_turns"] = max_turns

    return ValidationOutcome(True, updated_input=normalized)


async def agent_tool(tool_input: dict[str, Any], context: ToolContext) -> Any:
    if context.agent_runner is None:
        raise ValueError("No agent runner is configured")
    invocation_kwargs: dict[str, Any] = {
        "background": tool_input.get("background", False),
    }
    for key in (
        "spawn_mode",
        "cwd",
        "model",
        "model_route",
        "reason",
        "permission_mode",
        "isolation",
        "max_turns",
    ):
        if key in tool_input and tool_input.get(key) is not None:
            invocation_kwargs[key] = tool_input[key]
    return await context.agent_runner(
        tool_input["agent"],
        tool_input["prompt"],
        context,
        **invocation_kwargs,
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
    service = _task_list_service(context)
    task_list_id = await service.resolve_list_id(
        session_id=context.session_id,
        private_context=context.private_context,
    )
    task = await service.create(
        task_list_id,
        subject=tool_input["subject"],
        description=tool_input.get("description"),
        active_form=tool_input.get("active_form"),
        owner=tool_input.get("owner"),
        blocks=tool_input.get("blocks", ()),
        blocked_by=tool_input.get("blocked_by", ()),
        metadata=tool_input.get("metadata"),
    )
    _record_task_touch(context, task_list_id=task_list_id)
    return {"task_list_id": task_list_id, "task": task_list_entry_to_dict(task)}


async def task_get_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await service.resolve_list_id(
        session_id=context.session_id,
        private_context=context.private_context,
    )
    task = await service.get(task_list_id, tool_input["task_id"])
    if task is None:
        return _structured_error(
            "not_found",
            f"Task '{tool_input['task_id']}' was not found",
            task_list_id=task_list_id,
            task_id=tool_input["task_id"],
        )
    _record_task_touch(context, task_list_id=task_list_id)
    return {"task_list_id": task_list_id, "task": task_list_entry_to_dict(task)}


async def task_update_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await service.resolve_list_id(
        session_id=context.session_id,
        private_context=context.private_context,
    )
    patch = {
        key: tool_input[key]
        for key in ("status", "subject", "description", "active_form", "owner", "blocks", "blocked_by", "metadata")
        if key in tool_input
    }
    if not patch:
        return _structured_error(
            "invalid_request",
            "task_update requires at least one supported mutable field",
            task_list_id=task_list_id,
            task_id=tool_input["task_id"],
        )
    try:
        task = await service.update(
            task_list_id,
            tool_input["task_id"],
            patch=patch,
            strict_single_in_progress=_task_discipline_policy(context).strict_single_in_progress,
        )
    except TaskListError as exc:
        return _task_list_error_result(exc)
    _record_task_touch(context, task_list_id=task_list_id)
    return {"task_list_id": task_list_id, "task": task_list_entry_to_dict(task)}


async def task_list_tool(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    service = _task_list_service(context)
    task_list_id = await service.resolve_list_id(
        session_id=context.session_id,
        private_context=context.private_context,
    )
    tasks = await service.list(task_list_id)
    _record_task_touch(context, task_list_id=task_list_id)
    return {"task_list_id": task_list_id, "tasks": [task_list_entry_to_dict(task) for task in tasks]}


async def job_get_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    manager = _task_manager(context)
    task = manager.get(tool_input["job_id"])
    if task is None or not _job_visible_to_context(task, context):
        return _structured_error("not_found", f"Job '{tool_input['job_id']}' was not found", job_id=tool_input["job_id"])
    return {"job": _job_to_dict(task)}


async def job_list_tool(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    manager = _task_manager(context)
    jobs = [
        _job_to_dict(task)
        for task in manager.list_visible(
            session_id=context.session_id,
            team_id=_context_team_id(context),
        )
    ]
    return {"jobs": jobs}


async def job_stop_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    manager = _task_manager(context)
    task = manager.get(tool_input["job_id"])
    if task is None or not _job_visible_to_context(task, context):
        return _structured_error("not_found", f"Job '{tool_input['job_id']}' was not found", job_id=tool_input["job_id"])
    if task.status != TaskStatus.RUNNING:
        return _structured_error(
            "not_running",
            f"Job '{tool_input['job_id']}' is not currently running",
            job_id=tool_input["job_id"],
            status=task.status.value,
        )
    stopped = await manager.stop_job(tool_input["job_id"])
    return {"job": _job_to_dict(stopped)}


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
    requested_skill = tool_input["skill"]
    if any(skill.name == requested_skill for skill in context.skill_pool):
        return ValidationOutcome(True)
    registry = context.skill_registry
    registry_skill = registry.get(requested_skill) if registry is not None else None
    if context.skill_pool and registry_skill is not None:
        return ValidationOutcome(
            False,
            f"Skill '{requested_skill}' is not available in the current execution policy",
        )
    if context.skill_pool:
        return ValidationOutcome(False, f"Unknown skill: {requested_skill}")
    if registry is None or registry_skill is not None:
        return ValidationOutcome(True)
    return ValidationOutcome(False, f"Unknown skill: {requested_skill}")


def _resolve_path(cwd: Path, file_path: str, *, context: Any | None = None) -> Path:
    path = Path(file_path)
    resolved = path if path.is_absolute() else (cwd / path).resolve()
    if context is not None and not _path_allowed(resolved, context):
        raise ValueError(f"Path is reserved for runtime memory and cannot be accessed directly: {resolved}")
    return resolved


def _normalize_optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _task_manager(context: ToolContext):
    if context.task_manager is None and context.runtime_services is not None:
        context.task_manager = context.runtime_services.task_manager
    if context.task_manager is None:
        context.task_manager = TaskManager()
    return context.task_manager


def _job_to_dict(task: Any) -> dict[str, Any]:
    return {
        "job_id": task.task_id,
        "summary": task.title,
        "description": task.description,
        "status": task.status.value,
        "result": task.result,
        "error": task.error,
        "stop_requested": task.stop_requested,
        "metadata": task.metadata,
    }


def _task_list_service(context: ToolContext) -> DefaultTaskListService:
    if context.runtime_services is not None:
        return context.runtime_services.task_list_service
    key = (context.session_id, str(context.cwd))
    service = _EPHEMERAL_TASK_LIST_SERVICES.get(key)
    if service is None:
        service = DefaultTaskListService()
        _EPHEMERAL_TASK_LIST_SERVICES[key] = service
    return service


def _record_task_touch(context: ToolContext, *, task_list_id: str) -> None:
    runtime_services = context.runtime_services
    if runtime_services is None:
        return
    sidecar = getattr(runtime_services, "task_discipline", None)
    if sidecar is None or not hasattr(sidecar, "record_task_touch"):
        return
    sidecar.record_task_touch(session_id=context.session_id, task_list_id=task_list_id)


def _task_discipline_policy(context: ToolContext) -> TaskDisciplinePolicy:
    runtime_metadata = context.runtime_services.metadata if context.runtime_services is not None else None
    return TaskDisciplinePolicy.resolve(
        private_context=context.private_context,
        runtime_metadata=runtime_metadata,
    )


def _task_list_error_result(exc: TaskListError) -> ExecutionResult[dict[str, Any]]:
    return _structured_error(exc.code, str(exc), **exc.details)


def _structured_error(code: str, message: str, **details: Any) -> ExecutionResult[dict[str, Any]]:
    return ExecutionResult(
        status=ExecutionStatus.FAILED,
        value={"error": {"code": code, "message": message, "details": details}},
        error=message,
        metadata={"category": code, **details},
    )


def _job_visible_to_context(task: Any, context: ToolContext) -> bool:
    task_session_id = str(task.metadata.get("session_id") or "")
    team_id = _context_team_id(context)
    task_team_id = str(task.metadata.get("team_id") or "")
    return (
        (task_session_id != "" and task_session_id == context.session_id)
        or (team_id is not None and task_team_id == team_id)
    )


def _context_team_id(context: ToolContext) -> str | None:
    value = context.private_context.extensions.get("team_id")
    normalized = _normalize_optional_string(value)
    return normalized


def cancelled_result(call_id: str, tool_name: str, message: str) -> ToolCallResult:
    return ToolCallResult(call_id=call_id, tool_name=tool_name, status=ToolCallStatus.CANCELLED, error=message)


def json_output(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True)
from ..elicitation import ElicitationRequest


def _path_allowed(path: Path, context: Any) -> bool:
    if _looks_like_memory_directory(path):
        return False
    for root in _guarded_memory_roots(context):
        if _is_relative_to(path, root):
            return False
    return True


def _guarded_memory_roots(context: Any) -> tuple[Path, ...]:
    file_state = getattr(context, "file_state", None)
    if file_state is not None and getattr(file_state, "guarded_roots", ()):
        return tuple(Path(root).resolve() for root in file_state.guarded_roots)
    runtime_services = getattr(context, "runtime_services", None)
    if runtime_services is None:
        return ()
    memory_service = getattr(runtime_services, "memory", None)
    if memory_service is None or not hasattr(memory_service, "guarded_roots"):
        return ()
    agent = None
    if getattr(context, "agent_registry", None) is not None:
        agent = context.agent_registry.get(context.agent_name)
    if agent is None:
        agent = AgentDefinition(name=context.agent_name, description="", prompt="")
    roots = memory_service.guarded_roots(
        session_id=context.session_id,
        agent=agent,
        cwd=context.cwd,
    )
    return tuple(Path(root).resolve() for root in roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _looks_like_memory_directory(path: Path) -> bool:
    parts = path.resolve().parts
    for index in range(len(parts) - 1):
        if parts[index] == ".runtime" and parts[index + 1] == "memory":
            return True
    return False
