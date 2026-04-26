from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..runtime_services import RuntimeServices
from ..team_config import TeammateOrchestrationConfig
from ..team_control_plane import FileBackedTeamStore, RuntimeTeamControlPlane, RuntimeTeamRunnerManager
from ..team_message_bus import FileBackedTeamMessageBus, RuntimeTeamMessageBus
from ..team_workflows import FileBackedTeamWorkflowStore, RuntimeTeamWorkflowService
from ..teammate_orchestration import PersistentTeammateOrchestrator


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
    teammates: PersistentTeammateOrchestrator | None = None,
    control_plane: RuntimeTeamControlPlane | None = None,
    message_bus: RuntimeTeamMessageBus | None = None,
    workflow_service: RuntimeTeamWorkflowService | None = None,
) -> TeamCapabilityComponents:
    resolved_teammates = teammates or PersistentTeammateOrchestrator(
        config=config,
        project_root=project_root,
        runtime_services=runtime_services,
        execution_core=execution_core,
    )
    runtime_services.bind_teammates(resolved_teammates)

    runner_manager = RuntimeTeamRunnerManager(
        teammates=resolved_teammates,
        runtime_services=runtime_services,
    )
    resolved_control_plane = control_plane or RuntimeTeamControlPlane(
        store=FileBackedTeamStore(project_root / ".runtime" / "team_control_plane"),
        runtime_services=runtime_services,
        runner_manager=runner_manager,
    )
    resolved_workflows = workflow_service or RuntimeTeamWorkflowService(
        store=FileBackedTeamWorkflowStore(project_root / ".runtime" / "team_workflows"),
        control_plane=resolved_control_plane,
        runtime_services=runtime_services,
    )
    resolved_message_bus = message_bus or RuntimeTeamMessageBus(
        store=FileBackedTeamMessageBus(project_root / ".runtime" / "team_messages"),
        control_plane=resolved_control_plane,
        runtime_services=runtime_services,
    )
    resolved_workflows.bind_message_bus(resolved_message_bus)
    runtime_services.bind_team_services(
        control_plane=resolved_control_plane,
        message_bus=resolved_message_bus,
        workflow_service=resolved_workflows,
    )
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
