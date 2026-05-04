from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import weavert
import weavert.runtime_kernel.kernel as runtime_kernel_module
from weavert.contracts import MessageRole, RuntimeMessage
from weavert.devtools.builtins import devtools_builtin_tools
from weavert.diagnostics import Diagnostic, DiagnosticSeverity
from weavert.definitions import (
    AgentDefinition,
    DefinitionOrigin,
    DefinitionSource,
    InvocationDefinition,
    InvocationExecutionPolicy,
    InvocationSourceKind,
    InvocationTargetKind,
    InvocationVisibilityPolicy,
)
from weavert.hosts.base import NullHostAdapter
from weavert.invocation_catalog import StaticInvocationProvider
from weavert.jobs import FileJobStore
from weavert.runtime_kernel import (
    BuiltinPackConfig,
    RuntimeConfig,
    RuntimeDistribution,
    assemble_runtime,
    build_runtime_kernel,
)
from weavert.runtime_core_protocol_catalog import CORE_PROTOCOL_CATALOG_SCHEMA_VERSION
from weavert.runtime_package_catalog import (
    official_runtime_distribution_catalog,
    official_runtime_package_catalog,
)
from weavert.runtime_package_manifests import official_runtime_package_manifests
from weavert.runtime_package_resolution import (
    PACKAGE_CANDIDATE_METADATA_KEY,
    RuntimePackageResolutionError,
)
from weavert.runtime_package_protocols import (
    CapabilityBinding,
    CapabilityPackageBindingSpec,
    ContextContributorBinding,
    ContextContributorPackageBindingSpec,
    HostFacetBinding,
    HostFacetResolution,
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
    build_capability_only_package_manifest,
    build_context_contributor_only_package_manifest,
    build_provider_only_invocation_package_manifest,
)
from weavert.runtime_services import RuntimeServices
from weavert.session_runtime import FileTranscriptStore
from weavert.stores_file import FileChildRunStore
from weavert.task_lists import FileTaskListStore
from weavert.turn_engine import ModelStreamEvent, ModelStreamEventType


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


def _package_candidate_metadata(
    *,
    candidate_id: str | None = None,
    version: str | None = None,
    dependencies: tuple[dict[str, Any], ...] = (),
    compatibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {}
    if candidate_id is not None:
        candidate["candidate_id"] = candidate_id
    if version is not None:
        candidate["version"] = version
    if dependencies:
        candidate["dependencies"] = list(dependencies)
    if compatibility:
        candidate["compatibility"] = dict(compatibility)
    return {PACKAGE_CANDIDATE_METADATA_KEY: candidate}


def _resolve_team_capability(target, key: str):
    if hasattr(target, "resolve_capability"):
        return target.resolve_capability(key)
    services = getattr(target, "services", None)
    if services is not None and hasattr(services, "resolve_capability"):
        return services.resolve_capability(key)
    return None


def _team_control_plane(target):
    return _resolve_team_capability(target, RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value)


def _team_message_bus(target):
    return _resolve_team_capability(target, RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)


def _team_workflows(target):
    return _resolve_team_capability(target, RuntimeCapabilityKey.TEAM_WORKFLOWS.value)


def _require_team_workflow_facet(target):
    resolution = target.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)
    assert resolution.available is True
    assert resolution.facet is not None
    return resolution.facet


def test_official_runtime_package_manifests_follow_dependency_order() -> None:
    manifests = official_runtime_package_manifests(("weavert-team", "weavert-core"))

    assert tuple(manifest.name for manifest in manifests) == (
        "weavert-core",
        "weavert-team",
    )


def test_external_package_registration_accepts_manifest_entrypoints_and_publishes_candidate_metadata(
    tmp_path: Path,
) -> None:
    observed_stages: list[str] = []

    def assemble_external(context):
        observed_stages.append(context.stage.value)
        return PackageContribution()

    module_name = "test_external_runtime_package_manifest_module"
    module = types.ModuleType(module_name)
    module.external_manifest = RuntimePackageManifest(
        name="runtime-external",
        role="capability",
        description="External runtime package",
        dependencies=("weavert-core",),
        assembly_entrypoint=assemble_external,
    )
    sys.modules[module_name] = module
    try:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(f"{module_name}:external_manifest",),
            )
        )
    finally:
        sys.modules.pop(module_name, None)

    accepted = runtime.services.metadata["package_registration"]["accepted"]
    resolution = runtime.services.metadata["package_resolution"]

    assert runtime.kernel.first_party_packages == ("weavert-core",)
    assert tuple(manifest.name for manifest in runtime.kernel.package_manifests) == ("weavert-core",)
    assert observed_stages == []
    assert accepted == [
        {
            "package_name": "runtime-external",
            "manifest": {
                "name": "runtime-external",
                "role": "capability",
                "description": "External runtime package",
                "dependencies": ["weavert-core"],
                "invocation_providers": [],
            },
            "provenance": {
                "origin": "external",
                "registration_path": "RuntimeConfig.extra_package_manifests",
                "registration_index": 0,
                "source_kind": "entrypoint",
                "source_ref": f"{module_name}:external_manifest",
            },
            "trust_boundary": {
                "classification": "external",
                "protocol": "RuntimePackageManifest",
                "override_mode": "not_supported",
            },
            "diagnostics": [],
        }
    ]
    assert runtime.services.metadata["package_registration"]["rejected"] == []
    assert "runtime-external" not in runtime.services.metadata["package_manifests"]
    assert runtime.services.metadata["package_service_contributions"] == ["weavert-core"]
    assert set(resolution["candidate_catalog"]) == {"weavert-core", "runtime-external"}
    assert resolution["resolved_graph"]["order"] == ["weavert-core"]
    assert set(resolution["resolved_graph"]["packages"]) == {"weavert-core"}
    assert runtime.metadata["package_registration"] == runtime.services.metadata["package_registration"]
    assert runtime.metadata["package_resolution"] == runtime.services.metadata["package_resolution"]


def test_external_package_registration_accepts_single_entrypoint_string_config_for_requested_package(
    tmp_path: Path,
) -> None:
    observed_stages: list[str] = []

    def assemble_external(context):
        observed_stages.append(context.stage.value)
        return PackageContribution()

    module_name = "test_external_runtime_package_manifest_single_string_module"
    module = types.ModuleType(module_name)
    module.external_manifest = RuntimePackageManifest(
        name="runtime-external",
        role="capability",
        dependencies=("weavert-core",),
        assembly_entrypoint=assemble_external,
    )
    sys.modules[module_name] = module
    try:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=f"{module_name}:external_manifest",
                requested_packages={"runtime-external"},
            )
        )
    finally:
        sys.modules.pop(module_name, None)

    registration = runtime.services.metadata["package_registration"]
    resolution = runtime.services.metadata["package_resolution"]

    assert [record["package_name"] for record in registration["accepted"]] == ["runtime-external"]
    assert registration["rejected"] == []
    assert tuple(manifest.name for manifest in runtime.kernel.package_manifests) == (
        "weavert-core",
        "runtime-external",
    )
    assert observed_stages == [
        PackageAssemblyStage.BUILTINS.value,
        PackageAssemblyStage.SERVICES.value,
        PackageAssemblyStage.RUNTIME.value,
    ]
    assert resolution["request"]["explicit_package_requests"] == ["runtime-external"]
    assert resolution["resolved_graph"]["order"] == ["weavert-core", "runtime-external"]
    assert resolution["resolved_graph"]["packages"]["runtime-external"]["candidate_id"] == (
        "external::runtime-external#0"
    )


def test_package_resolution_selects_one_candidate_graph_and_keeps_raw_catalog_separate(
    tmp_path: Path,
) -> None:
    observed_stages: list[str] = []

    def assemble_candidate(label: str):
        def _assemble(context):
            observed_stages.append(f"{label}:{context.stage.value}")
            return PackageContribution()

        return _assemble

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            extra_package_manifests=(
                RuntimePackageManifest(
                    name="runtime-shared",
                    role="capability",
                    dependencies=("weavert-core",),
                    assembly_entrypoint=assemble_candidate("shared-v1"),
                    metadata=_package_candidate_metadata(
                        candidate_id="runtime-shared-v1",
                        version="1.0.0",
                    ),
                ),
                RuntimePackageManifest(
                    name="runtime-shared",
                    role="capability",
                    dependencies=("weavert-core",),
                    assembly_entrypoint=assemble_candidate("shared-v2"),
                    metadata=_package_candidate_metadata(
                        candidate_id="runtime-shared-v2",
                        version="2.0.0",
                    ),
                ),
                RuntimePackageManifest(
                    name="runtime-external-app",
                    role="capability",
                    dependencies=("weavert-core",),
                    assembly_entrypoint=assemble_candidate("app"),
                    metadata=_package_candidate_metadata(
                        candidate_id="runtime-external-app",
                        dependencies=(
                            {
                                "package_name": "runtime-shared",
                                "candidate_id": "runtime-shared-v2",
                            },
                        ),
                    ),
                ),
            ),
            requested_packages={"runtime-external-app"},
        )
    )

    registration = runtime.services.metadata["package_registration"]
    resolution = runtime.services.metadata["package_resolution"]

    assert [record["package_name"] for record in registration["accepted"]] == [
        "runtime-shared",
        "runtime-shared",
        "runtime-external-app",
    ]
    assert tuple(manifest.name for manifest in runtime.kernel.package_manifests) == (
        "weavert-core",
        "runtime-shared",
        "runtime-external-app",
    )
    assert observed_stages == [
        "shared-v2:builtins",
        "app:builtins",
        "shared-v2:services",
        "app:services",
        "shared-v2:runtime",
        "app:runtime",
    ]
    assert len(resolution["candidate_catalog"]["runtime-shared"]) == 2
    assert resolution["resolved_graph"]["packages"]["runtime-shared"]["candidate_id"] == (
        "runtime-shared-v2"
    )
    assert resolution["resolved_graph"]["packages"]["runtime-external-app"]["manifest"]["dependencies"] == [
        "weavert-core",
        "runtime-shared",
    ]
    assert set(runtime.services.metadata["package_manifests"]) == {
        "weavert-core",
        "runtime-shared",
        "runtime-external-app",
    }
    assert runtime.services.metadata["package_lookup"]
    assert runtime.services.metadata["core_protocol_catalog"]
    assert runtime.services.metadata["first_party_package_catalog"]["weavert-core"]["role"] == "core"
    assert runtime.metadata["package_resolution"] == runtime.services.metadata["package_resolution"]


