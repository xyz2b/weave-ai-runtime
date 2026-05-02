from __future__ import annotations

import asyncio
import shlex
import signal
from dataclasses import dataclass, field
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
_SESSION_OUTPUT_MAX_CHARS = 12_000
_SESSION_OUTPUT_MAX_CHUNKS = 256


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


@dataclass(frozen=True, slots=True)
class ShellOutputChunk:
    sequence: int
    stream: str
    text: str


@dataclass(slots=True)
class ShellSessionHandle:
    shell_session_id: str
    job_id: str
    command: str
    description: str | None
    shell: str
    cwd: Path
    workspace_root: Path
    classification: ShellClassification
    process: asyncio.subprocess.Process
    job_service: Any
    reader_tasks: list[asyncio.Task[None]] = field(default_factory=list)
    wait_task: asyncio.Task[None] | None = None
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    output_chunks: list[ShellOutputChunk] = field(default_factory=list)
    next_sequence: int = 1
    status: str = "running"
    stop_requested: bool = False
    interrupt_requested: bool = False


_SHELL_SESSIONS: dict[str, ShellSessionHandle] = {}


def build_code_assistant_bash_replacement() -> ToolDefinition:
    return ToolDefinition(
        name="bash",
        aliases=("Bash",),
        description=(
            "Run a coding-oriented shell command through a backward-compatible "
            "one-shot path or a longer-lived shell session with shared job visibility."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["exec", "start", "send", "read", "interrupt", "stop"],
                },
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "shell": {"type": "string", "enum": ["bash", "powershell"]},
                "timeout_ms": {"type": "integer", "minimum": 1},
                "description": {"type": "string"},
                "run_in_background": {"type": "boolean"},
                "shell_session_id": {"type": "string"},
                "stdin": {"type": "string"},
                "after_sequence": {"type": "integer", "minimum": 0},
                "max_output_chars": {"type": "integer", "minimum": 1},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
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
                "shell_session_id": {"type": ["string", "null"]},
                "session_mode": {"type": "string"},
                "session_status": {"type": ["string", "null"]},
                "session_output": {"type": "string"},
                "session_output_sequence": {"type": "integer"},
                "session_output_complete": {"type": "boolean"},
                "unsupported_shell": {"type": "boolean"},
                "unsupported_reason": {"type": ["string", "null"]},
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
                "action",
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
                "shell_session_id",
                "session_mode",
                "session_status",
                "session_output",
                "session_output_sequence",
                "session_output_complete",
                "unsupported_shell",
                "unsupported_reason",
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
        kind = str(record.metadata.get("kind") or "")
        if kind not in {"background_shell", "shell_session"}:
            continue
        if kind == "background_shell" and record.job_id in _BACKGROUND_SHELLS:
            continue
        shell_session_id = str(record.metadata.get("shell_session_id") or "").strip()
        if kind == "shell_session" and shell_session_id in _SHELL_SESSIONS:
            continue
        error_text = (
            "Interactive shell session could not be resumed after runtime restart."
            if kind == "shell_session"
            else "Background shell job could not be resumed after runtime restart."
        )
        job_service.update_compat(
            record.job_id,
            status=JobStatus.FAILED,
            error=error_text,
            metadata={
                "reconciled": True,
                "session_status": "failed" if kind == "shell_session" else None,
            },
        )


def validate_code_assistant_bash_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    action = _normalize_optional_string(tool_input.get("action")) or "exec"
    if action not in {"exec", "start", "send", "read", "interrupt", "stop"}:
        return ValidationOutcome(False, f"Unsupported action: {action}")
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
    shell_session_id = _normalize_optional_string(tool_input.get("shell_session_id"))
    if action in {"send", "read", "interrupt", "stop"} and shell_session_id is None:
        return ValidationOutcome(False, "shell_session_id is required for session actions")
    if action in {"exec", "start"}:
        command = str(tool_input.get("command") or "").strip()
        if not command:
            return ValidationOutcome(False, "command must be non-empty")
    elif "command" in tool_input and not isinstance(tool_input.get("command"), str):
        return ValidationOutcome(False, "command must be a string when provided")
    stdin = tool_input.get("stdin")
    if stdin is not None and not isinstance(stdin, str):
        return ValidationOutcome(False, "stdin must be a string")
    if action == "send" and not str(tool_input.get("stdin") or ""):
        return ValidationOutcome(False, "stdin must be non-empty for send")
    after_sequence = tool_input.get("after_sequence")
    if after_sequence is not None and (not isinstance(after_sequence, int) or after_sequence < 0):
        return ValidationOutcome(False, "after_sequence must be a non-negative integer")
    max_output_chars = tool_input.get("max_output_chars")
    if max_output_chars is not None and (not isinstance(max_output_chars, int) or max_output_chars < 1):
        return ValidationOutcome(False, "max_output_chars must be a positive integer")
    return ValidationOutcome(True)


async def code_assistant_bash_tool(tool_input: dict[str, Any], context: ToolContext) -> Any:
    action = _normalize_optional_string(tool_input.get("action")) or "exec"
    workspace_root = _workspace_root_for(context)
    description = _normalize_optional_string(tool_input.get("description"))
    shell = _normalize_optional_string(tool_input.get("shell")) or "bash"
    timeout_ms = tool_input.get("timeout_ms", _DEFAULT_TIMEOUT_MS)
    if action in {"send", "read", "interrupt", "stop"}:
        return await _handle_shell_session_action(
            action=action,
            shell_session_id=str(tool_input.get("shell_session_id") or "").strip(),
            shell=shell,
            description=description,
            context=context,
            stdin=str(tool_input.get("stdin") or ""),
            after_sequence=int(tool_input.get("after_sequence") or 0),
            max_output_chars=int(tool_input.get("max_output_chars") or _FULL_CAPTURE_MAX_CHARS),
        )

    command = str(tool_input.get("command") or "").strip()
    classification = _classify_command(command)
    try:
        cwd = _resolve_shell_cwd(context, tool_input.get("cwd"))
    except ValueError as exc:
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            value=_shell_result_payload(
                action=action,
                command=command,
                description=description,
                shell=shell,
                cwd=str(workspace_root),
                workspace_root=str(workspace_root),
                classification=classification,
                status="blocked",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="session" if action == "start" else "oneshot",
                session_status=None,
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
                action=action,
                command=command,
                description=description,
                shell=shell,
                cwd=str(cwd),
                workspace_root=str(workspace_root),
                classification=classification,
                status="blocked",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="session" if action == "start" else "oneshot",
                session_status=None,
                exit_code=None,
                stdout="",
                stderr=blocked_reason,
                timed_out=False,
            ),
            error=blocked_reason,
        )

    unsupported_reason = _unsupported_shell_reason(command)
    if unsupported_reason is not None:
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            value=_shell_result_payload(
                action=action,
                command=command,
                description=description,
                shell=shell,
                cwd=str(cwd),
                workspace_root=str(workspace_root),
                classification=classification,
                status="unsupported",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="session" if action == "start" else "oneshot",
                session_status=None,
                exit_code=None,
                stdout="",
                stderr=unsupported_reason,
                timed_out=False,
                unsupported_shell=True,
                unsupported_reason=unsupported_reason,
            ),
            error=unsupported_reason,
        )

    if action == "start":
        return await _start_shell_session(
            command=command,
            description=description,
            shell=shell,
            cwd=cwd,
            workspace_root=workspace_root,
            classification=classification,
            context=context,
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
                action=action,
                command=command,
                description=description,
                shell=shell,
                cwd=str(cwd),
                workspace_root=str(workspace_root),
                classification=classification,
                status="failed",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="oneshot",
                session_status=None,
                exit_code=None,
                stdout="",
                stderr=error_text,
                timed_out=True,
            ),
            error=error_text,
        )

    payload = _shell_result_payload(
        action=action,
        command=command,
        description=description,
        shell=shell,
        cwd=str(cwd),
        workspace_root=str(workspace_root),
        classification=classification,
        status="completed" if exit_code == 0 else "failed",
        background_reason=None,
        job_id=None,
        shell_session_id=None,
        session_mode="oneshot",
        session_status=None,
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
    action = _normalize_optional_string(tool_input.get("action")) or "exec"
    command = str(tool_input.get("command") or "").strip()
    description = _normalize_optional_string(tool_input.get("description"))
    shell_session_id = _normalize_optional_string(tool_input.get("shell_session_id"))
    classification = _classify_command(command)
    if action != "exec":
        subtitle = description or shell_session_id or command or action
        return ToolUsePresentation(
            title=f"Shell session {action}",
            subtitle=subtitle,
            emphasis=ToolPresentationEmphasis.NORMAL,
        )
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
    action = _normalize_optional_string(tool_input.get("action")) or "exec"
    command = str(tool_input.get("command") or "").strip()
    shell_session_id = _normalize_optional_string(tool_input.get("shell_session_id"))
    classification = _classify_command(command)
    if action != "exec":
        target = shell_session_id or command or "shell session"
        return ToolResultSummary(
            title="Shell session",
            summary=f"{action}: {target}",
            status=ToolResultSummaryStatus.SUCCESS,
        )
    return ToolResultSummary(
        title="Shell command",
        summary=f"{classification.summary}: {command}",
        status=ToolResultSummaryStatus.SUCCESS,
    )


def _classifier_input(tool_input: dict[str, Any], context: ToolContext) -> ToolClassifierInput:
    action = _normalize_optional_string(tool_input.get("action")) or "exec"
    command = str(tool_input.get("command") or "").strip()
    shell_session_id = _normalize_optional_string(tool_input.get("shell_session_id"))
    classification = _classify_command(command)
    cwd = _normalize_optional_string(tool_input.get("cwd"))
    if cwd is None:
        target_paths = (str(_workspace_root_for(context)),)
    else:
        target_paths = (cwd,)
    summary = f"{classification.summary}: {command}"
    tags = ("shell", classification.name)
    side_effects = not classification.read_only
    if action != "exec":
        summary = f"Shell session {action}: {shell_session_id or command or 'session'}"
        tags = ("shell", "session", action)
        side_effects = True
    return ToolClassifierInput(
        operation="bash",
        summary=summary,
        target_paths=target_paths,
        risk_level=classification.risk_level,
        side_effects=side_effects,
        tags=tags,
    )


async def _handle_shell_session_action(
    *,
    action: str,
    shell_session_id: str,
    shell: str,
    description: str | None,
    context: ToolContext,
    stdin: str,
    after_sequence: int,
    max_output_chars: int,
) -> Any:
    handle = _SHELL_SESSIONS.get(shell_session_id)
    job_service = _job_service_for(context)
    record = _job_record_for_shell_session(job_service, shell_session_id) if job_service is not None else None
    if handle is None and record is None:
        error_text = f"Unknown shell session: {shell_session_id}"
        payload = _shell_result_payload(
            action=action,
            command="",
            description=description,
            shell=shell,
            cwd=str(_workspace_root_for(context)),
            workspace_root=str(_workspace_root_for(context)),
            classification=_classify_command(""),
            status="failed",
            background_reason=None,
            job_id=None,
            shell_session_id=shell_session_id,
            session_mode="session",
            session_status="failed",
            exit_code=None,
            stdout="",
            stderr=error_text,
            timed_out=False,
        )
        return ExecutionResult(status=ExecutionStatus.FAILED, value=payload, error=error_text)

    if action == "read":
        if handle is not None:
            return _shell_session_payload_from_handle(
                action=action,
                handle=handle,
                after_sequence=after_sequence,
                max_output_chars=max_output_chars,
            )
        if record is not None:
            return _shell_session_payload_from_record(
                action=action,
                record=record,
                after_sequence=after_sequence,
            )

    if handle is None:
        payload = _shell_session_payload_from_record(
            action=action,
            record=record,
            after_sequence=after_sequence,
        )
        error_text = f"Shell session {shell_session_id} is not running."
        return ExecutionResult(status=ExecutionStatus.FAILED, value=payload, error=error_text)

    if action == "send":
        if handle.process.returncode is not None or handle.process.stdin is None:
            payload = _shell_session_payload_from_handle(
                action=action,
                handle=handle,
                after_sequence=after_sequence,
                max_output_chars=max_output_chars,
            )
            error_text = f"Shell session {shell_session_id} is no longer accepting stdin."
            return ExecutionResult(status=ExecutionStatus.FAILED, value=payload, error=error_text)
        try:
            handle.process.stdin.write(stdin.encode("utf-8"))
            await handle.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            payload = _shell_session_payload_from_handle(
                action=action,
                handle=handle,
                after_sequence=after_sequence,
                max_output_chars=max_output_chars,
            )
            return ExecutionResult(status=ExecutionStatus.FAILED, value=payload, error=str(exc))
        return _shell_session_payload_from_handle(
            action=action,
            handle=handle,
            after_sequence=after_sequence,
            max_output_chars=max_output_chars,
        )

    if action == "interrupt":
        if handle.process.returncode is None:
            handle.interrupt_requested = True
            handle.process.send_signal(signal.SIGINT)
        return _shell_session_payload_from_handle(
            action=action,
            handle=handle,
            after_sequence=after_sequence,
            max_output_chars=max_output_chars,
        )

    if action == "stop":
        await _stop_shell_session(shell_session_id)
        handle = _SHELL_SESSIONS.get(shell_session_id)
        if handle is not None:
            return _shell_session_payload_from_handle(
                action=action,
                handle=handle,
                after_sequence=after_sequence,
                max_output_chars=max_output_chars,
            )
        if job_service is not None:
            record = _job_record_for_shell_session(job_service, shell_session_id)
        if record is not None:
            return _shell_session_payload_from_record(
                action=action,
                record=record,
                after_sequence=after_sequence,
            )
    raise RuntimeError(f"Unsupported shell action dispatch: {action}")


async def _start_shell_session(
    *,
    command: str,
    description: str | None,
    shell: str,
    cwd: Path,
    workspace_root: Path,
    classification: ShellClassification,
    context: ToolContext,
) -> Any:
    job_service = _job_service_for(context)
    if job_service is None:
        error_text = "Interactive shell sessions require a runtime job service."
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            value=_shell_result_payload(
                action="start",
                command=command,
                description=description,
                shell=shell,
                cwd=str(cwd),
                workspace_root=str(workspace_root),
                classification=classification,
                status="failed",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="session",
                session_status="failed",
                exit_code=None,
                stdout="",
                stderr=error_text,
                timed_out=False,
            ),
            error=error_text,
        )

    process = await _spawn_process(command=command, shell=shell, cwd=cwd, stdin_pipe=True)
    shell_session_id = f"shell-session-{uuid4().hex[:10]}"
    job_id = f"shell-{uuid4().hex[:10]}"
    metadata = {
        "kind": "shell_session",
        "executor_kind": "bash",
        "shell_resource_kind": "session",
        "shell_session_id": shell_session_id,
        "session_status": "running",
        "session_id": context.session_id,
        "submitted_by": context.agent_name,
        "run_id": _run_id_for(context),
        "turn_id": context.turn_id,
        "command": command,
        "cwd": str(cwd),
        "workspace_root": str(workspace_root),
        "classification": classification.name,
        "shell": shell,
        "description": description,
        "pid": process.pid,
        "output_sequence": 0,
    }
    summary = description or f"{classification.summary}: {command}"
    job_service.create_or_update_compat(job_id, summary, description=description, metadata=metadata)

    handle = ShellSessionHandle(
        shell_session_id=shell_session_id,
        job_id=job_id,
        command=command,
        description=description,
        shell=shell,
        cwd=cwd,
        workspace_root=workspace_root,
        classification=classification,
        process=process,
        job_service=job_service,
    )
    _SHELL_SESSIONS[shell_session_id] = handle

    async def _stop_job(_: Any) -> None:
        await _stop_shell_session(shell_session_id)

    job_service.register_compat_stop_handler(job_id, _stop_job)
    handle.reader_tasks = [
        asyncio.create_task(_capture_shell_stream(handle, process.stdout, stream="stdout")),
        asyncio.create_task(_capture_shell_stream(handle, process.stderr, stream="stderr")),
    ]
    handle.wait_task = asyncio.create_task(_watch_shell_session(handle))
    payload = _shell_session_payload_from_handle(
        action="start",
        handle=handle,
        after_sequence=0,
        max_output_chars=_FULL_CAPTURE_MAX_CHARS,
    )
    job_service.update_compat(
        job_id,
        status=JobStatus.RUNNING,
        result=payload,
        metadata=_shell_session_metadata(handle, recent_output="", recent_stream=None),
    )
    return payload


