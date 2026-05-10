from __future__ import annotations

import asyncio
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from weavert.builtins.definition_helpers import static_semantics
from weavert.contracts import ExecutionResult, ExecutionStatus
from weavert.definitions import (
    DefinitionOrigin,
    DefinitionSource,
    PermissionBehavior,
    PermissionDecision,
    ToolCallStatus,
    ToolClassifierInput,
    ToolDefinition,
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

from .shell_broker import (
    broker_request,
    broker_request_sync,
    broker_socket_path,
    ensure_shell_broker,
    list_shell_sidecars,
    shell_state_root,
    stop_shell_broker,
)

_FULL_CAPTURE_MAX_CHARS = 4_000
_FULL_CAPTURE_MAX_LINES = 200
_PREVIEW_MAX_CHARS = 600
_PREVIEW_MAX_LINES = 12
_DEFAULT_TIMEOUT_MS = 60_000
_BROKER_WATCH_POLL_SECONDS = 0.1
_STOP_GRACE_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class ShellClassification:
    name: str
    summary: str
    risk_level: ToolRiskLevel
    read_only: bool
    high_risk: bool = False
    background_required: bool = False
    default_session_profile: str = "line_session"


@dataclass(frozen=True, slots=True)
class ShellCommandPolicy:
    classification: ShellClassification
    outcome: str
    reason: str
    effective_command: str
    wrappers: tuple[str, ...] = ()
    confinement_confidence: str = "workspace"


@dataclass(slots=True)
class BrokerShellWatch:
    entry_id: str
    job_id: str
    workspace_root: Path
    job_service: Any
    kind: str
    shell_session_id: str | None = None
    last_sequence: int = 0
    watch_task: asyncio.Task[None] | None = None


_BROKER_WATCHES: dict[str, BrokerShellWatch] = {}


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
                "session_profile": {
                    "type": "string",
                    "enum": ["auto", "line_session", "pty_session"],
                },
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
                "command_policy": {"type": "string"},
                "command_policy_reason": {"type": "string"},
                "effective_command": {"type": "string"},
                "wrapper_chain": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "confinement_confidence": {"type": "string"},
                "status": {"type": "string"},
                "run_in_background": {"type": "boolean"},
                "background_reason": {"type": ["string", "null"]},
                "job_id": {"type": ["string", "null"]},
                "shell_session_id": {"type": ["string", "null"]},
                "session_mode": {"type": "string"},
                "session_profile": {"type": "string"},
                "terminal_mode": {"type": "string"},
                "session_status": {"type": ["string", "null"]},
                "recovery_state": {"type": ["string", "null"]},
                "session_output": {"type": "string"},
                "session_output_sequence": {"type": "integer"},
                "session_output_complete": {"type": "boolean"},
                "unsupported_shell": {"type": "boolean"},
                "unsupported_reason": {"type": ["string", "null"]},
                "sidecar_dir": {"type": ["string", "null"]},
                "sidecar_output_path": {"type": ["string", "null"]},
                "broker_socket_path": {"type": ["string", "null"]},
                "broker_pid": {"type": ["integer", "null"]},
                "error_kind": {"type": ["string", "null"]},
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
                "command_policy",
                "command_policy_reason",
                "effective_command",
                "wrapper_chain",
                "confinement_confidence",
                "status",
                "run_in_background",
                "background_reason",
                "job_id",
                "shell_session_id",
                "session_mode",
                "session_profile",
                "terminal_mode",
                "session_status",
                "recovery_state",
                "session_output",
                "session_output_sequence",
                "session_output_complete",
                "unsupported_shell",
                "unsupported_reason",
                "sidecar_dir",
                "sidecar_output_path",
                "broker_socket_path",
                "broker_pid",
                "error_kind",
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
                failure_mode=ToolFailureMode.ERROR_RESULT,
                surfaced_status=ToolCallStatus.ERROR,
            ),
            tool_use_presentation=_tool_use_presentation,
            tool_result_summary=_tool_result_summary,
            classifier_input=_classifier_input,
        ),
        validate_input=validate_code_assistant_bash_tool,
        check_permissions=check_code_assistant_bash_permissions,
        execute=code_assistant_bash_tool,
        runtime_execution_class="privileged",
        origin=DefinitionOrigin(DefinitionSource.BUNDLED),
    )


def reconcile_background_shell_jobs(job_service: Any, workspace_root: Path | None = None) -> None:
    if job_service is None or not hasattr(job_service, "list_sync"):
        return
    for record in job_service.list_sync():
        kind = str(record.metadata.get("kind") or "").strip()
        if kind not in {"background_shell", "shell_session"}:
            continue
        if record.status.terminal:
            continue
        watch = _BROKER_WATCHES.get(record.job_id)
        if watch is not None and watch.watch_task is not None and not watch.watch_task.done():
            continue
        record_workspace_root = workspace_root
        if record_workspace_root is None:
            metadata_workspace = str(record.metadata.get("workspace_root") or "").strip()
            if metadata_workspace:
                record_workspace_root = Path(metadata_workspace)
        if record_workspace_root is None:
            _mark_reconciled_shell_job(
                job_service=job_service,
                record=record,
                payload_status="recovery_unavailable",
                error_text="Shell recovery metadata is missing the workspace root.",
            )
            continue
        entry_id = _shell_entry_id_from_record(record)
        snapshot = _sidecar_entry_snapshot(
            record_workspace_root,
            entry_id=entry_id,
            kind=kind,
        )
        if snapshot is None:
            _mark_reconciled_shell_job(
                job_service=job_service,
                record=record,
                payload_status="recovery_unavailable",
                error_text="Shell sidecar metadata is unavailable after runtime restart.",
            )
            continue
        broker_snapshot = _broker_snapshot_for_record(record_workspace_root, entry_id=entry_id)
        if broker_snapshot is not None:
            snapshot = dict(broker_snapshot)
            if str(snapshot.get("status") or "") == "running":
                snapshot["recovery_state"] = "reattached"
        else:
            snapshot = _reconcile_snapshot_after_broker_loss(snapshot=snapshot, metadata=dict(record.metadata))
        recovery_state = str(snapshot.get("recovery_state") or "")
        if str(snapshot.get("status") or "") == "running" and recovery_state in {"attached", "reattached"}:
            _register_shell_stop_handler(
                workspace_root=record_workspace_root,
                entry_id=entry_id,
                job_id=record.job_id,
                job_service=job_service,
            )
            _refresh_shell_job_from_snapshot(job_service=job_service, record=record, snapshot=snapshot)
            _register_broker_watch(
                workspace_root=record_workspace_root,
                entry_id=entry_id,
                job_id=record.job_id,
                kind=kind,
                shell_session_id=str(record.metadata.get("shell_session_id") or "").strip() or None,
                job_service=job_service,
            )
            continue
        payload_status = str(snapshot.get("status") or "recovery_unavailable")
        _mark_reconciled_shell_job(
            job_service=job_service,
            record=record,
            payload_status=payload_status,
            error_text=(
                None
                if payload_status in {"completed", "stopped", "interrupted"}
                else (
                    "Interactive shell session was reconciled explicitly after runtime restart."
                    if kind == "shell_session"
                    else "Background shell job was reconciled explicitly after runtime restart."
                )
            ),
            snapshot=snapshot,
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
    session_profile = _normalize_optional_string(tool_input.get("session_profile"))
    if session_profile is not None and session_profile not in {"auto", "line_session", "pty_session"}:
        return ValidationOutcome(False, f"Unsupported session_profile: {session_profile}")
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


def check_code_assistant_bash_permissions(tool_input: dict[str, Any], context: ToolContext) -> PermissionDecision:
    action = _normalize_optional_string(tool_input.get("action")) or "exec"
    if action in {"send", "read", "interrupt", "stop"}:
        target = _normalize_optional_string(tool_input.get("shell_session_id")) or action
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message=f"Approve shell session control: {action} {target}",
        )
    command = str(tool_input.get("command") or "").strip()
    try:
        cwd = _resolve_shell_cwd(context, tool_input.get("cwd"))
    except ValueError:
        cwd = _workspace_root_for(context)
    policy = _resolve_command_policy(command, workspace_root=_workspace_root_for(context), cwd=cwd)
    risk_label = "high-risk approval" if policy.outcome == "requires_high_risk_approval" else "approval"
    return PermissionDecision(
        behavior=PermissionBehavior.ASK,
        message=f"Approve {risk_label} for {policy.classification.summary.lower()}: {policy.reason}",
        details={
            "command_policy": policy.outcome,
            "effective_command": policy.effective_command,
            "wrapper_chain": list(policy.wrappers),
            "confinement_confidence": policy.confinement_confidence,
        },
    )