def test_package_resolution_backtracks_across_requested_roots_to_find_satisfiable_graph(
    tmp_path: Path,
) -> None:
    observed_stages: list[str] = []

    def assemble_candidate(label: str):
        def _assemble(context):
            observed_stages.append(f"{label}:{context.stage.value}")
            return PackageContribution()

        return _assemble

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            extra_package_manifests=(
                RuntimePackageManifest(
                    name="runtime-shared",
                    role="capability",
                    dependencies=("weavert-core",),
                    assembly_entrypoint=assemble_candidate("shared-v1"),
                    metadata=_package_candidate_metadata(
                        candidate_id="shared-v1",
                    ),
                ),
                RuntimePackageManifest(
                    name="runtime-shared",
                    role="capability",
                    dependencies=("weavert-core",),
                    assembly_entrypoint=assemble_candidate("shared-v2"),
                    metadata=_package_candidate_metadata(
                        candidate_id="shared-v2",
                    ),
                ),
                RuntimePackageManifest(
                    name="runtime-a-feature",
                    role="capability",
                    dependencies=("weavert-core",),
                    assembly_entrypoint=assemble_candidate("feature-v1"),
                    metadata=_package_candidate_metadata(
                        candidate_id="feature-v1",
                        dependencies=(
                            {
                                "package_name": "runtime-shared",
                                "candidate_id": "shared-v1",
                            },
                        ),
                    ),
                ),
                RuntimePackageManifest(
                    name="runtime-a-feature",
                    role="capability",
                    dependencies=("weavert-core",),
                    assembly_entrypoint=assemble_candidate("feature-v2"),
                    metadata=_package_candidate_metadata(
                        candidate_id="feature-v2",
                        dependencies=(
                            {
                                "package_name": "runtime-shared",
                                "candidate_id": "shared-v2",
                            },
                        ),
                    ),
                ),
                RuntimePackageManifest(
                    name="runtime-z-app",
                    role="capability",
                    dependencies=("weavert-core",),
                    assembly_entrypoint=assemble_candidate("app"),
                    metadata=_package_candidate_metadata(
                        candidate_id="app",
                        dependencies=(
                            {
                                "package_name": "runtime-shared",
                                "candidate_id": "shared-v2",
                            },
                        ),
                    ),
                ),
            ),
            requested_packages={"runtime-a-feature", "runtime-z-app"},
        )
    )

    resolution = runtime.services.metadata["package_resolution"]

    assert resolution["resolved_graph"]["packages"]["runtime-a-feature"]["candidate_id"] == "feature-v2"
    assert resolution["resolved_graph"]["packages"]["runtime-shared"]["candidate_id"] == "shared-v2"
    assert observed_stages == [
        "shared-v2:builtins",
        "feature-v2:builtins",
        "app:builtins",
        "shared-v2:services",
        "feature-v2:services",
        "app:services",
        "shared-v2:runtime",
        "feature-v2:runtime",
        "app:runtime",
    ]


def test_external_package_registration_rejects_reserved_first_party_name(tmp_path: Path) -> None:
    observed_stages: list[str] = []

    def assemble_external(context):
        observed_stages.append(context.stage.value)
        return PackageContribution()

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            extra_package_manifests=(
                RuntimePackageManifest(
                    name="weavert-core",
                    role="capability",
                    dependencies=(),
                    assembly_entrypoint=assemble_external,
                ),
            ),
        )
    )

    rejected = runtime.services.metadata["package_registration"]["rejected"]
    assert len(rejected) == 1
    assert rejected[0]["package_name"] == "weavert-core"
    assert rejected[0]["diagnostics"][0]["code"] == (
        "runtime_external_package_reserved_name_collision"
    )
    assert tuple(manifest.name for manifest in runtime.kernel.package_manifests) == ("weavert-core",)
    assert observed_stages == []


def test_package_resolution_reports_missing_package_before_assembly(tmp_path: Path) -> None:
    observed_stages: list[str] = []

    def assemble_external(context):
        observed_stages.append(context.stage.value)
        return PackageContribution()

    with pytest.raises(RuntimePackageResolutionError) as exc_info:
        assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(
                    RuntimePackageManifest(
                        name="runtime-external",
                        role="capability",
                        dependencies=("runtime-missing",),
                        assembly_entrypoint=assemble_external,
                    ),
                ),
                requested_packages={"runtime-external"},
            )
        )

    diagnostic = exc_info.value.report.diagnostics[0]
    assert diagnostic.code == "runtime_package_missing"
    assert diagnostic.package_name == "runtime-missing"
    assert observed_stages == []


def test_package_resolution_rejects_duplicate_candidate_ids_before_assembly(
    tmp_path: Path,
) -> None:
    observed_stages: list[str] = []

    def assemble_external(context):
        observed_stages.append(context.stage.value)
        return PackageContribution()

    with pytest.raises(RuntimePackageResolutionError) as exc_info:
        assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(
                    RuntimePackageManifest(
                        name="runtime-shared",
                        role="capability",
                        dependencies=("weavert-core",),
                        assembly_entrypoint=assemble_external,
                        metadata=_package_candidate_metadata(
                            candidate_id="shared-duplicate",
                            version="1.0.0",
                        ),
                    ),
                    RuntimePackageManifest(
                        name="runtime-shared",
                        role="capability",
                        dependencies=("weavert-core",),
                        assembly_entrypoint=assemble_external,
                        metadata=_package_candidate_metadata(
                            candidate_id="shared-duplicate",
                            version="2.0.0",
                        ),
                    ),
                    RuntimePackageManifest(
                        name="runtime-app",
                        role="capability",
                        dependencies=("weavert-core",),
                        assembly_entrypoint=assemble_external,
                        metadata=_package_candidate_metadata(
                            candidate_id="runtime-app",
                            dependencies=(
                                {
                                    "package_name": "runtime-shared",
                                    "candidate_id": "shared-duplicate",
                                },
                            ),
                        ),
                    ),
                ),
                requested_packages={"runtime-app"},
            )
        )

    diagnostic = exc_info.value.report.diagnostics[0]
    assert diagnostic.code == "runtime_package_duplicate_candidate_id"
    assert diagnostic.package_name == "runtime-shared"
    assert diagnostic.candidate_id == "shared-duplicate"
    assert len(diagnostic.details["duplicate_candidates"]) == 2
    assert observed_stages == []


def test_external_package_registration_reports_trust_boundary_diagnostics(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            extra_package_manifests=("weavert.devtools.builtins:devtools_builtin_tools",),
        )
    )

    rejected = runtime.services.metadata["package_registration"]["rejected"]
    assert len(rejected) == 1
    assert rejected[0]["package_name"] is None
    assert rejected[0]["diagnostics"][0]["code"] == (
        "runtime_external_package_trust_boundary_violation"
    )
    assert rejected[0]["diagnostics"][0]["provenance"]["source_kind"] == "entrypoint"


def test_external_package_registration_rejects_blank_entrypoint_with_diagnostics(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            extra_package_manifests=("   ",),
        )
    )

    rejected = runtime.services.metadata["package_registration"]["rejected"]
    assert len(rejected) == 1
    assert rejected[0]["package_name"] is None
    assert rejected[0]["provenance"]["source_ref"] == "<blank>"
    assert rejected[0]["diagnostics"][0]["code"] == (
        "runtime_external_package_manifest_load_failed"
    )
    assert rejected[0]["diagnostics"][0]["details"]["error"] == (
        "registration must be a non-empty string"
    )


def test_package_resolution_reports_conflicting_constraints_before_assembly(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimePackageResolutionError) as exc_info:
        assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(
                    RuntimePackageManifest(
                        name="runtime-shared",
                        role="capability",
                        dependencies=("weavert-core",),
                        metadata=_package_candidate_metadata(candidate_id="runtime-shared-v1"),
                    ),
                    RuntimePackageManifest(
                        name="runtime-shared",
                        role="capability",
                        dependencies=("weavert-core",),
                        metadata=_package_candidate_metadata(candidate_id="runtime-shared-v2"),
                    ),
                    RuntimePackageManifest(
                        name="runtime-uses-one",
                        role="capability",
                        dependencies=("weavert-core",),
                        metadata=_package_candidate_metadata(
                            dependencies=(
                                {
                                    "package_name": "runtime-shared",
                                    "candidate_id": "runtime-shared-v1",
                                },
                            )
                        ),
                    ),
                    RuntimePackageManifest(
                        name="runtime-uses-two",
                        role="capability",
                        dependencies=("weavert-core",),
                        metadata=_package_candidate_metadata(
                            dependencies=(
                                {
                                    "package_name": "runtime-shared",
                                    "candidate_id": "runtime-shared-v2",
                                },
                            )
                        ),
                    ),
                ),
                requested_packages={"runtime-uses-one", "runtime-uses-two"},
            )
        )

    diagnostic = exc_info.value.report.diagnostics[0]
    assert diagnostic.code == "runtime_package_conflicting_constraints"
    assert diagnostic.package_name == "runtime-shared"


def test_package_resolution_reports_incompatible_candidate_before_assembly(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimePackageResolutionError) as exc_info:
        assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(
                    RuntimePackageManifest(
                        name="runtime-external",
                        role="capability",
                        dependencies=("weavert-core",),
                        metadata=_package_candidate_metadata(
                            candidate_id="runtime-external-full-only",
                            compatibility={"distributions": ["weavert-full"]},
                        ),
                    ),
                ),
                requested_packages={"runtime-external"},
            )
        )

    diagnostic = exc_info.value.report.diagnostics[0]
    assert diagnostic.code == "runtime_package_incompatible_candidate"
    assert diagnostic.package_name == "runtime-external"
    assert diagnostic.details["distribution"] == RuntimeDistribution.CORE.value


