from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from weavert.builtins.definition_helpers import static_semantics
from weavert.builtins.tool_impls import ask_permission
from weavert.contracts import ExecutionResult, ExecutionStatus
from weavert.definitions import (
    DefinitionOrigin,
    DefinitionSource,
    ToolCallStatus,
    ToolClassifierInput,
    ToolDefinition,
    ToolFailureClassifier,
    ToolFailureMode,
    ToolFailurePolicy,
    ToolPresentationEmphasis,
    ToolResultSummary,
    ToolResultSummaryStatus,
    ToolRiskLevel,
    ToolUsePresentation,
    ValidationOutcome,
)
from weavert.jobs import JobStatus
from weavert.tool_runtime import ToolContext

_FULL_CAPTURE_MAX_CHARS = 4_000
_FULL_CAPTURE_MAX_LINES = 200
_PREVIEW_MAX_CHARS = 600
_PREVIEW_MAX_LINES = 12
_DEFAULT_TIMEOUT_MS = 60_000


@dataclass(frozen=True, slots=True)
class ShellClassification:
    name: str
    summary: str
    risk_level: ToolRiskLevel
    read_only: bool
    high_risk: bool = False
    background_required: bool = False


@dataclass(slots=True)
class BackgroundShellHandle:
    job_id: str
    command: str
    cwd: Path
    process: asyncio.subprocess.Process
    monitor_task: asyncio.Task[None]


_BACKGROUND_SHELLS: dict[str, BackgroundShellHandle] = {}


