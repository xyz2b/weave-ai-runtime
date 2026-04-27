from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from .first_party_loading import load_object
from .package_profiles import FIRST_PARTY_PACKAGE_SPECS
from .runtime_package_protocols import (
    CapabilityBinding,
    ContextContributorBinding,
    ContextContributorStage,
    HostFacetBinding,
    IngressReceiptHandlerBinding,
    InvocationProviderContribution,
    ModelProviderContribution,
    ModelRouteContribution,
    PackageAssemblyStage,
    PackageContext,
    PackageContribution,
    PackageLifecycleParticipant,
    PackageLifecyclePhase,
    RuntimeCapabilityKey,
    RuntimeHostFacetKey,
    RuntimePackageManifest,
    StoreBinding,
    annotate_builtin_owner,
    order_package_manifests,
)


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
        resolved_team_id = self._resolve_team_id(team_id=team_id, session_id=session_id)
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
    ) -> Any:
        return await self.workflows.respond_host(
            workflow_id=workflow_id,
            action=action,
            host_name=host_name,
            payload=payload,
        )

    def _resolve_team_id(
        self,
        *,
        team_id: str | None,
        session_id: str | None,
    ) -> str | None:
        if team_id is not None and str(team_id).strip():
            return str(team_id).strip()
        if session_id is None or not str(session_id).strip():
            return None
        if self.control_plane is None:
            return None
        team = self.control_plane.active_team_for_leader_session(str(session_id).strip())
        return None if team is None else team.team_id


_OFFICIAL_RUNTIME_PACKAGE_MANIFESTS: dict[str, RuntimePackageManifest]


def official_runtime_package_manifest_catalog() -> dict[str, RuntimePackageManifest]:
    return dict(_OFFICIAL_RUNTIME_PACKAGE_MANIFESTS)


def official_runtime_package_manifests(
    package_names: Iterable[str] | None = None,
) -> tuple[RuntimePackageManifest, ...]:
    selected = (
        tuple(FIRST_PARTY_PACKAGE_SPECS)
        if package_names is None
        else tuple(str(name) for name in package_names)
    )
    return order_package_manifests(selected, _OFFICIAL_RUNTIME_PACKAGE_MANIFESTS)


def package_manifest(package_name: str) -> RuntimePackageManifest:
    return _OFFICIAL_RUNTIME_PACKAGE_MANIFESTS[str(package_name)]


def assemble_runtime_core_package(context: PackageContext) -> PackageContribution:
    if context.stage == PackageAssemblyStage.BUILTINS:
        builtin_tool_factory = load_object("runtime.builtins.tools:builtin_tools")
        builtin_agent_factory = load_object("runtime.builtins.agents:builtin_agents")
        return PackageContribution(
            builtin_tools=_annotated_definitions(
                builtin_tool_factory(),
                package_name=context.manifest.name,
                package_role=context.manifest.role,
            ),
            builtin_agents=_annotated_definitions(
                builtin_agent_factory(),
                package_name=context.manifest.name,
                package_role=context.manifest.role,
            ),
        )
    if context.stage != PackageAssemblyStage.RUNTIME:
        return PackageContribution()
    from .runtime_services import NoopHookService

    services = context.require_resource("runtime_services")
    contributors: list[ContextContributorBinding] = []
    if (
        getattr(services, "hooks", None) is not None
        and hasattr(services.hooks, "collect")
        and not isinstance(services.hooks, NoopHookService)
    ):
        contributors.append(
            ContextContributorBinding(
                name="runtime-core.hooks.collect",
                stage=ContextContributorStage.HOOKS,
                contributor=services.hooks,
                owner=context.ownership(
                    "context_contributor",
                    component="hooks",
                    stage=ContextContributorStage.HOOKS.value,
                ),
                metadata={
                    "adapter": "RuntimeServices.hooks.collect",
                    "compatibility_surface": "RuntimeServices.hooks.collect",
                },
            )
        )
    if (
        getattr(services, "task_discipline", None) is not None
        and hasattr(services.task_discipline, "collect")
        and not isinstance(services.task_discipline, NoopHookService)
    ):
        contributors.append(
            ContextContributorBinding(
                name="runtime-core.task_discipline.collect",
                stage=ContextContributorStage.TASK_POLICY,
                contributor=services.task_discipline,
                owner=context.ownership(
                    "context_contributor",
                    component="task_discipline",
                    stage=ContextContributorStage.TASK_POLICY.value,
                ),
                metadata={
                    "adapter": "RuntimeServices.task_discipline.collect",
                    "compatibility_surface": "RuntimeServices.task_discipline.collect",
                },
            )
        )
    return PackageContribution(context_contributors=tuple(contributors))