def test_package_resolution_reports_cyclic_dependencies_before_assembly(
    tmp_path: Path,
) -> None:
    first_stages: list[str] = []
    second_stages: list[str] = []

    def assemble_first(context):
        first_stages.append(context.stage.value)
        return PackageContribution()

    def assemble_second(context):
        second_stages.append(context.stage.value)
        return PackageContribution()

    with pytest.raises(RuntimePackageResolutionError) as exc_info:
        assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
                extra_package_manifests=(
                    RuntimePackageManifest(
                        name="runtime-cycle-a",
                        role="capability",
                        dependencies=("runtime-cycle-b",),
                        assembly_entrypoint=assemble_first,
                    ),
                    RuntimePackageManifest(
                        name="runtime-cycle-b",
                        role="capability",
                        dependencies=("runtime-cycle-a",),
                        assembly_entrypoint=assemble_second,
                    ),
                ),
                requested_packages={"runtime-cycle-a"},
            )
        )

    diagnostic = exc_info.value.report.diagnostics[0]
    assert diagnostic.code == "runtime_package_cyclic_dependency"
    assert diagnostic.details["cycle_members"] == [
        "runtime-cycle-a",
        "runtime-cycle-b",
    ]
    assert diagnostic.details["cycle_path"] == [
        "runtime-cycle-a",
        "runtime-cycle-b",
        "runtime-cycle-a",
    ]
    assert first_stages == []
    assert second_stages == []


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
    owner = PackageOwnership(
        package_name="weavert-team",
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

    assert runtime.services.require_capability(RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value) is _team_control_plane(runtime)
    assert runtime.services.require_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value) is _team_workflows(runtime)
    assert runtime.services.metadata["compatibility_projections"]["teammates"] == RuntimeCapabilityKey.TEAMMATES.value
    assert "team_control_plane" not in runtime.services.metadata["compatibility_projections"]
    assert runtime.metadata["migration"] == runtime.services.metadata["migration"]
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
    assert "BoundHostRuntime.list_team_workflows" not in runtime.services.metadata["package_lookup"][
        "compatibility_wrappers"
    ]
    assert runtime.metadata["package_lookup"] == runtime.services.metadata["package_lookup"]
    assert {
        participant.name
        for participant in runtime.services.lifecycle_participants(PackageLifecyclePhase.RUNTIME_RECOVERY)
    } == {"weavert-team-recover-pending-workflows"}
    assert {
        participant.name
        for participant in runtime.services.lifecycle_participants(PackageLifecyclePhase.SESSION_OPEN)
    } == {"weavert-team-replay-pending-leader-messages"}
    assert (
        runtime.services.metadata["package_ingress_receipt_owners"]["weavert.team.delivery_ack"][
            "package_name"
        ]
        == "weavert-team"
    )
    facet = runtime.services.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)
    assert facet.available is True
    listed = asyncio.run(facet.facet.list_workflows(team_id="team-missing", session_id=None, pending_only=True))
    assert listed == ()
    assert runtime.services.metadata["migration"]["team_protocol_only"]["extension_event_contract"] == {
        "emit": "HostRuntime.emit_extension_event",
        "envelope": "weavert.hosts.HostExtensionEvent",
        "namespace": "weavert.team",
        "schema_version": "1.0",
        "unknown_namespace_behavior": "ignore_or_handle_generically",
    }


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
        "weavert.services.metadata['core_protocol_catalog']",
        "weavert.metadata['core_protocol_catalog']",
    ]
    assert catalog["adjacent_metadata"]["package_lookup"] == (
        "source of truth for package-specific canonical keys and wrapper status"
    )
    assert runtime.metadata["core_protocol_catalog"] == catalog
    assert set(protocols) == {
        "weavert.transcript.store",
        "weavert.job.service",
        "weavert.task-list.service",
        "weavert.permission.service",
        "weavert.elicitation.service",
        "weavert.context-contributors.registry",
        "weavert.invocation-provider.registry",
        "weavert.host.binding",
    }

    transcript = protocols["weavert.transcript.store"]
    assert transcript["canonical_name"] == "TranscriptStore"
    assert transcript["binding_boundary"] == "config-owned"
    assert transcript["canonical_binding_surface"] == "RuntimeConfig.transcript_store"
    assert transcript["discovery_surface"] == "RuntimeServices.transcript_store / RuntimeAssembly.transcript_store"

    context_contributors = protocols["weavert.context-contributors.registry"]
    assert context_contributors["compatibility_status"] == "stable-with-compatibility"
    assert context_contributors["retained_surfaces"] == [
        {"surface": "RuntimeServices.memory.collect", "status": "compatibility-only"},
        {"surface": "RuntimeServices.hooks.collect", "status": "compatibility-only"},
        {"surface": "RuntimeServices.task_discipline.collect", "status": "compatibility-only"},
    ]

    invocation_registry = protocols["weavert.invocation-provider.registry"]
    assert invocation_registry["canonical_binding_surface"] == "PackageContribution.invocation_providers"
    assert invocation_registry["compatibility_status"] == "stable"
    assert invocation_registry.get("retained_surfaces") is None
    assert invocation_registry["metadata"]["package_registration_order"] == [
        "builtin_skill_baseline",
        "PackageContribution.invocation_providers",
    ]
    assert invocation_registry["metadata"]["package_contribution_ordering"] == [
        "InvocationProviderContribution.order",
        "package dependency order",
        "InvocationProviderContribution.name",
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
    assert "weavert-memory.collect" in binding_names
    assert "weavert-core.task_discipline.collect" in binding_names

    lookup = runtime.services.metadata["package_lookup"]
    assert lookup["canonical_context_contributors"] == {
        "package_contributions": "PackageContribution.context_contributors",
        "registry": "RuntimeServices.context_contributor_execution_plan",
        "stage_catalog": ["memory", "hooks", "task_policy"],
    }
    assert lookup["canonical_service_family_protocols"] == {
        "memory": RuntimeCapabilityKey.MEMORY_SERVICE.value,
        "compaction": RuntimeCapabilityKey.COMPACTION_MANAGER.value,
        "isolation": RuntimeCapabilityKey.ISOLATION_MANAGER.value,
    }
    assert lookup["canonical_service_family_resolvers"] == {
        "memory": "RuntimeServices.resolve_memory_service",
        "compaction": "RuntimeServices.resolve_compaction_service",
        "isolation": "RuntimeServices.resolve_isolation_service",
    }
    assert lookup["compatibility_context_contributors"] == {
        "RuntimeServices.memory.collect": "compatibility-only",
        "RuntimeServices.hooks.collect": "compatibility-only",
        "RuntimeServices.task_discipline.collect": "compatibility-only",
    }
    assert lookup["compatibility_service_projections"] == {
        "memory": "RuntimeServices.memory",
        "compaction": "RuntimeServices.compaction",
        "isolation": "RuntimeServices.isolation",
    }
    assert "RuntimeServices.memory" in lookup["compatibility_wrappers"]
    assert "RuntimeServices.compaction" in lookup["compatibility_wrappers"]
    assert "RuntimeServices.isolation" in lookup["compatibility_wrappers"]
    assert lookup["wrapper_exit_criteria"][0] == (
        "memory, compaction, and isolation runtime-owned call sites resolve through package-service protocols only"
    )
    assert runtime.services.metadata["compatibility_surfaces"]["RuntimeServices.memory"] == "compatibility-only"
    assert runtime.services.metadata["compatibility_surfaces"]["RuntimeServices.memory.collect"] == (
        "compatibility-only"
    )
    assert runtime.services.metadata["compatibility_surfaces"]["RuntimeServices.compaction"] == (
        "compatibility-only"
    )
    assert runtime.services.metadata["compatibility_surfaces"]["RuntimeServices.isolation"] == (
        "compatibility-only"
    )
    assert runtime.services.metadata["compatibility_surfaces"]["RuntimeServices.compaction.prepare_turn"] == (
        "compatibility-only"
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
    assert "BoundHostRuntime.list_team_workflows" not in runtime.services.metadata["package_lookup"][
        "compatibility_wrappers"
    ]
    assert protocols["weavert.host.binding"]["metadata"]["extension_event_contract"] == (
        "HostRuntime.emit_extension_event"
    )


def test_runtime_core_protocol_catalog_matches_adjacent_metadata_contracts(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    catalog = runtime.services.metadata["core_protocol_catalog"]["protocols"]
    compatibility_surfaces = runtime.services.metadata["compatibility_surfaces"]
    package_lookup = runtime.services.metadata["package_lookup"]
    invocation_provider_paths = runtime.services.metadata["invocation_provider_paths"]

    for entry in catalog.values():
        for retained_surface in entry.get("retained_surfaces", []):
            surface = retained_surface["surface"]
            assert compatibility_surfaces[surface] == retained_surface["status"]

    assert catalog["weavert.job.service"]["canonical_binding_surface"] == (
        package_lookup["canonical_control_plane_services"]["job_service"]
    )
    assert catalog["weavert.task-list.service"]["canonical_binding_surface"] == (
        package_lookup["canonical_control_plane_services"]["task_list_service"]
    )
    assert catalog["weavert.context-contributors.registry"]["canonical_binding_surface"] == (
        package_lookup["canonical_context_contributors"]["package_contributions"]
    )
    assert catalog["weavert.context-contributors.registry"]["metadata"]["stage_catalog"] == (
        package_lookup["canonical_context_contributors"]["stage_catalog"]
    )
    assert catalog["weavert.invocation-provider.registry"]["canonical_binding_surface"] == (
        package_lookup["canonical_invocation_providers"]["package_contributions"]
    )
    assert catalog["weavert.invocation-provider.registry"]["metadata"]["builtin_baseline"] == (
        package_lookup["canonical_invocation_providers"]["builtins"]
    )
    assert catalog["weavert.invocation-provider.registry"]["metadata"]["builtin_baseline_status"] == (
        invocation_provider_paths["builtin_skill_baseline"]
    )


def test_runtime_publishes_compatibility_whitelists_and_protocol_only_findings(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    compatibility_boundaries = runtime.services.metadata["compatibility_boundaries"]
    assert runtime.metadata["compatibility_boundaries"] == compatibility_boundaries
    assert compatibility_boundaries["runtime_context"]["status"] == "compatibility-only"
    assert compatibility_boundaries["runtime_context"]["canonical_carriers"] == {
        "prompt_context": "PromptContextEnvelope",
        "private_context": "RuntimePrivateContext",
    }
    assert [
        entry["surface"]
        for entry in compatibility_boundaries["runtime_context"]["entry_points"]
    ] == list(runtime_kernel_module._runtime_context_compatibility_surfaces())
    assert compatibility_boundaries["runtime_context"]["unclassified_surfaces"] == []
    assert compatibility_boundaries["TaskManager"]["status"] == "compatibility-only"
    assert compatibility_boundaries["TaskManager"]["canonical_services"] == {
        "job_service": "RuntimeServices.job_service",
        "task_list_service": "RuntimeServices.task_list_service",
    }
    assert [
        entry["surface"]
        for entry in compatibility_boundaries["TaskManager"]["materialization_adapters"]
    ] == [
        "RuntimeServices.task_manager",
        "RuntimeAssembly.task_manager",
        "RuntimeServices.bind_task_manager",
        "TurnEngine.__init__(task_manager=...)",
        "AgentRuntime.__init__(task_manager=...)",
    ]
    assert compatibility_boundaries["TaskManager"]["unclassified_surfaces"] == []

    closure_report = runtime.services.metadata["closure_report"]
    assert runtime.metadata["closure_report"] == closure_report
    assert closure_report["status"] == "closure-green"
    retirement = closure_report["compatibility_retirement"]
    assert retirement["inventory_complete"] is True
    assert retirement["active_families"] == []
    assert {
        entry["family"] for entry in retirement["families"]
    } == {
        "task_manager",
        "runtime_context_authority",
        "context_contributor_adapters",
        "memory_projection",
        "compaction_projection",
        "isolation_projection",
        "teammates_projection",
        "agent_owned_hooks",
    }
    assert closure_report["persistence_profile"]["profile_name"] == RuntimeDistribution.DEFAULT.value
    assert closure_report["persistence_profile"]["surfaces"]["transcript"]["durability"] == "non_durable"
    assert closure_report["isolation_readiness"]["modes"]["worktree"]["status"] == "not_available"

    conformance = runtime.services.metadata["protocol_only_conformance"]
    assert runtime.metadata["protocol_only_conformance"] == conformance
    assert conformance["schema_version"] == "1.0"
    findings = {entry["rule_id"]: entry for entry in conformance["findings"]}
    assert findings["runtime_context_authority"] == {
        "rule_id": "runtime_context_authority",
        "family": "context-authority",
        "status": "pass",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "PromptContextEnvelope / RuntimePrivateContext",
        "compat_surface": "runtime_context",
        "evidence": list(runtime_kernel_module._runtime_context_compatibility_surfaces()),
    }
    assert findings["task_manager_authority"] == {
        "rule_id": "task_manager_authority",
        "family": "task-authority",
        "status": "pass",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "RuntimeServices.job_service / RuntimeServices.task_list_service",
        "compat_surface": "TaskManager",
        "evidence": [
            "RuntimeServices.task_manager",
            "RuntimeAssembly.task_manager",
            "RuntimeServices.bind_task_manager",
            "TurnEngine.__init__(task_manager=...)",
            "AgentRuntime.__init__(task_manager=...)",
        ],
    }
    assert findings["invocation_provider_provenance"] == {
        "rule_id": "invocation_provider_provenance",
        "family": "provider-provenance",
        "status": "pass",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "builtin_skill_baseline / PackageContribution.invocation_providers",
        "replacement_path": "PackageContribution.invocation_providers",
        "evidence": [
            "skills@builtin_skill_baseline",
        ],
        "baseline_tier": [
            {
                "provider_name": "skills",
                "origin": "builtin",
                "registration_path": "builtin_skill_baseline",
                "provider_tier": "builtin-baseline",
            }
        ],
        "package_tiers": [],
    }
    assert findings["team_runtime_projection_authority"] == {
        "rule_id": "team_runtime_projection_authority",
        "family": "team-bridge",
        "status": "pass",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": (
            "RuntimeServices.resolve_team_* / "
            "RuntimeAssembly.resolve_capability(RuntimeCapabilityKey.TEAM_*.value)"
        ),
        "replacement_path": (
            "RuntimeCapabilityKey.TEAM_CONTROL_PLANE / "
            "RuntimeCapabilityKey.TEAM_MESSAGE_BUS / "
            "RuntimeCapabilityKey.TEAM_WORKFLOWS"
        ),
        "availability": "team-present",
        "evidence": [
            "RuntimeServices.team_control_plane",
            "RuntimeServices.team_message_bus",
            "RuntimeServices.team_workflows",
            "RuntimeAssembly.team_control_plane",
            "RuntimeAssembly.team_message_bus",
            "RuntimeAssembly.team_workflows",
        ],
    }
    assert findings["team_workflow_wrapper_authority"] == {
        "rule_id": "team_workflow_wrapper_authority",
        "family": "team-bridge",
        "status": "pass",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "RuntimeAssembly.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)",
        "compat_surface": "BoundHostRuntime.list_team_workflows",
        "replacement_path": "RuntimeHostFacetKey.TEAM_WORKFLOWS.value",
        "availability": "team-present",
        "evidence": [
            "BoundHostRuntime.list_team_workflows",
            "BoundHostRuntime.respond_team_workflow",
            RuntimeHostFacetKey.TEAM_WORKFLOWS.value,
        ],
    }
    assert findings["team_host_event_bridge_authority"] == {
        "rule_id": "team_host_event_bridge_authority",
        "family": "team-bridge",
        "status": "pass",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "HostRuntime.emit_extension_event",
        "compat_surface": "HostRuntime.emit_team_event",
        "replacement_path": "HostRuntime.emit_extension_event(HostExtensionEvent(namespace='weavert.team', ...))",
        "availability": "team-present",
        "evidence": [
            "HostRuntime.emit_extension_event",
            "weavert.team",
        ],
    }
    assert findings["compatibility_retirement_state"]["status"] == "pass"
    assert findings["persistence_profile_state"]["status"] == "pass"
    assert findings["isolation_readiness_state"]["status"] == "pass"


def test_runtime_publishes_official_catalog_and_resolved_graph_provenance(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
        )
    )

    catalog_provenance = runtime.services.metadata["official_package_catalog_provenance"]
    assert runtime.metadata["official_package_catalog_provenance"] == catalog_provenance
    assert catalog_provenance["schema_version"] == "1.0"
    assert catalog_provenance["provider_kind"] == "manifest-backed"
    assert catalog_provenance["provider_path"] == (
        "weavert.runtime_package_catalog:official_runtime_package_catalog"
    )
    assert "weavert.runtime_package_manifests.assembly_function_name" in (
        catalog_provenance["retired_kernel_helpers"]
    )
    assert catalog_provenance["entries"]["weavert-core"]["assembly_entrypoint"] == (
        "weavert.runtime_package_manifests:assemble_runtime_core_package"
    )
    assert catalog_provenance["distributions"]["weavert-full"]["packages"] == list(
        runtime.kernel.first_party_packages
    )

    resolved_graph_provenance = runtime.services.metadata["resolved_active_package_graph_provenance"]
    assert runtime.metadata["resolved_active_package_graph_provenance"] == resolved_graph_provenance
    assert resolved_graph_provenance["distribution"] == RuntimeDistribution.FULL.value
    assert resolved_graph_provenance["selected_first_party_packages"] == list(
        runtime.kernel.first_party_packages
    )
    assert resolved_graph_provenance["resolved_order"] == list(runtime.kernel.first_party_packages)
    assert all(
        entry["origin"] == "first_party"
        for entry in resolved_graph_provenance["resolved_packages"]
    )
    assert resolved_graph_provenance["resolved_packages"][0]["assembly_entrypoint"] == (
        "weavert.runtime_package_manifests:assemble_runtime_core_package"
    )

    assembly_view = runtime.query_assembly_view()
    assert assembly_view["official_package_catalog_provenance"] == catalog_provenance
    assert assembly_view["resolved_active_package_graph_provenance"] == resolved_graph_provenance
    assert assembly_view["closure_report"] == runtime.metadata["closure_report"]
    assert assembly_view["protocol_only_conformance"] == runtime.metadata["protocol_only_conformance"]


def test_official_distribution_catalog_derives_packages_from_catalog_defaults() -> None:
    package_catalog = official_runtime_package_catalog()
    distribution_catalog = official_runtime_distribution_catalog()

    for distribution_name, distribution_entry in distribution_catalog.items():
        expected_packages = tuple(
            package_name
            for package_name, package_entry in package_catalog.items()
            if distribution_name in package_entry.distribution_defaults
        )
        assert distribution_entry.packages == expected_packages


def test_protocol_only_conformance_publishes_kernel_assembly_sources_and_gate(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    conformance = runtime.metadata["protocol_only_conformance"]
    assert conformance["finding_schema"] == {
        "required_fields": [
            "rule_id",
            "family",
            "status",
            "distribution",
            "evidence",
            "canonical_path",
        ],
        "optional_fields": [
            "compat_surface",
            "replacement_path",
        ],
    }
    assert conformance["rule_sources"]["official_package_catalog_authority"] == {
        "family": "kernel-assembly",
        "source_path": (
            "weavert.services.metadata['official_package_catalog_provenance'] / "
            "weavert.services.metadata['resolved_active_package_graph_provenance']"
        ),
    }

    findings = {entry["rule_id"]: entry for entry in conformance["findings"]}
    assert findings["official_package_catalog_authority"] == {
        "rule_id": "official_package_catalog_authority",
        "family": "kernel-assembly",
        "status": "pass",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "weavert.runtime_package_catalog:official_runtime_package_catalog",
        "replacement_path": "RuntimePackageManifest.assembly_entrypoint",
        "evidence": [
            "weavert-core@weavert.runtime_package_manifests:assemble_runtime_core_package",
            "weavert-memory@weavert.runtime_package_manifests:assemble_runtime_memory_package",
            "weavert-team@weavert.runtime_package_manifests:assemble_runtime_team_package",
        ],
    }

    gate = conformance["gate"]
    assert gate["mode"] == "enforced"
    assert gate["scope"] == "distribution-matrix"
    assert gate["status"] == "pass"
    assert gate["required_families"] == [
        "privileged-service-slot",
        "context-authority",
        "task-authority",
        "team-bridge",
        "provider-provenance",
        "kernel-assembly",
        "compatibility-retirement",
        "persistence-profile",
        "isolation-readiness",
    ]
    assert gate["green_criteria"] == {
        "required_distributions": [
            "weavert-core",
            "weavert-default",
            "weavert-full",
        ],
        "required_optional_package_cases": [
            "team-present",
            "team-absent",
            "explicit-package-enabled",
            "explicit-package-disabled",
        ],
    }
    assert gate["current_assembly"]["distribution"] == RuntimeDistribution.DEFAULT.value
    assert gate["current_assembly"]["selected_packages"] == [
        "weavert-core",
        "weavert-memory",
        "weavert-team",
    ]
    assert gate["current_assembly"]["status"] == "pass"
    assert gate["current_assembly"]["family_status"]["compatibility-retirement"] == {
        "status": "pass",
        "rule_ids": ["compatibility_retirement_state"],
    }
    assert gate["current_assembly"]["family_status"]["persistence-profile"] == {
        "status": "pass",
        "rule_ids": ["persistence_profile_state"],
    }
    assert gate["current_assembly"]["family_status"]["isolation-readiness"] == {
        "status": "pass",
        "rule_ids": ["isolation_readiness_state"],
    }
    assert gate["matrix_cases"] == [
        {
            "case_id": "weavert-core",
            "distribution": "weavert-core",
            "availability": ["team-absent"],
            "selected_packages": ["weavert-core"],
            "status": "pass",
        },
        {
            "case_id": "weavert-default",
            "distribution": "weavert-default",
            "availability": ["team-present"],
            "selected_packages": ["weavert-core", "weavert-memory", "weavert-team"],
            "status": "pass",
        },
        {
            "case_id": "weavert-full",
            "distribution": "weavert-full",
            "availability": ["team-present"],
            "selected_packages": [
                "weavert-core",
                "weavert-memory",
                "weavert-team",
                "weavert-compaction",
                "weavert-isolation",
                "weavert-openai",
                "weavert-hosts-reference",
                "weavert-stores-file",
                "weavert-builtin-workflows",
                "weavert-planning",
                "weavert-devtools",
            ],
            "status": "pass",
        },
        {
            "case_id": "weavert-core+weavert-planning",
            "distribution": "weavert-core",
            "availability": ["explicit-package-enabled"],
            "selected_packages": ["weavert-core", "weavert-planning"],
            "status": "pass",
        },
        {
            "case_id": "weavert-full-weavert-planning",
            "distribution": "weavert-full",
            "availability": ["explicit-package-disabled"],
            "selected_packages": [
                "weavert-core",
                "weavert-memory",
                "weavert-team",
                "weavert-compaction",
                "weavert-isolation",
                "weavert-openai",
                "weavert-hosts-reference",
                "weavert-stores-file",
                "weavert-builtin-workflows",
                "weavert-devtools",
            ],
            "status": "pass",
        },
    ]
    assert gate["family_status"]["task-authority"] == {
        "status": "pass",
        "rule_ids": ["task_manager_authority"],
        "cases": [
            {
                "case_id": "weavert-core",
                "distribution": "weavert-core",
                "availability": ["team-absent"],
                "status": "pass",
            },
            {
                "case_id": "weavert-default",
                "distribution": "weavert-default",
                "availability": ["team-present"],
                "status": "pass",
            },
            {
                "case_id": "weavert-full",
                "distribution": "weavert-full",
                "availability": ["team-present"],
                "status": "pass",
            },
            {
                "case_id": "weavert-core+weavert-planning",
                "distribution": "weavert-core",
                "availability": ["explicit-package-enabled"],
                "status": "pass",
            },
            {
                "case_id": "weavert-full-weavert-planning",
                "distribution": "weavert-full",
                "availability": ["explicit-package-disabled"],
                "status": "pass",
            },
            {
                "case_id": "current-assembly",
                "distribution": RuntimeDistribution.DEFAULT.value,
                "availability": ["current-assembly"],
                "status": "pass",
            },
        ],
    }


def test_runtime_publishes_privileged_service_protocol_metadata_and_findings(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
        )
    )

    protocols = runtime.services.metadata["package_service_protocols"]
    assert runtime.metadata["package_service_protocols"] == protocols
    assert runtime.services.metadata["compatibility_projections"]["memory"] == RuntimeCapabilityKey.MEMORY_SERVICE.value
    assert runtime.services.metadata["compatibility_projections"]["compaction"] == (
        RuntimeCapabilityKey.COMPACTION_MANAGER.value
    )
    assert runtime.services.metadata["compatibility_projections"]["isolation"] == (
        RuntimeCapabilityKey.ISOLATION_MANAGER.value
    )

    assert protocols["memory"]["canonical_key"] == RuntimeCapabilityKey.MEMORY_SERVICE.value
    assert protocols["memory"]["resolver"] == "RuntimeServices.resolve_memory_service"
    assert protocols["memory"]["owner"]["package_name"] == "weavert-memory"
    assert protocols["memory"]["compatibility_projection"] == {
        "surface": "RuntimeServices.memory",
        "status": "compatibility-only",
    }
    assert protocols["memory"]["retained_surfaces"] == [
        {"surface": "RuntimeServices.memory", "status": "compatibility-only"},
        {"surface": "RuntimeServices.memory.collect", "status": "compatibility-only"},
    ]

    assert protocols["compaction"]["canonical_key"] == RuntimeCapabilityKey.COMPACTION_MANAGER.value
    assert protocols["compaction"]["resolver"] == "RuntimeServices.resolve_compaction_service"
    assert protocols["compaction"]["owner"]["package_name"] == "weavert-compaction"
    assert protocols["compaction"]["compatibility_projection"] == {
        "surface": "RuntimeServices.compaction",
        "status": "compatibility-only",
    }
    assert protocols["compaction"]["retained_surfaces"] == [
        {"surface": "RuntimeServices.compaction", "status": "compatibility-only"},
        {"surface": "RuntimeServices.compaction.prepare_turn", "status": "compatibility-only"},
        {"surface": "RuntimeServices.compaction.collect", "status": "compatibility-only"},
    ]

    assert protocols["isolation"]["canonical_key"] == RuntimeCapabilityKey.ISOLATION_MANAGER.value
    assert protocols["isolation"]["resolver"] == "RuntimeServices.resolve_isolation_service"
    assert protocols["isolation"]["owner"]["package_name"] == "weavert-isolation"
    assert protocols["isolation"]["compatibility_projection"] == {
        "surface": "RuntimeServices.isolation",
        "status": "compatibility-only",
    }
    assert protocols["isolation"]["retained_surfaces"] == [
        {"surface": "RuntimeServices.isolation", "status": "compatibility-only"},
    ]

    findings = {
        entry["rule_id"]: entry
        for entry in runtime.services.metadata["protocol_only_conformance"]["findings"]
    }
    assert findings["memory_service_slot_authority"] == {
        "rule_id": "memory_service_slot_authority",
        "family": "privileged-service-slot",
        "status": "pass",
        "distribution": RuntimeDistribution.FULL.value,
        "canonical_path": RuntimeCapabilityKey.MEMORY_SERVICE.value,
        "compat_surface": "RuntimeServices.memory",
        "evidence": [
            "RuntimeServices.memory",
            "RuntimeServices.memory.collect",
        ],
    }
    assert findings["compaction_service_slot_authority"] == {
        "rule_id": "compaction_service_slot_authority",
        "family": "privileged-service-slot",
        "status": "pass",
        "distribution": RuntimeDistribution.FULL.value,
        "canonical_path": RuntimeCapabilityKey.COMPACTION_MANAGER.value,
        "compat_surface": "RuntimeServices.compaction",
        "evidence": [
            "RuntimeServices.compaction",
            "RuntimeServices.compaction.prepare_turn",
            "RuntimeServices.compaction.collect",
        ],
    }
    assert findings["isolation_service_slot_authority"] == {
        "rule_id": "isolation_service_slot_authority",
        "family": "privileged-service-slot",
        "status": "pass",
        "distribution": RuntimeDistribution.FULL.value,
        "canonical_path": RuntimeCapabilityKey.ISOLATION_MANAGER.value,
        "compat_surface": "RuntimeServices.isolation",
        "evidence": [
            "RuntimeServices.isolation",
        ],
    }


def test_runtime_publishes_team_bridge_findings_for_team_absent_distributions(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
        )
    )

    findings = {
        entry["rule_id"]: entry
        for entry in runtime.services.metadata["protocol_only_conformance"]["findings"]
        if entry["family"] == "team-bridge"
    }

    assert findings["team_runtime_projection_authority"]["availability"] == "team-absent"
    assert findings["team_runtime_projection_authority"]["status"] == "pass"
    assert findings["team_workflow_wrapper_authority"]["availability"] == "team-absent"
    assert findings["team_workflow_wrapper_authority"]["status"] == "pass"
    assert findings["team_host_event_bridge_authority"] == {
        "rule_id": "team_host_event_bridge_authority",
        "family": "team-bridge",
        "status": "pass",
        "distribution": RuntimeDistribution.CORE.value,
        "canonical_path": "HostRuntime.emit_extension_event",
        "compat_surface": "HostRuntime.emit_team_event",
        "replacement_path": "HostRuntime.emit_extension_event(HostExtensionEvent(namespace='weavert.team', ...))",
        "availability": "team-absent",
        "evidence": [
            "HostRuntime.emit_extension_event",
            "weavert.team",
        ],
    }


def test_protocol_only_conformance_fails_without_published_service_family_metadata() -> None:
    conformance = runtime_kernel_module._protocol_only_conformance_metadata(
        distribution=RuntimeDistribution.DEFAULT.value,
        compatibility_boundaries={},
        package_service_protocols={},
        closure_report={},
    )

    findings = {
        entry["rule_id"]: entry
        for entry in conformance["findings"]
        if entry["family"] == "privileged-service-slot"
    }

    assert findings["memory_service_slot_authority"] == {
        "rule_id": "memory_service_slot_authority",
        "family": "privileged-service-slot",
        "status": "fail",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "",
        "compat_surface": "RuntimeServices.memory",
        "evidence": [],
    }
    assert findings["compaction_service_slot_authority"] == {
        "rule_id": "compaction_service_slot_authority",
        "family": "privileged-service-slot",
        "status": "fail",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "",
        "compat_surface": "RuntimeServices.compaction",
        "evidence": [],
    }
    assert findings["isolation_service_slot_authority"] == {
        "rule_id": "isolation_service_slot_authority",
        "family": "privileged-service-slot",
        "status": "fail",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "",
        "compat_surface": "RuntimeServices.isolation",
        "evidence": [],
    }
    provider_finding = next(
        entry for entry in conformance["findings"] if entry["rule_id"] == "invocation_provider_provenance"
    )
    assert provider_finding == {
        "rule_id": "invocation_provider_provenance",
        "family": "provider-provenance",
        "status": "fail",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "builtin_skill_baseline / PackageContribution.invocation_providers",
        "replacement_path": "PackageContribution.invocation_providers",
        "evidence": [],
        "baseline_tier": [],
        "package_tiers": [],
    }
    task_authority_finding = next(
        entry for entry in conformance["findings"] if entry["rule_id"] == "task_manager_authority"
    )
    assert task_authority_finding == {
        "rule_id": "task_manager_authority",
        "family": "task-authority",
        "status": "pass",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "RuntimeServices.job_service / RuntimeServices.task_list_service",
        "compat_surface": "TaskManager",
        "evidence": [],
    }
    kernel_assembly_finding = next(
        entry for entry in conformance["findings"] if entry["rule_id"] == "official_package_catalog_authority"
    )
    assert kernel_assembly_finding == {
        "rule_id": "official_package_catalog_authority",
        "family": "kernel-assembly",
        "status": "fail",
        "distribution": RuntimeDistribution.DEFAULT.value,
        "canonical_path": "weavert.runtime_package_catalog:official_runtime_package_catalog",
        "replacement_path": "RuntimePackageManifest.assembly_entrypoint",
        "evidence": [],
    }
    assert next(
        entry for entry in conformance["findings"] if entry["rule_id"] == "compatibility_retirement_state"
    )["status"] == "fail"
    assert next(
        entry for entry in conformance["findings"] if entry["rule_id"] == "persistence_profile_state"
    )["status"] == "fail"
    assert next(
        entry for entry in conformance["findings"] if entry["rule_id"] == "isolation_readiness_state"
    )["status"] == "fail"
    assert conformance["gate"]["scope"] == "current-assembly"
    assert conformance["gate"]["status"] == "fail"
    assert conformance["gate"]["required_families"] == [
        "privileged-service-slot",
        "context-authority",
        "task-authority",
        "team-bridge",
        "provider-provenance",
        "kernel-assembly",
        "compatibility-retirement",
        "persistence-profile",
        "isolation-readiness",
    ]


def test_protocol_only_gate_fails_when_task_manager_surfaces_escape_authority(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    compatibility_boundaries = dict(runtime.services.metadata["compatibility_boundaries"])
    task_manager_boundaries = dict(compatibility_boundaries["TaskManager"])
    task_manager_boundaries["unclassified_surfaces"] = [
        "RuntimeAssembly.legacy_task_manager_bridge"
    ]
    compatibility_boundaries["TaskManager"] = task_manager_boundaries

    conformance = runtime_kernel_module._protocol_only_conformance_metadata(
        distribution=RuntimeDistribution.DEFAULT.value,
        compatibility_boundaries=compatibility_boundaries,
        package_service_protocols=runtime.services.metadata["package_service_protocols"],
        closure_report=runtime.services.metadata["closure_report"],
        invocation_provider_registrations=runtime.services.metadata["invocation_provider_registrations"],
        team_protocol_only=runtime.services.metadata["migration"]["team_protocol_only"],
        official_package_catalog_provenance=runtime.services.metadata[
            "official_package_catalog_provenance"
        ],
        resolved_active_package_graph_provenance=runtime.services.metadata[
            "resolved_active_package_graph_provenance"
        ],
        services=runtime.services,
        runtime=runtime,
    )

    findings = {entry["rule_id"]: entry for entry in conformance["findings"]}
    assert findings["task_manager_authority"]["status"] == "fail"
    assert findings["task_manager_authority"]["unknown_surfaces"] == [
        "RuntimeAssembly.legacy_task_manager_bridge"
    ]
    assert conformance["gate"]["status"] == "fail"
    assert conformance["gate"]["scope"] == "distribution-matrix"
    assert conformance["gate"]["current_assembly"]["family_status"]["task-authority"]["status"] == (
        "fail"
    )
    assert conformance["gate"]["family_status"]["task-authority"]["status"] == "fail"


@pytest.mark.parametrize(
    ("distribution", "enabled_packages", "disabled_packages", "expected_packages"),
    (
        (RuntimeDistribution.CORE, set(), set(), ("weavert-core",)),
        (
            RuntimeDistribution.DEFAULT,
            set(),
            set(),
            ("weavert-core", "weavert-memory", "weavert-team"),
        ),
        (
            RuntimeDistribution.FULL,
            set(),
            set(),
            (
                "weavert-core",
                "weavert-memory",
                "weavert-team",
                "weavert-compaction",
                "weavert-isolation",
                "weavert-openai",
                "weavert-hosts-reference",
                "weavert-stores-file",
                "weavert-builtin-workflows",
                "weavert-planning",
                "weavert-devtools",
            ),
        ),
        (
            RuntimeDistribution.CORE,
            {"weavert-planning"},
            set(),
            ("weavert-core", "weavert-planning"),
        ),
        (
            RuntimeDistribution.FULL,
            set(),
            {"weavert-planning"},
            (
                "weavert-core",
                "weavert-memory",
                "weavert-team",
                "weavert-compaction",
                "weavert-isolation",
                "weavert-openai",
                "weavert-hosts-reference",
                "weavert-stores-file",
                "weavert-builtin-workflows",
                "weavert-devtools",
            ),
        ),
    ),
)
def test_protocol_only_gate_is_green_across_distribution_and_optional_package_matrix(
    tmp_path: Path,
    distribution: RuntimeDistribution,
    enabled_packages: set[str],
    disabled_packages: set[str],
    expected_packages: tuple[str, ...],
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=distribution,
            enabled_packages=enabled_packages,
            disabled_packages=disabled_packages,
        )
    )

    assert runtime.kernel.first_party_packages == expected_packages

    assembly_view = runtime.query_assembly_view()
    assert assembly_view["resolved_active_package_graph_provenance"]["resolved_order"] == list(
        expected_packages
    )
    assert assembly_view["protocol_only_conformance"]["gate"]["scope"] == "distribution-matrix"
    assert assembly_view["protocol_only_conformance"]["gate"]["status"] == "pass"
    assert assembly_view["protocol_only_conformance"]["gate"]["current_assembly"]["status"] == "pass"
    assert len(assembly_view["protocol_only_conformance"]["gate"]["matrix_cases"]) == 5
    assert all(
        entry["status"] == "pass"
        for entry in assembly_view["protocol_only_conformance"]["gate"]["family_status"].values()
    )


def test_team_bridge_findings_fail_when_live_runtime_state_is_missing() -> None:
    class StubServices:
        def __init__(self) -> None:
            self.host = object()

        def resolve_capability(self, key: str, default=None):
            _ = key, default
            return None

        def resolve_team_workflow_host_facet(self):
            return HostFacetResolution(
                name=RuntimeHostFacetKey.TEAM_WORKFLOWS.value,
                available=False,
                code="not_available",
            )

    class StubRuntime:
        pass

    findings = {
        entry["rule_id"]: entry
        for entry in runtime_kernel_module._protocol_only_conformance_metadata(
            distribution=RuntimeDistribution.DEFAULT.value,
            compatibility_boundaries={},
            package_service_protocols={},
            closure_report={},
            team_protocol_only=runtime_kernel_module._team_protocol_only_migration_metadata(
                selected_packages=("weavert-core", "weavert-memory", "weavert-team"),
            ),
            services=StubServices(),
            runtime=StubRuntime(),
        )["findings"]
        if entry["family"] == "team-bridge"
    }

    assert findings["team_runtime_projection_authority"]["status"] == "fail"
    assert findings["team_workflow_wrapper_authority"]["status"] == "fail"
    assert findings["team_host_event_bridge_authority"]["status"] == "fail"


def test_protocol_only_conformance_flags_unclassified_runtime_context_surfaces(
    tmp_path: Path,
) -> None:
    def temporary_runtime_context_bridge(
        self,
        *,
        runtime_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return dict(runtime_context or {})

    runtime_kernel_module.RuntimeAssembly.temporary_runtime_context_bridge = (
        temporary_runtime_context_bridge
    )
    try:
        runtime = assemble_runtime(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.DEFAULT,
            )
        )
    finally:
        delattr(runtime_kernel_module.RuntimeAssembly, "temporary_runtime_context_bridge")

    compatibility_boundaries = runtime.services.metadata["compatibility_boundaries"]
    assert compatibility_boundaries["runtime_context"]["unclassified_surfaces"] == [
        "RuntimeAssembly.temporary_runtime_context_bridge"
    ]
    findings = {
        entry["rule_id"]: entry
        for entry in runtime.services.metadata["protocol_only_conformance"]["findings"]
    }
    assert findings["runtime_context_authority"]["status"] == "fail"
    assert findings["runtime_context_authority"]["unknown_surfaces"] == [
        "RuntimeAssembly.temporary_runtime_context_bridge"
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
            dependencies=("weavert-core",),
            assembly_entrypoint=assemble_package("zzz.context"),
        ),
        "pkg-beta": RuntimePackageManifest(
            name="pkg-beta",
            role="capability",
            dependencies=("weavert-core",),
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


def test_runtime_team_compatibility_projections_are_removed_in_favor_of_canonical_lookups(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )

    canonical_plane = runtime.services.require_capability(RuntimeCapabilityKey.TEAM_CONTROL_PLANE.value)
    canonical_bus = runtime.services.require_capability(RuntimeCapabilityKey.TEAM_MESSAGE_BUS.value)
    canonical_workflows = runtime.services.require_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value)
    assert runtime.services.resolve_team_control_plane() is canonical_plane
    assert runtime.services.resolve_team_message_bus() is canonical_bus
    assert runtime.services.resolve_team_workflows() is canonical_workflows
    assert _team_control_plane(runtime) is canonical_plane
    assert _team_message_bus(runtime) is canonical_bus
    assert _team_workflows(runtime) is canonical_workflows
    assert not hasattr(runtime.services, "team_control_plane")
    assert not hasattr(runtime.services, "team_message_bus")
    assert not hasattr(runtime.services, "team_workflows")
    assert not hasattr(runtime, "team_control_plane")
    assert not hasattr(runtime, "team_message_bus")
    assert not hasattr(runtime, "team_workflows")


def test_privileged_service_compatibility_slot_writes_rebind_canonical_capabilities(
    tmp_path: Path,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
        )
    )

    replacement_memory = object()
    replacement_compaction = object()
    replacement_isolation = object()
    runtime.services.memory = replacement_memory
    runtime.services.compaction = replacement_compaction
    runtime.services.isolation = replacement_isolation

    assert runtime.services.memory is replacement_memory
    assert runtime.services.compaction is replacement_compaction
    assert runtime.services.isolation is replacement_isolation
    assert runtime.services.require_capability(RuntimeCapabilityKey.MEMORY_SERVICE.value) is replacement_memory
    assert runtime.services.require_capability(RuntimeCapabilityKey.COMPACTION_MANAGER.value) is replacement_compaction
    assert runtime.services.require_capability(RuntimeCapabilityKey.ISOLATION_MANAGER.value) is replacement_isolation
    assert runtime.services.metadata["package_service_protocols"]["memory"]["owner"] == {
        "package_name": "weavert-core",
        "package_role": "compatibility",
        "surface": "compatibility_projection",
        "metadata": {"compatibility_surface": "RuntimeServices.memory"},
    }
    assert runtime.services.metadata["package_service_protocols"]["compaction"]["owner"] == {
        "package_name": "weavert-core",
        "package_role": "compatibility",
        "surface": "compatibility_projection",
        "metadata": {"compatibility_surface": "RuntimeServices.compaction"},
    }
    assert runtime.services.metadata["package_service_protocols"]["isolation"]["owner"] == {
        "package_name": "weavert-core",
        "package_role": "compatibility",
        "surface": "compatibility_projection",
        "metadata": {"compatibility_surface": "RuntimeServices.isolation"},
    }
    assert runtime.metadata["package_service_protocols"] == runtime.services.metadata["package_service_protocols"]
    assert runtime.metadata["protocol_only_conformance"] == runtime.services.metadata["protocol_only_conformance"]