async def _capture_shell_stream(
    handle: ShellSessionHandle,
    reader: asyncio.StreamReader | None,
    *,
    stream: str,
) -> None:
    if reader is None:
        return
    while True:
        chunk = await reader.read(512)
        if not chunk:
            return
        text = chunk.decode("utf-8", errors="replace")
        if not text:
            continue
        _append_shell_output(handle, stream=stream, text=text)


def _append_shell_output(
    handle: ShellSessionHandle,
    *,
    stream: str,
    text: str,
) -> None:
    if stream == "stdout":
        handle.stdout_buffer = _append_capped_text(handle.stdout_buffer, text)
    else:
        handle.stderr_buffer = _append_capped_text(handle.stderr_buffer, text)
    handle.output_chunks.append(
        ShellOutputChunk(
            sequence=handle.next_sequence,
            stream=stream,
            text=text,
        )
    )
    handle.next_sequence += 1
    if len(handle.output_chunks) > _SESSION_OUTPUT_MAX_CHUNKS:
        handle.output_chunks = handle.output_chunks[-_SESSION_OUTPUT_MAX_CHUNKS:]
    _refresh_shell_session_job(handle, recent_output=text, recent_stream=stream)


def _refresh_shell_session_job(
    handle: ShellSessionHandle,
    *,
    recent_output: str,
    recent_stream: str | None,
) -> None:
    record = handle.job_service.get_sync(handle.job_id)
    if record is None or record.status.terminal:
        return
    payload = _shell_session_payload_from_handle(
        action="read",
        handle=handle,
        after_sequence=max(0, handle.next_sequence - 2),
        max_output_chars=_FULL_CAPTURE_MAX_CHARS,
    )
    handle.job_service.update_compat(
        handle.job_id,
        status=JobStatus.RUNNING,
        result=payload,
        metadata=_shell_session_metadata(
            handle,
            recent_output=recent_output,
            recent_stream=recent_stream,
        ),
    )


