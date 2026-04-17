from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol, Sequence

from ..definitions import PermissionBehavior
from ..elicitation import ElicitationRequest, ElicitationResponse
from ..permissions import PermissionOutcome, PermissionRequest, coerce_permission_outcome

if TYPE_CHECKING:
    from ..contracts import RuntimeMessage
    from ..turn_engine.engine import TurnStreamEvent


class HostRuntime(Protocol):
    name: str

    async def startup(self) -> None: ...

    async def ready(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def request_permission(self, request: PermissionRequest) -> PermissionOutcome: ...

    async def request_elicitation(self, request: ElicitationRequest) -> ElicitationResponse: ...

    def current_notifications(self) -> Sequence["RuntimeMessage"]: ...

    async def emit_notification(self, message: "RuntimeMessage") -> None: ...

    async def emit_turn_event(self, session_id: str, event: "TurnStreamEvent") -> None: ...


class HostAdapter(HostRuntime, Protocol):
    pass


class HostFactory(Protocol):
    def __call__(
        self,
        name: str,
        config: Mapping[str, Any],
        kernel: Any,
    ) -> HostAdapter: ...


@dataclass(slots=True)
class NullHostAdapter:
    name: str = "null"
    _notifications: list["RuntimeMessage"] = field(default_factory=list)

    async def startup(self) -> None:
        return None

    async def ready(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def request_permission(self, request: PermissionRequest) -> PermissionOutcome:
        return PermissionOutcome(
            behavior=PermissionBehavior.DENY,
            message=request.message or "Permission required",
            updated_input=dict(request.payload),
            details={"host": self.name},
            source="host",
        )

    async def request_elicitation(self, request: ElicitationRequest) -> ElicitationResponse:
        raise RuntimeError(f"No elicitation handler is configured for host '{self.name}'")

    def current_notifications(self) -> tuple["RuntimeMessage", ...]:
        return tuple(self._notifications)

    async def emit_notification(self, message: "RuntimeMessage") -> None:
        self._notifications.append(message)

    async def emit_turn_event(self, session_id: str, event: "TurnStreamEvent") -> None:
        _ = session_id, event
        return None


@dataclass(slots=True)
class CallbackHostAdapter:
    name: str = "compat"
    permission_handler: Any = None
    ask_user_handler: Any = None
    notification_provider: Callable[[], Sequence["RuntimeMessage"]] | None = None
    notification_sink: Callable[["RuntimeMessage"], Any] | None = None
    turn_event_sink: Callable[[str, "TurnStreamEvent"], Any] | None = None
    lifecycle: list[str] = field(default_factory=list)

    async def startup(self) -> None:
        self.lifecycle.append("startup")

    async def ready(self) -> None:
        self.lifecycle.append("ready")

    async def shutdown(self) -> None:
        self.lifecycle.append("shutdown")

    async def request_permission(self, request: PermissionRequest) -> PermissionOutcome:
        if self.permission_handler is None:
            return await NullHostAdapter(name=self.name).request_permission(request)
        outcome = await _maybe_await(
            self.permission_handler(
                request.metadata.get("definition"),
                request.payload,
                request.metadata.get("decision"),
                request.metadata.get("runtime_context"),
            )
        )
        return coerce_permission_outcome(outcome)

    async def request_elicitation(self, request: ElicitationRequest) -> ElicitationResponse:
        if self.ask_user_handler is None:
            raise RuntimeError(f"No elicitation handler is configured for host '{self.name}'")
        response = await _maybe_await(self.ask_user_handler(request.prompt, list(request.options) or None))
        if isinstance(response, ElicitationResponse):
            return response
        return ElicitationResponse(response=response)

    def current_notifications(self) -> tuple["RuntimeMessage", ...]:
        if self.notification_provider is None:
            return ()
        return tuple(self.notification_provider())

    async def emit_notification(self, message: "RuntimeMessage") -> None:
        if self.notification_sink is None:
            return None
        await _maybe_await(self.notification_sink(message))

    async def emit_turn_event(self, session_id: str, event: "TurnStreamEvent") -> None:
        if self.turn_event_sink is None:
            return None
        await _maybe_await(self.turn_event_sink(session_id, event))


@dataclass(slots=True)
class BoundHostRuntime:
    kernel: Any
    host: HostAdapter
    runtime: Any = None
    services: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.services is not None and hasattr(self.services, "bind_host"):
            self.services.bind_host(self.host)

    async def startup(self) -> None:
        await self.host.startup()

    async def ready(self) -> None:
        await self.host.ready()

    async def shutdown(self) -> None:
        await self.host.shutdown()

    def create_session(self, **kwargs: Any) -> Any:
        if self.services is not None and hasattr(self.services, "bind_host"):
            self.services.bind_host(self.host)
        return self.runtime.create_session(**kwargs)

    def resolve_session_invocations(self, *args: Any, **kwargs: Any) -> Any:
        if self.services is not None and hasattr(self.services, "bind_host"):
            self.services.bind_host(self.host)
        return self.runtime.resolve_session_invocations(*args, **kwargs)

    def visible_invocations(self, *args: Any, **kwargs: Any) -> Any:
        if self.services is not None and hasattr(self.services, "bind_host"):
            self.services.bind_host(self.host)
        return self.runtime.visible_invocations(*args, **kwargs)

    def invocation_diagnostics(self, *args: Any, **kwargs: Any) -> Any:
        if self.services is not None and hasattr(self.services, "bind_host"):
            self.services.bind_host(self.host)
        return self.runtime.invocation_diagnostics(*args, **kwargs)

    async def run_prompt(self, *args: Any, **kwargs: Any) -> Any:
        if self.services is not None and hasattr(self.services, "bind_host"):
            self.services.bind_host(self.host)
        return await self.runtime.run_prompt(*args, **kwargs)

    async def stream_prompt(self, *args: Any, **kwargs: Any):
        if self.services is not None and hasattr(self.services, "bind_host"):
            self.services.bind_host(self.host)
        async for event in self.runtime.stream_prompt(*args, **kwargs):
            yield event


__all__ = [
    "BoundHostRuntime",
    "CallbackHostAdapter",
    "HostAdapter",
    "HostFactory",
    "HostRuntime",
    "NullHostAdapter",
]


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