def test_late_memory_capability_rebind_refreshes_published_protocol_metadata(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.FULL,
        )
    )

    replacement = object()
    runtime.services.bind_capability(
        CapabilityBinding(
            key=RuntimeCapabilityKey.MEMORY_SERVICE.value,
            value=replacement,
            owner=PackageOwnership(
                package_name="weavert-memory-override",
                package_role="capability",
                surface="capability",
            ),
        )
    )

    assert runtime.services.memory is replacement
    assert runtime.services.metadata["package_service_protocols"]["memory"]["owner"] == {
        "package_name": "weavert-memory-override",
        "package_role": "capability",
        "surface": "capability",
        "metadata": {},
    }
    findings = {
        entry["rule_id"]: entry
        for entry in runtime.services.metadata["protocol_only_conformance"]["findings"]
    }
    assert findings["memory_service_slot_authority"]["status"] == "pass"
    assert findings["memory_service_slot_authority"]["canonical_path"] == (
        RuntimeCapabilityKey.MEMORY_SERVICE.value
    )
    assert runtime.metadata["package_service_protocols"] == runtime.services.metadata["package_service_protocols"]
    assert runtime.metadata["protocol_only_conformance"] == runtime.services.metadata["protocol_only_conformance"]


def test_runtime_workflow_helpers_prefer_canonical_lookup_over_compatibility_slots(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.DEFAULT,
        )
    )
    plane = _team_control_plane(runtime)
    workflows = _team_workflows(runtime)
    assert plane is not None
    assert workflows is not None

    async def scenario():
        async with runtime.bind_host(NullHostAdapter(name="compat")) as bound:
            facet = _require_team_workflow_facet(bound)
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
            pending = await runtime.list_team_workflows(session_id="leader-session", pending_only=True)
            updated = await facet.respond(
                workflow.workflow_id,
                action="reject",
                host_name=bound.host.name,
                session_id="leader-session",
            )
            return pending, updated

    pending, updated = asyncio.run(scenario())

    assert pending
    assert pending[0]["workflow_kind"] == "permission"
    assert updated.workflow_id == pending[0]["workflow_id"]
    assert updated.status.value == "rejected"


