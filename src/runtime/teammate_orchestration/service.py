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
from ..definitions import IsolationMode, PermissionBehavior, PermissionMode
from ..hosts.base import HostRuntime
from ..jobs import task_status_to_job_status
from ..permissions import PermissionContext, PermissionOutcome, PermissionRequest
from ..team_control_plane import TeamRole
from ..team_workflows import (
    RuntimeTeamWorkflowService,
    TeamWorkflowActorKind,
    TeamWorkflowStatus,
)
from ..tasking import TaskStatus
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
        workflow_service = self._orchestrator.workflow_service
        if workflow_service is None:
            return await self._delegate_permission_request_with_wait(details=details, request=request)
        leader_member_id = self._leader_member_id(details["team_id"])
        team = self._team_record(details["team_id"])
        requester_name = self._teammate_name(details["team_id"], details["teammate_id"])
        responder_name = self._leader_name(details["team_id"])
        if team is None or leader_member_id is None:
            return await self._delegate_permission_request_with_wait(details=details, request=request)
        workflow = await workflow_service.create_permission_workflow(
            team=team,
            requester_member_id=details["teammate_id"],
            requester_name=requester_name,
            responder_member_id=leader_member_id,
            responder_name=responder_name,
            request_payload={
                "permission_target": request.target.value,
                "permission_name": request.name,
                "permission_message": request.message,
                "permission_payload": dict(request.payload),
            },
        )
        self._orchestrator.enter_permission_wait(
            team_id=details["team_id"],
            teammate_id=details["teammate_id"],
            permission_id=workflow.workflow_id,
        )
        await self.emit_notification(
            RuntimeMessage(
                message_id=uuid4().hex,
                role=MessageRole.NOTIFICATION,
                content=f"Teammate '{details['teammate_id']}' is waiting for permission",
                metadata={
                    "teammate_id": details["teammate_id"],
                    "team_id": details["team_id"],
                    "permission_id": workflow.workflow_id,
                    "source": "teammate_permission_bridge",
                },
            )
        )
        try:
            leader_resolution = await workflow_service.wait_for_permission_resolution(workflow.workflow_id)
            if leader_resolution.status is not TeamWorkflowStatus.WAITING_HOST:
                outcome = leader_resolution
            else:
                try:
                    delegated_outcome = await self._delegate.request_permission(request)
                except Exception as exc:
                    delegated_outcome = PermissionOutcome(
                        behavior=PermissionBehavior.DENY,
                        message=str(exc),
                        updated_input=dict(request.payload),
                        details={"host_error": str(exc)},
                        source="host",
                    )
                outcome = await workflow_service.record_permission_host_outcome(
                    workflow.workflow_id,
                    delegated_outcome,
                )
        except BaseException:
            current = workflow_service.get(workflow.workflow_id)
            if current is None or current.terminal:
                self._orchestrator.exit_permission_wait(
                    team_id=details["team_id"],
                    teammate_id=details["teammate_id"],
                    permission_id=workflow.workflow_id,
                )
            raise
        self._orchestrator.exit_permission_wait(
            team_id=details["team_id"],
            teammate_id=details["teammate_id"],
            permission_id=workflow.workflow_id,
        )
        return self._terminal_permission_outcome(outcome, request)

    async def _delegate_permission_request_with_wait(
        self,
        *,
        details: Mapping[str, str],
        request: PermissionRequest,
    ) -> PermissionOutcome:
        permission_id = f"hostperm:{uuid4().hex}"
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
            return await self._delegate.request_permission(request)
        finally:
            self._orchestrator.exit_permission_wait(
                team_id=details["team_id"],
                teammate_id=details["teammate_id"],
                permission_id=permission_id,
            )

    async def request_elicitation(self, request: Any) -> Any:
        return await self._delegate.request_elicitation(request)

    def current_notifications(self) -> tuple[RuntimeMessage, ...]:
        return tuple(self._delegate.current_notifications())

    async def emit_notification(self, message: RuntimeMessage) -> None:
        await self._delegate.emit_notification(message)

    async def emit_turn_event(self, session_id: str, event: Any) -> None:
        await self._delegate.emit_turn_event(session_id, event)

    async def emit_team_event(self, event: Any) -> None:
        if hasattr(self._delegate, "emit_team_event"):
            await self._delegate.emit_team_event(event)

    @property
    def workflow_service(self) -> RuntimeTeamWorkflowService | None:
        return self._orchestrator.workflow_service

    def _leader_member_id(self, team_id: str) -> str | None:
        services = getattr(self._orchestrator, "_runtime_services", None)
        control_plane = getattr(services, "team_control_plane", None)
        if control_plane is None or not hasattr(control_plane, "get_team"):
            return None
        team = control_plane.get_team(team_id)
        if team is None or getattr(team, "active", False) is False:
            return None
        return str(getattr(team, "leader_member_id", "") or "") or None

    def _leader_name(self, team_id: str) -> str:
        member_id = self._leader_member_id(team_id)
        if member_id is None:
            return TeamRole.LEADER.value
        member = self._member_record(team_id, member_id)
        return getattr(member, "name", None) or TeamRole.LEADER.value

    def _teammate_name(self, team_id: str, teammate_id: str) -> str:
        member = self._member_record(team_id, teammate_id)
        return getattr(member, "name", None) or teammate_id

    def _member_record(self, team_id: str, member_id: str) -> Any:
        services = getattr(self._orchestrator, "_runtime_services", None)
        control_plane = getattr(services, "team_control_plane", None)
        if control_plane is None or not hasattr(control_plane, "get_member"):
            return None
        return control_plane.get_member(team_id, member_id)

    def _team_record(self, team_id: str) -> Any:
        services = getattr(self._orchestrator, "_runtime_services", None)
        control_plane = getattr(services, "team_control_plane", None)
        if control_plane is None or not hasattr(control_plane, "get_team"):
            return None
        return control_plane.get_team(team_id)

    def _terminal_permission_outcome(
        self,
        workflow: Any,
        request: PermissionRequest,
    ) -> PermissionOutcome:
        response_payload = getattr(workflow, "response_payload", None) or {}
        if getattr(workflow, "status", None) == TeamWorkflowStatus.COMPLETED:
            return PermissionOutcome(
                behavior=PermissionBehavior.ALLOW,
                message=str(response_payload.get("host_message") or request.message or "Permission approved"),
                updated_input=dict(request.payload),
                details={
                    "workflow_id": getattr(workflow, "workflow_id", None),
                    "source": response_payload.get("host_source") or "workflow",
                    **dict(response_payload.get("host_details") or {}),
                },
                source=str(response_payload.get("host_source") or "workflow"),
            )
        return PermissionOutcome(
            behavior=PermissionBehavior.DENY,
            message=str(
                response_payload.get("host_message")
                or request.message
                or "Permission denied"
            ),
            updated_input=dict(request.payload),
            details={
                "workflow_id": getattr(workflow, "workflow_id", None),
                "workflow_status": getattr(getattr(workflow, "status", None), "value", None),
            },
            source=str(response_payload.get("host_source") or "workflow"),
        )

    async def _emit_team_control_message(
        self,
        *,
        team_id: str,
        sender_member_id: str | None,
        recipient_member_id: str | None,
        control_type: str,
        correlation_id: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        if sender_member_id is None or recipient_member_id is None:
            return
        services = getattr(self._orchestrator, "_runtime_services", None)
        message_bus = getattr(services, "team_message_bus", None)
        if message_bus is None or not hasattr(message_bus, "send_control_message"):
            return
        try:
            await message_bus.send_control_message(
                team_id=team_id,
                sender_member_id=sender_member_id,
                recipient_member_id=recipient_member_id,
                control_type=control_type,
                payload=payload,
                correlation_id=correlation_id,
            )
        except Exception:
            return


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
        mailbox_root = config.mailbox_root or (Path(project_root) / ".runtime" / "teammates")
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
        self._workflow_service: RuntimeTeamWorkflowService | None = None

    @property
    def config(self) -> TeammateOrchestrationConfig:
        return self._config

    @property
    def mailbox(self) -> FileBackedTeammateMailbox:
        return self._mailbox

    @property
    def registry(self) -> TeammateRegistry:
        return self._registry

    @property
    def workflow_service(self) -> RuntimeTeamWorkflowService | None:
        return self._workflow_service

    def bind_execution_core(self, execution_core: SharedExecutionCore) -> None:
        self._execution_core = execution_core

    def bind_workflow_service(self, workflow_service: RuntimeTeamWorkflowService) -> None:
        self._workflow_service = workflow_service

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
                    snapshot.current_message_id == envelope.message_id
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
            elif snapshot.state == TeammateLifecycleState.STOPPING:
                self._set_projection(snapshot, task_id=None, task_status=None, progress_status="stopping")
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

            existing_snapshot = self.snapshot(team_id, teammate_id)
            if existing_snapshot is not None and existing_snapshot.state in {
                TeammateLifecycleState.STOPPING,
                TeammateLifecycleState.STOPPED,
            }:
                if existing_snapshot.shutdown_workflow_id is not None and not existing_snapshot.current_work_attached:
                    await self.complete_shutdown(
                        team_id=team_id,
                        teammate_id=teammate_id,
                        workflow_id=existing_snapshot.shutdown_workflow_id,
                    )
                return None

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
                if snapshot is not None and snapshot.state == TeammateLifecycleState.STOPPING:
                    self._set_projection(snapshot, task_id=None, task_status=None, progress_status="stopping")
                    if snapshot.shutdown_workflow_id is not None and not active_claims:
                        await self.complete_shutdown(
                            team_id=team_id,
                            teammate_id=teammate_id,
                            workflow_id=snapshot.shutdown_workflow_id,
                        )
                    return None
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
            task_id = self._create_projection_job(
                summary=f"teammate:{teammate_id}",
                description=f"{registration.agent_name}:{claimed.kind}",
                metadata={
                    "session_id": registration.session_id,
                    "team_id": team_id,
                    "teammate_id": teammate_id,
                    "run_id": execution_spec.run_id,
                    "message_id": claimed.message_id,
                    "claim_id": claimed.claim_id,
                    "projection_kind": "teammate",
                    "kind": "teammate_projection",
                    "teammate_state": snapshot.state.value,
                },
            )
            self._update_projection_job(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={
                    "session_id": registration.session_id,
                    "teammate_state": snapshot.state.value,
                    "run_id": execution_spec.run_id,
                    "message_id": claimed.message_id,
                    "claim_id": claimed.claim_id,
                    "kind": "teammate_projection",
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
                self._update_projection_job(
                    task_id,
                    status=TaskStatus.FAILED,
                    error=str(exc),
                    metadata={
                        "session_id": registration.session_id,
                        "teammate_state": snapshot.state.value,
                        "mailbox_terminal_state": archived.terminal_state.value if archived.terminal_state else None,
                        "kind": "teammate_projection",
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

            if snapshot.shutdown_workflow_id is not None:
                snapshot = snapshot.stopped()
            else:
                snapshot = snapshot.idle()
            self._write_snapshot(snapshot)
            self._update_projection_job(
                task_id,
                status=terminal_task_status,
                result={
                    "run_id": execution_spec.run_id,
                    "status": status,
                    "message_id": claimed.message_id,
                },
                error=None if terminal_task_status == TaskStatus.COMPLETED else archived.terminal_reason or status,
                metadata={
                    "session_id": registration.session_id,
                    "teammate_state": snapshot.state.value,
                    "mailbox_terminal_state": archived.terminal_state.value if archived.terminal_state is not None else None,
                    "run_id": execution_spec.run_id,
                    "kind": "teammate_projection",
                },
            )
            self._set_projection(
                snapshot,
                task_id=task_id,
                task_status=terminal_task_status,
                progress_status="stopped" if snapshot.state == TeammateLifecycleState.STOPPED else "idle",
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
            if snapshot.shutdown_workflow_id is not None:
                await self.complete_shutdown(
                    team_id=team_id,
                    teammate_id=teammate_id,
                    workflow_id=snapshot.shutdown_workflow_id,
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

    def begin_shutdown(
        self,
        *,
        team_id: str,
        teammate_id: str,
        workflow_id: str,
    ) -> TeammateStateSnapshot | None:
        snapshot = self.snapshot(team_id, teammate_id)
        if snapshot is None:
            return None
        snapshot = snapshot.stopping(workflow_id)
        self._write_snapshot(snapshot)
        projection = self._projections.get((team_id, teammate_id))
        task_id = projection.task_id if projection is not None else None
        if task_id is not None:
            self._update_projection_job(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={
                    "session_id": snapshot.session_id,
                    "teammate_state": snapshot.state.value,
                    "shutdown_workflow_id": workflow_id,
                    "kind": "teammate_projection",
                },
            )
        self._set_projection(
            snapshot,
            task_id=task_id,
            task_status=TaskStatus.RUNNING if task_id is not None else None,
            progress_status="stopping",
            latest_notification=f"Teammate '{teammate_id}' is stopping",
        )
        return snapshot

    async def complete_shutdown(
        self,
        *,
        team_id: str,
        teammate_id: str,
        workflow_id: str,
    ) -> TeammateStateSnapshot | None:
        snapshot = self.snapshot(team_id, teammate_id)
        if snapshot is None:
            return None
        if snapshot.shutdown_workflow_id != workflow_id:
            return snapshot
        if self.workflow_service is not None:
            current = self.workflow_service.get(workflow_id)
            if current is not None and not current.terminal:
                if current.status is TeamWorkflowStatus.PENDING:
                    await self.workflow_service.acknowledge_shutdown(
                        workflow_id,
                        actor_kind=TeamWorkflowActorKind.TEAMMATE,
                        actor_id=teammate_id,
                        payload={"teammate_id": teammate_id},
                    )
                await self.workflow_service.complete_shutdown(
                    workflow_id,
                    actor_kind=TeamWorkflowActorKind.TEAMMATE,
                    actor_id=teammate_id,
                    payload={"teammate_id": teammate_id},
                )
        snapshot = snapshot.stopped()
        self._write_snapshot(snapshot)
        projection = self._projections.get((team_id, teammate_id))
        task_id = projection.task_id if projection is not None else None
        self._set_projection(
            snapshot,
            task_id=task_id,
            task_status=projection.task_status if projection is not None else None,
            progress_status="stopped",
            latest_notification=f"Teammate '{teammate_id}' stopped",
        )
        return snapshot

    async def remove_teammate(
        self,
        *,
        team_id: str,
        teammate_id: str,
    ) -> None:
        key = (team_id, teammate_id)
        await self._stop_heartbeat(team_id, teammate_id)
        self._processing_locks.pop(key, None)
        self._recovered_targets.discard(key)
        self._live_permission_waits = {
            wait for wait in self._live_permission_waits if wait[:2] != (team_id, teammate_id)
        }
        if hasattr(self._registry, "_records"):
            self._registry._records.pop(key, None)  # noqa: SLF001
        self._snapshots.pop(key, None)
        self._projections.pop(key, None)
        self._mailbox.delete_teammate(team_id, teammate_id)

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
            self._update_projection_job(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={
                    "session_id": snapshot.session_id,
                    "teammate_state": snapshot.state.value,
                    "waiting_permission_id": permission_id,
                    "kind": "teammate_projection",
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
            self._update_projection_job(
                task_id,
                status=TaskStatus.RUNNING,
                metadata={
                    "session_id": snapshot.session_id,
                    "teammate_state": snapshot.state.value,
                    "waiting_permission_id": None,
                    "kind": "teammate_projection",
                },
            )
        self._set_projection(
            snapshot,
            task_id=task_id,
            task_status=TaskStatus.RUNNING,
            progress_status=(
                "stopping" if snapshot.state == TeammateLifecycleState.STOPPING else "active"
            ),
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
        metadata.update(_coerce_mapping(payload.get("metadata")))
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
        if (snapshot.team_id, snapshot.teammate_id, permission_id) in self._live_permission_waits:
            return True
        workflow_service = self.workflow_service
        if workflow_service is None:
            return False
        return workflow_service.is_pending(permission_id)

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
            shutdown_workflow_id=snapshot.shutdown_workflow_id,
            progress_status=progress_status,
            latest_notification=latest_notification,
            metadata={
                "agent_name": snapshot.agent_name,
                "session_id": snapshot.session_id,
            },
        )

    def _create_projection_job(
        self,
        *,
        summary: str,
        description: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        record = self._runtime_services.job_service.create_or_update_compat(
            uuid4().hex,
            summary,
            description=description,
            metadata=metadata,
        )
        return record.job_id

    def _update_projection_job(
        self,
        job_id: str,
        *,
        status: TaskStatus | None = None,
        result: Mapping[str, Any] | None | object = None,
        error: str | None | object = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"metadata": metadata}
        if status is not None:
            kwargs["status"] = task_status_to_job_status(status)
        if result is not None:
            kwargs["result"] = result
        if error is not None:
            kwargs["error"] = error
        self._runtime_services.job_service.update_compat(job_id, **kwargs)

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


def _coerce_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): inner for key, inner in value.items()}
    return {}


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