def build_code_assistant_bash_replacement() -> ToolDefinition:
    return ToolDefinition(
        name="bash",
        aliases=("Bash",),
        description=(
            "Run a coding-oriented shell command with structured classification, "
            "workspace safeguards, and optional background job projection."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "shell": {"type": "string", "enum": ["bash", "powershell"]},
                "timeout_ms": {"type": "integer", "minimum": 1},
                "description": {"type": "string"},
                "run_in_background": {"type": "boolean"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "description": {"type": ["string", "null"]},
                "shell": {"type": "string"},
                "cwd": {"type": "string"},
                "workspace_root": {"type": "string"},
                "classification": {"type": "string"},
                "risk_level": {"type": "string"},
                "risk_summary": {"type": "string"},
                "high_risk": {"type": "boolean"},
                "status": {"type": "string"},
                "run_in_background": {"type": "boolean"},
                "background_reason": {"type": ["string", "null"]},
                "job_id": {"type": ["string", "null"]},
                "exit_code": {"type": ["integer", "null"]},
                "timed_out": {"type": "boolean"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "stdout_preview": {"type": "string"},
                "stderr_preview": {"type": "string"},
                "stdout_truncated": {"type": "boolean"},
                "stderr_truncated": {"type": "boolean"},
                "output_summary": {"type": "string"},
            },
            "required": [
                "command",
                "description",
                "shell",
                "cwd",
                "workspace_root",
                "classification",
                "risk_level",
                "risk_summary",
                "high_risk",
                "status",
                "run_in_background",
                "background_reason",
                "job_id",
                "exit_code",
                "timed_out",
                "stdout",
                "stderr",
                "stdout_preview",
                "stderr_preview",
                "stdout_truncated",
                "stderr_truncated",
                "output_summary",
            ],
            "additionalProperties": False,
        },
        semantics=static_semantics(
            read_only=False,
            concurrency_safe=False,
            failure_policy=ToolFailurePolicy(
                failure_mode=ToolFailureMode.FATAL,
                result_classifier=ToolFailureClassifier.NONZERO_EXIT_OR_EXCEPTION,
                cancel_running_siblings=True,
                block_queued_siblings=True,
                abort_model_stream=True,
                surfaced_status=ToolCallStatus.ERROR,
            ),
            tool_use_presentation=_tool_use_presentation,
            tool_result_summary=_tool_result_summary,
            classifier_input=_classifier_input,
        ),
        validate_input=validate_code_assistant_bash_tool,
        check_permissions=ask_permission,
        execute=code_assistant_bash_tool,
        runtime_execution_class="privileged",
        origin=DefinitionOrigin(DefinitionSource.BUNDLED),
    )


def reconcile_background_shell_jobs(job_service: Any) -> None:
    if job_service is None or not hasattr(job_service, "list_sync"):
        return
    for record in job_service.list_sync():
        if record.status is not JobStatus.RUNNING:
            continue
        if str(record.metadata.get("kind") or "") != "background_shell":
            continue
        if record.job_id in _BACKGROUND_SHELLS:
            continue
        job_service.update_compat(
            record.job_id,
            status=JobStatus.FAILED,
            error="Background shell job could not be resumed after runtime restart.",
            metadata={"reconciled": True},
        )


def validate_code_assistant_bash_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    command = str(tool_input.get("command") or "").strip()
    if not command:
        return ValidationOutcome(False, "command must be non-empty")
    shell = _normalize_optional_string(tool_input.get("shell"))
    if shell is not None and shell not in {"bash", "powershell"}:
        return ValidationOutcome(False, f"Unsupported shell: {shell}")
    timeout_ms = tool_input.get("timeout_ms")
    if timeout_ms is not None and (not isinstance(timeout_ms, int) or timeout_ms < 1):
        return ValidationOutcome(False, "timeout_ms must be a positive integer")
    description = tool_input.get("description")
    if description is not None and not isinstance(description, str):
        return ValidationOutcome(False, "description must be a string")
    run_in_background = tool_input.get("run_in_background")
    if run_in_background is not None and not isinstance(run_in_background, bool):
        return ValidationOutcome(False, "run_in_background must be a boolean")
    return ValidationOutcome(True)


async def code_assistant_bash_tool(tool_input: dict[str, Any], context: ToolContext) -> Any:
    command = str(tool_input["command"]).strip()
    classification = _classify_command(command)
    workspace_root = _workspace_root_for(context)
    description = _normalize_optional_string(tool_input.get("description"))
    shell = _normalize_optional_string(tool_input.get("shell")) or "bash"
    timeout_ms = tool_input.get("timeout_ms", _DEFAULT_TIMEOUT_MS)
    try:
        cwd = _resolve_shell_cwd(context, tool_input.get("cwd"))
    except ValueError as exc:
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            value=_shell_result_payload(
                command=command,
                description=description,
                shell=shell,
                cwd=str(workspace_root),
                workspace_root=str(workspace_root),
                classification=classification,
                status="blocked",
                background_reason=None,
                job_id=None,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                timed_out=False,
            ),
            error=str(exc),
        )

    blocked_reason = _blocked_command_reason(command, workspace_root=workspace_root, cwd=cwd)
    if blocked_reason is not None:
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            value=_shell_result_payload(
                command=command,
                description=description,
                shell=shell,
                cwd=str(cwd),
                workspace_root=str(workspace_root),
                classification=classification,
                status="blocked",
                background_reason=None,
                job_id=None,
                exit_code=None,
                stdout="",
                stderr=blocked_reason,
                timed_out=False,
            ),
            error=blocked_reason,
        )

    background_reason: str | None = None
    if bool(tool_input.get("run_in_background")):
        background_reason = "requested"
    elif classification.background_required:
        background_reason = "required_for_long_running_command"

    if background_reason is not None:
        return await _start_background_shell(
            command=command,
            description=description,
            shell=shell,
            cwd=cwd,
            workspace_root=workspace_root,
            classification=classification,
            context=context,
            background_reason=background_reason,
        )

    try:
        stdout, stderr, exit_code = await _run_foreground_shell(
            command=command,
            shell=shell,
            cwd=cwd,
            timeout_ms=timeout_ms,
        )
    except TimeoutError as exc:
        error_text = str(exc)
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            value=_shell_result_payload(
                command=command,
                description=description,
                shell=shell,
                cwd=str(cwd),
                workspace_root=str(workspace_root),
                classification=classification,
                status="failed",
                background_reason=None,
                job_id=None,
                exit_code=None,
                stdout="",
                stderr=error_text,
                timed_out=True,
            ),
            error=error_text,
        )

    payload = _shell_result_payload(
        command=command,
        description=description,
        shell=shell,
        cwd=str(cwd),
        workspace_root=str(workspace_root),
        classification=classification,
        status="completed" if exit_code == 0 else "failed",
        background_reason=None,
        job_id=None,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
    )
    if exit_code == 0:
        return payload
    return ExecutionResult(
        status=ExecutionStatus.FAILED,
        value=payload,
        error=payload["output_summary"],
    )


