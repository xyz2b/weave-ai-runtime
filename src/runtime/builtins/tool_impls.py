from __future__ import annotations

import asyncio
import json
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
    ValidationOutcome,
)
from ..jobs import JobControlError, JobScopeFilter, job_record_to_payload
from ..tasking import TaskManager, TaskStatus
from ..task_lists import (
    DefaultTaskListService,
    TaskDisciplinePolicy,
    TaskListError,
    task_list_entry_to_dict,
    task_list_snapshot_to_dict,
)
from ..elicitation import ElicitationRequest
from ..tool_runtime import ToolCallResult, ToolCallStatus, ToolContext

_EPHEMERAL_TASK_LIST_SERVICES: dict[tuple[str, str], DefaultTaskListService] = {}


def ask_permission(_: dict[str, Any], __: ToolContext) -> PermissionDecision:
    return PermissionDecision(
        behavior=PermissionBehavior.ASK,
        message="This tool requires explicit permission before execution.",
    )


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
    task_list_id = await _resolved_task_list_id(service, context)
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
    return {
        "task_list_id": task_list_id,
        "task": await _task_payload(service, task_list_id=task_list_id, task_id=task.task_id),
    }


async def task_get_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    task = await service.get_orchestration_task(task_list_id, tool_input["task_id"], include_archived=True)
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
    task_list_id = await _resolved_task_list_id(service, context)
    patch = {key: value for key, value in tool_input.items() if key != "task_id"}
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
    return {
        "task_list_id": task_list_id,
        "task": await _task_payload(service, task_list_id=task_list_id, task_id=task.task_id),
    }


async def task_archive_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    try:
        task = await service.archive(
            task_list_id,
            tool_input["task_id"],
            archived_by=context.agent_name,
        )
    except TaskListError as exc:
        return _task_list_error_result(exc)
    _record_task_touch(context, task_list_id=task_list_id)
    return {
        "task_list_id": task_list_id,
        "task": await _task_payload(service, task_list_id=task_list_id, task_id=task.task_id),
    }


async def task_unarchive_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    try:
        task = await service.unarchive(
            task_list_id,
            tool_input["task_id"],
        )
    except TaskListError as exc:
        return _task_list_error_result(exc)
    _record_task_touch(context, task_list_id=task_list_id)
    return {
        "task_list_id": task_list_id,
        "task": await _task_payload(service, task_list_id=task_list_id, task_id=task.task_id),
    }


async def task_delete_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    task = await service.get_orchestration_task(task_list_id, tool_input["task_id"], include_archived=True)
    if task is None:
        return _structured_error(
            "not_found",
            f"Task '{tool_input['task_id']}' was not found",
            task_list_id=task_list_id,
            task_id=tool_input["task_id"],
        )
    try:
        await service.delete(task_list_id, tool_input["task_id"])
    except TaskListError as exc:
        return _task_list_error_result(exc)
    _record_task_touch(context, task_list_id=task_list_id)
    return {"task_list_id": task_list_id, "task": task_list_entry_to_dict(task)}


async def task_claim_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    owner = _default_task_owner(context, tool_input.get("owner"))
    try:
        task = await service.claim(
            task_list_id,
            tool_input["task_id"],
            owner,
            set_in_progress=tool_input.get("set_in_progress", True),
            enforce_owner_busy=tool_input.get("enforce_owner_busy", False),
            strict_single_in_progress=_task_discipline_policy(context).strict_single_in_progress,
        )
    except TaskListError as exc:
        return _task_list_error_result(exc)
    _record_task_touch(context, task_list_id=task_list_id)
    return {
        "task_list_id": task_list_id,
        "task": await _task_payload(service, task_list_id=task_list_id, task_id=task.task_id),
    }


async def task_release_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    try:
        task = await service.release(
            task_list_id,
            tool_input["task_id"],
        )
    except TaskListError as exc:
        return _task_list_error_result(exc)
    _record_task_touch(context, task_list_id=task_list_id)
    return {
        "task_list_id": task_list_id,
        "task": await _task_payload(service, task_list_id=task_list_id, task_id=task.task_id),
    }


async def task_assign_next_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    owner = _default_task_owner(context, tool_input.get("owner"))
    try:
        task = await service.assign_next(
            task_list_id,
            owner,
            set_in_progress=tool_input.get("set_in_progress", True),
            enforce_owner_busy=tool_input.get("enforce_owner_busy", False),
            strict_single_in_progress=_task_discipline_policy(context).strict_single_in_progress,
        )
    except TaskListError as exc:
        return _task_list_error_result(exc)
    _record_task_touch(context, task_list_id=task_list_id)
    return {
        "task_list_id": task_list_id,
        "task": (
            await _task_payload(service, task_list_id=task_list_id, task_id=task.task_id)
            if task is not None
            else None
        ),
    }