def test_bound_host_workflow_facet_reports_absent_package_behavior(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
        )
    )

    async def scenario():
        async with runtime.bind_host(NullHostAdapter(name="compat")) as bound:
            resolution = bound.resolve_host_facet(RuntimeHostFacetKey.TEAM_WORKFLOWS.value)
            return resolution

    resolution = asyncio.run(scenario())

    assert resolution.available is False
    assert resolution.code == "not_available"
    assert resolution.facet is None


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
            self.respond_calls: list[
                tuple[str, str, str | None, dict[str, str] | None, str | None, str | None]
            ] = []

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
            team_id: str | None = None,
            session_id: str | None = None,
        ) -> FacetWorkflowRecord:
            self.respond_calls.append((workflow_id, action, host_name, payload, team_id, session_id))
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
            resolved = _require_team_workflow_facet(bound)
            listed = await resolved.list_workflows(session_id="leader-facet", pending_only=True)
            updated = await resolved.respond(
                "workflow-facet",
                action="reject",
                host_name=bound.host.name,
                session_id="leader-facet",
            )
            return listed, updated

    listed, updated = asyncio.run(scenario())

    assert runtime.services.resolve_capability(RuntimeCapabilityKey.TEAM_WORKFLOWS.value) is None
    assert listed[0].workflow_id == "workflow-facet"
    assert listed[0].leader_session_id == "leader-facet"
    assert updated.workflow_id == "workflow-facet"
    assert updated.status == "rejected"
    assert facet.respond_calls == [("workflow-facet", "reject", "compat", None, None, "leader-facet")]


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
    assert runtime.kernel.first_party_packages == ("weavert-core",)


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
    assert isinstance(runtime.agent_runtime.run_store, FileChildRunStore)
    assert isinstance(runtime.services.job_service.store, FileJobStore)
    assert isinstance(runtime.services.task_list_service.store, FileTaskListStore)
    assert runtime.services.metadata["package_store_bindings"] == {
        "transcript_store": "weavert-stores-file",
        "child_run_store": "weavert-stores-file",
        "job_store": "weavert-stores-file",
        "task_list_store": "weavert-stores-file",
        "team_store": "weavert-stores-file",
        "team_message_store": "weavert-stores-file",
        "team_workflow_store": "weavert-stores-file",
        "teammate_mailbox": "weavert-stores-file",
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

    assert kernel.tool_registry.get("read").metadata["builtin_owner"] == "weavert-devtools"
    assert kernel.tool_registry.get("read").metadata["builtin_owner_role"] == "profile_workflow"
    assert kernel.agent_registry.get("verification").metadata["builtin_owner"] == "weavert-devtools"
    assert kernel.agent_registry.get("verification").metadata["builtin_owner_role"] == "profile_workflow"


def test_package_builder_family_preserves_manifest_backed_registration_and_metadata(
    tmp_path: Path,
) -> None:
    class ReleaseFreezeContributor:
        async def collect(self, **_kwargs):
            return ("package context: release-freeze is active",)

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            extra_package_manifests=(
                build_capability_only_package_manifest(
                    name="weavert-capability-only",
                    capabilities=(
                        CapabilityPackageBindingSpec(
                            key="demo.release.freeze",
                            value={"active": True, "owner": "weavert-capability-only"},
                        ),
                    ),
                ),
                build_context_contributor_only_package_manifest(
                    name="weavert-context-only",
                    dependencies=("weavert-core", "weavert-capability-only"),
                    context_contributors=(
                        ContextContributorPackageBindingSpec(
                            name="demo.release.freeze.notice",
                            stage=ContextContributorStage.HOOKS,
                            contributor=ReleaseFreezeContributor(),
                            order=5,
                        ),
                    ),
                ),
                build_provider_only_invocation_package_manifest(
                    name="weavert-provider-only",
                    dependencies=("weavert-core", "weavert-context-only"),
                    provider_name="package-commands",
                    provider=StaticInvocationProvider(
                        "package-commands",
                        (
                            _invocation_definition(
                                "package-release-check",
                                target_name="package.release_check",
                                origin_path=str(tmp_path / "package-release-check.py"),
                            ),
                        ),
                    ),
                ),
            ),
            requested_packages={
                "weavert-capability-only",
                "weavert-context-only",
                "weavert-provider-only",
            },
        )
    )

    assert tuple(manifest.name for manifest in runtime.kernel.package_manifests) == (
        "weavert-core",
        "weavert-capability-only",
        "weavert-context-only",
        "weavert-provider-only",
    )
    assert runtime.services.metadata["resolved_active_package_graph_provenance"]["resolved_order"] == [
        "weavert-core",
        "weavert-capability-only",
        "weavert-context-only",
        "weavert-provider-only",
    ]
    assert runtime.services.require_capability("demo.release.freeze") == {
        "active": True,
        "owner": "weavert-capability-only",
    }
    capability_owner = runtime.services.capability_registry.owner("demo.release.freeze")
    assert capability_owner is not None
    assert capability_owner.package_name == "weavert-capability-only"
    assert capability_owner.metadata["capability_key"] == "demo.release.freeze"
    assert capability_owner.metadata["package_pattern"] == "capability-only"

    hook_plan = runtime.services.context_contributor_execution_plan()
    release_notice = next(
        entry.binding
        for entry in hook_plan
        if entry.binding.name == "demo.release.freeze.notice"
        and entry.stage.name == ContextContributorStage.HOOKS
    )
    assert release_notice.owner.package_name == "weavert-context-only"
    assert release_notice.owner.metadata["contributor_name"] == "demo.release.freeze.notice"
    assert release_notice.owner.metadata["contributor_stage"] == ContextContributorStage.HOOKS.value
    assert release_notice.owner.metadata["package_pattern"] == "context-contributor-only"

    session = runtime.create_session(session_id="builder-family", cwd=tmp_path)
    assert {entry.name for entry in session.visible_invocations()} == {"package-release-check"}

    accepted = {
        entry["package_name"]: entry["manifest"]
        for entry in runtime.services.metadata["package_registration"]["accepted"]
    }
    assert accepted["weavert-capability-only"] == {
        "name": "weavert-capability-only",
        "role": "capability",
        "description": "Capability-only runtime package.",
        "dependencies": ["weavert-core"],
        "invocation_providers": [],
        "package_pattern": "capability-only",
        "baseline_dependencies": ["weavert-core"],
        "capabilities": ["demo.release.freeze"],
        "capability_registration_path": "PackageContribution.capabilities",
    }
    assert accepted["weavert-context-only"] == {
        "name": "weavert-context-only",
        "role": "capability",
        "description": "Context-contributor-only runtime package.",
        "dependencies": ["weavert-core", "weavert-capability-only"],
        "invocation_providers": [],
        "package_pattern": "context-contributor-only",
        "baseline_dependencies": ["weavert-core", "weavert-capability-only"],
        "context_contributors": ["demo.release.freeze.notice"],
        "context_contributor_registration_path": "PackageContribution.context_contributors",
        "context_contributor_stages": [
            {
                "name": "demo.release.freeze.notice",
                "stage": ContextContributorStage.HOOKS.value,
                "order": 5,
            }
        ],
    }
    assert accepted["weavert-provider-only"] == {
        "name": "weavert-provider-only",
        "role": "provider",
        "description": "Provider-only runtime package.",
        "dependencies": ["weavert-core", "weavert-context-only"],
        "invocation_providers": ["package-commands"],
        "package_pattern": "provider-only",
        "baseline_dependencies": ["weavert-core", "weavert-context-only"],
        "provider_registration_path": "PackageContribution.invocation_providers",
        "provider_registration_order": [
            "builtin_skill_baseline",
            "PackageContribution.invocation_providers",
        ],
        "provider_package_ordering": [
            "InvocationProviderContribution.order",
            "package dependency order",
            "InvocationProviderContribution.name",
        ],
    }

    manifests = runtime.services.metadata["package_manifests"]
    assert manifests["weavert-capability-only"] == {
        "role": "capability",
        "description": "Capability-only runtime package.",
        "dependencies": ["weavert-core"],
        "invocation_providers": [],
        "package_pattern": "capability-only",
        "baseline_dependencies": ["weavert-core"],
        "capabilities": ["demo.release.freeze"],
        "capability_registration_path": "PackageContribution.capabilities",
    }
    assert manifests["weavert-context-only"] == {
        "role": "capability",
        "description": "Context-contributor-only runtime package.",
        "dependencies": ["weavert-core", "weavert-capability-only"],
        "invocation_providers": [],
        "package_pattern": "context-contributor-only",
        "baseline_dependencies": ["weavert-core", "weavert-capability-only"],
        "context_contributors": ["demo.release.freeze.notice"],
        "context_contributor_registration_path": "PackageContribution.context_contributors",
        "context_contributor_stages": [
            {
                "name": "demo.release.freeze.notice",
                "stage": ContextContributorStage.HOOKS.value,
                "order": 5,
            }
        ],
    }
    assert manifests["weavert-provider-only"] == {
        "role": "provider",
        "description": "Provider-only runtime package.",
        "dependencies": ["weavert-core", "weavert-context-only"],
        "invocation_providers": ["package-commands"],
        "package_pattern": "provider-only",
        "baseline_dependencies": ["weavert-core", "weavert-context-only"],
        "provider_registration_path": "PackageContribution.invocation_providers",
        "provider_registration_order": [
            "builtin_skill_baseline",
            "PackageContribution.invocation_providers",
        ],
        "provider_package_ordering": [
            "InvocationProviderContribution.order",
            "package dependency order",
            "InvocationProviderContribution.name",
        ],
    }

    contributions = {
        entry["package_name"]: entry
        for entry in runtime.services.metadata["package_contributions"]
        if entry["package_name"]
        in {
            "weavert-capability-only",
            "weavert-context-only",
            "weavert-provider-only",
        }
        and entry["stage"] == PackageAssemblyStage.SERVICES.value
    }
    assert contributions["weavert-capability-only"]["capabilities"] == ["demo.release.freeze"]
    assert contributions["weavert-capability-only"]["metadata"] == {
        "package_pattern": "capability-only",
        "registration_path": "PackageContribution.capabilities",
    }
    assert contributions["weavert-context-only"]["context_contributors"] == [
        "demo.release.freeze.notice"
    ]
    assert contributions["weavert-context-only"]["metadata"] == {
        "package_pattern": "context-contributor-only",
        "registration_path": "PackageContribution.context_contributors",
    }
    assert contributions["weavert-provider-only"]["invocation_providers"] == ["package-commands"]
    assert contributions["weavert-provider-only"]["metadata"] == {
        "package_pattern": "provider-only",
        "registration_path": "PackageContribution.invocation_providers",
    }