def _tool_use_presentation(tool_input: dict[str, Any], _context: ToolContext) -> ToolUsePresentation:
    command = str(tool_input.get("command") or "").strip()
    classification = _classify_command(command)
    description = _normalize_optional_string(tool_input.get("description"))
    return ToolUsePresentation(
        title="Run shell command",
        subtitle=description or command,
        emphasis=(
            ToolPresentationEmphasis.HIGH
            if classification.high_risk
            else ToolPresentationEmphasis.NORMAL
        ),
    )


def _tool_result_summary(tool_input: dict[str, Any], _context: ToolContext) -> ToolResultSummary:
    command = str(tool_input.get("command") or "").strip()
    classification = _classify_command(command)
    return ToolResultSummary(
        title="Shell command",
        summary=f"{classification.summary}: {command}",
        status=ToolResultSummaryStatus.SUCCESS,
    )


def _classifier_input(tool_input: dict[str, Any], context: ToolContext) -> ToolClassifierInput:
    command = str(tool_input.get("command") or "").strip()
    classification = _classify_command(command)
    cwd = _normalize_optional_string(tool_input.get("cwd"))
    if cwd is None:
        target_paths = (str(_workspace_root_for(context)),)
    else:
        target_paths = (cwd,)
    return ToolClassifierInput(
        operation="bash",
        summary=f"{classification.summary}: {command}",
        target_paths=target_paths,
        risk_level=classification.risk_level,
        side_effects=not classification.read_only,
        tags=("shell", classification.name),
    )


async def _start_background_shell(
    *,
    command: str,
    description: str | None,
    shell: str,
    cwd: Path,
    workspace_root: Path,
    classification: ShellClassification,
    context: ToolContext,
    background_reason: str,
) -> Any:
    job_service = _job_service_for(context)
    if job_service is None:
        error_text = "Background shell execution requires a runtime job service."
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            value=_shell_result_payload(
                command=command,
                description=description,
                shell=shell,
                cwd=str(cwd),
                workspace_root=str(workspace_root),
                classification=classification,
                status="failed",
                background_reason=background_reason,
                job_id=None,
                exit_code=None,
                stdout="",
                stderr=error_text,
                timed_out=False,
            ),
            error=error_text,
        )

    process = await _spawn_process(command=command, shell=shell, cwd=cwd)
    job_id = f"shell-{uuid4().hex[:10]}"
    metadata = {
        "kind": "background_shell",
        "executor_kind": "bash",
        "session_id": context.session_id,
        "submitted_by": context.agent_name,
        "run_id": _run_id_for(context),
        "turn_id": context.turn_id,
        "command": command,
        "cwd": str(cwd),
        "workspace_root": str(workspace_root),
        "classification": classification.name,
        "background_reason": background_reason,
        "shell": shell,
        "description": description,
        "pid": process.pid,
    }
    summary = description or f"{classification.summary}: {command}"
    job_service.create_or_update_compat(job_id, summary, description=description, metadata=metadata)

    async def _stop_job(_: Any) -> None:
        await _terminate_background_shell(job_id)

    job_service.register_compat_stop_handler(job_id, _stop_job)
    job_service.update_compat(job_id, status=JobStatus.RUNNING)
    monitor_task = asyncio.create_task(
        _monitor_background_shell(
            job_id=job_id,
            command=command,
            description=description,
            shell=shell,
            cwd=cwd,
            workspace_root=workspace_root,
            classification=classification,
            context=context,
            process=process,
        )
    )
    _BACKGROUND_SHELLS[job_id] = BackgroundShellHandle(
        job_id=job_id,
        command=command,
        cwd=cwd,
        process=process,
        monitor_task=monitor_task,
    )

    return _shell_result_payload(
        command=command,
        description=description,
        shell=shell,
        cwd=str(cwd),
        workspace_root=str(workspace_root),
        classification=classification,
        status="running",
        background_reason=background_reason,
        job_id=job_id,
        exit_code=None,
        stdout="",
        stderr="",
        timed_out=False,
    )


