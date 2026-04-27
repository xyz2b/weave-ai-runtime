from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import runtime.runtime_kernel.kernel as runtime_kernel_module
from runtime.contracts import MessageRole, RuntimeMessage
from runtime.devtools.builtins import devtools_builtin_tools
from runtime.diagnostics import Diagnostic, DiagnosticSeverity
from runtime.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    InvocationDefinition,
    InvocationExecutionPolicy,
    InvocationSourceKind,
    InvocationTargetKind,
    InvocationVisibilityPolicy,
)
from runtime.hosts.base import NullHostAdapter
from runtime.invocation_catalog import StaticInvocationProvider
from runtime.jobs import FileJobStore
from runtime.runtime_kernel import (
    BuiltinPackConfig,
    RuntimeConfig,
    RuntimeDistribution,
    assemble_runtime,
    build_runtime_kernel,
)
from runtime.runtime_core_protocol_catalog import CORE_PROTOCOL_CATALOG_SCHEMA_VERSION
from runtime.runtime_package_manifests import official_runtime_package_manifests
from runtime.runtime_package_protocols import (
    CapabilityBinding,
    ContextContributorBinding,
    HostFacetBinding,
    IngressReceiptHandlerBinding,
    InvocationProviderContribution,
    PackageAssemblyStage,
    PackageContribution,
    PackageLifecycleParticipant,
    PackageLifecyclePhase,
    PackageOwnership,
    ContextContributorStage,
    RuntimeCapabilityKey,
    RuntimeHostFacetKey,
    RuntimePackageManifest,
)
from runtime.runtime_services import RuntimeServices
from runtime.session_runtime import FileTranscriptStore
from runtime.task_lists import FileTaskListStore
from runtime.team_workflows import TeamWorkflowError
from runtime.turn_engine import ModelStreamEvent, ModelStreamEventType


def _invocation_definition(
    name: str,
    *,
    target_name: str,
    origin_path: str,
    paths: tuple[str, ...] = (),
) -> InvocationDefinition:
    return InvocationDefinition(
        name=name,
        source_kind=InvocationSourceKind.PLUGIN_COMMAND,
        description=f"{name} invocation",
        visibility_policy=InvocationVisibilityPolicy(paths=paths),
        execution_policy=InvocationExecutionPolicy(
            target_kind=InvocationTargetKind.PLUGIN_COMMAND,
            target_name=target_name,
        ),
        origin=DefinitionOrigin(DefinitionSource.USER, path=Path(origin_path)),
    )


def test_official_runtime_package_manifests_follow_dependency_order() -> None:
    manifests = official_runtime_package_manifests(("runtime-team", "runtime-core"))

    assert tuple(manifest.name for manifest in manifests) == (
        "runtime-core",
        "runtime-team",
    )


def test_runtime_services_apply_package_contribution_registers_protocol_surfaces() -> None:
    services = RuntimeServices(host=NullHostAdapter())
    manifest = RuntimePackageManifest(
        name="runtime-example",
        role="capability",
        description="Example package",
    )
    observed_phases: list[str] = []
    observed_receipts: list[str] = []

    class ExampleContributor:
        async def collect(self, **_kwargs):
            return ("example context",)

    async def handle_cleanup(**kwargs):
        observed_phases.append(kwargs["phase"].value)

    participant = PackageLifecycleParticipant(
        phase=PackageLifecyclePhase.SESSION_CLOSE,
        name="cleanup",
        handler=handle_cleanup,
        owner=PackageOwnership(
            package_name="runtime-example",
            package_role="capability",
            surface="lifecycle",
        ),
        order=10,
    )
    contribution = PackageContribution(
        context_contributors=(
            ContextContributorBinding(
                name="runtime.example.context",
                stage=ContextContributorStage.HOOKS,
                contributor=ExampleContributor(),
                owner=PackageOwnership(
                    package_name="runtime-example",
                    package_role="capability",
                    surface="context_contributor",
                ),
                order=5,
            ),
        ),
        capabilities=(
            CapabilityBinding(
                key="runtime.example.service",
                value={"service": "example"},
                owner=PackageOwnership(
                    package_name="runtime-example",
                    package_role="capability",
                    surface="capability",
                ),
            ),
        ),
        lifecycle_participants=(participant,),
        host_facets=(
            HostFacetBinding(
                name="runtime.example.facet",
                facet={"facet": "example"},
                owner=PackageOwnership(
                    package_name="runtime-example",
                    package_role="capability",
                    surface="host_facet",
                ),
            ),
        ),
        ingress_receipt_handlers=(
            IngressReceiptHandlerBinding(
                kind="runtime.example.receipt",
                handler=lambda *, receipt, **_kwargs: observed_receipts.append(receipt.receipt_id),
                owner=PackageOwnership(
                    package_name="runtime-example",
                    package_role="capability",
                    surface="ingress_receipt",
                ),
            ),
        ),
    )

    services.apply_package_contribution(manifest, contribution, stage="runtime")

    assert services.require_capability("runtime.example.service") == {"service": "example"}
    assert services.capability_registry.owner("runtime.example.service").package_name == "runtime-example"
    plan = services.context_contributor_execution_plan()
    assert [(entry.binding.name, entry.stage.name.value) for entry in plan] == [
        ("runtime.example.context", ContextContributorStage.HOOKS.value),
    ]
    assert services.lifecycle_participants(PackageLifecyclePhase.SESSION_CLOSE) == (participant,)
    facet = services.resolve_host_facet("runtime.example.facet")
    assert facet.available is True
    assert facet.facet == {"facet": "example"}
    assert services.metadata["package_capability_owners"]["runtime.example.service"]["package_name"] == "runtime-example"
    assert services.metadata["package_context_contributor_owners"]["runtime.example.context"]["stage"] == (
        ContextContributorStage.HOOKS.value
    )
    assert services.metadata["package_ingress_receipt_owners"]["runtime.example.receipt"]["package_name"] == "runtime-example"
    assert services.metadata["package_contributions"][0]["package_name"] == "runtime-example"
    assert services.metadata["package_contributions"][0]["context_contributors"] == ["runtime.example.context"]
    assert asyncio.run(services.dispatch_lifecycle_phase(PackageLifecyclePhase.SESSION_CLOSE)) == ()
    asyncio.run(
        services.execute_ingress_completion_receipt(
            type("Receipt", (), {"kind": "runtime.example.receipt", "receipt_id": "receipt-1"})()
        )
    )
    assert observed_phases == [PackageLifecyclePhase.SESSION_CLOSE.value]
    assert observed_receipts == ["receipt-1"]
    try:
        services.require_capability("runtime.example.missing")
    except KeyError as exc:
        assert "runtime.example.missing" in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("Missing capability lookup should raise KeyError")