def test_package_builder_family_preserves_explicit_empty_dependencies() -> None:
    capability_manifest = build_capability_only_package_manifest(
        name="weavert-capability-only",
        dependencies=(),
        capabilities=(CapabilityPackageBindingSpec(key="demo.release.freeze", value=True),),
    )
    assert capability_manifest.dependencies == ()
    assert capability_manifest.metadata["baseline_dependencies"] == []

    context_manifest = build_context_contributor_only_package_manifest(
        name="weavert-context-only",
        dependencies=(),
        context_contributors=(
            ContextContributorPackageBindingSpec(
                name="demo.release.freeze.notice",
                stage=ContextContributorStage.HOOKS,
                contributor=object(),
            ),
        ),
    )
    assert context_manifest.dependencies == ()
    assert context_manifest.metadata["baseline_dependencies"] == []

    provider_manifest = build_provider_only_invocation_package_manifest(
        name="weavert-provider-only",
        dependencies=(),
        provider_name="package-commands",
        provider=StaticInvocationProvider(
            "package-commands",
            (
                _invocation_definition(
                    "package-release-check",
                    target_name="package.release_check",
                    origin_path="package-release-check.py",
                ),
            ),
        ),
    )
    assert provider_manifest.dependencies == ()
    assert provider_manifest.metadata["baseline_dependencies"] == []


