from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..runtime_services import RuntimeServices
from ..team_config import TeammateOrchestrationConfig
from ..team_control_plane import InMemoryTeamStore, RuntimeTeamControlPlane, RuntimeTeamRunnerManager, TeamStore
from ..team_message_bus import InMemoryTeamMessageStore, RuntimeTeamMessageBus, TeamMessageStore
from ..team_workflows import InMemoryTeamWorkflowStore, RuntimeTeamWorkflowService, TeamWorkflowStore
from ..teammate_orchestration import PersistentTeammateOrchestrator
from ..teammate_orchestration.mailbox import InMemoryTeammateMailbox, TeammateMailboxStore


@dataclass(frozen=True, slots=True)
class TeamCapabilityComponents:
    teammates: PersistentTeammateOrchestrator
    control_plane: RuntimeTeamControlPlane
    message_bus: RuntimeTeamMessageBus
    workflows: RuntimeTeamWorkflowService


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


__all__ = [
    "TeamCapabilityComponents",
    "assemble_team_capability",
]
