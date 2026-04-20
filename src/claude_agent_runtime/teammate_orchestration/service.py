from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from ..agent_execution import AgentRunStatus, SpawnMode
from ..agent_runtime import AgentInvocation
from ..contracts import MessageRole, RuntimeMessage
from ..definitions import IsolationMode, PermissionMode
from ..hosts.base import HostRuntime
from ..permissions import PermissionContext, PermissionOutcome, PermissionRequest
from ..tasking import TaskManager, TaskStatus
from .mailbox import FileBackedTeammateMailbox
from .models import (
    MailboxEnvelope,
    SharedExecutionCore,
    TeammateExecutionRequest,
    TeammateLifecycleState,
    TeammateOrchestrationConfig,
    TeammateProjection,
    TeammateRecoveryResult,
    TeammateRegistration,
    TeammateStateSnapshot,
)


@dataclass(slots=True)
class TeammateRegistry:
    _records: dict[tuple[str, str], TeammateRegistration] = field(default_factory=dict)

    def register(self, registration: TeammateRegistration) -> TeammateRegistration:
        self._records[registration.key] = registration
        return registration

    def get(self, team_id: str, teammate_id: str) -> TeammateRegistration | None:
        return self._records.get((team_id, teammate_id))

    def list(self) -> tuple[TeammateRegistration, ...]:
        return tuple(self._records[key] for key in sorted(self._records))


class PersistentTeammateHostBridge:
    def __init__(
        self,
        *,
        delegate: HostRuntime,
        orchestrator: "PersistentTeammateOrchestrator",
    ) -> None:
        self._delegate = delegate
        self._orchestrator = orchestrator
        self.name = delegate.name

    async def startup(self) -> None:
        await self._delegate.startup()

    async def ready(self) -> None:
        await self._delegate.ready()

    async def shutdown(self) -> None:
        await self._delegate.shutdown()

    async def request_permission(self, request: PermissionRequest) -> PermissionOutcome:
        details = self._orchestrator.permission_bridge_details(request)
        if details is None:
            return await self._delegate.request_permission(request)

        permission_id = uuid4().hex
        self._orchestrator.enter_permission_wait(
            team_id=details["team_id"],
            teammate_id=details["teammate_id"],
            permission_id=permission_id,
        )
        await self.emit_notification(
            RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.NOTIFICATION,
                content=f"Teammate '{details['teammate_id']}' is waiting for permission",
                metadata={
                    "teammate_id": details["teammate_id"],
                    "team_id": details["team_id"],
                    "permission_id": permission_id,
                    "source": "teammate_permission_bridge",
                },
            )
        )
        try:
            outcome = await self._delegate.request_permission(request)
        except BaseException:
            self._orchestrator.exit_permission_wait(
                team_id=details["team_id"],
                teammate_id=details["teammate_id"],
                permission_id=permission_id,
            )
            raise
        self._orchestrator.exit_permission_wait(
            team_id=details["team_id"],
            teammate_id=details["teammate_id"],
            permission_id=permission_id,
        )
        return outcome

    async def request_elicitation(self, request: Any) -> Any:
        return await self._delegate.request_elicitation(request)

    def current_notifications(self) -> tuple[RuntimeMessage, ...]:
        return tuple(self._delegate.current_notifications())

    async def emit_notification(self, message: RuntimeMessage) -> None:
        await self._delegate.emit_notification(message)

    async def emit_turn_event(self, session_id: str, event: Any) -> None:
        await self._delegate.emit_turn_event(session_id, event)