async def code_assistant_bash_tool(tool_input: dict[str, Any], context: ToolContext) -> Any:
    action = _normalize_optional_string(tool_input.get("action")) or "exec"
    workspace_root = _workspace_root_for(context)
    description = _normalize_optional_string(tool_input.get("description"))
    shell = _normalize_optional_string(tool_input.get("shell")) or "bash"
    timeout_ms = int(tool_input.get("timeout_ms") or _DEFAULT_TIMEOUT_MS)
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
    try:
        cwd = _resolve_shell_cwd(context, tool_input.get("cwd"))
    except ValueError as exc:
        policy = ShellCommandPolicy(
            classification=_classify_command(command),
            outcome="blocked",
            reason=str(exc),
            effective_command=command,
            confinement_confidence="not_confinable",
        )
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            value=_shell_result_payload(
                action=action,
                command=command,
                description=description,
                shell=shell,
                cwd=str(workspace_root),
                workspace_root=str(workspace_root),
                policy=policy,
                status="blocked",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="session" if action == "start" else "oneshot",
                session_profile="line_session" if action == "start" else "oneshot",
                terminal_mode="line" if action == "start" else "none",
                session_status=None,
                recovery_state=None,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                error_kind="policy_denied",
            ),
            error=str(exc),
        )

    policy = _resolve_command_policy(command, workspace_root=workspace_root, cwd=cwd)
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
                policy=policy,
                status="unsupported",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="session" if action == "start" else "oneshot",
                session_profile="line_session" if action == "start" else "oneshot",
                terminal_mode="line" if action == "start" else "none",
                session_status=None,
                recovery_state=None,
                exit_code=None,
                stdout="",
                stderr=unsupported_reason,
                timed_out=False,
                unsupported_shell=True,
                unsupported_reason=unsupported_reason,
                error_kind="unsupported_shell",
            ),
            error=unsupported_reason,
        )
    if policy.outcome in {"blocked", "not_confinable"}:
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            value=_shell_result_payload(
                action=action,
                command=command,
                description=description,
                shell=shell,
                cwd=str(cwd),
                workspace_root=str(workspace_root),
                policy=policy,
                status=policy.outcome,
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="session" if action == "start" else "oneshot",
                session_profile="line_session" if action == "start" else "oneshot",
                terminal_mode="line" if action == "start" else "none",
                session_status=None,
                recovery_state=None,
                exit_code=None,
                stdout="",
                stderr=policy.reason,
                timed_out=False,
                error_kind="policy_denied",
            ),
            error=policy.reason,
        )

    if action == "start":
        return await _start_shell_session(
            command=command,
            description=description,
            shell=shell,
            cwd=cwd,
            workspace_root=workspace_root,
            policy=policy,
            context=context,
            requested_profile=_normalize_optional_string(tool_input.get("session_profile")) or "auto",
        )

    background_reason: str | None = None
    if bool(tool_input.get("run_in_background")):
        background_reason = "requested"
    elif policy.classification.background_required:
        background_reason = "required_for_long_running_command"

    if background_reason is not None:
        return await _start_background_shell(
            command=command,
            description=description,
            shell=shell,
            cwd=cwd,
            workspace_root=workspace_root,
            policy=policy,
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
                policy=policy,
                status="timed_out",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="oneshot",
                session_profile="oneshot",
                terminal_mode="none",
                session_status=None,
                recovery_state=None,
                exit_code=None,
                stdout="",
                stderr=error_text,
                timed_out=True,
                error_kind="timeout",
            ),
            error=error_text,
        )
    except OSError as exc:
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
                policy=policy,
                status="spawn_failed",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="oneshot",
                session_profile="oneshot",
                terminal_mode="none",
                session_status=None,
                recovery_state=None,
                exit_code=None,
                stdout="",
                stderr=error_text,
                timed_out=False,
                error_kind="spawn_failed",
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
        policy=policy,
        status="completed" if exit_code == 0 else "command_failed",
        background_reason=None,
        job_id=None,
        shell_session_id=None,
        session_mode="oneshot",
        session_profile="oneshot",
        terminal_mode="none",
        session_status=None,
        recovery_state=None,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
        error_kind=None if exit_code == 0 else "command_failed",
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
    policy = _policy_for_presentation(command)
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
            if policy.classification.high_risk or policy.outcome == "requires_high_risk_approval"
            else ToolPresentationEmphasis.NORMAL
        ),
    )


def _tool_result_summary(tool_input: dict[str, Any], _context: ToolContext) -> ToolResultSummary:
    action = _normalize_optional_string(tool_input.get("action")) or "exec"
    command = str(tool_input.get("command") or "").strip()
    shell_session_id = _normalize_optional_string(tool_input.get("shell_session_id"))
    policy = _policy_for_presentation(command)
    if action != "exec":
        target = shell_session_id or command or "shell session"
        return ToolResultSummary(
            title="Shell session",
            summary=f"{action}: {target}",
            status=ToolResultSummaryStatus.SUCCESS,
        )
    return ToolResultSummary(
        title="Shell command",
        summary=f"{policy.classification.summary}: {command}",
        status=ToolResultSummaryStatus.SUCCESS,
    )


