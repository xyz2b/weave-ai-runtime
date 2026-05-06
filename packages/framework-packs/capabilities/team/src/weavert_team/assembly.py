from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from weavert.package_system.manifests import _load_builtin_tool_contribution
from weavert.package_system.protocols import (
    CapabilityBinding,
    HostFacetBinding,
    IngressReceiptHandlerBinding,
    PackageAssemblyStage,
    PackageContext,
    PackageContribution,
    PackageLifecycleParticipant,
    PackageLifecyclePhase,
    RuntimeCapabilityKey,
    RuntimeHostFacetKey,
)
from weavert.runtime_services import RuntimeServices
from weavert.team_config import TeammateOrchestrationConfig
from weavert.team_control_plane import InMemoryTeamStore, RuntimeTeamControlPlane, RuntimeTeamRunnerManager, TeamStore
from weavert.team_message_bus import InMemoryTeamMessageStore, RuntimeTeamMessageBus, TeamMessageStore
from weavert.team_workflows import InMemoryTeamWorkflowStore, RuntimeTeamWorkflowService, TeamWorkflowStore
from weavert.teammate_orchestration import PersistentTeammateOrchestrator
from weavert.teammate_orchestration.mailbox import InMemoryTeammateMailbox, TeammateMailboxStore


@dataclass(frozen=True, slots=True)
class TeamCapabilityComponents:
    teammates: PersistentTeammateOrchestrator
    control_plane: RuntimeTeamControlPlane
    message_bus: RuntimeTeamMessageBus
    workflows: RuntimeTeamWorkflowService


@dataclass(frozen=True, slots=True)
class TeamWorkflowHostFacet:
    control_plane: Any
    workflows: Any

    async def list_workflows(
        self,
        *,
        team_id: str | None = None,
        session_id: str | None = None,
        pending_only: bool | None = True,
    ) -> tuple[Any, ...]:
        resolved_team_id, _ = self._resolve_team_workflow_scope(
            team_id=team_id,
            session_id=session_id,
        )
        return tuple(
            self.workflows.list_workflows(team_id=resolved_team_id, pending_only=pending_only)
        )

    async def respond(
        self,
        workflow_id: str,
        *,
        action: str,
        host_name: str | None = None,
        payload: dict[str, Any] | None = None,
        team_id: str | None = None,
        session_id: str | None = None,
    ) -> Any:
        resolved_team_id, resolved_session_id = self._resolve_team_workflow_scope(
            team_id=team_id,
            session_id=session_id,
        )
        self._resolve_scoped_workflow(
            workflow_id,
            team_id=resolved_team_id,
            session_id=resolved_session_id,
        )
        return await self.workflows.respond_host(
            workflow_id=workflow_id,
            action=action,
            host_name=host_name,
            payload=payload,
        )

    def _resolve_team_workflow_scope(
        self,
        *,
        team_id: str | None,
        session_id: str | None,
    ) -> tuple[str | None, str | None]:
        from weavert.team_workflows import TeamWorkflowError

        resolved_team_id = str(team_id).strip() if team_id is not None and str(team_id).strip() else None
        resolved_session_id = (
            str(session_id).strip() if session_id is not None and str(session_id).strip() else None
        )
        if resolved_team_id is None and resolved_session_id is None:
            raise TeamWorkflowError(
                "invalid_workflow_scope",
                "Host workflow operations require a team_id or session_id scope",
            )
        if resolved_session_id is None:
            return resolved_team_id, resolved_session_id
        if self.control_plane is None or not hasattr(self.control_plane, "active_team_for_leader_session"):
            return resolved_team_id, resolved_session_id
        team = self.control_plane.active_team_for_leader_session(resolved_session_id)
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
        return team.team_id, resolved_session_id

    def _resolve_scoped_workflow(
        self,
        workflow_id: str,
        *,
        team_id: str | None,
        session_id: str | None,
    ) -> Any:
        from weavert.team_workflows import TeamWorkflowError

        normalized_workflow_id = str(workflow_id).strip()
        for record in self.workflows.list_workflows(team_id=team_id, pending_only=None):
            if str(getattr(record, "workflow_id", "") or "") == normalized_workflow_id:
                return record
        if hasattr(self.workflows, "get"):
            record = self.workflows.get(normalized_workflow_id)
            if record is not None and (team_id is None or getattr(record, "team_id", None) == team_id):
                return record
        scope_details = {"workflow_id": normalized_workflow_id}
        if team_id is not None:
            scope_details["team_id"] = team_id
        if session_id is not None:
            scope_details["session_id"] = session_id
        raise TeamWorkflowError(
            "not_found",
            f"Workflow '{normalized_workflow_id}' was not found in the requested team scope",
            **scope_details,
        )


