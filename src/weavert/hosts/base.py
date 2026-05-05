from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol, Sequence

from ..contracts import utc_now
from ..definitions import PermissionBehavior
from ..elicitation import ElicitationRequest, ElicitationResponse
from ..hooks import (
    ConfiguredHookRegistrar,
    HookDispatchTraceQuery,
    HookInventoryQuery,
    HookRegistrationRequest,
    HookScopeLifetime,
    HookSourceKind,
    build_configured_hook_registrar,
    is_advanced_phase,
)
from ..permissions import PermissionOutcome, PermissionRequest, coerce_permission_outcome
if TYPE_CHECKING:
    from ..contracts import RuntimeMessage
    from ..turn_engine.engine import TurnStreamEvent


@dataclass(frozen=True, slots=True)
class HostExtensionEvent:
    namespace: str
    event_type: str
    event_id: str
    occurred_at: Any = field(default_factory=utc_now)
    schema_version: str = "1.0"
    correlation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at.isoformat(),
            "correlation_id": self.correlation_id,
            "payload": dict(self.payload),
        }


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

    async def emit_extension_event(self, event: HostExtensionEvent) -> None: ...


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

    async def emit_extension_event(self, event: HostExtensionEvent) -> None:
        _ = event
        return None


@dataclass(slots=True)
class CallbackHostAdapter:
    name: str = "compat"
    permission_handler: Any = None
    ask_user_handler: Any = None
    notification_provider: Callable[[], Sequence["RuntimeMessage"]] | None = None
    notification_sink: Callable[["RuntimeMessage"], Any] | None = None
    turn_event_sink: Callable[[str, "TurnStreamEvent"], Any] | None = None
    extension_event_sink: Callable[[HostExtensionEvent], Any] | None = None
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

    async def emit_extension_event(self, event: HostExtensionEvent) -> None:
        if self.extension_event_sink is None:
            return None
        await _maybe_await(self.extension_event_sink(event))