def test_runtime_services_prefer_team_capabilities_over_compatibility_slots() -> None:
    services = RuntimeServices(host=NullHostAdapter())
    capability_control_plane = object()
    capability_message_bus = object()
    capability_workflows = object()
    services.team_control_plane = object()
    services.team_message_bus = object()
    services.team_workflows = object()
    owner = PackageOwnership(
        package_name="runtime-team",
        package_role="capability",
        surface="capability",
    )

    services.bind_capability(
        CapabilityBinding(
            key=RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value,
            value=capability_control_plane,
            owner=owner,
        )
    )
    services.bind_capability(
        CapabilityBinding(
            key=RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value,
            value=capability_message_bus,
            owner=owner,
        )
    )
    services.bind_capability(
        CapabilityBinding(
            key=RuntimeCapabilityKey.TEAM_WORKFLOWS.value,
            value=capability_workflows,
            owner=owner,
        )
    )

    assert services.resolve_team_control_plane() is capability_control_plane
    assert services.resolve_team_message_bus() is capability_message_bus
    assert services.resolve_team_workflows() is capability_workflows


def test_manifest_backed_team_runtime_registers_capabilities_and_host_facet(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    assert runtime.services.require_capability(RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value) is runtime.team_control_plane
    assert runtime.services.require_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value) is runtime.team_workflows
    assert runtime.services.metadata["compatibility_projections"]["teammates"] == RuntimeCapabilityKey.TEAMMATES.value
    assert runtime.services.metadata["compatibility_projections"]["team_control_plane"] == RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value
    assert runtime.services.metadata["package_lookup"]["canonical_capabilities"] == {
        "teammates": RuntimeCapabilityKey.TEAMMATES.value,
        "team_control_plane": RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value,
        "team_message_bus": RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value,
        "team_workflows": RuntimeCapabilityKey.TEAM_WORKFLOWS.value,
    }
    assert runtime.services.metadata["package_lookup"]["canonical_host_facets"] == {
        "team_workflows": RuntimeHostFacetKey.TEAM_WORKFLOWS.value,
    }
    assert "TaskManager" in runtime.services.metadata["package_lookup"]["compatibility_wrappers"]
    assert "RuntimeServices.teammates" in runtime.services.metadata["package_lookup"]["compatibility_wrappers"]
    assert "RuntimeAssembly.teammates" in runtime.services.metadata["package_lookup"]["compatibility_wrappers"]
    assert runtime.metadata["package_lookup"] == runtime.services.metadata["package_lookup"]
    assert {
        participant.name
        for participant in runtime.services.lifecycle_participants(PackageLifecyclePhase.RUNTIME_RECOVERY)
    } == {"runtime-team-recover-pending-workflows"}
    assert {
        participant.name
        for participant in runtime.services.lifecycle_participants(PackageLifecyclePhase.SESSION_OPEN)
    } == {"runtime-team-replay-pending-leader-messages"}
    assert runtime.services.metadata["package_ingress_receipt_owners"]["runtime.team.delivery_ack"]["package_name"] == "runtime-team"
    facet = runtime.services.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)
    assert facet.available is True
    listed = asyncio.run(facet.facet.list_workflows(team_id=None, session_id=None, pending_only=True))
    assert listed == ()