def assemble_team_capability(
    *,
    config: TeammateOrchestrationConfig,
    project_root: Path,
    runtime_services: RuntimeServices,
    execution_core: Any,
    bind_runtime_services: bool = True,
    teammates: PersistentTeammateOrchestrator | None = None,
    control_plane: RuntimeTeamControlPlane | None = None,
    message_bus: RuntimeTeamMessageBus | None = None,
    workflow_service: RuntimeTeamWorkflowService | None = None,
    team_store: TeamStore | None = None,
    message_store: TeamMessageStore | None = None,
    workflow_store: TeamWorkflowStore | None = None,
    mailbox: TeammateMailboxStore | None = None,
) -> TeamCapabilityComponents:
    resolved_team_store = team_store or InMemoryTeamStore()
    resolved_message_store = message_store or InMemoryTeamMessageStore()
    resolved_workflow_store = workflow_store or InMemoryTeamWorkflowStore()
    resolved_mailbox = mailbox or InMemoryTeammateMailbox(
        default_claim_lease_ms=config.claim_lease_ms,
        default_retry_max_attempts=config.retry_max_attempts,
        retry_backoff_ms=config.retry_backoff_ms,
    )
    resolved_teammates = teammates or PersistentTeammateOrchestrator(
        config=config,
        project_root=project_root,
        runtime_services=runtime_services,
        execution_core=execution_core,
        mailbox=resolved_mailbox,
    )
    if bind_runtime_services:
        runtime_services.bind_teammates(resolved_teammates)

    runner_manager = RuntimeTeamRunnerManager(
        teammates=resolved_teammates,
        runtime_services=runtime_services,
    )
    resolved_control_plane = control_plane or RuntimeTeamControlPlane(
        store=resolved_team_store,
        runtime_services=runtime_services,
        runner_manager=runner_manager,
    )
    resolved_workflows = workflow_service or RuntimeTeamWorkflowService(
        store=resolved_workflow_store,
        control_plane=resolved_control_plane,
        runtime_services=runtime_services,
    )
    resolved_message_bus = message_bus or RuntimeTeamMessageBus(
        store=resolved_message_store,
        control_plane=resolved_control_plane,
        runtime_services=runtime_services,
    )
    resolved_workflows.bind_message_bus(resolved_message_bus)
    if hasattr(resolved_teammates, "bind_workflow_service"):
        resolved_teammates.bind_workflow_service(resolved_workflows)
    return TeamCapabilityComponents(
        teammates=resolved_teammates,
        control_plane=resolved_control_plane,
        message_bus=resolved_message_bus,
        workflows=resolved_workflows,
    )