def assemble_runtime_memory_package(context: PackageContext) -> PackageContribution:
    if context.stage == PackageAssemblyStage.BUILTINS:
        return PackageContribution(
            builtin_skills=_load_builtin_skill_contribution(context, "runtime.memory.builtins:memory_builtin_skills")
        )
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = load_object("runtime.memory.package:assemble_memory_capability")(
        project_root=context.working_directory,
        memory_config=getattr(context.config, "memory_config", None),
    )
    return PackageContribution(
        context_contributors=(
            ContextContributorBinding(
                name="runtime-memory.collect",
                stage=ContextContributorStage.MEMORY,
                contributor=components.service,
                owner=context.ownership(
                    "context_contributor",
                    component="collect",
                    stage=ContextContributorStage.MEMORY.value,
                ),
                metadata={
                    "compatibility_surface": "RuntimeServices.memory.collect",
                },
            ),
        ),
        capabilities=(
            CapabilityBinding(
                key=RuntimeCapabilityKey.MEMORY_SERVICE.value,
                value=components.service,
                owner=context.ownership("capability", component="service"),
            ),
        )
    )


def assemble_runtime_team_package(context: PackageContext) -> PackageContribution:
    if context.stage == PackageAssemblyStage.BUILTINS:
        return PackageContribution(
            builtin_tools=_load_builtin_tool_contribution(context, "runtime.team.builtins:team_builtin_tools")
        )
    if context.stage != PackageAssemblyStage.RUNTIME:
        return PackageContribution()
    services = context.require_resource("runtime_services")
    execution_core = context.require_resource("execution_core")
    store_bindings = dict(context.resource("store_bindings", {}))
    teammate_config = _resolve_team_config(context)
    components = load_object("runtime.team.assembly:assemble_team_capability")(
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
                kind="runtime.team.delivery_ack",
                handler=acknowledge_team_delivery,
                owner=context.ownership("ingress_receipt", kind="runtime.team.delivery_ack"),
            ),
        ),
        lifecycle_participants=(
            PackageLifecycleParticipant(
                phase=PackageLifecyclePhase.RUNTIME_RECOVERY,
                name="runtime-team-recover-pending-workflows",
                handler=recover_team_workflows,
                owner=context.ownership("lifecycle", phase=PackageLifecyclePhase.RUNTIME_RECOVERY.value),
            ),
            PackageLifecycleParticipant(
                phase=PackageLifecyclePhase.SESSION_OPEN,
                name="runtime-team-replay-pending-leader-messages",
                handler=replay_pending_leader_messages,
                owner=context.ownership("lifecycle", phase=PackageLifecyclePhase.SESSION_OPEN.value),
            ),
        ),
    )


def assemble_runtime_compaction_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = load_object("runtime.compaction.package:assemble_compaction_package")()
    return PackageContribution(
        capabilities=(
            CapabilityBinding(
                key=RuntimeCapabilityKey.COMPACTION_MANAGER.value,
                value=components.manager,
                owner=context.ownership("capability", component="manager"),
            ),
        )
    )


def assemble_runtime_isolation_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = load_object("runtime.isolation_package:assemble_isolation_package")()
    return PackageContribution(
        capabilities=(
            CapabilityBinding(
                key=RuntimeCapabilityKey.ISOLATION_MANAGER.value,
                value=components.manager,
                owner=context.ownership("capability", component="manager"),
            ),
        )
    )


