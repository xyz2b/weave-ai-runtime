from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from weavert.hosts import SdkHostRuntime
from weavert.permissions import PermissionOutcome, PermissionRequest
from weavert.definitions import PermissionBehavior
from weavert.turn_engine.engine import TurnStreamEventType


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
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
    approvals: list[ApprovalRecord] = field(default_factory=list)
    terminal_events: list[dict[str, Any]] = field(default_factory=list)
    child_run_events: list[dict[str, Any]] = field(default_factory=list)

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
            self.output_writer(f"[notification] {message.text}")

    async def emit_turn_event(self, session_id: str, event) -> None:
        await SdkHostRuntime.emit_turn_event(self, session_id, event)
        if event.event_type == TurnStreamEventType.CHILD_RUN and event.child_run is not None:
            self.child_run_events.append(
                {
                    "session_id": session_id,
                    "agent": event.child_run.agent_name,
                    "status": event.child_run.status.value,
                    "summary": event.child_run.messages[-1].text if event.child_run.messages else "",
                    "run_id": event.child_run.run_id,
                }
            )
        elif event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
            self.terminal_events.append(
                {
                    "session_id": session_id,
                    "stop_reason": event.terminal.stop_reason,
                    "error": event.terminal.error,
                    "metadata": dict(event.terminal.metadata),
                }
            )


def _permission_summary(request: PermissionRequest) -> str:
    payload = dict(request.payload)
    if isinstance(payload.get("file_path"), str):
        return str(payload["file_path"])
    if isinstance(payload.get("command"), str):
        return str(payload["command"])
    if isinstance(payload.get("cwd"), str):
        return str(payload["cwd"])
    return request.message or request.name


__all__ = ["ApprovalRecord", "CodeAssistantHost"]