def test_runtime_core_protocol_catalog_is_published_separately_from_package_lookup(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    catalog = runtime.services.metadata["core_protocol_catalog"]
    protocols = catalog["protocols"]

    assert catalog["schema_version"] == CORE_PROTOCOL_CATALOG_SCHEMA_VERSION
    assert catalog["published_metadata_paths"] == [
        "runtime.services.metadata['core_protocol_catalog']",
        "runtime.metadata['core_protocol_catalog']",
    ]
    assert catalog["adjacent_metadata"]["package_lookup"] == (
        "source of truth for package-specific canonical keys and wrapper status"
    )
    assert runtime.metadata["core_protocol_catalog"] == catalog
    assert set(protocols) == {
        "runtime.transcript.store",
        "runtime.job.service",
        "runtime.task-list.service",
        "runtime.permission.service",
        "runtime.elicitation.service",
        "runtime.context-contributors.registry",
        "runtime.invocation-provider.registry",
        "runtime.host.binding",
    }

    transcript = protocols["runtime.transcript.store"]
    assert transcript["canonical_name"] == "TranscriptStore"
    assert transcript["binding_boundary"] == "config-owned"
    assert transcript["canonical_binding_surface"] == "RuntimeConfig.transcript_store"
    assert transcript["discovery_surface"] == "RuntimeServices.transcript_store / RuntimeAssembly.transcript_store"

    context_contributors = protocols["runtime.context-contributors.registry"]
    assert context_contributors["compatibility_status"] == "stable-with-compatibility"
    assert context_contributors["retained_surfaces"] == [
        {"surface": "RuntimeServices.memory.collect", "status": "compatibility-only"},
        {"surface": "RuntimeServices.hooks.collect", "status": "compatibility-only"},
        {"surface": "RuntimeServices.task_discipline.collect", "status": "compatibility-only"},
    ]

    invocation_registry = protocols["runtime.invocation-provider.registry"]
    assert invocation_registry["canonical_binding_surface"] == "PackageContribution.invocation_providers"
    assert invocation_registry["retained_surfaces"] == [
        {
            "surface": "RuntimeConfig.extra_invocation_providers",
            "status": "bounded-compatibility",
        }
    ]

    assert RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value not in protocols
    assert runtime.services.metadata["package_lookup"]["canonical_capabilities"]["team_control_plane"] == (
        RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value
    )


def test_runtime_context_contributor_registry_exposes_canonical_stage_catalog(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    stage_names = [stage["name"] for stage in runtime.services.metadata["context_contributors"]["stages"]]
    assert stage_names == ["memory", "hooks", "task_policy"]

    bindings = runtime.services.metadata["context_contributors"]["bindings"]
    binding_names = [entry["name"] for entry in bindings]
    assert "runtime-memory.collect" in binding_names
    assert "runtime-core.task_discipline.collect" in binding_names

    lookup = runtime.services.metadata["package_lookup"]
    assert lookup["canonical_context_contributors"] == {
        "package_contributions": "PackageContribution.context_contributors",
        "registry": "RuntimeServices.context_contributor_execution_plan",
        "stage_catalog": ["memory", "hooks", "task_policy"],
    }
    assert lookup["compatibility_context_contributors"] == {
        "RuntimeServices.memory.collect": "compatibility-only",
        "RuntimeServices.hooks.collect": "compatibility-only",
        "RuntimeServices.task_discipline.collect": "compatibility-only",
    }
    assert lookup["dedicated_control_plane_paths"] == {
        "compaction": "RuntimeServices.compaction.prepare_turn / RuntimeServices.compaction.collect",
    }
    assert runtime.services.metadata["compatibility_surfaces"]["RuntimeServices.memory.collect"] == (
        "compatibility-only"
    )
    assert runtime.services.metadata["compatibility_surfaces"]["RuntimeServices.compaction.prepare_turn"] == (
        "dedicated-control-plane"
    )
    assert runtime.metadata["context_contributors"] == runtime.services.metadata["context_contributors"]


def test_runtime_core_protocol_catalog_keeps_package_capabilities_and_wrappers_out_of_core_entries(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
        )
    )

    protocols = runtime.services.metadata["core_protocol_catalog"]["protocols"]
    retained_surfaces = {
        surface["surface"]
        for entry in protocols.values()
        for surface in entry.get("retained_surfaces", [])
    }

    assert RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value not in protocols
    assert RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value not in protocols
    assert RuntimeCapabilityKey.TEAM_WORKFLOWS.value not in protocols
    assert RuntimeHostFacetKey.TEAM_WORKFLOWS.value not in protocols
    assert "TaskManager" not in {entry["canonical_name"] for entry in protocols.values()}
    assert "RuntimeServices.teammates" not in retained_surfaces
    assert "RuntimeAssembly.teammates" not in retained_surfaces
    assert "BoundHostRuntime.list_team_workflows" not in retained_surfaces
    assert runtime.services.metadata["compatibility_surfaces"]["RuntimeServices.teammates"] == (
        "compatibility-only"
    )
    assert "RuntimeServices.teammates" in runtime.services.metadata["package_lookup"]["compatibility_wrappers"]
    assert "BoundHostRuntime.list_team_workflows" in runtime.services.metadata["package_lookup"][
        "compatibility_wrappers"
    ]


def test_package_context_contributor_order_is_deterministic_across_packages(tmp_path: Path) -> None:
    original = runtime_kernel_module.official_runtime_package_manifests

    def assemble_package(binding_name: str):
        class ExampleContributor:
            async def collect(self, **_kwargs):
                return ()

        def _assemble(context):
            if context.stage != PackageAssemblyStage.SERVICES:
                return PackageContribution()
            return PackageContribution(
                context_contributors=(
                    ContextContributorBinding(
                        name=binding_name,
                        stage=ContextContributorStage.HOOKS,
                        contributor=ExampleContributor(),
                        owner=context.ownership("context_contributor"),
                        order=0,
                    ),
                )
            )

        return _assemble

    manifests = {
        "pkg-alpha": RuntimePackageManifest(
            name="pkg-alpha",
            role="capability",
            dependencies=("runtime-core",),
            assembly_entrypoint=assemble_package("zzz.context"),
        ),
        "pkg-beta": RuntimePackageManifest(
            name="pkg-beta",
            role="capability",
            dependencies=("runtime-core",),
            assembly_entrypoint=assemble_package("aaa.context"),
        ),
    }

    def build_kernel(package_order: tuple[str, str]):
        def patched_manifests(selected_packages):
            return (
                *original(selected_packages),
                *(manifests[name] for name in package_order),
            )

        runtime_kernel_module.official_runtime_package_manifests = patched_manifests
        try:
            return build_runtime_kernel(
                RuntimeConfig(
                    working_directory=tmp_path,
                    distribution=RuntimeDistribution.CORE,
                )
            )
        finally:
            runtime_kernel_module.official_runtime_package_manifests = original

    forward = build_kernel(("pkg-beta", "pkg-alpha"))
    reversed_order = build_kernel(("pkg-alpha", "pkg-beta"))

    def contributor_names(kernel) -> list[str]:
        return [
            entry.binding.name
            for entry in kernel.services.context_contributor_execution_plan()
            if entry.binding.owner.package_name in {"pkg-alpha", "pkg-beta"}
        ]

    assert contributor_names(forward) == ["zzz.context", "aaa.context"]
    assert contributor_names(reversed_order) == ["zzz.context", "aaa.context"]


def test_runtime_team_compatibility_projections_delegate_to_canonical_capabilities(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    canonical_plane = runtime.services.require_capability(RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value)
    canonical_bus = runtime.services.require_capability(RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)
    canonical_workflows = runtime.services.require_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value)
    runtime.services.team_control_plane = object()
    runtime.services.team_message_bus = object()
    runtime.services.team_workflows = object()
    runtime.team_control_plane = object()
    runtime.team_message_bus = object()
    runtime.team_workflows = object()

    assert runtime.services.team_control_plane is canonical_plane
    assert runtime.services.team_message_bus is canonical_bus
    assert runtime.services.team_workflows is canonical_workflows
    assert runtime.team_control_plane is canonical_plane
    assert runtime.team_message_bus is canonical_bus
    assert runtime.team_workflows is canonical_workflows


def test_runtime_workflow_helpers_prefer_canonical_lookup_over_compatibility_slots(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )
    plane = runtime.team_control_plane
    workflows = runtime.team_workflows
    assert plane is not None
    assert workflows is not None

    async def scenario():
        async with runtime.bind_host(NullHostAdapter(name="compat")) as bound:
            team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
            member = await plane.register_member(
                session_id="leader-session",
                extensions={},
                name="alpha",
                agent_name="main-router",
                execution_defaults={"cwd": str(tmp_path)},
            )
            workflow = await workflows.create_permission_workflow(
                team=team,
                requester_member_id=member.member_id,
                requester_name=member.name,
                responder_member_id=team.leader_member_id,
                responder_name="leader",
                request_payload={"permission_name": "bash", "permission_message": "approve?"},
            )
            runtime.services.team_control_plane = object()
            runtime.services.team_workflows = object()
            runtime.team_control_plane = object()
            runtime.team_workflows = object()

            pending = await runtime.list_team_workflows(session_id="leader-session", pending_only=True)
            updated = await bound.respond_team_workflow(
                workflow.workflow_id,
                action="reject",
                session_id="leader-session",
            )
            return pending, updated

    pending, updated = asyncio.run(scenario())

    assert pending
    assert pending[0]["workflow_kind"] == "permission"
    assert updated["workflow_id"] == pending[0]["workflow_id"]
    assert updated["status"] == "rejected"


def test_bound_host_workflow_helpers_preserve_bounded_absent_package_behavior(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
        )
    )

    async def scenario():
        async with runtime.bind_host(NullHostAdapter(name="compat")) as bound:
            listed = await bound.list_team_workflows(team_id="team-core", pending_only=True)
            missing = None
            try:
                await bound.respond_team_workflow(
                    "workflow-core",
                    action="reject",
                    team_id="team-core",
                )
            except TeamWorkflowError as exc:
                missing = exc
            return listed, missing

    listed, missing = asyncio.run(scenario())

    assert listed == ()
    assert missing is not None
    assert missing.code == "not_available"