def assemble_runtime_openai_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = load_object("runtime.openai_package:assemble_openai_package")()
    return PackageContribution(
        model_providers=(
            ModelProviderContribution(
                name=components.provider_name,
                binding=components.provider_binding,
                owner=context.ownership("model_provider", provider_name=components.provider_name),
            ),
        ),
        model_routes=(
            ModelRouteContribution(
                name=components.route_name,
                binding=components.route_binding,
                owner=context.ownership("model_route", route_name=components.route_name),
            ),
        ),
    )


def assemble_runtime_hosts_reference_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = load_object("runtime.hosts.package:assemble_reference_host_package")()
    return PackageContribution(
        capabilities=(
            CapabilityBinding(
                key=RuntimeCapabilityKey.REFERENCE_HOST_TYPES.value,
                value=components.host_types,
                owner=context.ownership("capability", component="host_types"),
            ),
        )
    )


def assemble_runtime_stores_file_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = load_object("runtime.stores_file.package:assemble_file_store_bundle")(
        project_root=context.working_directory,
        teammate_config=getattr(context.config, "teammate_orchestration", None),
    )
    owner = context.ownership("store_binding")
    return PackageContribution(
        store_bindings=(
            StoreBinding(slot="transcript_store", store=components.transcript_store, owner=owner),
            StoreBinding(slot="job_store", store=components.job_store, owner=owner),
            StoreBinding(slot="task_list_store", store=components.task_list_store, owner=owner),
            StoreBinding(slot="team_store", store=components.team_store, owner=owner),
            StoreBinding(slot="team_message_store", store=components.team_message_store, owner=owner),
            StoreBinding(slot="team_workflow_store", store=components.team_workflow_store, owner=owner),
            StoreBinding(slot="teammate_mailbox", store=components.teammate_mailbox, owner=owner),
        )
    )


def assemble_runtime_builtin_workflows_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.BUILTINS:
        return PackageContribution()
    return PackageContribution(
        builtin_skills=_load_builtin_skill_contribution(
            context,
            "runtime.builtin_workflows.builtins:builtin_workflow_skills",
        )
    )


def assemble_runtime_planning_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.BUILTINS:
        return PackageContribution()
    return PackageContribution(
        builtin_agents=_load_builtin_agent_contribution(
            context,
            "runtime.planning.builtins:planning_builtin_agents",
        )
    )


def assemble_runtime_devtools_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.BUILTINS:
        return PackageContribution()
    return PackageContribution(
        builtin_tools=_load_builtin_tool_contribution(
            context,
            "runtime.devtools.builtins:devtools_builtin_tools",
        ),
        builtin_agents=_load_builtin_agent_contribution(
            context,
            "runtime.devtools.builtins:devtools_builtin_agents",
        ),
    )


def assembly_function_name(package_name: str) -> str:
    return {
        "runtime-core": "assemble_runtime_core_package",
        "runtime-memory": "assemble_runtime_memory_package",
        "runtime-team": "assemble_runtime_team_package",
        "runtime-compaction": "assemble_runtime_compaction_package",
        "runtime-isolation": "assemble_runtime_isolation_package",
        "runtime-openai": "assemble_runtime_openai_package",
        "runtime-hosts-reference": "assemble_runtime_hosts_reference_package",
        "runtime-stores-file": "assemble_runtime_stores_file_package",
        "runtime-builtin-workflows": "assemble_runtime_builtin_workflows_package",
        "runtime-planning": "assemble_runtime_planning_package",
        "runtime-devtools": "assemble_runtime_devtools_package",
    }[package_name]


_OFFICIAL_RUNTIME_PACKAGE_MANIFESTS = {
    package_name: RuntimePackageManifest(
        name=package_name,
        role=spec.role.value,
        description=spec.description,
        dependencies=spec.dependencies,
        assembly_entrypoint=(
            f"runtime.runtime_package_manifests:{assembly_function_name(package_name)}"
        ),
        metadata={
            "builtin_tools": list(spec.builtin_tools),
            "builtin_agents": list(spec.builtin_agents),
            "builtin_skills": list(spec.builtin_skills),
            "invocation_providers": list(spec.invocation_providers),
        },
    )
    for package_name, spec in FIRST_PARTY_PACKAGE_SPECS.items()
}


