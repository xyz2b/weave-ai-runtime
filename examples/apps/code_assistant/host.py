from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from weavert.child_result_projection import project_child_run_record
from weavert.contracts import MessageRole, ToolResultBlock
from weavert.definitions import ToolCallStatus
from weavert_hosts_reference import SdkHostRuntime
from weavert.permissions import PermissionOutcome, PermissionRequest
from weavert.definitions import PermissionBehavior
from weavert.turn_engine.engine import TurnStreamEventType


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    session_id: str
    target: str
    name: str
    approved: bool
    summary: str
    payload: dict[str, Any]


@dataclass(slots=True)
class CodeAssistantHost(SdkHostRuntime):
    auto_approve: bool = False
    input_reader: Callable[[str], str] = input
    output_writer: Callable[[str], Any] = print
    interactive_shell: bool = False
    approvals: list[ApprovalRecord] = field(default_factory=list)
    terminal_events: list[dict[str, Any]] = field(default_factory=list)
    child_run_events: list[dict[str, Any]] = field(default_factory=list)
    tool_activity: list[dict[str, Any]] = field(default_factory=list)
    job_watch_events: list[dict[str, Any]] = field(default_factory=list)
    task_watch_events: list[dict[str, Any]] = field(default_factory=list)
    workflow_events: list[dict[str, Any]] = field(default_factory=list)
    _tool_use_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    _active_session_id: str | None = None
    _prompt_boundary: str | None = None
    _waiting_for_input: bool = False
    _last_job_signatures: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    _last_task_signature: tuple[Any, ...] | None = None
    _last_workflow_signature: tuple[Any, ...] | None = None

    def activate_session(self, session_id: str) -> None:
        self._active_session_id = session_id
        self._last_job_signatures = {}
        self._last_task_signature = None
        self._last_workflow_signature = None

    def begin_input_wait(self, prompt_boundary: str) -> None:
        self._prompt_boundary = prompt_boundary
        self._waiting_for_input = True

    def end_input_wait(self) -> None:
        self._waiting_for_input = False

    def render_job_watch_update(self, *, session_id: str, jobs: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> None:
        if self._active_session_id is not None and session_id != self._active_session_id:
            return
        current_signatures: dict[str, tuple[Any, ...]] = {}
        lines: list[str] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            job_id = str(job.get("job_id") or "")
            if not job_id:
                continue
            signature = _job_signature(job)
            current_signatures[job_id] = signature
            if self._last_job_signatures.get(job_id) == signature:
                continue
            event = {
                "session_id": session_id,
                "job_id": job_id,
                "status": str(job.get("status") or "unknown"),
                "summary": str(job.get("summary") or "<job>"),
                "metadata": dict(job.get("metadata")) if isinstance(job.get("metadata"), dict) else {},
                "result": dict(job.get("result")) if isinstance(job.get("result"), dict) else {},
            }
            self.job_watch_events.append(event)
            lines.extend(_job_event_lines(event))
        self._last_job_signatures = current_signatures
        if lines:
            self._write_lines(lines, async_event=True)

    def render_task_watch_update(self, *, session_id: str, task_list: dict[str, Any]) -> None:
        if self._active_session_id is not None and session_id != self._active_session_id:
            return
        signature = _task_signature(task_list)
        if signature == self._last_task_signature:
            return
        self._last_task_signature = signature
        event = {
            "session_id": session_id,
            "task_list_id": task_list.get("list_id") or task_list.get("task_list_id"),
            "tasks": list(task_list.get("tasks", ())) if isinstance(task_list.get("tasks"), list) else [],
        }
        self.task_watch_events.append(event)
        summary = _task_watch_summary(task_list)
        self._write_lines([f"[tasks:update] {summary}"], async_event=True)

    def render_workflow_state(
        self,
        *,
        session_id: str,
        ledger: dict[str, Any],
        warning: str | None = None,
        force: bool = False,
    ) -> None:
        if self._active_session_id is not None and session_id != self._active_session_id:
            return
        signature = (
            ledger.get("current_state"),
            ledger.get("change_revision"),
            ledger.get("verified_revision"),
            ledger.get("reviewed_revision"),
        )
        if not force and signature == self._last_workflow_signature and warning is None:
            return
        self._last_workflow_signature = signature
        event = {"session_id": session_id, "ledger": dict(ledger), "warning": warning}
        self.workflow_events.append(event)
        lines = [
            (
                f"[workflow] {ledger.get('current_state', 'unknown')} "
                f"(change={ledger.get('change_revision', 0)}, "
                f"verified={ledger.get('verified_revision', 0)}, "
                f"reviewed={ledger.get('reviewed_revision', 0)})"
            )
        ]
        if warning:
            lines.append(f"[workflow:warning] {warning}")
        self._write_lines(lines, async_event=True)

    def _write_lines(self, lines: list[str], *, async_event: bool = False) -> None:
        for line in lines:
            self.output_writer(line)
        if async_event:
            self._render_prompt_boundary()

    def _render_prompt_boundary(self) -> None:
        if self.interactive_shell and self._waiting_for_input and self._prompt_boundary:
            self.output_writer(f"[prompt] {self._prompt_boundary}")

    async def request_permission(self, request: PermissionRequest) -> PermissionOutcome:
        summary = _permission_summary(request)
        if self.auto_approve:
            approved = True
            self.output_writer(f"[approval:auto] {request.name} {summary}")
        else:
            answer = await asyncio.to_thread(
                self.input_reader,
                f"[approval] {request.name} {summary} [y/N] ",
            )
            approved = answer.strip().lower() in {"y", "yes"}
        self.approvals.append(
            ApprovalRecord(
                session_id=request.session_id,
                target=request.target.value,
                name=request.name,
                approved=approved,
                summary=summary,
                payload=dict(request.payload),
            )
        )
        return PermissionOutcome(
            behavior=PermissionBehavior.ALLOW if approved else PermissionBehavior.DENY,
            message=request.message,
            updated_input=dict(request.payload),
            details={"host": self.name, "approved": approved},
            source="host",
        )

    async def emit_notification(self, message) -> None:
        await SdkHostRuntime.emit_notification(self, message)
        if message.text:
            level = str(message.metadata.get("level", "info"))
            self.output_writer(f"[notification:{level}] {message.text}")

    async def emit_turn_event(self, session_id: str, event) -> None:
        await SdkHostRuntime.emit_turn_event(self, session_id, event)
        if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
            self._render_message_event(event.message)
            return
        if event.event_type == TurnStreamEventType.TOOL_LIFECYCLE and event.tool_event is not None:
            self._record_tool_lifecycle(session_id=session_id, event=event.tool_event)
            return
        if event.event_type == TurnStreamEventType.CHILD_RUN and event.child_run is not None:
            projection = project_child_run_record(event.child_run)
            projection["session_id"] = session_id
            self.child_run_events.append(projection)
            self._write_lines(
                [f"[child:{projection['status']}] {projection['agent']}: {projection['summary']}"]
            )
        elif event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
            projected = {
                "session_id": session_id,
                "stop_reason": event.terminal.stop_reason,
                "error": event.terminal.error,
                "metadata": dict(event.terminal.metadata),
            }
            self.terminal_events.append(projected)
            self._render_terminal_event(projected)

    def _render_message_event(self, message) -> None:
        if message.role == MessageRole.ASSISTANT:
            text = message.text.strip()
            if text:
                self._write_lines([f"assistant: {text}"])
            return
        if message.role != MessageRole.USER:
            return
        tool_results = message.metadata.get("tool_results")
        if not isinstance(tool_results, list):
            return
        blocks = {
            block.tool_use_id: block
            for block in message.content
            if isinstance(block, ToolResultBlock)
        }
        for entry in tool_results:
            if not isinstance(entry, dict):
                continue
            tool_use_id = str(entry.get("tool_use_id") or "")
            block = blocks.get(tool_use_id)
            self._render_tool_result(entry=entry, block=block)

    def _record_tool_lifecycle(self, *, session_id: str, event: Any) -> None:
        kind = str(getattr(event, "kind", ""))
        tool_use_id = str(getattr(event, "tool_use_id", ""))
        details = self._tool_use_details.setdefault(tool_use_id, {"session_id": session_id})
        if hasattr(event, "canonical_tool_name") and getattr(event, "canonical_tool_name") is not None:
            details["tool_name"] = getattr(event, "canonical_tool_name")
        if hasattr(event, "classifier_input") and getattr(event, "classifier_input") is not None:
            classifier_input = getattr(event, "classifier_input")
            details["summary"] = classifier_input.summary
        if kind == "execution_started":
            tool_name = str(details.get("tool_name") or "tool")
            summary = str(details.get("summary") or tool_name)
            if tool_name in {"bash", "edit", "write", "skill"}:
                self._write_lines([f"[tool] {summary}"])
        self.tool_activity.append(
            {
                "session_id": session_id,
                "tool_use_id": tool_use_id,
                "kind": kind,
                "tool_name": details.get("tool_name"),
                "summary": details.get("summary"),
            }
        )

    def _render_tool_result(self, *, entry: dict[str, Any], block: ToolResultBlock | None) -> None:
        tool_name = str(entry.get("tool_name") or self._tool_use_details.get(str(entry.get("tool_use_id") or ""), {}).get("tool_name") or "tool")
        status = str(entry.get("status") or "unknown")
        content = block.content if block is not None else None
        if tool_name == "bash" and isinstance(content, dict):
            self._render_bash_result(content=content, status=status)
            return
        if tool_name == "edit" and isinstance(content, dict):
            file_path = _relative_path(content.get("file_path"))
            self._write_lines([f"[edit:{status}] {file_path}"])
            return
        if tool_name == "write" and isinstance(content, dict):
            file_path = _relative_path(content.get("file_path"))
            bytes_written = content.get("bytes_written")
            detail = f" ({bytes_written} bytes)" if isinstance(bytes_written, int) else ""
            self._write_lines([f"[write:{status}] {file_path}{detail}"])
            return
        if tool_name == "skill" and isinstance(content, dict):
            skill_name = str(content.get("skill") or "skill")
            self._write_lines([f"[skill:{status}] {skill_name}"])
            return
        if tool_name == "agent" and isinstance(content, dict):
            agent_name = str(content.get("agent") or "agent")
            summary = str(content.get("summary") or content.get("status") or "").strip()
            suffix = f": {summary}" if summary else ""
            self._write_lines([f"[agent:{status}] {agent_name}{suffix}"])
            return
        summary = status
        if isinstance(content, dict) and isinstance(content.get("output_summary"), str):
            summary = content["output_summary"]
        self._write_lines([f"[tool:{tool_name}:{status}] {summary}"])

    def _render_bash_result(self, *, content: dict[str, Any], status: str) -> None:
        action = str(content.get("action") or "exec")
        command = str(content.get("command") or "").strip()
        classification = str(content.get("classification") or "other")
        output_summary = str(content.get("output_summary") or "").strip()
        job_id = str(content.get("job_id") or "").strip() or None
        shell_session_id = str(content.get("shell_session_id") or "").strip() or None
        session_mode = str(content.get("session_mode") or "oneshot")
        session_output = str(content.get("session_output") or "")
        exit_code = content.get("exit_code")
        shell_status = str(content.get("status") or status)
        prefix = "ok"
        if shell_status == "running":
            prefix = "running"
        elif shell_status in {"failed", "blocked"} or status == ToolCallStatus.ERROR.value:
            prefix = "failed"
        elif shell_status == "stopped":
            prefix = "stopped"
        elif shell_status == "unsupported":
            prefix = "unsupported"
        exit_suffix = f", exit={exit_code}" if isinstance(exit_code, int) else ""
        job_suffix = f", job={job_id}" if job_id is not None else ""
        lines: list[str] = []
        if session_mode == "session" and shell_session_id is not None:
            lines.append(
                f"[bash:{prefix}:{action}] session={shell_session_id}{exit_suffix}{job_suffix} {command}".rstrip()
            )
            lines.extend(f"[shell:output] {line}" for line in _preview_output_lines(session_output))
        else:
            lines.append(
                f"[bash:{prefix}] {classification}{exit_suffix}{job_suffix} {command}".rstrip()
            )
        if output_summary:
            lines.append(f"[bash:summary] {output_summary}")
        self._write_lines(lines)

    def _render_terminal_event(self, event: dict[str, Any]) -> None:
        metadata = event["metadata"]
        failure_class = str(metadata.get("failure_class") or "").strip()
        if failure_class and failure_class != "none":
            error_text = str(event.get("error") or metadata.get("error") or failure_class)
            self._write_lines([f"[provider-failure:{failure_class}] {error_text}"])
            return
        stop_reason = str(event.get("stop_reason") or "").strip()
        if stop_reason in {"blocked", "interrupted"}:
            self._write_lines([f"[session:{stop_reason}] terminal stop reason: {stop_reason}"])


def _permission_summary(request: PermissionRequest) -> str:
    payload = dict(request.payload)
    if isinstance(payload.get("file_path"), str):
        return str(payload["file_path"])
    if isinstance(payload.get("command"), str):
        return str(payload["command"])
    if isinstance(payload.get("cwd"), str):
        return str(payload["cwd"])
    return request.message or request.name


def _relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "<unknown>"
    path = Path(value)
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _job_signature(job: dict[str, Any]) -> tuple[Any, ...]:
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    return (
        str(job.get("status") or "unknown"),
        str(metadata.get("session_status") or ""),
        str(metadata.get("output_sequence") or ""),
        str(metadata.get("recent_output_preview") or ""),
        str(result.get("output_summary") or ""),
    )


def _job_event_lines(event: dict[str, Any]) -> list[str]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    status = str(metadata.get("session_status") or event.get("status") or "unknown")
    job_id = str(event.get("job_id") or "<job>")
    summary = str(event.get("summary") or "<job>")
    kind = str(metadata.get("kind") or "").strip()
    shell_session_id = str(metadata.get("shell_session_id") or "").strip()
    lines = [f"[job:{status}] {shell_session_id or job_id}: {summary}"]
    recent_output = str(metadata.get("recent_output_preview") or "").strip()
    recent_stream = str(metadata.get("recent_output_stream") or "output")
    if recent_output and kind == "shell_session":
        lines.extend(f"[shell:{recent_stream}] {line}" for line in _preview_output_lines(recent_output))
    elif isinstance(result, dict) and isinstance(result.get("output_summary"), str):
        lines.append(f"[job:summary] {result['output_summary']}")
    return lines


def _task_signature(task_list: dict[str, Any]) -> tuple[Any, ...]:
    tasks = task_list.get("tasks", ())
    if not isinstance(tasks, list):
        return ()
    return tuple(
        (
            str(task.get("subject") or ""),
            str(task.get("status") or ""),
            str(task.get("readiness_state") or ""),
        )
        for task in tasks
        if isinstance(task, dict)
    )


def _task_watch_summary(task_list: dict[str, Any]) -> str:
    tasks = task_list.get("tasks", ())
    if not isinstance(tasks, list) or not tasks:
        return "no shared tasks yet"
    rendered: list[str] = []
    for task in tasks[:4]:
        if not isinstance(task, dict):
            continue
        readiness = str(task.get("readiness_state") or "").strip()
        readiness_suffix = f", {readiness}" if readiness else ""
        rendered.append(
            f"{task.get('subject', '<unnamed>')}[{task.get('status', 'unknown')}{readiness_suffix}]"
        )
    return "; ".join(rendered)


def _preview_output_lines(text: str) -> list[str]:
    preview = text.strip()
    if not preview:
        return []
    return [line for line in preview.splitlines()[:3] if line.strip()]


__all__ = ["ApprovalRecord", "CodeAssistantHost"]