def test_package_builder_family_rejects_conflicting_builder_owned_manifest_metadata() -> None:
    with pytest.raises(ValueError, match="baseline_dependencies, package_pattern"):
        build_capability_only_package_manifest(
            name="weavert-capability-only",
            capabilities=(CapabilityPackageBindingSpec(key="demo.release.freeze", value=True),),
            manifest_metadata={
                "baseline_dependencies": ["custom"],
                "package_pattern": "custom",
            },
        )

    with pytest.raises(ValueError, match="context_contributor_registration_path, package_pattern"):
        build_context_contributor_only_package_manifest(
            name="weavert-context-only",
            context_contributors=(
                ContextContributorPackageBindingSpec(
                    name="demo.release.freeze.notice",
                    stage=ContextContributorStage.HOOKS,
                    contributor=object(),
                ),
            ),
            manifest_metadata={
                "package_pattern": "custom",
                "context_contributor_registration_path": "custom.path",
            },
        )

    with pytest.raises(ValueError, match="package_pattern, provider_registration_path"):
        build_provider_only_invocation_package_manifest(
            name="weavert-provider-only",
            provider_name="package-commands",
            provider=StaticInvocationProvider(
                "package-commands",
                (
                    _invocation_definition(
                        "package-release-check",
                        target_name="package.release_check",
                        origin_path="package-release-check.py",
                    ),
                ),
            ),
            manifest_metadata={
                "package_pattern": "custom",
                "provider_registration_path": "custom.path",
            },
        )


def test_package_builder_family_allows_matching_builder_owned_manifest_metadata() -> None:
    manifest = build_capability_only_package_manifest(
        name="weavert-capability-only",
        dependencies=(),
        capabilities=(CapabilityPackageBindingSpec(key="demo.release.freeze", value=True),),
        manifest_metadata={
            "baseline_dependencies": [],
            "package_pattern": "capability-only",
            "custom_metadata": "kept",
        },
    )

    assert manifest.metadata["baseline_dependencies"] == []
    assert manifest.metadata["package_pattern"] == "capability-only"
    assert manifest.metadata["custom_metadata"] == "kept"