def test_bound_host_workflow_helpers_delegate_through_host_facet_without_capability(tmp_path: Path) -> None:
    class FacetWorkflowRecord:
        def __init__(
            self,
            *,
            workflow_id: str = "workflow-facet",
            team_id: str = "team-facet",
            leader_session_id: str | None = "leader-facet",
            status: str = "pending",
            response_payload: dict[str, str] | None = None,
        ) -> None:
            self.workflow_id = workflow_id
            self.team_id = team_id
            self.workflow_kind = "permission"
            self.requester_member_id = "member-1"
            self.requester_name = "member"
            self.responder_member_id = "leader-1"
            self.responder_name = "leader"
            self.leader_session_id = leader_session_id
            self.status = status
            self.allowed_actions = ("approve", "reject")
            self.request_payload = {"permission_name": "bash"}
            self.response_payload = response_payload
            self.message_ids = ()
            self.created_at = None
            self.updated_at = None
            self.deadline_at = None
            self.terminal_at = None
            self.terminal = status != "pending"
            self.metadata = {}

    class FacetOnlyWorkflowHostFacet:
        def __init__(self) -> None:
            self.respond_calls: list[tuple[str, str, str | None, dict[str, str] | None]] = []

        async def list_workflows(
            self,
            *,
            team_id: str | None = None,
            session_id: str | None = None,
            pending_only: bool | None = True,
        ) -> tuple[FacetWorkflowRecord, ...]:
            _ = pending_only
            return (
                FacetWorkflowRecord(
                    team_id=team_id or "team-facet",
                    leader_session_id=session_id or "leader-facet",
                ),
            )

        async def respond(
            self,
            workflow_id: str,
            *,
            action: str,
            host_name: str | None = None,
            payload: dict[str, str] | None = None,
        ) -> FacetWorkflowRecord:
            self.respond_calls.append((workflow_id, action, host_name, payload))
            return FacetWorkflowRecord(
                workflow_id=workflow_id,
                status="rejected",
                response_payload={"action": action, "host": host_name or "unknown"},
            )

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
        )
    )
    facet = FacetOnlyWorkflowHostFacet()
    runtime.services.register_host_facet(
        HostFacetBinding(
            name=RuntimeHostFacetKey.TEAM_WORKFLOWS.value,
            facet=facet,
            owner=PackageOwnership(
                package_name="runtime-example",
                package_role="capability",
                surface="host_facet",
            ),
        )
    )

    async def scenario():
        async with runtime.bind_host(NullHostAdapter(name="compat")) as bound:
            listed = await bound.list_team_workflows(session_id="leader-facet", pending_only=True)
            updated = await bound.respond_team_workflow(
                "workflow-facet",
                action="reject",
                session_id="leader-facet",
            )
            return listed, updated

    listed, updated = asyncio.run(scenario())

    assert runtime.services.resolve_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value) is None
    assert listed[0]["workflow_id"] == "workflow-facet"
    assert listed[0]["leader_session_id"] == "leader-facet"
    assert updated["workflow_id"] == "workflow-facet"
    assert updated["status"] == "rejected"
    assert facet.respond_calls == [("workflow-facet", "reject", "compat", None)]


