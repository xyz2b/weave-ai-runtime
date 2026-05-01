from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from weavert.child_result_projection import project_child_run_record
from weavert.contracts import MessageRole, ToolResultBlock
from weavert.definitions import ToolCallStatus
from weavert.hosts import SdkHostRuntime
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
    _tool_use_details: dict[str, dict[str, Any]] = field(default_factory=dict)

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
            self.output_writer(
                f"[child:{projection['status']}] {projection['agent']}: {projection['summary']}"
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
                self.output_writer(f"assistant: {text}")
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
                self.output_writer(f"[tool] {summary}")
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
            self.output_writer(f"[edit:{status}] {file_path}")
            return
        if tool_name == "write" and isinstance(content, dict):
            file_path = _relative_path(content.get("file_path"))
            bytes_written = content.get("bytes_written")
            detail = f" ({bytes_written} bytes)" if isinstance(bytes_written, int) else ""
            self.output_writer(f"[write:{status}] {file_path}{detail}")
            return
        if tool_name == "skill" and isinstance(content, dict):
            skill_name = str(content.get("skill") or "skill")
            self.output_writer(f"[skill:{status}] {skill_name}")
            return
        if tool_name == "agent" and isinstance(content, dict):
            agent_name = str(content.get("agent") or "agent")
            summary = str(content.get("summary") or content.get("status") or "").strip()
            suffix = f": {summary}" if summary else ""
            self.output_writer(f"[agent:{status}] {agent_name}{suffix}")
            return
        summary = status
        if isinstance(content, dict) and isinstance(content.get("output_summary"), str):
            summary = content["output_summary"]
        self.output_writer(f"[tool:{tool_name}:{status}] {summary}")

    def _render_bash_result(self, *, content: dict[str, Any], status: str) -> None:
        command = str(content.get("command") or "").strip()
        classification = str(content.get("classification") or "other")
        output_summary = str(content.get("output_summary") or "").strip()
        job_id = str(content.get("job_id") or "").strip() or None
        exit_code = content.get("exit_code")
        shell_status = str(content.get("status") or status)
        prefix = "ok"
        if shell_status == "running":
            prefix = "running"
        elif shell_status in {"failed", "blocked"} or status == ToolCallStatus.ERROR.value:
            prefix = "failed"
        elif shell_status == "stopped":
            prefix = "stopped"
        exit_suffix = f", exit={exit_code}" if isinstance(exit_code, int) else ""
        job_suffix = f", job={job_id}" if job_id is not None else ""
        self.output_writer(
            f"[bash:{prefix}] {classification}{exit_suffix}{job_suffix} {command}".rstrip()
        )
        if output_summary:
            self.output_writer(f"[bash:summary] {output_summary}")

    def _render_terminal_event(self, event: dict[str, Any]) -> None:
        metadata = event["metadata"]
        failure_class = str(metadata.get("failure_class") or "").strip()
        if failure_class and failure_class != "none":
            error_text = str(event.get("error") or metadata.get("error") or failure_class)
            self.output_writer(f"[provider-failure:{failure_class}] {error_text}")
            return
        stop_reason = str(event.get("stop_reason") or "").strip()
        if stop_reason in {"blocked", "interrupted"}:
            self.output_writer(f"[session:{stop_reason}] terminal stop reason: {stop_reason}")


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


__all__ = ["ApprovalRecord", "CodeAssistantHost"]