def test_package_builder_family_is_exported_on_root_public_api() -> None:
    assert weavert.CapabilityPackageBindingSpec is CapabilityPackageBindingSpec
    assert weavert.ContextContributorPackageBindingSpec is ContextContributorPackageBindingSpec
    assert weavert.build_capability_only_package_manifest is build_capability_only_package_manifest
    assert (
        weavert.build_context_contributor_only_package_manifest
        is build_context_contributor_only_package_manifest
    )
    assert (
        weavert.build_provider_only_invocation_package_manifest
        is build_provider_only_invocation_package_manifest
    )


def test_provider_only_runtime_packages_publish_pre_session_catalogs_and_metadata(
    tmp_path: Path,
) -> None:
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

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=RuntimeDistribution.CORE,
            extra_package_manifests=(
                build_provider_only_invocation_package_manifest(
                    name="weavert-provider-only",
                    provider_name="package-commands",
                    factory=build_package_provider,
                    order=5,
                    contribution_metadata={"package_channel": "test"},
                ),
            ),
            requested_packages={"weavert-provider-only"},
        )
    )

    session = runtime.create_session(session_id="package-provider-catalog", cwd=tmp_path)
    visible = {entry.name for entry in session.visible_invocations()}
    assert visible == {"package-command"}

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
    assert set(visible_after_path) == {"package-command", "package-path-review"}
    assert visible_after_path["package-command"].capability.metadata["provider_name"] == "package-commands"
    assert visible_after_path["package-command"].capability.metadata["provider_origin"] == "package"
    assert visible_after_path["package-command"].capability.metadata["provider_tier"] == "package-contribution"
    assert visible_after_path["package-command"].capability.metadata["provider_registration_path"] == (
        "PackageContribution.invocation_providers"
    )
    assert visible_after_path["package-command"].capability.metadata["provider_owner"]["package_name"] == (
        "weavert-provider-only"
    )

    accepted = runtime.services.metadata["package_registration"]["accepted"]
    assert accepted == [
        {
            "package_name": "weavert-provider-only",
            "manifest": {
                "name": "weavert-provider-only",
                "role": "provider",
                "description": "Provider-only runtime package.",
                "dependencies": ["weavert-core"],
                "package_pattern": "provider-only",
                "baseline_dependencies": ["weavert-core"],
                "invocation_providers": ["package-commands"],
                "provider_registration_path": "PackageContribution.invocation_providers",
                "provider_registration_order": [
                    "builtin_skill_baseline",
                    "PackageContribution.invocation_providers",
                ],
                "provider_package_ordering": [
                    "InvocationProviderContribution.order",
                    "package dependency order",
                    "InvocationProviderContribution.name",
                ],
            },
            "provenance": {
                "origin": "external",
                "registration_path": "RuntimeConfig.extra_package_manifests",
                "registration_index": 0,
                "source_kind": "manifest",
                "source_ref": "manifest:weavert-provider-only",
            },
            "trust_boundary": {
                "classification": "external",
                "protocol": "RuntimePackageManifest",
                "override_mode": "not_supported",
            },
            "diagnostics": [],
        }
    ]

    registrations = runtime.services.metadata["invocation_provider_registrations"]
    assert [(entry["provider_name"], entry["origin"], entry["registration_path"]) for entry in registrations] == [
        ("skills", "builtin", "builtin_skill_baseline"),
        ("package-commands", "package", "PackageContribution.invocation_providers"),
    ]
    assert [entry["provider_tier"] for entry in registrations] == [
        "builtin-baseline",
        "package-contribution",
    ]
    assert "RuntimeConfig.extra_invocation_providers" not in runtime.services.metadata["compatibility_surfaces"]
    assert runtime.services.metadata["invocation_provider_paths"] == {
        "builtin_skill_baseline": "baseline",
        "package_contributions": "canonical-package-path",
        "canonical_package_surface": "PackageContribution.invocation_providers",
        "registration_order": [
            "builtin_skill_baseline",
            "PackageContribution.invocation_providers",
        ],
        "package_ordering": [
            "InvocationProviderContribution.order",
            "package dependency order",
            "InvocationProviderContribution.name",
        ],
    }
    assert runtime.metadata["invocation_provider_paths"] == runtime.services.metadata["invocation_provider_paths"]
    assert runtime.services.metadata["package_lookup"]["canonical_invocation_providers"] == {
        "package_contributions": "PackageContribution.invocation_providers",
        "builtins": "builtin_skill_baseline",
    }
    assert "compatibility_invocation_providers" not in runtime.services.metadata["package_lookup"]
    assert next(
        entry
        for entry in runtime.services.metadata["package_contributions"]
        if entry["package_name"] == "weavert-provider-only"
    )["invocation_providers"] == ["package-commands"]
    findings = {
        entry["rule_id"]: entry
        for entry in runtime.services.metadata["protocol_only_conformance"]["findings"]
    }
    assert findings["invocation_provider_provenance"] == {
        "rule_id": "invocation_provider_provenance",
        "family": "provider-provenance",
        "status": "pass",
        "distribution": RuntimeDistribution.CORE.value,
        "canonical_path": "builtin_skill_baseline / PackageContribution.invocation_providers",
        "replacement_path": "PackageContribution.invocation_providers",
        "evidence": [
            "skills@builtin_skill_baseline",
            "package-commands@PackageContribution.invocation_providers",
        ],
        "baseline_tier": [
            {
                "provider_name": "skills",
                "origin": "builtin",
                "registration_path": "builtin_skill_baseline",
                "provider_tier": "builtin-baseline",
            }
        ],
        "package_tiers": [
            {
                "provider_name": "package-commands",
                "origin": "package",
                "registration_path": "PackageContribution.invocation_providers",
                "provider_tier": "package-contribution",
                "package_name": "weavert-provider-only",
            }
        ],
    }
    assert observed_resources["skill_registry"] is runtime.kernel.skill_registry
    assert observed_resources["tool_registry"] is runtime.kernel.tool_registry


@pytest.mark.parametrize(
    "distribution",
    (
        RuntimeDistribution.CORE,
        RuntimeDistribution.DEFAULT,
        RuntimeDistribution.FULL,
    ),
)
def test_provider_only_runtime_packages_assemble_consistently_across_distributions(
    tmp_path: Path,
    distribution: RuntimeDistribution,
) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            distribution=distribution,
            extra_package_manifests=(
                build_provider_only_invocation_package_manifest(
                    name="weavert-provider-only",
                    provider_name="distribution-provider",
                    provider=StaticInvocationProvider(
                        "distribution-provider",
                        (
                            _invocation_definition(
                                "distribution-command",
                                target_name="distribution.command",
                                origin_path=str(tmp_path / f"{distribution.value}-provider.py"),
                            ),
                        ),
                    ),
                ),
            ),
            requested_packages={"weavert-provider-only"},
        )
    )

    registrations = runtime.services.metadata["invocation_provider_registrations"]
    assert [(entry["provider_name"], entry["registration_path"], entry["provider_tier"]) for entry in registrations] == [
        ("skills", "builtin_skill_baseline", "builtin-baseline"),
        (
            "distribution-provider",
            "PackageContribution.invocation_providers",
            "package-contribution",
        ),
    ]
    assert runtime.services.metadata["package_manifests"]["weavert-provider-only"] == {
        "role": "provider",
        "description": "Provider-only runtime package.",
        "dependencies": ["weavert-core"],
        "package_pattern": "provider-only",
        "baseline_dependencies": ["weavert-core"],
        "invocation_providers": ["distribution-provider"],
        "provider_registration_path": "PackageContribution.invocation_providers",
        "provider_registration_order": [
            "builtin_skill_baseline",
            "PackageContribution.invocation_providers",
        ],
        "provider_package_ordering": [
            "InvocationProviderContribution.order",
            "package dependency order",
            "InvocationProviderContribution.name",
        ],
    }
    session = runtime.create_session(session_id=f"provider-only-{distribution.value}", cwd=tmp_path)
    assert "distribution-command" in {entry.name for entry in session.visible_invocations()}


def test_package_invocation_providers_share_replacement_and_conflict_diagnostics(
    tmp_path: Path,
) -> None:
    original = runtime_kernel_module.official_runtime_package_manifests

    def assemble_base_package(context):
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
                                "package-base-override",
                                target_name="package.base_override",
                                origin_path=str(tmp_path / "package-base-override.py"),
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

    def assemble_override_package(context):
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
                    name="override-conflicts",
                    provider=StaticInvocationProvider(
                        "override-conflicts",
                        (
                            _invocation_definition(
                                "shared-command",
                                target_name="package.override_conflict",
                                origin_path=str(tmp_path / "a-package-shared.py"),
                            ),
                        ),
                    ),
                    owner=context.ownership("invocation_provider", provider_name="override-conflicts"),
                    order=3,
                ),
            )
        )

    def patched_manifests(selected_packages):
        return (
            *original(selected_packages),
            RuntimePackageManifest(
                name="runtime-provider-base",
                role="provider",
                dependencies=("weavert-core",),
                assembly_entrypoint=assemble_base_package,
                metadata={"invocation_providers": ["override-source", "package-conflicts"]},
            ),
            RuntimePackageManifest(
                name="runtime-provider-override",
                role="provider",
                dependencies=("weavert-core", "runtime-provider-base"),
                assembly_entrypoint=assemble_override_package,
                metadata={"invocation_providers": ["override-source", "override-conflicts"]},
            ),
        )

    runtime_kernel_module.official_runtime_package_manifests = patched_manifests
    try:
        kernel = build_runtime_kernel(
            RuntimeConfig(
                working_directory=tmp_path,
                distribution=RuntimeDistribution.CORE,
            )
        )
    finally:
        runtime_kernel_module.official_runtime_package_manifests = original

    registrations = kernel.invocation_registry.registrations()
    assert [(entry.name, entry.origin) for entry in registrations] == [
        ("skills", "builtin"),
        ("override-source", "package"),
        ("package-conflicts", "package"),
        ("override-conflicts", "package"),
    ]
    assert {definition.name for definition in kernel.invocation_registry.definitions()} == {
        "package-override",
        "shared-command",
    }

    replacement = next(diag for diag in kernel.diagnostics if diag.code == "invocation_provider_replaced")
    assert replacement.details["replaced_origin"] == "package"
    assert replacement.details["replacement_origin"] == "package"
    assert replacement.details["replaced_owner"]["package_name"] == "runtime-provider-base"
    assert replacement.details["replacement_owner"]["package_name"] == "runtime-provider-override"
    assert replacement.details["replaced_registration_path"] == "PackageContribution.invocation_providers"
    assert replacement.details["replacement_registration_path"] == "PackageContribution.invocation_providers"
    assert replacement.details["replaced_provider_tier"] == "package-contribution"
    assert replacement.details["replacement_provider_tier"] == "package-contribution"

    conflict = next(diag for diag in kernel.diagnostics if diag.code == "invocation_definition_conflict")
    assert conflict.location == str(tmp_path / "a-package-shared.py")
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
                dependencies=("weavert-core",),
                assembly_entrypoint=assemble_lower_order_package,
                metadata={"invocation_providers": ["shared-provider"]},
            ),
            "pkg-higher": RuntimePackageManifest(
                name="pkg-higher",
                role="capability",
                dependencies=("weavert-core",),
                assembly_entrypoint=assemble_higher_order_package,
                metadata={"invocation_providers": ["shared-provider"]},
            ),
        }

        def patched_manifests(selected_packages):
            return (
                *original(("weavert-core",)),
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
                dependencies=("weavert-core",),
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
                dependencies=("weavert-core",),
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