@dataclass(slots=True)
class BoundHostRuntime:
    kernel: Any
    host: HostAdapter
    runtime: Any = None
    services: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _host_started: bool = False
    _host_ready: bool = False
    _managed_sessions: dict[str, Any] = field(default_factory=dict)
    _managed_session_owners: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._bind_host()

    async def __aenter__(self) -> "BoundHostRuntime":
        await self.startup()
        await self.ready()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        _ = exc_type, exc, tb
        await self.shutdown()

    async def startup(self) -> None:
        self._bind_host()
        if self._host_started:
            return
        await self.host.startup()
        self._host_started = True

    async def ready(self) -> None:
        self._bind_host()
        if not self._host_started:
            await self.startup()
        if self._host_ready:
            return
        await self.host.ready()
        if self.services is not None and hasattr(self.services, "wait_until_runtime_ready"):
            await self.services.wait_until_runtime_ready()
        self._host_ready = True

    async def shutdown(self) -> None:
        self._bind_host()
        errors: list[Exception] = []
        managed_sessions = tuple(self._managed_sessions.values())
        self.metadata["managed_shutdown_order"] = [
            session.state.session_id for session in managed_sessions if hasattr(session, "state")
        ]
        for session in managed_sessions:
            try:
                await session.close(final_status=_managed_session_close_status(session))
            except Exception as exc:  # pragma: no cover - defensive cleanup path
                errors.append(exc)
                self.metadata.setdefault("managed_session_shutdown_errors", []).append(str(exc))
        if self._host_started or self._host_ready:
            try:
                await self.host.shutdown()
            except Exception as exc:  # pragma: no cover - defensive cleanup path
                errors.append(exc)
                self.metadata.setdefault("managed_session_shutdown_errors", []).append(str(exc))
        self._host_started = False
        self._host_ready = False
        if errors:
            raise errors[0]

    def create_session(self, **kwargs: Any) -> Any:
        self._bind_host()
        self._ensure_managed_session_id_available(kwargs.get("session_id"))
        session = self.runtime.create_session(
            **kwargs,
            close_callback=self._on_managed_session_close,
        )
        self._register_managed_session(session, owner="bound")
        return session

    def resolve_session_invocations(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return self.runtime.resolve_session_invocations(*args, **kwargs)

    def visible_invocations(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return self.runtime.visible_invocations(*args, **kwargs)

    def invocation_diagnostics(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return self.runtime.invocation_diagnostics(*args, **kwargs)

    def resolve_host_facet(self, name: str) -> Any:
        self._bind_host()
        return self.runtime.resolve_host_facet(name)

    async def resolve_task_list_id(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.resolve_task_list_id(*args, **kwargs)

    async def list_task_lists(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.list_task_lists(*args, **kwargs)

    async def create_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.create_task(*args, **kwargs)

    async def get_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.get_task(*args, **kwargs)

    async def update_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.update_task(*args, **kwargs)

    async def claim_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.claim_task(*args, **kwargs)

    async def release_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.release_task(*args, **kwargs)

    async def assign_next_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.assign_next_task(*args, **kwargs)

    async def block_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.block_task(*args, **kwargs)

    async def unblock_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.unblock_task(*args, **kwargs)

    async def archive_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.archive_task(*args, **kwargs)

    async def unarchive_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.unarchive_task(*args, **kwargs)

    async def delete_task(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.delete_task(*args, **kwargs)

    async def get_task_list(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.get_task_list(*args, **kwargs)

    async def watch_task_list(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.watch_task_list(*args, **kwargs)

    async def list_jobs(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.list_jobs(*args, **kwargs)

    async def get_job(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.get_job(*args, **kwargs)

    async def watch_jobs(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.watch_jobs(*args, **kwargs)

    async def stop_job(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        return await self.runtime.stop_job(*args, **kwargs)

    def bind_hook_callback(self, name: str, handler: Any) -> None:
        self._bind_host()
        self.services.hook_bus.bind_callback(name, handler)

    @property
    def hooks(self) -> ConfiguredHookRegistrar:
        self._bind_host()
        return build_configured_hook_registrar(
            bus=self.services.hook_bus,
            source_kind=HookSourceKind.HOST_API,
            owner=lambda: f"host:{self.host.name}",
            source_ref=lambda: self.host.name,
            session_id=None,
            turn_id=None,
            default_scope_lifetime=HookScopeLifetime.SESSION_TEMPLATE,
            list_hooks=self.list_hooks,
            list_hook_dispatch_traces=self.list_hook_dispatch_traces,
        )

    def register_hook(
        self,
        request: HookRegistrationRequest | Mapping[str, Any],
    ) -> Any:
        if isinstance(request, HookRegistrationRequest):
            if is_advanced_phase(request.phase):
                return self.hooks.advanced.raw.register(request)
        elif is_advanced_phase(str(request.get("phase") or request.get("name") or "")):
            return self.hooks.advanced.raw.register(request)
        return self.hooks.raw.register(request)

    def list_hooks(
        self,
        query: HookInventoryQuery | Mapping[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        self._bind_host()
        return self.services.hook_bus.list_hooks(query)

    def list_hook_dispatch_traces(
        self,
        query: HookDispatchTraceQuery | Mapping[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        self._bind_host()
        return self.services.hook_bus.list_hook_dispatch_traces(query)

    async def run_prompt(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Any:
        self._bind_host()
        await self.ready()
        session = self._create_helper_owned_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
        )
        final_status = "completed"
        try:
            return await self.runtime._run_prompt_in_session(
                session,
                prompt,
                metadata=metadata,
            )
        except Exception:
            final_status = _managed_session_close_status(session, default="failed")
            raise
        finally:
            await session.close(final_status=final_status)

    async def run_prompt_report(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
        wait_for_finalization: bool = False,
    ) -> Any:
        self._bind_host()
        await self.ready()
        session = self._create_helper_owned_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
        )
        try:
            return await self.runtime._run_prompt_report_in_session(
                session,
                prompt,
                metadata=metadata,
                session_owner="helper",
                wait_for_finalization=wait_for_finalization,
            )
        except asyncio.CancelledError:
            await self._close_active_helper_owned_session(
                session,
                default_status="interrupted",
                interrupt_reason="bound_run_prompt_report_cancelled",
            )
            raise
        except Exception:
            await self._close_active_helper_owned_session(
                session,
                default_status="failed",
            )
            raise

    async def run_prompt_report_in_session(
        self,
        session: Any,
        prompt: str,
        *,
        metadata: dict[str, object] | None = None,
        wait_for_finalization: bool = False,
    ) -> Any:
        self._bind_host()
        await self.ready()
        return await self.runtime.run_prompt_report_in_session(
            session,
            prompt,
            metadata=metadata,
            wait_for_finalization=wait_for_finalization,
        )

    async def stream_prompt(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, object] | None = None,
    ):
        self._bind_host()
        await self.ready()
        session = self._create_helper_owned_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
        )
        final_status = "completed"
        try:
            await self.runtime._prepare_one_shot_session(session, prompt, metadata=metadata)
            async for event in session.stream_until_idle():
                if getattr(event, "event_type", None) is not None and getattr(event.event_type, "value", None) == "terminal":
                    terminal = getattr(event, "terminal", None)
                    final_status = _managed_session_close_status(session, terminal=terminal)
                yield event
        except Exception:
            final_status = _managed_session_close_status(session, default="failed")
            raise
        finally:
            await session.close(final_status=final_status)

    def _bind_host(self) -> None:
        if self.services is not None and hasattr(self.services, "bind_host"):
            self.services.bind_host(self.host)

    def _register_managed_session(self, session: Any, *, owner: str) -> None:
        session_id = getattr(getattr(session, "state", None), "session_id", None)
        if session_id is None:
            return
        session_key = str(session_id)
        existing = self._managed_sessions.get(session_key)
        if existing is not None and existing is not session:
            raise ValueError(f"Managed session '{session_key}' is already active")
        self._managed_sessions[session_key] = session
        self._managed_session_owners[session_key] = owner

    def _ensure_managed_session_id_available(self, session_id: str | None) -> None:
        if session_id is None:
            return
        session_key = str(session_id)
        if self._managed_sessions.get(session_key) is not None:
            raise ValueError(f"Managed session '{session_key}' is already active")

    def _managed_session_is_active(self, session: Any) -> bool:
        session_id = getattr(getattr(session, "state", None), "session_id", None)
        if session_id is None:
            return False
        return self._managed_sessions.get(str(session_id)) is session

    def _create_helper_owned_session(
        self,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
    ) -> Any:
        self._ensure_managed_session_id_available(session_id)
        session = self.runtime.create_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
            close_callback=self._on_managed_session_close,
        )
        self._register_managed_session(session, owner="helper")
        return session

    async def _close_active_helper_owned_session(
        self,
        session: Any,
        *,
        default_status: str,
        interrupt_reason: str | None = None,
    ) -> None:
        if not self._managed_session_is_active(session):
            return
        session_status = getattr(getattr(session, "state", None), "status", None)
        session_status_value = getattr(session_status, "value", session_status)
        if interrupt_reason is not None and str(session_status_value).strip().lower() == "running":
            session.interrupt(interrupt_reason)
        await session.close(final_status=_managed_session_close_status(session, default=default_status))

    async def _on_managed_session_close(self, session: Any, final_status: str) -> None:
        session_id = getattr(getattr(session, "state", None), "session_id", None)
        if session_id is None:
            return
        session_key = str(session_id)
        self._managed_sessions.pop(session_key, None)
        owner = self._managed_session_owners.pop(session_key, None)
        closed_history = self.metadata.setdefault("closed_sessions", [])
        if isinstance(closed_history, list):
            closed_history.append(
                {
                    "session_id": session_key,
                    "owner": owner,
                    "final_status": final_status,
                }
            )


__all__ = [
    "BoundHostRuntime",
    "CallbackHostAdapter",
    "HostExtensionEvent",
    "HostAdapter",
    "HostFactory",
    "HostRuntime",
    "NullHostAdapter",
]


def _managed_session_close_status(
    session: Any,
    *,
    terminal: Any | None = None,
    default: str = "completed",
) -> str:
    if terminal is not None:
        if getattr(terminal, "error", None):
            return "failed"
        if getattr(terminal, "abort_reason", None):
            return "interrupted"
        post_effects = getattr(terminal, "post_effects", None)
        if post_effects is not None:
            session_status_hint = getattr(post_effects, "session_status_hint", None)
            if session_status_hint == "waiting":
                return "stopped"
            if session_status_hint == "interrupted":
                return "interrupted"
        terminal_metadata = getattr(terminal, "metadata", None)
        if isinstance(terminal_metadata, dict):
            failure_class = terminal_metadata.get("failure_class")
            if failure_class not in {None, "", "none"}:
                return "failed"
            if terminal_metadata.get("continuation_blocked"):
                return "stopped"
        if getattr(terminal, "stop_reason", None) == "interrupted":
            return "interrupted"
        if getattr(terminal, "stop_reason", None) == "blocked":
            return "stopped"
    status = getattr(getattr(session, "state", None), "status", None)
    normalized = str(status) if status is not None else ""
    if normalized.endswith("INTERRUPTED") or normalized.endswith("interrupted"):
        return "interrupted"
    if normalized.endswith("FAILED") or normalized.endswith("failed"):
        return "failed"
    if normalized.endswith("STOPPED") or normalized.endswith("stopped"):
        return "stopped"
    return default


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