def test_non_participating_runtime_reports_host_facet_not_available(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
        )
    )

    facet = runtime.services.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)

    assert facet.available is False
    assert facet.code == "not_available"


def test_manifest_backed_core_runtime_still_boots_without_optional_packages(tmp_path: Path) -> None:
    class MinimalModelClient:
        def __init__(self) -> None:
            self.requests = []

        async def complete(self, request):  # pragma: no cover - protocol completeness
            raise NotImplementedError

        async def stream(self, request):
            self.requests.append(request)
            yield ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-core-manifest"})
            yield ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "core ok"})
            yield ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"})

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            model_client=MinimalModelClient(),
        )
    )

    produced = asyncio.run(runtime.run_prompt("hello", session_id="core-manifest"))

    assert produced[-1].text == "core ok"
    assert runtime.kernel.first_party_packages == ("runtime-core",)


def test_manifest_backed_openai_and_store_bindings_preserve_full_distribution_defaults(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
        )
    )

    assert runtime.kernel.config.default_model_route == "openai_default"
    assert "openai-prod" in runtime.kernel.config.model_providers
    assert "openai_default" in runtime.kernel.config.model_routes
    assert isinstance(runtime.services.transcript_store, FileTranscriptStore)
    assert isinstance(runtime.services.job_service.store, FileJobStore)
    assert isinstance(runtime.services.task_list_service.store, FileTaskListStore)
    assert runtime.services.metadata["package_store_bindings"] == {
        "transcript_store": "runtime-stores-file",
        "job_store": "runtime-stores-file",
        "task_list_store": "runtime-stores-file",
        "team_store": "runtime-stores-file",
        "team_message_store": "runtime-stores-file",
        "team_workflow_store": "runtime-stores-file",
        "teammate_mailbox": "runtime-stores-file",
    }