async def _watch_shell_session(handle: ShellSessionHandle) -> None:
    try:
        returncode = await handle.process.wait()
        if handle.reader_tasks:
            await asyncio.gather(*handle.reader_tasks, return_exceptions=True)
    finally:
        record = handle.job_service.get_sync(handle.job_id)
        if record is not None and not record.status.terminal:
            session_status = _terminal_session_status(handle, record=record, returncode=handle.process.returncode)
            handle.status = session_status
            payload = _shell_session_payload_from_handle(
                action="start",
                handle=handle,
                after_sequence=max(0, handle.next_sequence - 2),
                max_output_chars=_FULL_CAPTURE_MAX_CHARS,
            )
            terminal_status = {
                "completed": JobStatus.COMPLETED,
                "failed": JobStatus.FAILED,
                "stopped": JobStatus.STOPPED,
            }[session_status]
            handle.job_service.update_compat(
                handle.job_id,
                status=terminal_status,
                result=payload,
                error=None if terminal_status in {JobStatus.COMPLETED, JobStatus.STOPPED} else payload["output_summary"],
                metadata=_shell_session_metadata(handle, recent_output="", recent_stream=None),
            )
        handle.job_service.unregister_compat_stop_handler(handle.job_id)
        _SHELL_SESSIONS.pop(handle.shell_session_id, None)