def _classifier_input(tool_input: dict[str, Any], context: ToolContext) -> ToolClassifierInput:
    action = _normalize_optional_string(tool_input.get("action")) or "exec"
    command = str(tool_input.get("command") or "").strip()
    shell_session_id = _normalize_optional_string(tool_input.get("shell_session_id"))
    policy = _policy_for_presentation(command)
    cwd = _normalize_optional_string(tool_input.get("cwd"))
    if cwd is None:
        target_paths = (str(_workspace_root_for(context)),)
    else:
        target_paths = (cwd,)
    summary = f"{policy.classification.summary}: {command}"
    tags = ("shell", policy.classification.name, policy.outcome)
    side_effects = not policy.classification.read_only
    if action != "exec":
        summary = f"Shell session {action}: {shell_session_id or command or 'session'}"
        tags = ("shell", "session", action)
        side_effects = True
    return ToolClassifierInput(
        operation="bash",
        summary=summary,
        target_paths=target_paths,
        risk_level=policy.classification.risk_level,
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
    job_service = _job_service_for(context)
    record = _job_record_for_shell_session(job_service, shell_session_id) if job_service is not None else None
    if record is None:
        error_text = f"Unknown shell session: {shell_session_id}"
        payload = _shell_result_payload(
            action=action,
            command="",
            description=description,
            shell=shell,
            cwd=str(_workspace_root_for(context)),
            workspace_root=str(_workspace_root_for(context)),
            policy=_policy_for_presentation(""),
            status="recovery_unavailable",
            background_reason=None,
            job_id=None,
            shell_session_id=shell_session_id,
            session_mode="session",
            session_profile="line_session",
            terminal_mode="line",
            session_status="recovery_unavailable",
            recovery_state="recovery_unavailable",
            exit_code=None,
            stdout="",
            stderr=error_text,
            timed_out=False,
            error_kind="broker_failed",
        )
        return ExecutionResult(status=ExecutionStatus.FAILED, value=payload, error=error_text)
    workspace_root = Path(str(record.metadata.get("workspace_root") or _workspace_root_for(context))).resolve()
    broker_response: dict[str, Any] | None = None
    broker_error: str | None = None
    try:
        if action == "read":
            broker_response = await broker_request(
                workspace_root,
                {
                    "op": "read",
                    "entry_id": shell_session_id,
                    "after_sequence": after_sequence,
                    "max_output_chars": max_output_chars,
                },
                ensure=False,
            )
        elif action == "send":
            broker_response = await broker_request(
                workspace_root,
                {"op": "send", "entry_id": shell_session_id, "stdin": stdin},
                ensure=False,
            )
        elif action == "interrupt":
            broker_response = await broker_request(
                workspace_root,
                {"op": "interrupt", "entry_id": shell_session_id},
                ensure=False,
            )
        elif action == "stop":
            broker_response = await broker_request(
                workspace_root,
                {"op": "stop", "entry_id": shell_session_id},
                ensure=False,
            )
        else:
            raise RuntimeError(f"Unsupported shell action dispatch: {action}")
    except Exception as exc:
        broker_error = str(exc)
    snapshot = (
        dict(broker_response.get("entry", {}))
        if broker_response is not None and isinstance(broker_response.get("entry"), dict)
        else _sidecar_entry_snapshot(workspace_root, entry_id=shell_session_id, kind="shell_session")
    )
    if broker_error is not None and snapshot is not None:
        snapshot = _reconcile_snapshot_after_broker_loss(snapshot=snapshot, metadata=dict(record.metadata))
    payload = _shell_payload_from_snapshot(
        action=action,
        record=record,
        snapshot=snapshot,
        session_output=str(broker_response.get("session_output") or "") if broker_response is not None else "",
        session_output_sequence=int(broker_response.get("session_output_sequence") or 0) if broker_response is not None else None,
        session_output_complete=bool(broker_response.get("session_output_complete", False)) if broker_response is not None else None,
    )
    if broker_error is None:
        return payload
    return ExecutionResult(status=ExecutionStatus.FAILED, value=payload, error=broker_error)


async def _start_shell_session(
    *,
    command: str,
    description: str | None,
    shell: str,
    cwd: Path,
    workspace_root: Path,
    policy: ShellCommandPolicy,
    context: ToolContext,
    requested_profile: str,
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
                policy=policy,
                status="broker_failed",
                background_reason=None,
                job_id=None,
                shell_session_id=None,
                session_mode="session",
                session_profile="line_session",
                terminal_mode="line",
                session_status="broker_failed",
                recovery_state=None,
                exit_code=None,
                stdout="",
                stderr=error_text,
                timed_out=False,
                error_kind="broker_failed",
            ),
            error=error_text,
        )
    shell_session_id = f"shell-session-{uuid4().hex[:10]}"
    job_id = f"shell-{uuid4().hex[:10]}"
    resolved_profile, terminal_mode, unsupported_reason = _resolved_session_profile(
        requested_profile=requested_profile,
        policy=policy,
    )
    if unsupported_reason is not None:
        payload = _shell_result_payload(
            action="start",
            command=command,
            description=description,
            shell=shell,
            cwd=str(cwd),
            workspace_root=str(workspace_root),
            policy=policy,
            status="unsupported",
            background_reason=None,
            job_id=None,
            shell_session_id=None,
            session_mode="session",
            session_profile=resolved_profile,
            terminal_mode=terminal_mode,
            session_status=None,
            recovery_state=None,
            exit_code=None,
            stdout="",
            stderr=unsupported_reason,
            timed_out=False,
            unsupported_shell=True,
            unsupported_reason=unsupported_reason,
            error_kind="unsupported_shell",
        )
        return ExecutionResult(status=ExecutionStatus.FAILED, value=payload, error=unsupported_reason)
    try:
        await ensure_shell_broker(workspace_root)
        broker_response = await broker_request(
            workspace_root,
            {
                "op": "start",
                "kind": "shell_session",
                "entry_id": shell_session_id,
                "job_id": job_id,
                "shell_session_id": shell_session_id,
                "command": command,
                "shell": shell,
                "cwd": str(cwd),
                "description": description,
                "classification": policy.classification.name,
                "session_profile": resolved_profile,
                "terminal_mode": terminal_mode,
            },
            ensure=False,
        )
    except Exception as exc:
        error_text = str(exc)
        payload = _shell_result_payload(
            action="start",
            command=command,
            description=description,
            shell=shell,
            cwd=str(cwd),
            workspace_root=str(workspace_root),
            policy=policy,
            status="broker_failed",
            background_reason=None,
            job_id=None,
            shell_session_id=None,
            session_mode="session",
            session_profile=resolved_profile,
            terminal_mode=terminal_mode,
            session_status=None,
            recovery_state=None,
            exit_code=None,
            stdout="",
            stderr=error_text,
            timed_out=False,
            error_kind="broker_failed",
        )
        return ExecutionResult(status=ExecutionStatus.FAILED, value=payload, error=error_text)
    snapshot = dict(broker_response.get("entry", {}))
    metadata = {
        "kind": "shell_session",
        "executor_kind": "bash",
        "shell_resource_kind": "session",
        "shell_session_id": shell_session_id,
        "session_status": str(snapshot.get("status") or "running"),
        "session_profile": str(snapshot.get("session_profile") or resolved_profile),
        "terminal_mode": str(snapshot.get("terminal_mode") or terminal_mode),
        "recovery_state": str(snapshot.get("recovery_state") or "attached"),
        "session_id": context.session_id,
        "submitted_by": context.agent_name,
        "run_id": _run_id_for(context),
        "turn_id": context.turn_id,
        "command": command,
        "cwd": str(cwd),
        "workspace_root": str(workspace_root),
        "classification": policy.classification.name,
        "command_policy": policy.outcome,
        "command_policy_reason": policy.reason,
        "effective_command": policy.effective_command,
        "wrapper_chain": list(policy.wrappers),
        "confinement_confidence": policy.confinement_confidence,
        "shell": shell,
        "description": description,
        "pid": snapshot.get("pid"),
        "broker_pid": snapshot.get("broker_pid"),
        "broker_socket_path": str(snapshot.get("socket_path") or broker_socket_path(workspace_root)),
        "sidecar_dir": snapshot.get("sidecar_dir"),
        "sidecar_output_path": snapshot.get("output_path"),
        "output_sequence": int(snapshot.get("output_sequence") or 0),
    }
    summary = _shell_job_summary(policy=policy, command=command, description=description)
    job_service.create_or_update_compat(job_id, summary, description=description, metadata=metadata)
    _register_shell_stop_handler(workspace_root=workspace_root, entry_id=shell_session_id, job_id=job_id, job_service=job_service)
    payload = _shell_payload_from_snapshot(
        action="start",
        record=job_service.get_sync(job_id),
        snapshot=snapshot,
        policy=policy,
        session_output="",
        session_output_sequence=int(snapshot.get("output_sequence") or 0),
        session_output_complete=False,
    )
    job_service.update_compat(
        job_id,
        status=JobStatus.RUNNING,
        result=payload,
        metadata=_shell_job_metadata_from_payload(kind="shell_session", payload=payload, existing=metadata),
    )
    _register_broker_watch(
        workspace_root=workspace_root,
        entry_id=shell_session_id,
        job_id=job_id,
        kind="shell_session",
        shell_session_id=shell_session_id,
        job_service=job_service,
    )
    return payload


