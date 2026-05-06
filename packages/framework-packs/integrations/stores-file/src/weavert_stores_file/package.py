from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from weavert.agent_execution import ChildRunStore
from weavert.jobs import FileJobStore
from weavert.session_runtime import FileTranscriptStore
from weavert.task_lists import FileTaskListStore
from weavert.team_config import TeammateOrchestrationConfig
from weavert.team_control_plane import FileBackedTeamStore
from weavert.team_message_bus import FileBackedTeamMessageBus
from weavert.team_workflows import FileBackedTeamWorkflowStore
from weavert.teammate_orchestration import FileBackedTeammateMailbox
from weavert.extension_contracts.public_contract import ensure_canonical_workspace_root
from weavert.package_system.protocols import (
    PackageAssemblyStage,
    PackageContext,
    PackageContribution,
    StoreBinding,
)
from .child_runs import FileChildRunStore


@dataclass(frozen=True, slots=True)
class RuntimeFileStoreBundle:
    transcript_store: FileTranscriptStore
    child_run_store: ChildRunStore
    job_store: FileJobStore
    task_list_store: FileTaskListStore
    team_store: FileBackedTeamStore
    team_message_store: FileBackedTeamMessageBus
    team_workflow_store: FileBackedTeamWorkflowStore
    teammate_mailbox: FileBackedTeammateMailbox


@dataclass(frozen=True, slots=True)
class TeamFileStoreBundle:
    team_store: FileBackedTeamStore
    team_message_store: FileBackedTeamMessageBus
    team_workflow_store: FileBackedTeamWorkflowStore
    teammate_mailbox: FileBackedTeammateMailbox


def assemble_team_file_store_bundle(
    *,
    project_root: Path,
    teammate_config: TeammateOrchestrationConfig | None = None,
) -> TeamFileStoreBundle:
    runtime_root = ensure_canonical_workspace_root(project_root)
    config = teammate_config or TeammateOrchestrationConfig()
    mailbox_root = config.mailbox_root or (runtime_root / "teammates")
    return TeamFileStoreBundle(
        team_store=FileBackedTeamStore(runtime_root / "team_control_plane"),
        team_message_store=FileBackedTeamMessageBus(runtime_root / "team_messages"),
        team_workflow_store=FileBackedTeamWorkflowStore(runtime_root / "team_workflows"),
        teammate_mailbox=FileBackedTeammateMailbox(
            mailbox_root,
            default_claim_lease_ms=config.claim_lease_ms,
            default_retry_max_attempts=config.retry_max_attempts,
            retry_backoff_ms=config.retry_backoff_ms,
        ),
    )


def assemble_file_store_bundle(
    *,
    project_root: Path,
    teammate_config: TeammateOrchestrationConfig | None = None,
) -> RuntimeFileStoreBundle:
    runtime_root = ensure_canonical_workspace_root(project_root)
    team_bundle = assemble_team_file_store_bundle(
        project_root=project_root,
        teammate_config=teammate_config,
    )
    return RuntimeFileStoreBundle(
        transcript_store=FileTranscriptStore(runtime_root / "transcripts"),
        child_run_store=FileChildRunStore(runtime_root / "child_runs"),
        job_store=FileJobStore(runtime_root / "jobs"),
        task_list_store=FileTaskListStore(runtime_root / "task_lists"),
        team_store=team_bundle.team_store,
        team_message_store=team_bundle.team_message_store,
        team_workflow_store=team_bundle.team_workflow_store,
        teammate_mailbox=team_bundle.teammate_mailbox,
    )


def assemble_runtime_stores_file_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = assemble_file_store_bundle(
        project_root=context.working_directory,
        teammate_config=getattr(context.config, "teammate_orchestration", None),
    )
    owner = context.ownership("store_binding")
    return PackageContribution(
        store_bindings=(
            StoreBinding(slot="transcript_store", store=components.transcript_store, owner=owner),
            StoreBinding(slot="child_run_store", store=components.child_run_store, owner=owner),
            StoreBinding(slot="job_store", store=components.job_store, owner=owner),
            StoreBinding(slot="task_list_store", store=components.task_list_store, owner=owner),
            StoreBinding(slot="team_store", store=components.team_store, owner=owner),
            StoreBinding(slot="team_message_store", store=components.team_message_store, owner=owner),
            StoreBinding(slot="team_workflow_store", store=components.team_workflow_store, owner=owner),
            StoreBinding(slot="teammate_mailbox", store=components.teammate_mailbox, owner=owner),
        ),
    )


__all__ = [
    "RuntimeFileStoreBundle",
    "TeamFileStoreBundle",
    "assemble_file_store_bundle",
    "assemble_runtime_stores_file_package",
    "assemble_team_file_store_bundle",
]