def _terminal_session_status(
    handle: ShellSessionHandle,
    *,
    record: Any,
    returncode: int | None,
) -> str:
    if record.stop_requested or handle.stop_requested:
        return "stopped"
    if returncode == 0:
        return "completed"
    return "failed"


async def _stop_shell_session(shell_session_id: str) -> None:
    handle = _SHELL_SESSIONS.get(shell_session_id)
    if handle is None:
        return
    handle.stop_requested = True
    if handle.process.returncode is None:
        handle.process.terminate()
    if handle.wait_task is not None:
        await handle.wait_task


def _shell_session_payload_from_handle(
    *,
    action: str,
    handle: ShellSessionHandle,
    after_sequence: int,
    max_output_chars: int,
) -> dict[str, Any]:
    session_output, latest_sequence = _output_since_sequence(
        handle.output_chunks,
        after_sequence=after_sequence,
        max_output_chars=max_output_chars,
    )
    exit_code = handle.process.returncode
    if exit_code is None:
        session_status = handle.status
    else:
        record = handle.job_service.get_sync(handle.job_id)
        session_status = _terminal_session_status(handle, record=record, returncode=exit_code) if record is not None else (
            "completed" if exit_code == 0 else "failed"
        )
    handle.status = session_status
    return _shell_result_payload(
        action=action,
        command=handle.command,
        description=handle.description,
        shell=handle.shell,
        cwd=str(handle.cwd),
        workspace_root=str(handle.workspace_root),
        classification=handle.classification,
        status=session_status,
        background_reason=None,
        job_id=handle.job_id,
        shell_session_id=handle.shell_session_id,
        session_mode="session",
        session_status=session_status,
        exit_code=exit_code,
        stdout=handle.stdout_buffer,
        stderr=handle.stderr_buffer,
        timed_out=False,
        session_output=session_output,
        session_output_sequence=latest_sequence,
        session_output_complete=exit_code is not None,
    )