async def task_block_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    try:
        blocker_task, blocked_task = await service.add_dependency(
            task_list_id,
            tool_input["blocker_task_id"],
            tool_input["blocked_task_id"],
        )
    except TaskListError as exc:
        return _task_list_error_result(exc)
    _record_task_touch(context, task_list_id=task_list_id)
    return {
        "task_list_id": task_list_id,
        "blocker_task": await _task_payload(
            service,
            task_list_id=task_list_id,
            task_id=blocker_task.task_id,
        ),
        "blocked_task": await _task_payload(
            service,
            task_list_id=task_list_id,
            task_id=blocked_task.task_id,
        ),
    }


async def task_unblock_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    try:
        blocker_task, blocked_task = await service.remove_dependency(
            task_list_id,
            tool_input["blocker_task_id"],
            tool_input["blocked_task_id"],
        )
    except TaskListError as exc:
        return _task_list_error_result(exc)
    _record_task_touch(context, task_list_id=task_list_id)
    return {
        "task_list_id": task_list_id,
        "blocker_task": await _task_payload(
            service,
            task_list_id=task_list_id,
            task_id=blocker_task.task_id,
        ),
        "blocked_task": await _task_payload(
            service,
            task_list_id=task_list_id,
            task_id=blocked_task.task_id,
        ),
    }


async def task_list_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    service = _task_list_service(context)
    task_list_id = await _resolved_task_list_id(service, context)
    tasks = await service.get_orchestration_snapshot(
        task_list_id,
        include_archived=tool_input.get("include_archived", False),
    )
    _record_task_touch(context, task_list_id=task_list_id)
    payload = task_list_snapshot_to_dict(tasks)
    payload["task_list_id"] = task_list_id
    return payload


async def job_get_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    service = _job_service(context)
    job = await service.get(
        tool_input["job_id"],
        scope=JobScopeFilter(
            session_id=context.session_id,
            team_id=_context_team_id(context),
        ),
    )
    if job is None:
        return _structured_error("not_found", f"Job '{tool_input['job_id']}' was not found", job_id=tool_input["job_id"])
    return {"job": _job_to_dict(job)}


async def job_list_tool(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    jobs = [
        _job_to_dict(job)
        for job in await _job_service(context).list(
            scope=JobScopeFilter(
                session_id=context.session_id,
                team_id=_context_team_id(context),
            )
        )
    ]
    return {"jobs": jobs}


async def job_stop_tool(
    tool_input: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any] | ExecutionResult[dict[str, Any]]:
    try:
        stopped = await _job_service(context).stop(
            tool_input["job_id"],
            scope=JobScopeFilter(
                session_id=context.session_id,
                team_id=_context_team_id(context),
            ),
        )
    except JobControlError as exc:
        return _structured_error(exc.code, str(exc), **exc.details)
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


def _job_service(context: ToolContext):
    if context.runtime_services is not None:
        return context.runtime_services.job_service
    if context.task_manager is None:
        context.task_manager = TaskManager()
    return context.task_manager.job_service


def _job_to_dict(task: Any) -> dict[str, Any]:
    if hasattr(task, "job_id"):
        return job_record_to_payload(task)
    return {
        "job_id": task.task_id,
        "executor_kind": str(task.metadata.get("executor_kind") or task.metadata.get("kind") or "legacy"),
        "summary": task.title,
        "description": task.description,
        "status": task.status.value,
        "control": {
            "stoppable": bool(task.metadata.get("stoppable", False)),
            "stop_requested": task.stop_requested,
        },
        "timestamps": {
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "started_at": None,
            "ended_at": task.updated_at.isoformat()
            if task.status.value in {"completed", "failed", "stopped"}
            else None,
        },
        "visibility": {
            "session_id": task.metadata.get("session_id"),
            "team_id": task.metadata.get("team_id"),
            "submitted_by": task.metadata.get("submitted_by"),
            "projection_kind": task.metadata.get("projection_kind") or task.metadata.get("kind"),
        },
        "linkage": {
            "parent_run_id": task.metadata.get("run_id"),
            "parent_turn_id": task.metadata.get("turn_id"),
        },
        "result": task.result,
        "error": task.error,
        "metadata": task.metadata,
        "sidecars": [],
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


async def _resolved_task_list_id(
    service: DefaultTaskListService,
    context: ToolContext,
) -> str:
    return await service.resolve_list_id(
        session_id=context.session_id,
        private_context=context.private_context,
    )


async def _task_payload(
    service: DefaultTaskListService,
    *,
    task_list_id: str,
    task_id: str,
) -> dict[str, Any]:
    task = await service.get_orchestration_task(task_list_id, task_id, include_archived=True)
    if task is None:
        raise ValueError(f"Task '{task_id}' was not found in task list '{task_list_id}'")
    return task_list_entry_to_dict(task)


def _default_task_owner(context: ToolContext, explicit_owner: Any) -> str:
    owner = _normalize_optional_string(explicit_owner)
    return owner or context.agent_name


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
    resolver = getattr(runtime_services, "resolve_memory_service", None)
    memory_service = resolver() if callable(resolver) else getattr(runtime_services, "memory", None)
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