def assemble_runtime_team_package(context: PackageContext) -> PackageContribution:
    if context.stage == PackageAssemblyStage.BUILTINS:
        return PackageContribution(
            builtin_tools=_load_builtin_tool_contribution(
                context,
                "weavert_team.builtins:team_builtin_tools",
            )
        )
    if context.stage != PackageAssemblyStage.RUNTIME:
        return PackageContribution()
    services = context.require_resource("runtime_services")
    execution_core = context.require_resource("execution_core")
    store_bindings = dict(context.resource("store_bindings", {}))
    teammate_config = _resolve_team_config(context)
    components = assemble_team_capability(
        config=teammate_config,
        project_root=context.working_directory,
        runtime_services=services,
        execution_core=execution_core,
        bind_runtime_services=False,
        team_store=store_bindings.get("team_store"),
        message_store=store_bindings.get("team_message_store"),
        workflow_store=store_bindings.get("team_workflow_store"),
        mailbox=store_bindings.get("teammate_mailbox"),
    )
    workflow_facet = TeamWorkflowHostFacet(
        control_plane=components.control_plane,
        workflows=components.workflows,
    )

    async def recover_team_workflows(*, services: Any = None, **_kwargs: Any) -> None:
        _ = services
        await components.workflows.recover_pending()

    async def replay_pending_leader_messages(
        *,
        session: Any = None,
        services: Any = None,
        **_kwargs: Any,
    ) -> None:
        if session is None or getattr(getattr(session, "state", None), "queued_commands", None):
            return
        runtime_services = services or context.require_resource("runtime_services")
        message_bus = runtime_services.resolve_capability(RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)
        if message_bus is None or not hasattr(message_bus, "replay_pending_leader_messages"):
            return
        await message_bus.replay_pending_leader_messages(
            session_id=session.state.session_id,
            session=session,
        )

    async def acknowledge_team_delivery(
        *,
        receipt: Any,
        services: Any = None,
        **_kwargs: Any,
    ) -> None:
        runtime_services = services or context.require_resource("runtime_services")
        message_bus = runtime_services.resolve_capability(RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)
        if message_bus is None or not hasattr(message_bus, "acknowledge_delivery"):
            return
        payload = getattr(receipt, "payload", None)
        if not isinstance(payload, dict):
            return
        team_id = str(payload.get("team_id") or "").strip()
        message_id = str(payload.get("message_id") or "").strip()
        delivery_id = str(payload.get("delivery_id") or "").strip()
        if not team_id or not message_id or not delivery_id:
            return
        await message_bus.acknowledge_delivery(
            team_id=team_id,
            message_id=message_id,
            delivery_id=delivery_id,
        )

    return PackageContribution(
        capabilities=(
            CapabilityBinding(
                key=RuntimeCapabilityKey.TEAMMATES.value,
                value=components.teammates,
                owner=context.ownership("capability", component="teammates"),
            ),
            CapabilityBinding(
                key=RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value,
                value=components.control_plane,
                owner=context.ownership("capability", component="control_plane"),
            ),
            CapabilityBinding(
                key=RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value,
                value=components.message_bus,
                owner=context.ownership("capability", component="message_bus"),
            ),
            CapabilityBinding(
                key=RuntimeCapabilityKey.TEAM_WORKFLOWS.value,
                value=components.workflows,
                owner=context.ownership("capability", component="workflows"),
            ),
        ),
        host_facets=(
            HostFacetBinding(
                name=RuntimeHostFacetKey.TEAM_WORKFLOWS.value,
                facet=workflow_facet,
                owner=context.ownership("host_facet", facet=RuntimeHostFacetKey.TEAM_WORKFLOWS.value),
            ),
        ),
        ingress_receipt_handlers=(
            IngressReceiptHandlerBinding(
                kind="weavert.team.delivery_ack",
                handler=acknowledge_team_delivery,
                owner=context.ownership("ingress_receipt", kind="weavert.team.delivery_ack"),
            ),
        ),
        lifecycle_participants=(
            PackageLifecycleParticipant(
                phase=PackageLifecyclePhase.RUNTIME_RECOVERY,
                name="weavert-team-recover-pending-workflows",
                handler=recover_team_workflows,
                owner=context.ownership("lifecycle", phase=PackageLifecyclePhase.RUNTIME_RECOVERY.value),
            ),
            PackageLifecycleParticipant(
                phase=PackageLifecyclePhase.SESSION_OPEN,
                name="weavert-team-replay-pending-leader-messages",
                handler=replay_pending_leader_messages,
                owner=context.ownership("lifecycle", phase=PackageLifecyclePhase.SESSION_OPEN.value),
            ),
        ),
    )


def _resolve_team_config(context: PackageContext) -> TeammateOrchestrationConfig:
    config = getattr(context.config, "teammate_orchestration", None)
    if config is None:
        return TeammateOrchestrationConfig(enabled=True)
    return replace(config, enabled=True)


__all__ = [
    "TeamCapabilityComponents",
    "assemble_team_capability",
    "assemble_runtime_team_package",
]