def _shell_session_payload_from_record(
    *,
    action: str,
    record: Any | None,
    after_sequence: int,
) -> dict[str, Any]:
    payload = dict(record.result) if record is not None and isinstance(record.result, dict) else {}
    metadata = dict(record.metadata) if record is not None and isinstance(record.metadata, dict) else {}
    command = str(payload.get("command") or metadata.get("command") or "")
    shell = str(payload.get("shell") or metadata.get("shell") or "bash")
    cwd = str(payload.get("cwd") or metadata.get("cwd") or "")
    workspace_root = str(payload.get("workspace_root") or metadata.get("workspace_root") or cwd)
    classification = _classification_from_payload(command=command, payload=payload, metadata=metadata)
    session_status = str(payload.get("session_status") or metadata.get("session_status") or _job_status_to_shell_status(record.status.value) if record is not None else "failed")
    session_output = str(payload.get("session_output") or metadata.get("recent_output_preview") or "")
    session_output_sequence = int(payload.get("session_output_sequence") or metadata.get("output_sequence") or 0)
    if action == "read" and session_output_sequence <= after_sequence:
        session_output = ""
    return _shell_result_payload(
        action=action,
        command=command,
        description=_normalize_optional_string(payload.get("description") or metadata.get("description")),
        shell=shell,
        cwd=cwd,
        workspace_root=workspace_root,
        classification=classification,
        status=str(payload.get("status") or session_status),
        background_reason=_normalize_optional_string(payload.get("background_reason")),
        job_id=str(payload.get("job_id") or record.job_id if record is not None else ""),
        shell_session_id=_normalize_optional_string(payload.get("shell_session_id") or metadata.get("shell_session_id")),
        session_mode=str(payload.get("session_mode") or metadata.get("shell_resource_kind") or "session"),
        session_status=session_status,
        exit_code=payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None,
        stdout=str(payload.get("stdout") or ""),
        stderr=str(payload.get("stderr") or ""),
        timed_out=bool(payload.get("timed_out", False)),
        session_output=session_output,
        session_output_sequence=session_output_sequence,
        session_output_complete=bool(
            payload.get("session_output_complete", record.status.terminal if record is not None else True)
        ),
        unsupported_shell=bool(payload.get("unsupported_shell", False)),
        unsupported_reason=_normalize_optional_string(payload.get("unsupported_reason")),
    )