async def _monitor_background_shell(
    *,
    job_id: str,
    command: str,
    description: str | None,
    shell: str,
    cwd: Path,
    workspace_root: Path,
    classification: ShellClassification,
    context: ToolContext,
    process: asyncio.subprocess.Process,
) -> None:
    job_service = _job_service_for(context)
    if job_service is None:
        return
    stdout_bytes, stderr_bytes = await process.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    record = job_service.get_sync(job_id)
    if record is None or record.status.terminal:
        job_service.unregister_compat_stop_handler(job_id)
        _BACKGROUND_SHELLS.pop(job_id, None)
        return
    status = JobStatus.STOPPED if record.stop_requested else (
        JobStatus.COMPLETED if process.returncode == 0 else JobStatus.FAILED
    )
    payload = _shell_result_payload(
        command=command,
        description=description,
        shell=shell,
        cwd=str(cwd),
        workspace_root=str(workspace_root),
        classification=classification,
        status="completed" if status is JobStatus.COMPLETED else (
            "stopped" if status is JobStatus.STOPPED else "failed"
        ),
        background_reason=str(record.metadata.get("background_reason") or "requested"),
        job_id=job_id,
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
    )
    job_service.update_compat(
        job_id,
        status=status,
        result=payload,
        error=None if status in {JobStatus.COMPLETED, JobStatus.STOPPED} else payload["output_summary"],
    )
    job_service.unregister_compat_stop_handler(job_id)
    _BACKGROUND_SHELLS.pop(job_id, None)


async def _terminate_background_shell(job_id: str) -> None:
    handle = _BACKGROUND_SHELLS.get(job_id)
    if handle is None:
        return
    if handle.process.returncode is None:
        handle.process.terminate()
    await handle.monitor_task


async def _run_foreground_shell(
    *,
    command: str,
    shell: str,
    cwd: Path,
    timeout_ms: int,
) -> tuple[str, str, int]:
    process = await _spawn_process(command=command, shell=shell, cwd=cwd)
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_ms / 1000,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise TimeoutError(f"Command timed out after {timeout_ms}ms.") from exc
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    return stdout, stderr, int(process.returncode or 0)