def _shell_session_payload_from_record(
    *,
    action: str,
    record: Any | None,
    after_sequence: int,
) -> dict[str, Any]:
    payload = dict(record.result) if record is not None and isinstance(record.result, dict) else {}
    session_output = str(payload.get("session_output") or "")
    session_output_sequence = int(payload.get("session_output_sequence") or 0)
    if action == "read" and session_output_sequence <= after_sequence:
        session_output = ""
    return _shell_payload_from_snapshot(
        action=action,
        record=record,
        snapshot=None,
        session_output=session_output,
        session_output_sequence=session_output_sequence,
        session_output_complete=bool(payload.get("session_output_complete", record.status.terminal if record is not None else True)),
    )


def _job_record_for_shell_session(job_service: Any, shell_session_id: str) -> Any | None:
    if job_service is None or not hasattr(job_service, "list_sync"):
        return None
    for record in job_service.list_sync():
        if str(record.metadata.get("shell_session_id") or "") == shell_session_id:
            return record
    return None


def _policy_from_payload(
    *,
    command: str,
    payload: dict[str, Any],
    metadata: dict[str, Any],
) -> ShellCommandPolicy:
    base = _policy_for_presentation(command)
    classification = ShellClassification(
        name=str(payload.get("classification") or metadata.get("classification") or base.classification.name),
        summary=str(payload.get("risk_summary") or metadata.get("risk_summary") or base.classification.summary),
        risk_level=_coerce_risk_level(payload.get("risk_level"), fallback=base.classification.risk_level),
        read_only=base.classification.read_only,
        high_risk=bool(payload.get("high_risk", metadata.get("high_risk", base.classification.high_risk))),
        background_required=base.classification.background_required,
        default_session_profile=str(metadata.get("session_profile") or base.classification.default_session_profile or "line_session"),
    )
    wrappers = payload.get("wrapper_chain") or metadata.get("wrapper_chain") or ()
    return ShellCommandPolicy(
        classification=classification,
        outcome=str(payload.get("command_policy") or metadata.get("command_policy") or base.outcome),
        reason=str(payload.get("command_policy_reason") or metadata.get("command_policy_reason") or base.reason),
        effective_command=str(payload.get("effective_command") or metadata.get("effective_command") or base.effective_command),
        wrappers=tuple(str(item) for item in wrappers if isinstance(item, str)),
        confinement_confidence=str(
            payload.get("confinement_confidence") or metadata.get("confinement_confidence") or base.confinement_confidence
        ),
    )


def _job_status_to_shell_status(status: str) -> str:
    return {
        JobStatus.PENDING.value: "running",
        JobStatus.RUNNING.value: "running",
        JobStatus.COMPLETED.value: "completed",
        JobStatus.FAILED.value: "command_failed",
        JobStatus.STOPPED.value: "stopped",
    }.get(status, "recovery_unavailable")


async def _start_background_shell(
    *,
    command: str,
    description: str | None,
    shell: str,
    cwd: Path,
    workspace_root: Path,
    policy: ShellCommandPolicy,
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
                policy=policy,
                status="broker_failed",
                background_reason=background_reason,
                job_id=None,
                shell_session_id=None,
                session_mode="background",
                session_profile="background",
                terminal_mode="none",
                session_status=None,
                recovery_state=None,
                exit_code=None,
                stdout="",
                stderr=error_text,
                timed_out=False,
                error_kind="broker_failed",
            ),
            error=error_text,
        )
    job_id = f"shell-{uuid4().hex[:10]}"
    try:
        await ensure_shell_broker(workspace_root)
        broker_response = await broker_request(
            workspace_root,
            {
                "op": "start",
                "kind": "background_shell",
                "entry_id": job_id,
                "job_id": job_id,
                "command": command,
                "shell": shell,
                "cwd": str(cwd),
                "description": description,
                "classification": policy.classification.name,
                "session_profile": "background",
                "terminal_mode": "none",
            },
            ensure=False,
        )
    except Exception as exc:
        error_text = str(exc)
        payload = _shell_result_payload(
            action="exec",
            command=command,
            description=description,
            shell=shell,
            cwd=str(cwd),
            workspace_root=str(workspace_root),
            policy=policy,
            status="broker_failed",
            background_reason=background_reason,
            job_id=None,
            shell_session_id=None,
            session_mode="background",
            session_profile="background",
            terminal_mode="none",
            session_status=None,
            recovery_state=None,
            exit_code=None,
            stdout="",
            stderr=error_text,
            timed_out=False,
            error_kind="broker_failed",
        )
        return ExecutionResult(status=ExecutionStatus.FAILED, value=payload, error=error_text)
    snapshot = dict(broker_response.get("entry", {}))
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
        "classification": policy.classification.name,
        "command_policy": policy.outcome,
        "command_policy_reason": policy.reason,
        "effective_command": policy.effective_command,
        "wrapper_chain": list(policy.wrappers),
        "confinement_confidence": policy.confinement_confidence,
        "background_reason": background_reason,
        "shell": shell,
        "description": description,
        "pid": snapshot.get("pid"),
        "broker_pid": snapshot.get("broker_pid"),
        "broker_socket_path": str(snapshot.get("socket_path") or broker_socket_path(workspace_root)),
        "sidecar_dir": snapshot.get("sidecar_dir"),
        "sidecar_output_path": snapshot.get("output_path"),
        "session_profile": "background",
        "terminal_mode": "none",
        "recovery_state": str(snapshot.get("recovery_state") or "attached"),
        "output_sequence": int(snapshot.get("output_sequence") or 0),
    }
    summary = _shell_job_summary(policy=policy, command=command, description=description)
    job_service.create_or_update_compat(job_id, summary, description=description, metadata=metadata)
    _register_shell_stop_handler(workspace_root=workspace_root, entry_id=job_id, job_id=job_id, job_service=job_service)
    payload = _shell_payload_from_snapshot(
        action="exec",
        record=job_service.get_sync(job_id),
        snapshot=snapshot,
        policy=policy,
        background_reason=background_reason,
        session_output_complete=False,
    )
    job_service.update_compat(
        job_id,
        status=JobStatus.RUNNING,
        result=payload,
        metadata=_shell_job_metadata_from_payload(kind="background_shell", payload=payload, existing=metadata),
    )
    _register_broker_watch(
        workspace_root=workspace_root,
        entry_id=job_id,
        job_id=job_id,
        kind="background_shell",
        job_service=job_service,
    )
    return payload