def test_builtin_replacements_preserve_manifest_owned_builtin_metadata(tmp_path: Path) -> None:
    read_replacement = replace(
        next(tool for tool in devtools_builtin_tools() if tool.name == "read"),
        description="custom read replacement",
        metadata={},
    )
    verification_replacement = AgentDefinition(
        name="verification",
        description="replacement verification agent",
        prompt="verify replacements",
        metadata={},
        origin=DefinitionOrigin(DefinitionSource.BUNDLED, path=Path("<verification>")),
    )

    kernel = build_runtime_kernel(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
            builtins=BuiltinPackConfig(
                tool_replacements={"read": read_replacement},
                agent_replacements={"verification": verification_replacement},
            ),
        )
    )

    assert kernel.tool_registry.get("read").metadata["builtin_owner"] == "runtime-devtools"
    assert kernel.tool_registry.get("read").metadata["builtin_owner_role"] == "profile_workflow"
    assert kernel.agent_registry.get("verification").metadata["builtin_owner"] == "runtime-devtools"
    assert kernel.agent_registry.get("verification").metadata["builtin_owner_role"] == "profile_workflow"


def test_package_invocation_provider_contributions_publish_pre_session_catalogs_and_metadata(
    tmp_path: Path,
) -> None:
    original = runtime_kernel_module.official_runtime_package_manifests
    observed_resources: dict[str, object] = {}
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "main.py").write_text("print('ok')\n", encoding="utf-8")

    def build_package_provider(build_context):
        observed_resources["skill_registry"] = build_context.require_resource("skill_registry")
        observed_resources["tool_registry"] = build_context.require_resource("tool_registry")
        return StaticInvocationProvider(
            "package-commands",
            (
                _invocation_definition(
                    "package-command",
                    target_name="package.command",
                    origin_path=str(tmp_path / "package-command.py"),
                ),
                _invocation_definition(
                    "package-path-review",
                    target_name="package.path_review",
                    origin_path=str(tmp_path / "package-path-review.py"),
                    paths=("src/**/*.py",),
                ),
            ),
        )

    def assemble_test_package(context):
        if context.stage != PackageAssemblyStage.SERVICES:
            return PackageContribution()
        return PackageContribution(
            invocation_providers=(
                InvocationProviderContribution(
                    name="package-commands",
                    factory=build_package_provider,
                    owner=context.ownership("invocation_provider", provider_name="package-commands"),
                    order=5,
                    metadata={"package_channel": "test"},
                ),
            )
        )

    def patched_manifests(selected_packages):
        return (
            *original(selected_packages),
            RuntimePackageManifest(
                name="runtime-test",
                role="capability",
                dependencies=("runtime-core",),
                assembly_entrypoint=assemble_test_package,
                metadata={"invocation_providers": ["package-commands"]},
            ),
        )

    runtime_kernel_module.official_runtime_package_manifests = patched_manifests
    try:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
                extra_invocation_providers=[
                    StaticInvocationProvider(
                        "config-commands",
                        (
                            _invocation_definition(
                                "config-command",
                                target_name="config.command",
                                origin_path=str(tmp_path / "config-command.py"),
                            ),
                        ),
                    )
                ],
            )
        )
    finally:
        runtime_kernel_module.official_runtime_package_manifests = original

    session = runtime.create_session(session_id="package-provider-catalog", cwd=tmp_path)
    visible = {entry.name for entry in session.visible_invocations()}
    assert visible == {"package-command", "config-command"}

    catalog = runtime.resolve_invocations(
        session_id=session.state.session_id,
        cwd=session.cwd,
        messages=(
                RuntimeMessage(
                    message_id="user-1",
                    role=MessageRole.USER,
                    content="Inspect src/app/main.py",
                ),
            ),
        )
    visible_after_path = {entry.capability.name: entry for entry in catalog.visible}
    assert set(visible_after_path) == {"package-command", "package-path-review", "config-command"}
    assert visible_after_path["package-command"].capability.metadata["provider_name"] == "package-commands"
    assert visible_after_path["package-command"].capability.metadata["provider_origin"] == "package"
    assert visible_after_path["package-command"].capability.metadata["provider_owner"]["package_name"] == "runtime-test"

    registrations = runtime.services.metadata["invocation_provider_registrations"]
    assert [(entry["provider_name"], entry["origin"]) for entry in registrations] == [
        ("skills", "builtin"),
        ("package-commands", "package"),
        ("config-commands", "config"),
    ]
    assert runtime.services.metadata["compatibility_surfaces"]["RuntimeConfig.extra_invocation_providers"] == (
        "bounded-compatibility"
    )
    assert runtime.services.metadata["invocation_provider_paths"]["package_contributions"] == (
        "canonical-package-path"
    )
    assert runtime.metadata["invocation_provider_paths"] == runtime.services.metadata["invocation_provider_paths"]
    assert runtime.services.metadata["package_lookup"]["canonical_invocation_providers"] == {
        "package_contributions": "PackageContribution.invocation_providers",
        "builtins": "builtin_skill_baseline",
    }
    assert runtime.services.metadata["package_lookup"]["compatibility_invocation_providers"] == {
        "embedder_config": "RuntimeConfig.extra_invocation_providers",
    }
    assert next(
        entry for entry in runtime.services.metadata["package_contributions"] if entry["package_name"] == "runtime-test"
    )["invocation_providers"] == ["package-commands"]
    assert observed_resources["skill_registry"] is runtime.kernel.skill_registry
    assert observed_resources["tool_registry"] is runtime.kernel.tool_registry


