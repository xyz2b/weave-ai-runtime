from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import runtime.runtime_kernel.kernel as runtime_kernel_module
from runtime.devtools.builtins import devtools_builtin_tools
from runtime.diagnostics import Diagnostic, DiagnosticSeverity
from runtime.definitions import AgentDefinition, DefinitionOrigin, DefinitionSource
from runtime.hosts.base import NullHostAdapter
from runtime.jobs import FileJobStore
from runtime.runtime_kernel import (
    BuiltinPackConfig,
    RuntimeConfig,
    RuntimeDistribution,
    assemble_runtime,
    build_runtime_kernel,
)
from runtime.runtime_package_manifests import official_runtime_package_manifests
from runtime.runtime_package_protocols import (
    CapabilityBinding,
    HostFacetBinding,
    IngressReceiptHandlerBinding,
    PackageAssemblyStage,
    PackageContribution,
    PackageLifecycleParticipant,
    PackageLifecyclePhase,
    PackageOwnership,
    RuntimeCapabilityKey,
    RuntimeHostFacetKey,
    RuntimePackageManifest,
)
from runtime.runtime_services import RuntimeServices
from runtime.session_runtime import FileTranscriptStore
from runtime.task_lists import FileTaskListStore
from runtime.turn_engine import ModelStreamEvent, ModelStreamEventType


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
    assert services.lifecycle_participants(PackageLifecyclePhase.SESSION_CLOSE) == (participant,)
    facet = services.resolve_host_facet("runtime.example.facet")
    assert facet.available is True
    assert facet.facet == {"facet": "example"}
    assert services.metadata["package_capability_owners"]["runtime.example.service"]["package_name"] == "runtime-example"
    assert services.metadata["package_ingress_receipt_owners"]["runtime.example.receipt"]["package_name"] == "runtime-example"
    assert services.metadata["package_contributions"][0]["package_name"] == "runtime-example"
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
    assert runtime.services.metadata["compatibility_projections"]["team_control_plane"] == RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value
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