def _register_shell_stop_handler(*, workspace_root: Path, entry_id: str, job_id: str, job_service: Any) -> None:
    async def _stop_job(_: Any) -> None:
        try:
            broker_response = await broker_request(workspace_root, {"op": "stop", "entry_id": entry_id}, ensure=False)
            record = job_service.get_sync(job_id)
            if record is None:
                return
            payload = _shell_payload_from_snapshot(
                action="stop",
                record=record,
                snapshot=dict(broker_response.get("entry", {})),
            )
            job_service.update_compat(
                job_id,
                status=_payload_status_to_job_status(str(payload.get("status") or "")),
                result=payload,
                error=None if str(payload.get("status") or "") in {"completed", "stopped"} else payload["output_summary"],
                metadata=_shell_job_metadata_from_payload(kind=str(record.metadata.get("kind") or "background_shell"), payload=payload, existing=dict(record.metadata)),
            )
        except Exception:
            snapshot = _sidecar_entry_snapshot(workspace_root, entry_id=entry_id)
            if snapshot is None:
                return
            record = job_service.get_sync(job_id)
            if record is None:
                return
            payload = _shell_payload_from_snapshot(action="stop", record=record, snapshot=snapshot)
            job_service.update_compat(
                job_id,
                status=_payload_status_to_job_status(str(payload.get("status") or "")),
                result=payload,
                error=None if str(payload.get("status") or "") in {"completed", "stopped"} else payload["output_summary"],
                metadata=_shell_job_metadata_from_payload(kind=str(record.metadata.get("kind") or "background_shell"), payload=payload, existing=dict(record.metadata)),
            )

    job_service.register_compat_stop_handler(job_id, _stop_job)


def _register_broker_watch(
    *,
    workspace_root: Path,
    entry_id: str,
    job_id: str,
    kind: str,
    shell_session_id: str | None = None,
    job_service: Any,
) -> bool:
    existing = _BROKER_WATCHES.get(job_id)
    if existing is not None and existing.watch_task is not None and not existing.watch_task.done():
        return True
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    watch = BrokerShellWatch(
        entry_id=entry_id,
        job_id=job_id,
        workspace_root=workspace_root,
        job_service=job_service,
        kind=kind,
        shell_session_id=shell_session_id,
    )
    watch.watch_task = asyncio.create_task(_watch_broker_entry(watch))
    _BROKER_WATCHES[job_id] = watch
    return True


async def _watch_broker_entry(watch: BrokerShellWatch) -> None:
    try:
        while True:
            record = watch.job_service.get_sync(watch.job_id)
            if record is None or record.status.terminal:
                return
            broker_response: dict[str, Any] | None = None
            try:
                broker_response = await broker_request(
                    watch.workspace_root,
                    {
                        "op": "read",
                        "entry_id": watch.entry_id,
                        "after_sequence": watch.last_sequence,
                        "max_output_chars": _FULL_CAPTURE_MAX_CHARS,
                    },
                    ensure=False,
                )
            except Exception:
                pass
            snapshot = (
                dict(broker_response.get("entry", {}))
                if broker_response is not None and isinstance(broker_response.get("entry"), dict)
                else _sidecar_entry_snapshot(watch.workspace_root, entry_id=watch.entry_id, kind=watch.kind)
            )
            if snapshot is None:
                return
            if broker_response is None:
                snapshot = _reconcile_snapshot_after_broker_loss(snapshot=snapshot, metadata=dict(record.metadata))
            payload = _shell_payload_from_snapshot(
                action="read",
                record=record,
                snapshot=snapshot,
                session_output=str(broker_response.get("session_output") or "") if broker_response is not None else "",
                session_output_sequence=int(broker_response.get("session_output_sequence") or 0) if broker_response is not None else None,
                session_output_complete=bool(broker_response.get("session_output_complete", False)) if broker_response is not None else None,
            )
            watch.last_sequence = int(payload.get("session_output_sequence") or watch.last_sequence)
            shell_status = str(payload.get("status") or "")
            job_status = JobStatus.RUNNING if shell_status == "running" else _payload_status_to_job_status(shell_status)
            watch.job_service.update_compat(
                watch.job_id,
                status=job_status,
                result=payload,
                error=None if job_status in {JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.STOPPED} else payload["output_summary"],
                metadata=_shell_job_metadata_from_payload(kind=watch.kind, payload=payload, existing=dict(record.metadata)),
            )
            if job_status is not JobStatus.RUNNING:
                watch.job_service.unregister_compat_stop_handler(watch.job_id)
                return
            await asyncio.sleep(_BROKER_WATCH_POLL_SECONDS)
    finally:
        _BROKER_WATCHES.pop(watch.job_id, None)