def _resolve_team_config(context: PackageContext) -> Any:
    config = getattr(context.config, "teammate_orchestration", None)
    if config is None:
        config_type = load_object("runtime.team_config:TeammateOrchestrationConfig")
        return config_type(enabled=True)
    return replace(config, enabled=True)


def _load_builtin_tool_contribution(
    context: PackageContext,
    loader_spec: str,
) -> tuple[Any, ...]:
    return _load_builtin_definitions(context, loader_spec, kind="tool")


def _load_builtin_agent_contribution(
    context: PackageContext,
    loader_spec: str,
) -> tuple[Any, ...]:
    return _load_builtin_definitions(context, loader_spec, kind="agent")


def _load_builtin_skill_contribution(
    context: PackageContext,
    loader_spec: str,
) -> tuple[Any, ...]:
    return _load_builtin_definitions(context, loader_spec, kind="skill")


def _load_invocation_provider_contribution(
    context: PackageContext,
    loader_spec: str,
) -> tuple[InvocationProviderContribution, ...]:
    factory = load_object(loader_spec)
    loaded = factory()
    if loaded is None:
        contributions: tuple[InvocationProviderContribution, ...] = ()
    else:
        raw_items = loaded if isinstance(loaded, Iterable) and not hasattr(loaded, "list_invocations") else (loaded,)
        resolved: list[InvocationProviderContribution] = []
        for item in raw_items:
            if isinstance(item, InvocationProviderContribution):
                resolved.append(item)
                continue
            provider_name = getattr(item, "name", None)
            resolved.append(
                InvocationProviderContribution(
                    name=provider_name,
                    provider=item,
                    owner=context.ownership("invocation_provider", provider_name=provider_name),
                )
            )
        contributions = tuple(resolved)
    expected_names = _expected_invocation_provider_names(context.manifest.name)
    actual_names = tuple(binding.name for binding in contributions)
    if actual_names != expected_names:
        raise ValueError(
            f"Invocation provider contributions for {context.manifest.name} do not match the "
            f"published package profile: expected {expected_names}, got {actual_names}"
        )
    return contributions


def _load_builtin_definitions(
    context: PackageContext,
    loader_spec: str,
    *,
    kind: str,
) -> tuple[Any, ...]:
    factory = load_object(loader_spec)
    definitions = tuple(factory())
    expected_names = _expected_builtin_names(context.manifest.name, kind)
    actual_names = tuple(getattr(definition, "name", None) for definition in definitions)
    if actual_names != expected_names:
        raise ValueError(
            f"Builtin {kind} definitions for {context.manifest.name} do not match the published "
            f"package profile: expected {expected_names}, got {actual_names}"
        )
    return _annotated_definitions(
        definitions,
        package_name=context.manifest.name,
        package_role=context.manifest.role,
    )


def _expected_builtin_names(package_name: str, kind: str) -> tuple[str, ...]:
    spec = FIRST_PARTY_PACKAGE_SPECS[package_name]
    if kind == "tool":
        return spec.builtin_tools
    if kind == "agent":
        return spec.builtin_agents
    if kind == "skill":
        return spec.builtin_skills
    raise ValueError(f"Unsupported builtin kind: {kind}")


def _expected_invocation_provider_names(package_name: str) -> tuple[str, ...]:
    return FIRST_PARTY_PACKAGE_SPECS[package_name].invocation_providers


def _annotated_definitions(
    definitions: Iterable[Any],
    *,
    package_name: str,
    package_role: str,
) -> tuple[Any, ...]:
    return tuple(
        annotate_builtin_owner(
            definition,
            package_name=package_name,
            package_role=package_role,
        )
        for definition in definitions
    )


__all__ = [
    "TeamWorkflowHostFacet",
    "official_runtime_package_manifest_catalog",
    "official_runtime_package_manifests",
    "package_manifest",
]
