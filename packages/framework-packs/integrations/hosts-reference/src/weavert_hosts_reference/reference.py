from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Sequence

from weavert.definitions import PermissionBehavior
from weavert.elicitation import ElicitationRequest, ElicitationResponse
from weavert.permissions import PermissionOutcome, PermissionRequest
from weavert.hosts.base import CallbackHostAdapter, NullHostAdapter

if TYPE_CHECKING:
    from weavert.contracts import RuntimeMessage
    from weavert.turn_engine.engine import TurnStreamEvent


@dataclass(slots=True)
class CliHostRuntime(NullHostAdapter):
    input_reader: Callable[[str], str] = input
    output_writer: Callable[[str], Any] = print
    turn_events: list["TurnStreamEvent"] = field(default_factory=list)
    extension_events: list[Any] = field(default_factory=list)

    async def request_permission(self, request: PermissionRequest) -> PermissionOutcome:
        prompt = f"[permission] {request.target.value}:{request.name} {request.message or 'Allow?'} [y/N] "
        answer = await asyncio.to_thread(self.input_reader, prompt)
        approved = answer.strip().lower() in {"y", "yes"}
        return PermissionOutcome(
            behavior=PermissionBehavior.ALLOW if approved else PermissionBehavior.DENY,
            message=request.message,
            updated_input=dict(request.payload),
            details={"host": self.name, "approved": approved},
            source="host",
        )

    async def request_elicitation(self, request: ElicitationRequest) -> ElicitationResponse:
        prompt = request.prompt
        if request.options:
            prompt = f"{prompt} ({', '.join(request.options)}) "
        response = await asyncio.to_thread(self.input_reader, prompt)
        return ElicitationResponse(response=response, source="host")

    async def emit_notification(self, message: "RuntimeMessage") -> None:
        await super().emit_notification(message)
        self.output_writer(message.text)

    async def emit_turn_event(self, session_id: str, event: "TurnStreamEvent") -> None:
        _ = session_id
        self.turn_events.append(event)

    async def emit_extension_event(self, event: Any) -> None:
        self.extension_events.append(event)


@dataclass(slots=True)
class SdkHostRuntime(CallbackHostAdapter):
    notifications: list["RuntimeMessage"] = field(default_factory=list)
    turn_events: list[tuple[str, "TurnStreamEvent"]] = field(default_factory=list)
    extension_events: list[Any] = field(default_factory=list)

    async def emit_notification(self, message: "RuntimeMessage") -> None:
        self.notifications.append(message)
        await CallbackHostAdapter.emit_notification(self, message)

    async def emit_turn_event(self, session_id: str, event: "TurnStreamEvent") -> None:
        self.turn_events.append((session_id, event))
        await CallbackHostAdapter.emit_turn_event(self, session_id, event)

    async def emit_extension_event(self, event: Any) -> None:
        self.extension_events.append(event)
        await CallbackHostAdapter.emit_extension_event(self, event)


__all__ = ["CliHostRuntime", "SdkHostRuntime"]