def _shell_payload_from_snapshot(
    *,
    action: str,
    record: Any | None,
    snapshot: dict[str, Any] | None,
    policy: ShellCommandPolicy | None = None,
    background_reason: str | None = None,
    session_output: str = "",
    session_output_sequence: int | None = None,
    session_output_complete: bool | None = None,
) -> dict[str, Any]:
    payload = dict(record.result) if record is not None and isinstance(record.result, dict) else {}
    metadata = dict(record.metadata) if record is not None and isinstance(record.metadata, dict) else {}
    snapshot = snapshot or {}
    command = str(snapshot.get("command") or payload.get("command") or metadata.get("command") or "")
    resolved_policy = policy or _policy_from_payload(command=command, payload=payload, metadata=metadata)
    shell = str(snapshot.get("shell") or payload.get("shell") or metadata.get("shell") or "bash")
    cwd = str(snapshot.get("cwd") or payload.get("cwd") or metadata.get("cwd") or "")
    workspace_root = str(snapshot.get("workspace_root") or payload.get("workspace_root") or metadata.get("workspace_root") or cwd)
    shell_status = str(
        snapshot.get("status")
        or payload.get("status")
        or metadata.get("session_status")
        or _job_status_to_shell_status(record.status.value) if record is not None else "recovery_unavailable"
    )
    recovered_session_output = session_output or str(payload.get("session_output") or metadata.get("recent_output_preview") or "")
    recovered_sequence = (
        session_output_sequence
        if session_output_sequence is not None
        else int(snapshot.get("output_sequence") or payload.get("session_output_sequence") or metadata.get("output_sequence") or 0)
    )
    recovered_complete = (
        session_output_complete
        if session_output_complete is not None
        else bool(payload.get("session_output_complete", shell_status not in {"running"}))
    )
    return _shell_result_payload(
        action=action,
        command=command,
        description=_normalize_optional_string(snapshot.get("description") or payload.get("description") or metadata.get("description")),
        shell=shell,
        cwd=cwd,
        workspace_root=workspace_root,
        policy=resolved_policy,
        status=shell_status,
        background_reason=_normalize_optional_string(
            background_reason or snapshot.get("background_reason") or payload.get("background_reason") or metadata.get("background_reason")
        ),
        job_id=str(snapshot.get("job_id") or payload.get("job_id") or record.job_id if record is not None else ""),
        shell_session_id=_normalize_optional_string(snapshot.get("shell_session_id") or payload.get("shell_session_id") or metadata.get("shell_session_id")),
        session_mode=str(snapshot.get("session_mode") or payload.get("session_mode") or metadata.get("shell_resource_kind") or "session"),
        session_profile=str(snapshot.get("session_profile") or payload.get("session_profile") or metadata.get("session_profile") or "line_session"),
        terminal_mode=str(snapshot.get("terminal_mode") or payload.get("terminal_mode") or metadata.get("terminal_mode") or "line"),
        session_status=shell_status,
        recovery_state=_normalize_optional_string(snapshot.get("recovery_state") or payload.get("recovery_state") or metadata.get("recovery_state")),
        exit_code=_coerce_optional_int(snapshot.get("exit_code") if "exit_code" in snapshot else payload.get("exit_code")),
        stdout=str(payload.get("stdout") or metadata.get("stdout_preview") or ""),
        stderr=str(payload.get("stderr") or metadata.get("stderr_preview") or ""),
        timed_out=bool(payload.get("timed_out", False)),
        session_output=recovered_session_output,
        session_output_sequence=recovered_sequence,
        session_output_complete=recovered_complete,
        unsupported_shell=bool(payload.get("unsupported_shell", False)),
        unsupported_reason=_normalize_optional_string(payload.get("unsupported_reason")),
        sidecar_dir=_normalize_optional_string(snapshot.get("sidecar_dir") or metadata.get("sidecar_dir")),
        sidecar_output_path=_normalize_optional_string(snapshot.get("output_path") or metadata.get("sidecar_output_path")),
        broker_socket_path=_normalize_optional_string(snapshot.get("socket_path") or metadata.get("broker_socket_path")),
        broker_pid=_coerce_optional_int(snapshot.get("broker_pid") or metadata.get("broker_pid")),
        error_kind=_normalize_optional_string(payload.get("error_kind")),
    )


def _shell_job_metadata_from_payload(
    *,
    kind: str,
    payload: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(existing or {})
    metadata.update(
        {
            "kind": kind,
            "shell_resource_kind": payload.get("session_mode"),
            "shell_session_id": payload.get("shell_session_id"),
            "session_status": payload.get("session_status") or payload.get("status"),
            "session_profile": payload.get("session_profile"),
            "terminal_mode": payload.get("terminal_mode"),
            "recovery_state": payload.get("recovery_state"),
            "classification": payload.get("classification"),
            "command_policy": payload.get("command_policy"),
            "command_policy_reason": payload.get("command_policy_reason"),
            "effective_command": payload.get("effective_command"),
            "wrapper_chain": list(payload.get("wrapper_chain") or ()),
            "confinement_confidence": payload.get("confinement_confidence"),
            "output_sequence": payload.get("session_output_sequence"),
            "recent_output_preview": payload.get("session_output"),
            "recent_output_stream": payload.get("terminal_mode") if payload.get("terminal_mode") == "pty" else "stdout",
            "stdout_preview": payload.get("stdout_preview"),
            "stderr_preview": payload.get("stderr_preview"),
            "sidecar_dir": payload.get("sidecar_dir"),
            "sidecar_output_path": payload.get("sidecar_output_path"),
            "broker_socket_path": payload.get("broker_socket_path"),
            "broker_pid": payload.get("broker_pid"),
        }
    )
    return metadata


def _payload_status_to_job_status(status: str) -> JobStatus:
    if status == "completed":
        return JobStatus.COMPLETED
    if status in {"stopped", "interrupted"}:
        return JobStatus.STOPPED
    return JobStatus.FAILED


def _mark_reconciled_shell_job(
    *,
    job_service: Any,
    record: Any,
    payload_status: str,
    error_text: str | None,
    snapshot: dict[str, Any] | None = None,
) -> None:
    resolved_snapshot = dict(snapshot or {})
    resolved_snapshot["status"] = payload_status
    resolved_snapshot["recovery_state"] = payload_status
    payload = _shell_payload_from_snapshot(
        action="read",
        record=record,
        snapshot=resolved_snapshot,
        session_output_complete=True,
    )
    job_status = _payload_status_to_job_status(payload_status)
    job_service.update_compat(
        record.job_id,
        status=job_status,
        result=payload,
        error=None if job_status in {JobStatus.COMPLETED, JobStatus.STOPPED} else (error_text or payload["output_summary"]),
        metadata=_shell_job_metadata_from_payload(kind=str(record.metadata.get("kind") or "background_shell"), payload=payload, existing=dict(record.metadata)),
    )


def _sidecar_entry_snapshot(
    workspace_root: Path,
    *,
    entry_id: str,
    kind: str | None = None,
) -> dict[str, Any] | None:
    for payload in list_shell_sidecars(workspace_root):
        if str(payload.get("entry_id") or "") != entry_id:
            continue
        if kind is not None and str(payload.get("kind") or "") != kind:
            continue
        return dict(payload)
    return None


def _shell_entry_id_from_record(record: Any) -> str:
    kind = str(record.metadata.get("kind") or "")
    if kind == "shell_session":
        return str(record.metadata.get("shell_session_id") or record.job_id)
    return str(record.job_id)


def _shell_job_summary(*, policy: ShellCommandPolicy, command: str, description: str | None) -> str:
    return description or f"{policy.classification.summary}: {command}"


def _broker_snapshot_for_record(workspace_root: Path, *, entry_id: str) -> dict[str, Any] | None:
    try:
        response = broker_request_sync(workspace_root, {"op": "describe", "entry_id": entry_id})
    except Exception:
        return None
    entry = response.get("entry")
    return dict(entry) if isinstance(entry, dict) else None


def _refresh_shell_job_from_snapshot(*, job_service: Any, record: Any, snapshot: dict[str, Any]) -> None:
    payload = _shell_payload_from_snapshot(action="read", record=record, snapshot=snapshot)
    shell_status = str(payload.get("status") or "")
    job_status = JobStatus.RUNNING if shell_status == "running" else _payload_status_to_job_status(shell_status)
    job_service.update_compat(
        record.job_id,
        status=job_status,
        result=payload,
        error=None if job_status in {JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.STOPPED} else payload["output_summary"],
        metadata=_shell_job_metadata_from_payload(kind=str(record.metadata.get("kind") or "background_shell"), payload=payload, existing=dict(record.metadata)),
    )


def _reconcile_snapshot_after_broker_loss(*, snapshot: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    resolved_snapshot = dict(snapshot)
    if str(resolved_snapshot.get("status") or "") != "running":
        return resolved_snapshot
    pid = _coerce_optional_int(resolved_snapshot.get("pid") or metadata.get("pid"))
    if _shell_pid_alive(pid):
        resolved_snapshot["status"] = "orphaned"
        resolved_snapshot["recovery_state"] = "orphaned"
        return resolved_snapshot
    resolved_snapshot["status"] = "recovery_unavailable"
    resolved_snapshot["recovery_state"] = "recovery_unavailable"
    return resolved_snapshot


def _resolved_session_profile(*, requested_profile: str, policy: ShellCommandPolicy) -> tuple[str, str, str | None]:
    if requested_profile == "pty_session":
        if os.name == "nt":
            return "pty_session", "pty", "PTY shell sessions are unsupported on this platform."
        return "pty_session", "pty", None
    if requested_profile == "line_session":
        return "line_session", "line", None
    auto_profile = policy.classification.default_session_profile
    if auto_profile == "pty_session" and os.name == "nt":
        return "line_session", "line", None
    if auto_profile == "pty_session":
        return "pty_session", "pty", None
    return "line_session", "line", None


def _shell_pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _terminate_process(
    process: asyncio.subprocess.Process,
    *,
    grace_period_seconds: float = _STOP_GRACE_SECONDS,
) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_period_seconds)
        return
    except asyncio.TimeoutError:
        pass
    if process.returncode is not None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        return
    await process.wait()


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
            start_new_session=True,
        )
    return await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE if stdin_pipe else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
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
    path_reason = _outside_workspace_path_reason(tokens, workspace_root=workspace_root, cwd=cwd)
    if path_reason is not None:
        return path_reason
    if cwd != workspace_root and workspace_root not in cwd.parents:
        return f"Blocked shell command outside the workspace: {cwd}"
    return None