async def _spawn_process(
    *,
    command: str,
    shell: str,
    cwd: Path,
) -> asyncio.subprocess.Process:
    if shell == "powershell":
        return await asyncio.create_subprocess_exec(
            "pwsh",
            "-NoProfile",
            "-Command",
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    return await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def _resolve_shell_cwd(context: ToolContext, raw_cwd: Any) -> Path:
    workspace_root = _workspace_root_for(context)
    value = _normalize_optional_string(raw_cwd)
    resolved = workspace_root if value is None else Path(value).expanduser()
    if not resolved.is_absolute():
        resolved = (workspace_root / resolved).resolve()
    else:
        resolved = resolved.resolve()
    if not resolved.exists():
        raise ValueError(f"cwd does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"cwd is not a directory: {resolved}")
    if resolved != workspace_root and workspace_root not in resolved.parents:
        raise ValueError(f"cwd must stay inside the workspace: {resolved}")
    return resolved


def _blocked_command_reason(command: str, *, workspace_root: Path, cwd: Path) -> str | None:
    lowered = command.lower()
    blocked_patterns = {
        "git reset --hard": "Blocked destructive command: git reset --hard",
        "git clean -fd": "Blocked destructive command: git clean -fd",
        "git clean -xdf": "Blocked destructive command: git clean -xdf",
        "rm -rf /": "Blocked destructive command: rm -rf /",
        "rm -rf ~": "Blocked destructive command: rm -rf ~",
        "sudo ": "Blocked privileged command: sudo",
    }
    for pattern, message in blocked_patterns.items():
        if pattern in lowered:
            return message
    if cwd != workspace_root and workspace_root not in cwd.parents:
        return f"Blocked shell command outside the workspace: {cwd}"
    return None


def _classify_command(command: str) -> ShellClassification:
    lowered = command.lower().strip()
    tokens = _command_tokens(command)
    first = tokens[0].lower() if tokens else ""
    second = tokens[1].lower() if len(tokens) > 1 else ""
    third = tokens[2].lower() if len(tokens) > 2 else ""

    if any(pattern in lowered for pattern in ("git reset --hard", "git clean -fd", "git clean -xdf", "rm -rf /", "sudo ")):
        return ShellClassification(
            name="destructive",
            summary="Blocked destructive shell operation",
            risk_level=ToolRiskLevel.WRITE,
            read_only=False,
            high_risk=True,
        )
    if first == "git" and second in {"status", "diff", "show", "log", "branch"}:
        return ShellClassification("git-read", "Inspect git state", ToolRiskLevel.READ, True)
    if first == "git" and second in {"add", "commit", "checkout", "restore", "reset", "rebase", "merge", "push", "pull"}:
        return ShellClassification("git-write", "Mutate git state", ToolRiskLevel.WRITE, False, high_risk=True)
    if first in {"rg", "grep", "ag", "fd", "findstr"}:
        return ShellClassification("search", "Search the workspace", ToolRiskLevel.READ, True)
    if first in {"cat", "head", "tail", "less"} or (first == "sed" and "-i" not in tokens):
        return ShellClassification("read", "Read file content", ToolRiskLevel.READ, True)
    if first in {"ls", "find", "tree", "pwd"}:
        return ShellClassification("list", "List workspace paths", ToolRiskLevel.READ, True)
    if first in {"pytest", "tox", "nox"}:
        return ShellClassification("test", "Run verification tests", ToolRiskLevel.EXEC, False)
    if first.startswith("python") and second == "-m" and third == "unittest":
        return ShellClassification("test", "Run verification tests", ToolRiskLevel.EXEC, False)
    if first in {"npm", "pnpm", "yarn"} and (
        second == "test" or (second == "run" and third == "test")
    ):
        return ShellClassification("test", "Run verification tests", ToolRiskLevel.EXEC, False)
    if first in {"npm", "pnpm", "yarn"} and (
        second == "build" or (second == "run" and third == "build")
    ):
        return ShellClassification("build", "Build project artifacts", ToolRiskLevel.EXEC, False)
    if first in {"make", "cargo", "go"} and second in {"build", "check"}:
        return ShellClassification("build", "Build project artifacts", ToolRiskLevel.EXEC, False)
    if first in {"npm", "pnpm", "yarn"} and (
        second in {"dev", "start"} or (second == "run" and third in {"dev", "start", "serve", "watch"})
    ):
        return ShellClassification(
            "dev-server",
            "Start a long-running dev server",
            ToolRiskLevel.EXEC,
            False,
            background_required=True,
        )
    if first in {"uvicorn", "gunicorn"} or (
        first.startswith("python") and second == "-m" and third == "http.server"
    ):
        return ShellClassification(
            "dev-server",
            "Start a long-running dev server",
            ToolRiskLevel.EXEC,
            False,
            background_required=True,
        )
    if first in {"mkdir", "touch", "mv", "cp", "rm", "chmod"} or any(
        marker in lowered for marker in (" > ", " >> ", "| tee ", "sed -i")
    ):
        return ShellClassification("write", "Modify workspace files", ToolRiskLevel.WRITE, False, high_risk=True)
    return ShellClassification("other", "Run a shell command", ToolRiskLevel.EXEC, False)


def _shell_result_payload(
    *,
    command: str,
    description: str | None,
    shell: str,
    cwd: str,
    workspace_root: str,
    classification: ShellClassification,
    status: str,
    background_reason: str | None,
    job_id: str | None,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    timed_out: bool,
) -> dict[str, Any]:
    stdout_full, stdout_truncated = _truncate_text(stdout, _FULL_CAPTURE_MAX_CHARS, _FULL_CAPTURE_MAX_LINES)
    stderr_full, stderr_truncated = _truncate_text(stderr, _FULL_CAPTURE_MAX_CHARS, _FULL_CAPTURE_MAX_LINES)
    stdout_preview, _ = _truncate_text(stdout, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
    stderr_preview, _ = _truncate_text(stderr, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
    if not stdout_preview and stderr_preview:
        stdout_preview = stderr_preview
    return {
        "command": command,
        "description": description,
        "shell": shell,
        "cwd": cwd,
        "workspace_root": workspace_root,
        "classification": classification.name,
        "risk_level": classification.risk_level.value,
        "risk_summary": classification.summary,
        "high_risk": classification.high_risk,
        "status": status,
        "run_in_background": background_reason is not None,
        "background_reason": background_reason,
        "job_id": job_id,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": stdout_full,
        "stderr": stderr_full,
        "stdout_preview": stdout_preview,
        "stderr_preview": stderr_preview,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "output_summary": _output_summary(
            command=command,
            classification=classification,
            status=status,
            exit_code=exit_code,
            background_reason=background_reason,
            job_id=job_id,
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            timed_out=timed_out,
        ),
    }


def _output_summary(
    *,
    command: str,
    classification: ShellClassification,
    status: str,
    exit_code: int | None,
    background_reason: str | None,
    job_id: str | None,
    stdout_preview: str,
    stderr_preview: str,
    timed_out: bool,
) -> str:
    if status == "running" and job_id is not None:
        return f"{classification.summary} in background as job {job_id} ({background_reason or 'requested'})."
    if status == "blocked":
        return stderr_preview or f"Blocked command: {command}"
    if timed_out:
        return stderr_preview or f"{classification.summary} timed out."
    if status == "stopped":
        return f"{classification.summary} stopped."
    if status == "failed":
        detail = _first_non_empty_line(stderr_preview) or _first_non_empty_line(stdout_preview)
        suffix = f" (exit {exit_code})" if exit_code is not None else ""
        return detail or f"{classification.summary} failed{suffix}."
    detail = _first_non_empty_line(stdout_preview) or _first_non_empty_line(stderr_preview)
    return detail or f"{classification.summary} completed successfully."


def _truncate_text(text: str, max_chars: int, max_lines: int) -> tuple[str, bool]:
    if not text:
        return "", False
    lines = text.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    clipped = "\n".join(lines)
    if len(clipped) > max_chars:
        clipped = clipped[:max_chars].rstrip()
        truncated = True
    return clipped, truncated


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _job_service_for(context: ToolContext) -> Any | None:
    runtime_services = _runtime_services_for(context)
    if runtime_services is not None:
        return runtime_services.job_service
    task_manager = getattr(context, "task_manager", None)
    if task_manager is not None:
        return task_manager.job_service
    return None


def _runtime_services_for(context: Any) -> Any | None:
    runtime_services = getattr(context, "runtime_services", None)
    if runtime_services is not None:
        return runtime_services
    internal_context = getattr(context, "internal_context", None)
    if internal_context is not None:
        runtime_services = getattr(internal_context, "runtime_services", None)
        if runtime_services is not None:
            return runtime_services
    capability_context = getattr(context, "capability_context", None)
    if capability_context is not None:
        runtime_services = getattr(capability_context, "runtime_services", None)
        if runtime_services is not None:
            return runtime_services
        internal_context = getattr(capability_context, "internal_context", None)
        if internal_context is not None:
            return getattr(internal_context, "runtime_services", None)
    return None


def _workspace_root_for(context: Any) -> Path:
    return Path(context.cwd).resolve()


def _run_id_for(context: Any) -> str | None:
    private_context = getattr(context, "private_context", None)
    if private_context is not None:
        run_id = getattr(private_context, "run_id", None)
        if run_id:
            return str(run_id)
    private_context_view = getattr(context, "private_context_view", None)
    if private_context_view is not None:
        run_id = getattr(private_context_view, "run_id", None)
        if run_id:
            return str(run_id)
    return None


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _normalize_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "build_code_assistant_bash_replacement",
    "reconcile_background_shell_jobs",
]