def test_package_and_config_invocation_providers_share_replacement_and_conflict_diagnostics(
    tmp_path: Path,
) -> None:
    original = runtime_kernel_module.official_runtime_package_manifests

    def assemble_test_package(context):
        if context.stage != PackageAssemblyStage.SERVICES:
            return PackageContribution()
        return PackageContribution(
            invocation_providers=(
                InvocationProviderContribution(
                    name="override-source",
                    provider=StaticInvocationProvider(
                        "override-source",
                        (
                            _invocation_definition(
                                "package-override",
                                target_name="package.override",
                                origin_path=str(tmp_path / "package-override.py"),
                            ),
                        ),
                    ),
                    owner=context.ownership("invocation_provider", provider_name="override-source"),
                    order=1,
                ),
                InvocationProviderContribution(
                    name="package-conflicts",
                    provider=StaticInvocationProvider(
                        "package-conflicts",
                        (
                            _invocation_definition(
                                "shared-command",
                                target_name="package.shared",
                                origin_path=str(tmp_path / "z-package-shared.py"),
                            ),
                        ),
                    ),
                    owner=context.ownership("invocation_provider", provider_name="package-conflicts"),
                    order=2,
                ),
            )
        )

    def patched_manifests(selected_packages):
        return (
            *original(selected_packages),
            RuntimePackageManifest(
                name="runtime-test",
                role="capability",
                dependencies=("runtime-core",),
                assembly_entrypoint=assemble_test_package,
                metadata={"invocation_providers": ["override-source", "package-conflicts"]},
            ),
        )

    runtime_kernel_module.official_runtime_package_manifests = patched_manifests
    try:
        kernel = build_runtime_kernel(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
                extra_invocation_providers=[
                    StaticInvocationProvider(
                        "override-source",
                        (
                            _invocation_definition(
                                "config-override",
                                target_name="config.override",
                                origin_path=str(tmp_path / "config-override.py"),
                            ),
                        ),
                    ),
                    StaticInvocationProvider(
                        "config-conflicts",
                        (
                            _invocation_definition(
                                "shared-command",
                                target_name="config.shared",
                                origin_path=str(tmp_path / "a-config-shared.py"),
                            ),
                        ),
                    ),
                ],
            )
        )
    finally:
        runtime_kernel_module.official_runtime_package_manifests = original

    registrations = kernel.invocation_registry.registrations()
    assert [(entry.name, entry.origin) for entry in registrations] == [
        ("skills", "builtin"),
        ("package-conflicts", "package"),
        ("override-source", "config"),
        ("config-conflicts", "config"),
    ]
    assert {definition.name for definition in kernel.invocation_registry.definitions()} == {
        "config-override",
        "shared-command",
    }

    replacement = next(diag for diag in kernel.diagnostics if diag.code == "invocation_provider_replaced")
    assert replacement.details["replaced_origin"] == "package"
    assert replacement.details["replacement_origin"] == "config"
    assert replacement.details["replaced_owner"]["package_name"] == "runtime-test"
    assert replacement.details["replacement_owner"] is None

    conflict = next(diag for diag in kernel.diagnostics if diag.code == "invocation_definition_conflict")
    assert conflict.location == str(tmp_path / "a-config-shared.py")
    assert conflict.details["ignored"] == str(tmp_path / "z-package-shared.py")