class PersistentTeammateOrchestrator:
    def __init__(
        self,
        *,
        config: TeammateOrchestrationConfig,
        project_root: Path,
        runtime_services: Any,
        execution_core: SharedExecutionCore | None = None,
    ) -> None:
        self._config = config
        self._runtime_services = runtime_services
        self._execution_core = execution_core
        mailbox_root = config.mailbox_root or (Path(project_root) / ".claude" / "teammates")
        self._mailbox = FileBackedTeammateMailbox(
            mailbox_root,
            default_claim_lease_ms=config.claim_lease_ms,
            default_retry_max_attempts=config.retry_max_attempts,
            retry_backoff_ms=config.retry_backoff_ms,
        )
        self._registry = TeammateRegistry()
        self._snapshots: dict[tuple[str, str], TeammateStateSnapshot] = {}
        self._projections: dict[tuple[str, str], TeammateProjection] = {}
        self._heartbeat_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._processing_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._recovered_targets: set[tuple[str, str]] = set()
        self._live_permission_waits: set[tuple[str, str, str]] = set()
        self._host_bridge: PersistentTeammateHostBridge | None = None

    @property
    def config(self) -> TeammateOrchestrationConfig:
        return self._config

    @property
    def mailbox(self) -> FileBackedTeammateMailbox:
        return self._mailbox

    @property
    def registry(self) -> TeammateRegistry:
        return self._registry

    def bind_execution_core(self, execution_core: SharedExecutionCore) -> None:
        self._execution_core = execution_core

    def bind_host(self, host: HostRuntime) -> HostRuntime:
        bridge = PersistentTeammateHostBridge(delegate=host, orchestrator=self)
        self._host_bridge = bridge
        return bridge

    def register_teammate(
        self,
        *,
        team_id: str,
        teammate_id: str,
        agent_name: str,
        session_id: str,
        working_directory: str | Path,
        metadata: Mapping[str, Any] | None = None,
        claim_lease_ms: int | None = None,
        retry_max_attempts: int | None = None,
    ) -> TeammateStateSnapshot:
        registration = TeammateRegistration(
            team_id=team_id,
            teammate_id=teammate_id,
            agent_name=agent_name,
            session_id=session_id,
            working_directory=Path(working_directory),
            claim_lease_ms=claim_lease_ms or self._config.claim_lease_ms,
            retry_max_attempts=retry_max_attempts or self._config.retry_max_attempts,
            metadata=dict(metadata or {}),
        )
        self._registry.register(registration)
        current = self._mailbox.read_state(team_id, teammate_id)
        if current is None:
            current = TeammateStateSnapshot(
                team_id=team_id,
                teammate_id=teammate_id,
                state=TeammateLifecycleState.IDLE,
            )
        snapshot = current.with_registration(
            agent_name=agent_name,
            session_id=session_id,
            working_directory=registration.working_directory,
            metadata=registration.metadata,
        )
        self._write_snapshot(snapshot)
        if snapshot.state == TeammateLifecycleState.IDLE:
            self._set_projection(
                snapshot,
                task_id=None,
                task_status=None,
                progress_status="idle",
            )
        return snapshot

    def snapshot(self, team_id: str, teammate_id: str) -> TeammateStateSnapshot | None:
        snapshot = self._snapshots.get((team_id, teammate_id))
        if snapshot is not None:
            return snapshot
        snapshot = self._mailbox.read_state(team_id, teammate_id)
        if snapshot is not None:
            self._snapshots[(team_id, teammate_id)] = snapshot
        return snapshot

    def projection(self, team_id: str, teammate_id: str) -> TeammateProjection | None:
        return self._projections.get((team_id, teammate_id))

    def publish_work_item(
        self,
        *,
        team_id: str,
        teammate_id: str,
        prompt: str,
        sender: Mapping[str, Any] | None = None,
        kind: str = "work_item",
        correlation_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        payload_ref: str | None = None,
        requested_model_route: str | None = None,
        requested_model: str | None = None,
        requested_effort: Any = None,
        requested_permission_mode: str | PermissionMode | None = None,
        requested_isolation: str | IsolationMode | None = None,
        max_turns: int | None = None,
    ) -> MailboxEnvelope:
        registration = self._require_registration(team_id, teammate_id)
        payload_data = dict(payload or {})
        payload_data.setdefault("prompt", prompt)
        if requested_model_route is not None:
            payload_data["requested_model_route"] = str(requested_model_route)
        if requested_model is not None:
            payload_data["requested_model"] = str(requested_model)
        if requested_effort is not None:
            payload_data["requested_effort"] = requested_effort
        if requested_permission_mode is not None:
            payload_data["requested_permission_mode"] = str(requested_permission_mode)
        if requested_isolation is not None:
            payload_data["requested_isolation"] = str(requested_isolation)
        if max_turns is not None:
            payload_data["max_turns"] = int(max_turns)
        envelope = MailboxEnvelope(
            message_id=uuid4().hex,
            team_id=team_id,
            teammate_id=teammate_id,
            kind=kind,
            sender=_coerce_sender(sender),
            correlation_id=correlation_id or uuid4().hex,
            payload=payload_data,
            payload_ref=payload_ref,
            retry_max_attempts=registration.retry_max_attempts,
        )
        self._mailbox.publish(envelope)
        return envelope

    async def recover(
        self,
        *,
        team_id: str | None = None,
        teammate_id: str | None = None,
    ) -> tuple[TeammateRecoveryResult, ...]:
        recovered: list[TeammateRecoveryResult] = []
        targets = (
            ((team_id, teammate_id),)
            if team_id is not None and teammate_id is not None
            else self._mailbox.scan_teammates()
        )
        for resolved_team_id, resolved_teammate_id in targets:
            key = (resolved_team_id, resolved_teammate_id)
            snapshot = self._mailbox.read_state(resolved_team_id, resolved_teammate_id)
            if snapshot is None:
                continue
            self._snapshots[(resolved_team_id, resolved_teammate_id)] = snapshot
            self._restore_registration(snapshot)
            live_permission_wait = self._has_live_permission_wait(snapshot)
            claimed = self._mailbox.list_claimed(resolved_team_id, resolved_teammate_id)
            if not claimed and snapshot.state in {
                TeammateLifecycleState.ACTIVE,
                TeammateLifecycleState.WAITING_PERMISSION,
                TeammateLifecycleState.STARTING,
            }:
                snapshot = snapshot.idle()
                self._write_snapshot(snapshot)
                recovered.append(
                    TeammateRecoveryResult(
                        team_id=resolved_team_id,
                        teammate_id=resolved_teammate_id,
                        message_id=None,
                        action="reset_idle",
                    )
                )
                self._recovered_targets.add(key)
                continue

            for envelope in claimed:
                active_run_linked = await self._active_run_linked(snapshot, envelope)
                waiting_permission_snapshot = (
                    snapshot.state == TeammateLifecycleState.WAITING_PERMISSION
                    and snapshot.current_message_id == envelope.message_id
                    and snapshot.current_claim_id == envelope.claim_id
                    and snapshot.waiting_permission_id is not None
                )
                waiting_permission = waiting_permission_snapshot and live_permission_wait
                lost_permission_wait = (
                    waiting_permission_snapshot and not live_permission_wait and not active_run_linked
                )
                if lost_permission_wait:
                    archived, _ = self._mailbox.fail_or_retry(
                        envelope,
                        reason="lost_permission_wait",
                        retry_max_attempts=self._resolve_registration(
                            resolved_team_id,
                            resolved_teammate_id,
                        ).retry_max_attempts,
                    )
                    recovered.append(
                        TeammateRecoveryResult(
                            team_id=resolved_team_id,
                            teammate_id=resolved_teammate_id,
                            message_id=envelope.message_id,
                            action=archived.terminal_state.value if archived.terminal_state is not None else "retry",
                            reason="lost_permission_wait",
                        )
                    )
                    if snapshot.current_message_id == envelope.message_id:
                        snapshot = snapshot.idle()
                        self._write_snapshot(snapshot)
                    continue
                if not self._mailbox.stale_claim(
                    envelope,
                    active_run_linked=active_run_linked,
                    waiting_permission=waiting_permission,
                ):
                    if waiting_permission:
                        recovered.append(
                            TeammateRecoveryResult(
                                team_id=resolved_team_id,
                                teammate_id=resolved_teammate_id,
                                message_id=envelope.message_id,
                                action="kept_waiting_permission",
                            )
                        )
                    continue

                archived, _ = self._mailbox.fail_or_retry(
                    envelope,
                    reason="stale_claim",
                    retry_max_attempts=self._resolve_registration(
                        resolved_team_id,
                        resolved_teammate_id,
                    ).retry_max_attempts,
                )
                recovered.append(
                    TeammateRecoveryResult(
                        team_id=resolved_team_id,
                        teammate_id=resolved_teammate_id,
                        message_id=envelope.message_id,
                        action=archived.terminal_state.value if archived.terminal_state is not None else "retry",
                        reason="stale_claim",
                    )
                )
                if snapshot.current_message_id == envelope.message_id:
                    snapshot = snapshot.idle()
                    self._write_snapshot(snapshot)
            if snapshot.state == TeammateLifecycleState.IDLE:
                self._set_projection(snapshot, task_id=None, task_status=None, progress_status="idle")
            self._recovered_targets.add(key)
        return tuple(recovered)

    async def process_next_work_item(
        self,
        *,
        team_id: str,
        teammate_id: str,
    ) -> Any | None:
        if self._execution_core is None:
            raise RuntimeError("Persistent teammate orchestration is not bound to an execution core")
        key = (team_id, teammate_id)
        async with self._processing_lock(team_id, teammate_id):
            if key not in self._recovered_targets:
                await self.recover(team_id=team_id, teammate_id=teammate_id)

            registration = self._resolve_registration(team_id, teammate_id)
            claimed = self._mailbox.claim_next(
                team_id,
                teammate_id,
                claimer_identity=f"teammate:{teammate_id}",
                claim_lease_ms=registration.claim_lease_ms,
                now=datetime.now(timezone.utc),
            )
            if claimed is None:
                snapshot = self.snapshot(team_id, teammate_id)
                active_claims = self._mailbox.list_claimed(team_id, teammate_id)
                if snapshot is not None and not active_claims and snapshot.state != TeammateLifecycleState.IDLE:
                    snapshot = snapshot.idle()
                    self._write_snapshot(snapshot)
                if snapshot is not None and snapshot.state == TeammateLifecycleState.IDLE:
                    self._set_projection(snapshot, task_id=None, task_status=None, progress_status="idle")
                return None

            execution_request = self._build_execution_request(registration, claimed)
            invocation = self._build_agent_invocation(execution_request)
            agent, execution_spec = self._execution_core.prepare_execution(invocation)
            claimed = self._mailbox.update_claim(claimed.with_run_linkage(execution_spec.run_id))

            snapshot = self.snapshot(team_id, teammate_id) or TeammateStateSnapshot(
                team_id=team_id,
                teammate_id=teammate_id,
                state=TeammateLifecycleState.STARTING,
            )
            snapshot = snapshot.activate(
                message_id=claimed.message_id,
                run_id=execution_spec.run_id,
                claim_id=str(claimed.claim_id),
            ).with_registration(
                agent_name=registration.agent_name,
                session_id=registration.session_id,
                working_directory=registration.working_directory,
                metadata=registration.metadata,
            )
            self._write_snapshot(snapshot)
            task_id = self._task_manager().create(
                uuid4().hex,
                title=f"teammate:{teammate_id}",
                description=f"{registration.agent_name}:{claimed.kind}",
                metadata={
                    "team_id": team_id,
                    "teammate_id": teammate_id,
                    "run_id": execution_spec.run_id,
                    "message_id": claimed.message_id,
                    "claim_id": claimed.claim_id,
                    "projection_kind": "teammate",
                    "teammate_state": snapshot.state.value,
                },
            ).task_id
            self._task_manager().update(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={
                    "teammate_state": snapshot.state.value,
                    "run_id": execution_spec.run_id,
                    "message_id": claimed.message_id,
                    "claim_id": claimed.claim_id,
                },
            )
            self._set_projection(
                snapshot,
                task_id=task_id,
                task_status=TaskStatus.RUNNING,
                progress_status="active",
            )
            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(
                    team_id=team_id,
                    teammate_id=teammate_id,
                    message_id=claimed.message_id,
                    claim_id=str(claimed.claim_id),
                )
            )
            self._heartbeat_tasks[(team_id, teammate_id)] = heartbeat_task
            try:
                result = await self._execution_core.dispatch_prepared(
                    invocation,
                    agent=agent,
                    execution_spec=execution_spec,
                )
            except Exception as exc:
                archived, _ = self._mailbox.fail_or_retry(
                    claimed,
                    reason=str(exc),
                    retry_max_attempts=registration.retry_max_attempts,
                )
                snapshot = snapshot.idle()
                self._write_snapshot(snapshot)
                self._task_manager().update(
                    task_id,
                    status=TaskStatus.FAILED,
                    error=str(exc),
                    metadata={
                        "teammate_state": snapshot.state.value,
                        "mailbox_terminal_state": archived.terminal_state.value if archived.terminal_state else None,
                    },
                )
                self._set_projection(
                    snapshot,
                    task_id=task_id,
                    task_status=TaskStatus.FAILED,
                    progress_status="idle",
                    latest_notification=f"Teammate '{teammate_id}' failed mailbox item",
                )
                await self._emit_notification(
                    f"Teammate '{teammate_id}' failed mailbox item: {exc}",
                    metadata={
                        "team_id": team_id,
                        "teammate_id": teammate_id,
                        "message_id": claimed.message_id,
                        "run_id": execution_spec.run_id,
                    },
                )
                raise
            finally:
                await self._stop_heartbeat(team_id, teammate_id)

            status = str(result.status)
            if status == AgentRunStatus.COMPLETED.value:
                archived = self._mailbox.complete_done(claimed)
                terminal_task_status = TaskStatus.COMPLETED
                notification_text = f"Teammate '{teammate_id}' completed mailbox item"
            else:
                archived, requeued = self._mailbox.fail_or_retry(
                    claimed,
                    reason=status,
                    retry_max_attempts=registration.retry_max_attempts,
                )
                terminal_task_status = TaskStatus.FAILED
                notification_text = (
                    f"Teammate '{teammate_id}' scheduled mailbox retry"
                    if requeued is not None
                    else f"Teammate '{teammate_id}' failed mailbox item"
                )

            snapshot = snapshot.idle()
            self._write_snapshot(snapshot)
            self._task_manager().update(
                task_id,
                status=terminal_task_status,
                result={
                    "run_id": execution_spec.run_id,
                    "status": status,
                    "message_id": claimed.message_id,
                },
                error=None if terminal_task_status == TaskStatus.COMPLETED else archived.terminal_reason or status,
                metadata={
                    "teammate_state": snapshot.state.value,
                    "mailbox_terminal_state": archived.terminal_state.value if archived.terminal_state is not None else None,
                    "run_id": execution_spec.run_id,
                },
            )
            self._set_projection(
                snapshot,
                task_id=task_id,
                task_status=terminal_task_status,
                progress_status="idle",
                latest_notification=notification_text,
            )
            await self._emit_notification(
                notification_text,
                metadata={
                    "team_id": team_id,
                    "teammate_id": teammate_id,
                    "message_id": claimed.message_id,
                    "run_id": execution_spec.run_id,
                    "mailbox_terminal_state": archived.terminal_state.value if archived.terminal_state is not None else None,
                },
            )
            return result

    async def drain_teammate(
        self,
        *,
        team_id: str,
        teammate_id: str,
        limit: int | None = None,
    ) -> tuple[Any, ...]:
        results: list[Any] = []
        while limit is None or len(results) < limit:
            result = await self.process_next_work_item(team_id=team_id, teammate_id=teammate_id)
            if result is None:
                break
            results.append(result)
        return tuple(results)

    def permission_bridge_details(self, request: PermissionRequest) -> dict[str, str] | None:
        context = request.context
        if context is None:
            return None
        metadata = getattr(context, "metadata", None)
        if not isinstance(metadata, Mapping):
            return None
        team_id = _coerce_optional_string(metadata.get("team_id"))
        teammate_id = _coerce_optional_string(metadata.get("teammate_id"))
        if not team_id or not teammate_id:
            return None
        return {"team_id": team_id, "teammate_id": teammate_id}

    def enter_permission_wait(
        self,
        *,
        team_id: str,
        teammate_id: str,
        permission_id: str,
    ) -> None:
        snapshot = self.snapshot(team_id, teammate_id)
        if snapshot is None:
            return
        self._live_permission_waits.add((team_id, teammate_id, permission_id))
        snapshot = snapshot.waiting_permission(permission_id)
        self._write_snapshot(snapshot)
        projection = self._projections.get((team_id, teammate_id))
        task_id = projection.task_id if projection is not None else None
        if task_id is not None:
            self._task_manager().update(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={
                    "teammate_state": snapshot.state.value,
                    "waiting_permission_id": permission_id,
                },
            )
        self._set_projection(
            snapshot,
            task_id=task_id,
            task_status=TaskStatus.RUNNING,
            progress_status="waiting_permission",
        )

    def exit_permission_wait(
        self,
        *,
        team_id: str,
        teammate_id: str,
        permission_id: str,
    ) -> None:
        self._live_permission_waits.discard((team_id, teammate_id, permission_id))
        snapshot = self.snapshot(team_id, teammate_id)
        if snapshot is None or snapshot.waiting_permission_id != permission_id:
            return
        snapshot = snapshot.resume_active()
        self._write_snapshot(snapshot)
        projection = self._projections.get((team_id, teammate_id))
        task_id = projection.task_id if projection is not None else None
        if task_id is not None:
            self._task_manager().update(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={
                    "teammate_state": snapshot.state.value,
                    "waiting_permission_id": None,
                },
            )
        self._set_projection(
            snapshot,
            task_id=task_id,
            task_status=TaskStatus.RUNNING,
            progress_status="active",
        )

    async def _active_run_linked(
        self,
        snapshot: TeammateStateSnapshot,
        envelope: MailboxEnvelope,
    ) -> bool:
        if snapshot.current_run_id is None or envelope.current_run_id != snapshot.current_run_id:
            return False
        run_store = getattr(self._execution_core, "run_store", None) or getattr(
            getattr(self._execution_core, "runtime_services", None),
            "run_store",
            None,
        )
        if run_store is None or not hasattr(run_store, "get"):
            return False
        record = await run_store.get(snapshot.current_run_id)
        return bool(record is not None and getattr(record, "status", None) == AgentRunStatus.RUNNING)

    def _build_execution_request(
        self,
        registration: TeammateRegistration,
        envelope: MailboxEnvelope,
    ) -> TeammateExecutionRequest:
        payload = dict(envelope.payload)
        prompt = _coerce_optional_string(payload.get("prompt"))
        if prompt is None:
            raise ValueError("Mailbox work item is missing payload.prompt")
        permission_mode = _coerce_permission_mode(payload.get("requested_permission_mode"))
        isolation_mode = _coerce_isolation_mode(payload.get("requested_isolation"))
        metadata = {
            "team_id": registration.team_id,
            "teammate_id": registration.teammate_id,
            "mailbox_message_id": envelope.message_id,
            "mailbox_claim_id": envelope.claim_id,
            "mailbox_kind": envelope.kind,
            "query_source": "teammate_mailbox",
        }
        return TeammateExecutionRequest(
            team_id=registration.team_id,
            teammate_id=registration.teammate_id,
            message_id=envelope.message_id,
            claim_id=str(envelope.claim_id),
            agent_name=registration.agent_name,
            prompt=prompt,
            session_id=registration.session_id,
            cwd=registration.working_directory,
            requested_model_route=_coerce_optional_string(payload.get("requested_model_route")),
            requested_model=_coerce_optional_string(payload.get("requested_model")),
            requested_effort=payload.get("requested_effort"),
            requested_permission_mode=permission_mode,
            requested_isolation=isolation_mode,
            max_turns=_coerce_optional_int(payload.get("max_turns")),
            metadata=metadata,
        )

    def _build_agent_invocation(self, request: TeammateExecutionRequest) -> AgentInvocation:
        permission_context = PermissionContext(
            session_id=request.session_id,
            mode=request.requested_permission_mode or PermissionMode.DEFAULT,
            metadata={
                "team_id": request.team_id,
                "teammate_id": request.teammate_id,
                "message_id": request.message_id,
                "claim_id": request.claim_id,
            },
        )
        return AgentInvocation(
            agent_name=request.agent_name,
            prompt=request.prompt,
            session_id=request.session_id,
            cwd=request.cwd,
            query_source="teammate_mailbox",
            spawn_mode=SpawnMode.TEAMMATE,
            requested_model_route=request.requested_model_route,
            requested_model=request.requested_model,
            requested_effort=request.requested_effort,
            requested_permission_mode=request.requested_permission_mode,
            requested_isolation=request.requested_isolation,
            max_turns=request.max_turns,
            metadata={**request.metadata, "permission_context": permission_context},
        )

    async def _heartbeat_loop(
        self,
        *,
        team_id: str,
        teammate_id: str,
        message_id: str,
        claim_id: str,
    ) -> None:
        delay = max(self._config.heartbeat_interval_ms, 1) / 1000
        while True:
            await asyncio.sleep(delay)
            try:
                self._mailbox.heartbeat(
                    team_id,
                    teammate_id,
                    message_id=message_id,
                    claim_id=claim_id,
                    now=datetime.now(timezone.utc),
                )
            except FileNotFoundError:
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                return

    async def _stop_heartbeat(self, team_id: str, teammate_id: str) -> None:
        task = self._heartbeat_tasks.pop((team_id, teammate_id), None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    def _processing_lock(self, team_id: str, teammate_id: str) -> asyncio.Lock:
        key = (team_id, teammate_id)
        lock = self._processing_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._processing_locks[key] = lock
        return lock

    def _has_live_permission_wait(self, snapshot: TeammateStateSnapshot) -> bool:
        permission_id = snapshot.waiting_permission_id
        if permission_id is None:
            return False
        return (snapshot.team_id, snapshot.teammate_id, permission_id) in self._live_permission_waits

    def _restore_registration(self, snapshot: TeammateStateSnapshot) -> None:
        if snapshot.agent_name is None or snapshot.session_id is None or snapshot.working_directory is None:
            return
        self._registry.register(
            TeammateRegistration(
                team_id=snapshot.team_id,
                teammate_id=snapshot.teammate_id,
                agent_name=snapshot.agent_name,
                session_id=snapshot.session_id,
                working_directory=Path(snapshot.working_directory),
                claim_lease_ms=self._config.claim_lease_ms,
                retry_max_attempts=self._config.retry_max_attempts,
                metadata=dict(snapshot.metadata),
            )
        )

    def _resolve_registration(self, team_id: str, teammate_id: str) -> TeammateRegistration:
        registration = self._registry.get(team_id, teammate_id)
        if registration is not None:
            return registration
        snapshot = self._mailbox.read_state(team_id, teammate_id)
        if snapshot is None:
            raise KeyError(f"Unknown teammate: {team_id}/{teammate_id}")
        self._restore_registration(snapshot)
        registration = self._registry.get(team_id, teammate_id)
        if registration is None:
            raise KeyError(f"Teammate registration for {team_id}/{teammate_id} is incomplete")
        return registration

    def _require_registration(self, team_id: str, teammate_id: str) -> TeammateRegistration:
        return self._resolve_registration(team_id, teammate_id)

    def _write_snapshot(self, snapshot: TeammateStateSnapshot) -> TeammateStateSnapshot:
        self._snapshots[(snapshot.team_id, snapshot.teammate_id)] = snapshot
        return self._mailbox.write_state(snapshot)

    def _set_projection(
        self,
        snapshot: TeammateStateSnapshot,
        *,
        task_id: str | None,
        task_status: TaskStatus | None,
        progress_status: str | None,
        latest_notification: str | None = None,
    ) -> None:
        self._projections[(snapshot.team_id, snapshot.teammate_id)] = TeammateProjection(
            team_id=snapshot.team_id,
            teammate_id=snapshot.teammate_id,
            lifecycle_state=snapshot.state,
            task_id=task_id,
            task_status=task_status,
            current_run_id=snapshot.current_run_id,
            current_message_id=snapshot.current_message_id,
            waiting_permission_id=snapshot.waiting_permission_id,
            progress_status=progress_status,
            latest_notification=latest_notification,
            metadata={
                "agent_name": snapshot.agent_name,
                "session_id": snapshot.session_id,
            },
        )

    def _task_manager(self) -> TaskManager:
        return self._runtime_services.task_manager

    async def _emit_notification(
        self,
        content: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        await self._runtime_services.host.emit_notification(
            RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.NOTIFICATION,
                content=content,
                metadata=dict(metadata or {}),
            )
        )


def _coerce_sender(value: Mapping[str, Any] | None) -> Any:
    from .models import MailboxSender

    return MailboxSender.from_value(value)


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_permission_mode(value: object) -> PermissionMode | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    return PermissionMode(normalized)


def _coerce_isolation_mode(value: object) -> IsolationMode | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    return IsolationMode(normalized)


__all__ = [
    "PersistentTeammateHostBridge",
    "PersistentTeammateOrchestrator",
    "TeammateOrchestrationConfig",
    "TeammateRegistry",
]