def _shell_session_metadata(
    handle: ShellSessionHandle,
    *,
    recent_output: str,
    recent_stream: str | None,
) -> dict[str, Any]:
    stdout_preview, _ = _truncate_text(handle.stdout_buffer, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
    stderr_preview, _ = _truncate_text(handle.stderr_buffer, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
    recent_output_preview, _ = _truncate_text(recent_output, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
    return {
        "kind": "shell_session",
        "shell_resource_kind": "session",
        "shell_session_id": handle.shell_session_id,
        "session_status": handle.status,
        "output_sequence": handle.next_sequence - 1,
        "recent_output_preview": recent_output_preview,
        "recent_output_stream": recent_stream,
        "stdout_preview": stdout_preview,
        "stderr_preview": stderr_preview,
        "pid": handle.process.pid,
    }


def _job_record_for_shell_session(job_service: Any, shell_session_id: str) -> Any | None:
    if job_service is None or not hasattr(job_service, "list_sync"):
        return None
    for record in job_service.list_sync():
        if str(record.metadata.get("shell_session_id") or "") == shell_session_id:
            return record
    return None


def _output_since_sequence(
    chunks: list[ShellOutputChunk],
    *,
    after_sequence: int,
    max_output_chars: int,
) -> tuple[str, int]:
    relevant = [chunk for chunk in chunks if chunk.sequence > after_sequence]
    text = "".join(chunk.text for chunk in relevant)
    if len(text) > max_output_chars:
        text = text[-max_output_chars:]
    latest_sequence = relevant[-1].sequence if relevant else after_sequence
    return text, latest_sequence


def _append_capped_text(current: str, text: str) -> str:
    combined = current + text
    if len(combined) <= _SESSION_OUTPUT_MAX_CHARS:
        return combined
    return combined[-_SESSION_OUTPUT_MAX_CHARS:]


def _classification_from_payload(
    *,
    command: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> ShellClassification:
    base = _classify_command(command)
    try:
        risk_level = ToolRiskLevel(str(payload.get("risk_level") or base.risk_level.value))
    except ValueError:
        risk_level = base.risk_level
    return ShellClassification(
        name=str(payload.get("classification") or metadata.get("classification") or base.name),
        summary=str(payload.get("risk_summary") or base.summary),
        risk_level=risk_level,
        read_only=base.read_only,
        high_risk=bool(payload.get("high_risk", base.high_risk)),
        background_required=base.background_required,
    )


def _job_status_to_shell_status(status: str) -> str:
    return {
        JobStatus.PENDING.value: "running",
        JobStatus.RUNNING.value: "running",
        JobStatus.COMPLETED.value: "completed",
        JobStatus.FAILED.value: "failed",
        JobStatus.STOPPED.value: "stopped",
    }.get(status, "failed")


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
                action="exec",
                command=command,
                description=description,
                shell=shell,
                cwd=str(cwd),
                workspace_root=str(workspace_root),
                classification=classification,
                status="failed",
                background_reason=background_reason,
                job_id=None,
                shell_session_id=None,
                session_mode="background",
                session_status=None,
                exit_code=None,
                stdout="",
                stderr=error_text,
                timed_out=False,
            ),
            error=error_text,
        )

    process = await _spawn_process(command=command, shell=shell, cwd=cwd, stdin_pipe=False)
    job_id = f"shell-{uuid4().hex[:10]}"
    metadata = {
        "kind": "background_shell",
        "executor_kind": "bash",
        "shell_resource_kind": "background",
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
        action="exec",
        command=command,
        description=description,
        shell=shell,
        cwd=str(cwd),
        workspace_root=str(workspace_root),
        classification=classification,
        status="running",
        background_reason=background_reason,
        job_id=job_id,
        shell_session_id=None,
        session_mode="background",
        session_status="running",
        exit_code=None,
        stdout="",
        stderr="",
        timed_out=False,
        session_output_complete=False,
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
        action="exec",
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
        shell_session_id=None,
        session_mode="background",
        session_status="completed" if status is JobStatus.COMPLETED else (
            "stopped" if status is JobStatus.STOPPED else "failed"
        ),
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
    process = await _spawn_process(command=command, shell=shell, cwd=cwd, stdin_pipe=False)
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
    stdin_pipe: bool,
) -> asyncio.subprocess.Process:
    if shell == "powershell":
        return await asyncio.create_subprocess_exec(
            "pwsh",
            "-NoProfile",
            "-Command",
            command,
            cwd=str(cwd),
            stdin=asyncio.subprocess.PIPE if stdin_pipe else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    return await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE if stdin_pipe else None,
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
    tokens = _command_tokens(command)
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
    inline_reason = _inline_code_reason(tokens)
    if inline_reason is not None:
        return inline_reason
    path_reason = _outside_workspace_path_reason(tokens, workspace_root=workspace_root, cwd=cwd)
    if path_reason is not None:
        return path_reason
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
    if first.startswith("python") and second == "-m" and third in {"unittest", "pytest"}:
        return ShellClassification("test", "Run verification tests", ToolRiskLevel.EXEC, False)
    if first == "make" and second in {"test", "check"}:
        return ShellClassification("test", "Run verification tests", ToolRiskLevel.EXEC, False)
    if first == "cargo" and second in {"test", "nextest"}:
        return ShellClassification("test", "Run verification tests", ToolRiskLevel.EXEC, False)
    if first == "go" and second == "test":
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


def _unsupported_shell_reason(command: str) -> str | None:
    tokens = _command_tokens(command)
    first = tokens[0].lower() if tokens else ""
    if first in {"vim", "vi", "nvim", "nano", "less", "more", "top", "htop", "watch", "tmux", "screen", "man"}:
        return (
            "Unsupported shell workload for bash v2: the first cut only supports line-oriented "
            f"shell interaction, not full-screen terminal UIs such as '{first}'."
        )
    return None


def _shell_result_payload(
    *,
    action: str = "exec",
    command: str,
    description: str | None,
    shell: str,
    cwd: str,
    workspace_root: str,
    classification: ShellClassification,
    status: str,
    background_reason: str | None,
    job_id: str | None,
    shell_session_id: str | None = None,
    session_mode: str = "oneshot",
    session_status: str | None = None,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    timed_out: bool,
    session_output: str = "",
    session_output_sequence: int = 0,
    session_output_complete: bool = True,
    unsupported_shell: bool = False,
    unsupported_reason: str | None = None,
) -> dict[str, Any]:
    stdout_full, stdout_truncated = _truncate_text(stdout, _FULL_CAPTURE_MAX_CHARS, _FULL_CAPTURE_MAX_LINES)
    stderr_full, stderr_truncated = _truncate_text(stderr, _FULL_CAPTURE_MAX_CHARS, _FULL_CAPTURE_MAX_LINES)
    stdout_preview, _ = _truncate_text(stdout, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
    stderr_preview, _ = _truncate_text(stderr, _PREVIEW_MAX_CHARS, _PREVIEW_MAX_LINES)
    if not stdout_preview and stderr_preview:
        stdout_preview = stderr_preview
    return {
        "action": action,
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
        "shell_session_id": shell_session_id,
        "session_mode": session_mode,
        "session_status": session_status,
        "session_output": session_output,
        "session_output_sequence": session_output_sequence,
        "session_output_complete": session_output_complete,
        "unsupported_shell": unsupported_shell,
        "unsupported_reason": unsupported_reason,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": stdout_full,
        "stderr": stderr_full,
        "stdout_preview": stdout_preview,
        "stderr_preview": stderr_preview,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "output_summary": _output_summary(
            action=action,
            command=command,
            classification=classification,
            status=status,
            exit_code=exit_code,
            background_reason=background_reason,
            job_id=job_id,
            shell_session_id=shell_session_id,
            session_mode=session_mode,
            session_status=session_status,
            session_output=session_output,
            session_output_complete=session_output_complete,
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            timed_out=timed_out,
            unsupported_shell=unsupported_shell,
            unsupported_reason=unsupported_reason,
        ),
    }


def _output_summary(
    *,
    action: str,
    command: str,
    classification: ShellClassification,
    status: str,
    exit_code: int | None,
    background_reason: str | None,
    job_id: str | None,
    shell_session_id: str | None,
    session_mode: str,
    session_status: str | None,
    session_output: str,
    session_output_complete: bool,
    stdout_preview: str,
    stderr_preview: str,
    timed_out: bool,
    unsupported_shell: bool,
    unsupported_reason: str | None,
) -> str:
    if unsupported_shell:
        return unsupported_reason or "Unsupported shell workload."
    if action == "start" and shell_session_id is not None and job_id is not None:
        return f"Started shell session {shell_session_id} as job {job_id}."
    if action == "send" and shell_session_id is not None:
        return f"Sent stdin to shell session {shell_session_id}."
    if action == "interrupt" and shell_session_id is not None:
        return f"Sent interrupt to shell session {shell_session_id}."
    if action == "stop" and shell_session_id is not None and session_status in {"stopped", "completed", "failed"}:
        return f"Stopped shell session {shell_session_id} with status {session_status}."
    if action == "read" and shell_session_id is not None:
        detail = _first_non_empty_line(session_output) or _first_non_empty_line(stdout_preview) or _first_non_empty_line(stderr_preview)
        if detail:
            return detail
        if session_output_complete:
            return f"Shell session {shell_session_id} is {session_status or status}."
        return f"Shell session {shell_session_id} is still running."
    if status == "running" and session_mode == "session" and shell_session_id is not None:
        return f"Shell session {shell_session_id} is running."
    if status == "running" and job_id is not None:
        return f"{classification.summary} in background as job {job_id} ({background_reason or 'requested'})."
    if status == "blocked":
        return stderr_preview or f"Blocked command: {command}"
    if status == "unsupported":
        return stderr_preview or f"Unsupported shell workload: {command}"
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


def _inline_code_reason(tokens: list[str]) -> str | None:
    if len(tokens) < 2:
        return None
    executable = tokens[0].lower()
    inline_flags = {"-c", "-e", "-r", "-command", "-lc"}
    supports_inline_code = (
        executable.startswith("python")
        or executable in {"bash", "sh", "zsh", "pwsh", "powershell", "node", "perl", "ruby", "php"}
    )
    if not supports_inline_code:
        return None
    for token in tokens[1:]:
        if token.lower() in inline_flags:
            return (
                "Blocked inline interpreter command because workspace confinement cannot be "
                f"enforced safely: {tokens[0]} {token}"
            )
    return None


def _outside_workspace_path_reason(
    tokens: list[str],
    *,
    workspace_root: Path,
    cwd: Path,
) -> str | None:
    if len(tokens) < 2:
        return None
    pending_redirect = False
    for raw_token in tokens[1:]:
        candidate = raw_token
        if pending_redirect:
            pending_redirect = False
        else:
            if raw_token in {"<", ">", ">>", "1>", "2>", "1>>", "2>>"}:
                pending_redirect = True
                continue
            candidate = _strip_redirection_prefix(raw_token)
        if "://" in candidate or not _looks_like_explicit_path(candidate):
            continue
        resolved = _resolve_command_path(candidate, cwd=cwd)
        if resolved != workspace_root and workspace_root not in resolved.parents:
            return f"Blocked shell path outside the workspace: {candidate}"
    return None


def _strip_redirection_prefix(token: str) -> str:
    stripped = token.lstrip("0123456789")
    for prefix in (">>", ">", "<"):
        if stripped.startswith(prefix) and len(stripped) > len(prefix):
            return stripped[len(prefix):]
    return token


def _looks_like_explicit_path(token: str) -> bool:
    if token in {".", "..", "~"}:
        return True
    if token.startswith(("/", "~/", "./", "../", "..\\")):
        return True
    if len(token) >= 3 and token[1] == ":" and token[2] in {"\\", "/"}:
        return True
    return False


def _resolve_command_path(token: str, *, cwd: Path) -> Path:
    candidate = Path(token).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return (cwd / candidate).resolve(strict=False)


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