def test_package_invocation_provider_order_is_deterministic_across_packages(tmp_path: Path) -> None:
    original = runtime_kernel_module.official_runtime_package_manifests

    def assemble_lower_order_package(context):
        if context.stage != PackageAssemblyStage.SERVICES:
            return PackageContribution()
        return PackageContribution(
            invocation_providers=(
                InvocationProviderContribution(
                    name="shared-provider",
                    provider=StaticInvocationProvider(
                        "shared-provider",
                        (
                            _invocation_definition(
                                "lower-order-command",
                                target_name="package.lower",
                                origin_path=str(tmp_path / "lower-order.py"),
                            ),
                        ),
                    ),
                    owner=context.ownership("invocation_provider", provider_name="shared-provider"),
                    order=0,
                ),
            )
        )

    def assemble_higher_order_package(context):
        if context.stage != PackageAssemblyStage.SERVICES:
            return PackageContribution()
        return PackageContribution(
            invocation_providers=(
                InvocationProviderContribution(
                    name="shared-provider",
                    provider=StaticInvocationProvider(
                        "shared-provider",
                        (
                            _invocation_definition(
                                "higher-order-command",
                                target_name="package.higher",
                                origin_path=str(tmp_path / "higher-order.py"),
                            ),
                        ),
                    ),
                    owner=context.ownership("invocation_provider", provider_name="shared-provider"),
                    order=50,
                ),
            )
        )

    def build_kernel(package_order: tuple[str, str]):
        manifests = {
            "pkg-lower": RuntimePackageManifest(
                name="pkg-lower",
                role="capability",
                dependencies=("runtime-core",),
                assembly_entrypoint=assemble_lower_order_package,
                metadata={"invocation_providers": ["shared-provider"]},
            ),
            "pkg-higher": RuntimePackageManifest(
                name="pkg-higher",
                role="capability",
                dependencies=("runtime-core",),
                assembly_entrypoint=assemble_higher_order_package,
                metadata={"invocation_providers": ["shared-provider"]},
            ),
        }

        def patched_manifests(selected_packages):
            return (
                *original(("runtime-core",)),
                *(manifests[name] for name in package_order),
            )

        runtime_kernel_module.official_runtime_package_manifests = patched_manifests
        try:
            return build_runtime_kernel(
                RuntimeConfig(
                    working_directory=tmp_path,
                    distribution=RuntimeDistribution.CORE,
                )
            )
        finally:
            runtime_kernel_module.official_runtime_package_manifests = original

    forward = build_kernel(("pkg-lower", "pkg-higher"))
    reversed_order = build_kernel(("pkg-higher", "pkg-lower"))

    for kernel in (forward, reversed_order):
        registrations = kernel.invocation_registry.registrations()
        assert [(entry.name, entry.origin) for entry in registrations] == [
            ("skills", "builtin"),
            ("shared-provider", "package"),
        ]
        shared_provider = next(entry for entry in registrations if entry.name == "shared-provider")
        assert shared_provider.order == 50
        assert shared_provider.owner is not None
        assert shared_provider.owner.package_name == "pkg-higher"
        assert {definition.name for definition in kernel.invocation_registry.definitions()} == {
            "higher-order-command"
        }
        replacement = next(diag for diag in kernel.diagnostics if diag.code == "invocation_provider_replaced")
        assert replacement.details["replaced_owner"]["package_name"] == "pkg-lower"
        assert replacement.details["replacement_owner"]["package_name"] == "pkg-higher"


def test_session_start_waits_for_async_runtime_recovery_participants(tmp_path: Path) -> None:
    original = runtime_kernel_module.official_runtime_package_manifests
    observed: list[str] = []

    async def record_recovery(**kwargs):
        await asyncio.sleep(0)
        observed.append(kwargs["phase"].value)

    def assemble_test_package(context):
        if context.stage != PackageAssemblyStage.RUNTIME:
            return PackageContribution()
        return PackageContribution(
            lifecycle_participants=(
                PackageLifecycleParticipant(
                    phase=PackageLifecyclePhase.RUNTIME_RECOVERY,
                    name="runtime-test-observer",
                    handler=record_recovery,
                    owner=PackageOwnership(
                        package_name="runtime-test",
                        package_role="capability",
                        surface="lifecycle",
                    ),
                ),
            ),
        )

    def patched_manifests(selected_packages):
        return (
            *original(selected_packages),
            RuntimePackageManifest(
                name="runtime-test",
                role="capability",
                dependencies=("runtime-core",),
                assembly_entrypoint=assemble_test_package,
            ),
        )

    async def scenario() -> None:
        runtime_kernel_module.official_runtime_package_manifests = patched_manifests
        try:
            runtime = assemble_runtime(
                RuntimeConfig(
                    working_directory=tmp_path,
                    distribution=RuntimeDistribution.CORE,
                )
            )
            session = runtime.create_session(session_id="runtime-ready")
            await session.start()
            assert observed == [PackageLifecyclePhase.RUNTIME_RECOVERY.value]
            assert runtime.services.runtime_ready is True
            await session.close()
        finally:
            runtime_kernel_module.official_runtime_package_manifests = original

    asyncio.run(scenario())


def test_runtime_stage_package_diagnostics_extend_kernel_diagnostics(tmp_path: Path) -> None:
    original = runtime_kernel_module.official_runtime_package_manifests

    def assemble_test_package(context):
        if context.stage != PackageAssemblyStage.RUNTIME:
            return PackageContribution()
        return PackageContribution(
            diagnostics=(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    code="runtime_test_warning",
                    message="runtime-stage package warning",
                ),
            ),
        )

    def patched_manifests(selected_packages):
        return (
            *original(selected_packages),
            RuntimePackageManifest(
                name="runtime-test",
                role="capability",
                dependencies=("runtime-core",),
                assembly_entrypoint=assemble_test_package,
            ),
        )

    runtime_kernel_module.official_runtime_package_manifests = patched_manifests
    try:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
            )
        )
    finally:
        runtime_kernel_module.official_runtime_package_manifests = original

    assert any(diag.code == "runtime_test_warning" for diag in runtime.kernel.diagnostics)