def _classify_command(command: str) -> ShellClassification:
    tokens = _command_tokens(command)
    effective_tokens, wrappers = _effective_command_tokens(tokens)
    lowered = " ".join(token.lower() for token in effective_tokens).strip()
    if not effective_tokens:
        return ShellClassification("other", "Run a shell command", ToolRiskLevel.EXEC, False)
    tokens = effective_tokens
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
    if wrappers and first == "test":
        return ShellClassification("test", "Run verification tests", ToolRiskLevel.EXEC, False)
    if first.startswith("python") and second == "-m" and third in {"unittest", "pytest"}:
        return ShellClassification("test", "Run verification tests", ToolRiskLevel.EXEC, False)
    if first in {"ruff", "flake8", "eslint"}:
        return ShellClassification("lint", "Run lint checks", ToolRiskLevel.EXEC, False)
    if wrappers and first == "lint":
        return ShellClassification("lint", "Run lint checks", ToolRiskLevel.EXEC, False)
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
    if first in {"npm", "pnpm", "yarn"} and (
        second == "lint" or (second == "run" and third == "lint")
    ):
        return ShellClassification("lint", "Run lint checks", ToolRiskLevel.EXEC, False)
    if first in {"make", "cargo", "go"} and second in {"build", "check"}:
        return ShellClassification("build", "Build project artifacts", ToolRiskLevel.EXEC, False)
    if wrappers and first == "build":
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
            default_session_profile="pty_session",
        )
    if wrappers and first in {"dev", "start", "serve", "watch"}:
        return ShellClassification(
            "dev-server",
            "Start a long-running dev server",
            ToolRiskLevel.EXEC,
            False,
            background_required=True,
            default_session_profile="pty_session",
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
            default_session_profile="pty_session",
        )
    if first in {"python", "python3", "node", "irb"} and len(tokens) == 1:
        return ShellClassification(
            "interactive",
            "Start an interactive shell workload",
            ToolRiskLevel.EXEC,
            False,
            default_session_profile="pty_session",
        )
    if first in {"mkdir", "touch", "mv", "cp", "rm", "chmod"} or any(
        marker in lowered for marker in (" > ", " >> ", "| tee ", "sed -i")
    ):
        return ShellClassification("write", "Modify workspace files", ToolRiskLevel.WRITE, False, high_risk=True)
    if wrappers:
        return ShellClassification("other", "Run a wrapper-based shell command", ToolRiskLevel.EXEC, False, high_risk=True)
    return ShellClassification("other", "Run a shell command", ToolRiskLevel.EXEC, False)


def _effective_command_tokens(tokens: list[str]) -> tuple[list[str], tuple[str, ...]]:
    if not tokens:
        return [], ()
    wrappers: list[str] = []
    effective = list(tokens)
    while len(effective) >= 2 and effective[0].lower() in {"uv", "poetry"} and effective[1].lower() == "run":
        wrappers.extend(effective[:2])
        effective = effective[2:]
    if len(effective) >= 3 and effective[0].lower() in {"npm", "pnpm", "yarn"} and effective[1].lower() == "run":
        wrappers.extend(effective[:2])
        effective = [effective[2], *effective[3:]]
    elif len(effective) >= 2 and effective[0].lower() in {"npm", "pnpm", "yarn"}:
        wrappers.append(effective[0])
        effective = [effective[1], *effective[2:]]
    return effective, tuple(wrappers)


def _not_confinable_reason(command: str, *, tokens: list[str]) -> str | None:
    inline_reason = _inline_code_reason(tokens)
    if inline_reason is not None:
        return inline_reason.replace("Blocked", "Not-confinable", 1)
    lowered = command.lower()
    opaque_markers = ("$(", "`", " xargs ", " eval ", " -exec ")
    if any(marker in lowered for marker in opaque_markers):
        return "Not-confinable shell command because compound shell control flow obscures workspace boundaries."
    return None


def _resolve_command_policy(command: str, *, workspace_root: Path, cwd: Path) -> ShellCommandPolicy:
    classification = _classify_command(command)
    tokens = _command_tokens(command)
    effective_tokens, wrappers = _effective_command_tokens(tokens)
    effective_command = " ".join(effective_tokens) if effective_tokens else command
    blocked_reason = _blocked_command_reason(command, workspace_root=workspace_root, cwd=cwd)
    if blocked_reason is not None:
        return ShellCommandPolicy(
            classification=classification,
            outcome="blocked",
            reason=blocked_reason,
            effective_command=effective_command,
            wrappers=wrappers,
            confinement_confidence="blocked",
        )
    not_confinable_reason = _not_confinable_reason(command, tokens=tokens)
    if not_confinable_reason is not None:
        return ShellCommandPolicy(
            classification=classification,
            outcome="not_confinable",
            reason=not_confinable_reason,
            effective_command=effective_command,
            wrappers=wrappers,
            confinement_confidence="not_confinable",
        )
    if classification.high_risk or classification.name in {"git-write", "write", "other"}:
        return ShellCommandPolicy(
            classification=classification,
            outcome="requires_high_risk_approval",
            reason=f"{classification.summary} with explicit high-risk approval.",
            effective_command=effective_command,
            wrappers=wrappers,
            confinement_confidence="workspace",
        )
    return ShellCommandPolicy(
        classification=classification,
        outcome="allowed",
        reason=classification.summary,
        effective_command=effective_command,
        wrappers=wrappers,
        confinement_confidence="workspace",
    )


