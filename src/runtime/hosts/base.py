from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol, Sequence

from ..definitions import PermissionBehavior
from ..elicitation import ElicitationRequest, ElicitationResponse
from ..hooks import HookDispatchTraceQuery, HookInventoryQuery, HookRegistrationRequest, HookSourceKind
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

    async def emit_team_event(self, event: Any) -> None: ...


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

    async def emit_team_event(self, event: Any) -> None:
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
    team_event_sink: Callable[[Any], Any] | None = None
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

    async def emit_team_event(self, event: Any) -> None:
        if self.team_event_sink is None:
            return None
        await _maybe_await(self.team_event_sink(event))


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

    async def list_team_workflows(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        resolved_team_id = self._resolve_team_workflow_scope(
            team_id=kwargs.pop("team_id", None),
            session_id=kwargs.pop("session_id", None),
        )
        return await self.runtime.list_team_workflows(team_id=resolved_team_id, *args, **kwargs)

    async def respond_team_workflow(self, *args: Any, **kwargs: Any) -> Any:
        self._bind_host()
        if not args:
            raise TypeError("respond_team_workflow requires a workflow_id")
        workflow_id = args[0]
        remaining_args = args[1:]
        resolved_team_id = self._resolve_team_workflow_scope(
            team_id=kwargs.pop("team_id", None),
            session_id=kwargs.pop("session_id", None),
        )
        workflow = self._resolve_scoped_team_workflow(workflow_id, team_id=resolved_team_id)
        return await self.runtime.respond_team_workflow(
            workflow.workflow_id,
            *remaining_args,
            host_name=kwargs.pop("host_name", self.host.name),
            **kwargs,
        )

    def bind_hook_callback(self, name: str, handler: Any) -> None:
        self._bind_host()
        self.services.hook_bus.bind_callback(name, handler)

    def register_hook(
        self,
        request: HookRegistrationRequest | Mapping[str, Any],
    ) -> Any:
        self._bind_host()
        return self.services.hook_bus.register_request(
            request,
            source_kind=HookSourceKind.HOST_API,
            owner=f"host:{self.host.name}",
            source_ref=self.host.name,
        )

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
        self._ensure_managed_session_id_available(session_id)
        session = self.runtime.create_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
            close_callback=self._on_managed_session_close,
        )
        self._register_managed_session(session, owner="helper")
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
        self._ensure_managed_session_id_available(session_id)
        session = self.runtime.create_session(
            session_id=session_id,
            agent_name=agent_name,
            cwd=cwd,
            system_prompt=system_prompt,
            close_callback=self._on_managed_session_close,
        )
        self._register_managed_session(session, owner="helper")
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

    def _resolve_team_workflow_scope(
        self,
        *,
        team_id: Any,
        session_id: Any,
    ) -> str:
        from ..team_workflows import TeamWorkflowError

        resolved_team_id = str(team_id).strip() if team_id is not None and str(team_id).strip() else None
        resolved_session_id = (
            str(session_id).strip() if session_id is not None and str(session_id).strip() else None
        )
        if resolved_team_id is None and resolved_session_id is None:
            raise TeamWorkflowError(
                "invalid_workflow_scope",
                "Host workflow operations require a team_id or session_id scope",
            )
        if resolved_session_id is not None:
            plane = getattr(self.runtime, "team_control_plane", None)
            team = plane.active_team_for_leader_session(resolved_session_id) if plane is not None else None
            if team is None:
                raise TeamWorkflowError(
                    "invalid_workflow_scope",
                    "No active team is bound to that leader session",
                    session_id=resolved_session_id,
                )
            if resolved_team_id is not None and resolved_team_id != team.team_id:
                raise TeamWorkflowError(
                    "invalid_workflow_scope",
                    "team_id does not match the active team for that leader session",
                    team_id=resolved_team_id,
                    session_id=resolved_session_id,
                    active_team_id=team.team_id,
                )
            resolved_team_id = team.team_id
        assert resolved_team_id is not None
        return resolved_team_id

    def _resolve_scoped_team_workflow(self, workflow_id: Any, *, team_id: str) -> Any:
        from ..team_workflows import TeamWorkflowError

        service = getattr(self.services, "team_workflows", None)
        if service is None or not hasattr(service, "get"):
            raise RuntimeError("Runtime team workflow service is not configured")
        normalized_workflow_id = str(workflow_id).strip()
        record = service.get(normalized_workflow_id)
        if record is None or record.team_id != team_id:
            raise TeamWorkflowError(
                "not_found",
                f"Workflow '{normalized_workflow_id}' was not found in the requested team scope",
                workflow_id=normalized_workflow_id,
                team_id=team_id,
            )
        return record

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