def _policy_for_presentation(command: str) -> ShellCommandPolicy:
    cwd = Path.cwd()
    return _resolve_command_policy(command, workspace_root=cwd, cwd=cwd)


def _unsupported_shell_reason(command: str) -> str | None:
    tokens = _command_tokens(command)
    first = tokens[0].lower() if tokens else ""
    if first in {"vim", "vi", "nvim", "nano", "less", "more", "top", "htop", "watch", "tmux", "screen", "man"}:
        return (
            "Unsupported shell workload for the code assistant shell: full-screen editors, pagers, "
            f"monitors, and multiplexers such as '{first}' remain intentionally unsupported."
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
    policy: ShellCommandPolicy,
    status: str,
    background_reason: str | None,
    job_id: str | None,
    shell_session_id: str | None = None,
    session_mode: str = "oneshot",
    session_profile: str = "oneshot",
    terminal_mode: str = "none",
    session_status: str | None = None,
    recovery_state: str | None = None,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    timed_out: bool,
    session_output: str = "",
    session_output_sequence: int = 0,
    session_output_complete: bool = True,
    unsupported_shell: bool = False,
    unsupported_reason: str | None = None,
    sidecar_dir: str | None = None,
    sidecar_output_path: str | None = None,
    broker_socket_path: str | None = None,
    broker_pid: int | None = None,
    error_kind: str | None = None,
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
        "classification": policy.classification.name,
        "risk_level": policy.classification.risk_level.value,
        "risk_summary": policy.classification.summary,
        "high_risk": policy.classification.high_risk,
        "command_policy": policy.outcome,
        "command_policy_reason": policy.reason,
        "effective_command": policy.effective_command,
        "wrapper_chain": list(policy.wrappers),
        "confinement_confidence": policy.confinement_confidence,
        "status": status,
        "run_in_background": background_reason is not None,
        "background_reason": background_reason,
        "job_id": job_id,
        "shell_session_id": shell_session_id,
        "session_mode": session_mode,
        "session_profile": session_profile,
        "terminal_mode": terminal_mode,
        "session_status": session_status,
        "recovery_state": recovery_state,
        "session_output": session_output,
        "session_output_sequence": session_output_sequence,
        "session_output_complete": session_output_complete,
        "unsupported_shell": unsupported_shell,
        "unsupported_reason": unsupported_reason,
        "sidecar_dir": sidecar_dir,
        "sidecar_output_path": sidecar_output_path,
        "broker_socket_path": broker_socket_path,
        "broker_pid": broker_pid,
        "error_kind": error_kind,
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
            policy=policy,
            status=status,
            exit_code=exit_code,
            background_reason=background_reason,
            job_id=job_id,
            shell_session_id=shell_session_id,
            session_mode=session_mode,
            session_profile=session_profile,
            terminal_mode=terminal_mode,
            session_status=session_status,
            recovery_state=recovery_state,
            session_output=session_output,
            session_output_complete=session_output_complete,
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            timed_out=timed_out,
            unsupported_shell=unsupported_shell,
            unsupported_reason=unsupported_reason,
            error_kind=error_kind,
        ),
    }


def _output_summary(
    *,
    action: str,
    command: str,
    policy: ShellCommandPolicy,
    status: str,
    exit_code: int | None,
    background_reason: str | None,
    job_id: str | None,
    shell_session_id: str | None,
    session_mode: str,
    session_profile: str,
    terminal_mode: str,
    session_status: str | None,
    recovery_state: str | None,
    session_output: str,
    session_output_complete: bool,
    stdout_preview: str,
    stderr_preview: str,
    timed_out: bool,
    unsupported_shell: bool,
    unsupported_reason: str | None,
    error_kind: str | None,
) -> str:
    if unsupported_shell:
        return unsupported_reason or "Unsupported shell workload."
    if action == "start" and shell_session_id is not None and job_id is not None:
        return f"Started {session_profile} shell session {shell_session_id} as job {job_id}."
    if action == "send" and shell_session_id is not None:
        return f"Sent stdin to shell session {shell_session_id}."
    if action == "interrupt" and shell_session_id is not None:
        return f"Sent interrupt to shell session {shell_session_id}."
    if action == "stop" and shell_session_id is not None and session_status in {"stopped", "completed", "command_failed", "interrupted"}:
        return f"Stopped shell session {shell_session_id} with status {session_status}."
    if action == "read" and shell_session_id is not None:
        detail = _first_non_empty_line(session_output) or _first_non_empty_line(stdout_preview) or _first_non_empty_line(stderr_preview)
        if detail:
            return detail
        if session_output_complete:
            return f"Shell session {shell_session_id} is {session_status or status}."
        return f"Shell session {shell_session_id} is still running."
    if status == "running" and session_mode == "session" and shell_session_id is not None:
        return f"Shell session {shell_session_id} is running ({session_profile}, {terminal_mode})."
    if status == "running" and job_id is not None:
        return f"{policy.classification.summary} in background as job {job_id} ({background_reason or 'requested'})."
    if status == "blocked":
        return stderr_preview or f"Blocked command: {command}"
    if status == "not_confinable":
        return stderr_preview or f"Not-confinable command: {command}"
    if status == "unsupported":
        return stderr_preview or f"Unsupported shell workload: {command}"
    if status == "broker_failed":
        return stderr_preview or "Shell broker failed before the command could complete."
    if status == "spawn_failed":
        return stderr_preview or "Shell process launch failed."
    if status in {"orphaned", "recovery_unavailable"}:
        return f"Shell recovery ended in {status.replace('_', ' ')}."
    if timed_out:
        return stderr_preview or f"{policy.classification.summary} timed out."
    if status == "stopped":
        return f"{policy.classification.summary} stopped."
    if status == "interrupted":
        return f"{policy.classification.summary} was interrupted."
    if status == "command_failed":
        detail = _first_non_empty_line(stderr_preview) or _first_non_empty_line(stdout_preview)
        suffix = f" (exit {exit_code})" if exit_code is not None else ""
        return detail or f"{policy.classification.summary} failed{suffix}."
    if error_kind == "policy_denied":
        return stderr_preview or policy.reason
    detail = _first_non_empty_line(stdout_preview) or _first_non_empty_line(stderr_preview)
    return detail or f"{policy.classification.summary} completed successfully."


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


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_risk_level(value: Any, *, fallback: ToolRiskLevel) -> ToolRiskLevel:
    try:
        return ToolRiskLevel(str(value))
    except ValueError:
        return fallback


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
