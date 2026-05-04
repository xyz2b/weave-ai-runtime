from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .definitions import AgentDefinition, InvocationProvider, SkillDefinition, ToolDefinition
from .diagnostics import Diagnostic
from .first_party_loading import load_object
from .jobs import JobExecutorBinding
from .public_contract import (
    canonical_distribution_name,
    canonical_first_party_name,
    canonical_public_namespace,
)


class PackageAssemblyStage(StrEnum):
    BUILTINS = "builtins"
    SERVICES = "services"
    RUNTIME = "runtime"


class PackageLifecyclePhase(StrEnum):
    RUNTIME_START = "runtime_start"
    RUNTIME_RECOVERY = "runtime_recovery"
    SESSION_OPEN = "session_open"
    SESSION_CLOSE = "session_close"


class ContextContributorStage(StrEnum):
    MEMORY = "memory"
    HOOKS = "hooks"
    TASK_POLICY = "task_policy"


class ContextContributorPromptChannel(StrEnum):
    MEMORY = "memory"
    HOOKS = "hooks"


class RuntimeCapabilityKey(StrEnum):
    MEMORY_SERVICE = "weavert.memory.service"
    COMPACTION_MANAGER = "weavert.compaction.manager"
    ISOLATION_MANAGER = "weavert.isolation.manager"
    REFERENCE_HOST_TYPES = "weavert.hosts.reference_types"
    TEAMMATES = "weavert.team.teammates"
    TEAM_CONTROL_PLANE = "weavert.team.control_plane"
    TEAM_MESSAGE_BUS = "weavert.team.message_bus"
    TEAM_WORKFLOWS = "weavert.team.workflows"


class RuntimeHostFacetKey(StrEnum):
    TEAM_WORKFLOWS = "weavert.team.workflows"


@dataclass(frozen=True, slots=True)
class PackageOwnership:
    package_name: str
    package_role: str
    surface: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "package_name", _require_non_empty(self.package_name, "package_name"))
        object.__setattr__(self, "package_role", _require_non_empty(self.package_role, "package_role"))
        object.__setattr__(self, "surface", _require_non_empty(self.surface, "surface"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    key: str
    value: Any
    owner: PackageOwnership
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _require_non_empty(self.key, "key"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class PackageLifecycleParticipant:
    phase: PackageLifecyclePhase | str
    name: str
    handler: Callable[..., Any]
    owner: PackageOwnership
    order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", PackageLifecyclePhase(self.phase))
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class HostFacetBinding:
    name: str
    facet: Any
    owner: PackageOwnership
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class IngressReceiptHandlerBinding:
    kind: str
    handler: Callable[..., Any]
    owner: PackageOwnership
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _require_non_empty(self.kind, "kind"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class HostFacetResolution:
    name: str
    available: bool
    facet: Any = None
    owner: PackageOwnership | None = None
    code: str = "available"
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "code", _require_non_empty(self.code, "code"))


@dataclass(frozen=True, slots=True)
class StoreBinding:
    slot: str
    store: Any
    owner: PackageOwnership
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "slot", _require_non_empty(self.slot, "slot"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ModelProviderContribution:
    name: str
    binding: Any
    owner: PackageOwnership
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ModelRouteContribution:
    name: str
    binding: Any
    owner: PackageOwnership
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class JobExecutorContribution:
    kind: str
    binding: JobExecutorBinding
    owner: PackageOwnership
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _require_non_empty(self.kind, "kind"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ContextContributorBinding:
    name: str
    stage: ContextContributorStage | str
    contributor: Any
    owner: PackageOwnership
    order: int = 0
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "stage", ContextContributorStage(self.stage))
        object.__setattr__(self, "order", int(self.order))
        if self.contributor is None:
            raise ValueError("ContextContributorBinding.contributor must not be None")
        if self.timeout_seconds is not None:
            normalized_timeout = float(self.timeout_seconds)
            if normalized_timeout < 0:
                raise ValueError("ContextContributorBinding.timeout_seconds must be >= 0")
            object.__setattr__(self, "timeout_seconds", normalized_timeout)
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ContextContributorStageDefinition:
    name: ContextContributorStage | str
    order: int
    prompt_channel: ContextContributorPromptChannel | str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", ContextContributorStage(self.name))
        object.__setattr__(self, "order", int(self.order))
        object.__setattr__(self, "prompt_channel", ContextContributorPromptChannel(self.prompt_channel))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ContextContributorExecutionEntry:
    binding: ContextContributorBinding
    stage: ContextContributorStageDefinition
    sequence: int

    @property
    def ordering_key(self) -> tuple[int, int, bool, str, str, str, int]:
        # Canonical contributors sort ahead of compatibility-only adapters, then
        # fall back to stable package/binding identity instead of registration order.
        return (
            self.stage.order,
            self.binding.order,
            bool(self.binding.metadata.get("compatibility_only")),
            self.binding.owner.package_name,
            self.binding.owner.package_role,
            self.binding.name,
            self.sequence,
        )


DEFAULT_CONTEXT_CONTRIBUTOR_STAGES = (
    ContextContributorStageDefinition(
        name=ContextContributorStage.MEMORY,
        order=100,
        prompt_channel=ContextContributorPromptChannel.MEMORY,
        metadata={"description": "retrieval-style prompt context before generic hook guidance"},
    ),
    ContextContributorStageDefinition(
        name=ContextContributorStage.HOOKS,
        order=200,
        prompt_channel=ContextContributorPromptChannel.HOOKS,
        metadata={"description": "generic request-time guidance and prompt-visible sidecars"},
    ),
    ContextContributorStageDefinition(
        name=ContextContributorStage.TASK_POLICY,
        order=300,
        prompt_channel=ContextContributorPromptChannel.HOOKS,
        metadata={"description": "runtime-owned policy reminders and task discipline sidecars"},
    ),
)


@dataclass(frozen=True, slots=True)
class InvocationProviderFactoryContext:
    manifest: "RuntimePackageManifest"
    owner: PackageOwnership
    distribution: str
    working_directory: Path
    config: Any = None
    resources: Mapping[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "distribution",
            canonical_distribution_name(_require_non_empty(self.distribution, "distribution")),
        )
        object.__setattr__(self, "working_directory", Path(self.working_directory))
        object.__setattr__(self, "resources", dict(self.resources))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def resource(self, name: str, default: Any = None) -> Any:
        return self.resources.get(name, default)

    def require_resource(self, name: str) -> Any:
        if name not in self.resources:
            raise KeyError(
                f"Invocation provider '{self.name}' requires build resource '{name}'"
            )
        return self.resources[name]

    @property
    def name(self) -> str:
        return self.owner.metadata.get("provider_name", "") or "<unknown>"


@dataclass(frozen=True, slots=True)
class InvocationProviderContribution:
    name: str
    owner: PackageOwnership
    provider: InvocationProvider | None = None
    factory: Callable[[InvocationProviderFactoryContext], InvocationProvider] | None = None
    order: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "metadata", dict(self.metadata))
        has_provider = self.provider is not None
        has_factory = self.factory is not None
        if has_provider == has_factory:
            raise ValueError("InvocationProviderContribution requires exactly one of provider or factory")
        if self.provider is not None:
            self._validate_provider(self.provider)

    def build_provider(self, context: InvocationProviderFactoryContext) -> InvocationProvider:
        provider = self.provider if self.provider is not None else self.factory(context)
        return self._validate_provider(provider)

    def _validate_provider(self, provider: InvocationProvider) -> InvocationProvider:
        provider_name = _require_non_empty(getattr(provider, "name", None), "provider.name")
        if provider_name != self.name:
            raise ValueError(
                f"Invocation provider contribution '{self.name}' resolved provider '{provider_name}'"
            )
        return provider


@dataclass(frozen=True, slots=True)
class PackageContribution:
    builtin_tools: tuple[ToolDefinition, ...] = ()
    builtin_agents: tuple[AgentDefinition, ...] = ()
    builtin_skills: tuple[SkillDefinition, ...] = ()
    invocation_providers: tuple[InvocationProviderContribution, ...] = ()
    context_contributors: tuple[ContextContributorBinding, ...] = ()
    capabilities: tuple[CapabilityBinding, ...] = ()
    lifecycle_participants: tuple[PackageLifecycleParticipant, ...] = ()
    host_facets: tuple[HostFacetBinding, ...] = ()
    ingress_receipt_handlers: tuple[IngressReceiptHandlerBinding, ...] = ()
    store_bindings: tuple[StoreBinding, ...] = ()
    model_providers: tuple[ModelProviderContribution, ...] = ()
    model_routes: tuple[ModelRouteContribution, ...] = ()
    job_executors: tuple[JobExecutorContribution, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "builtin_tools", tuple(self.builtin_tools))
        object.__setattr__(self, "builtin_agents", tuple(self.builtin_agents))
        object.__setattr__(self, "builtin_skills", tuple(self.builtin_skills))
        object.__setattr__(self, "invocation_providers", tuple(self.invocation_providers))
        object.__setattr__(self, "context_contributors", tuple(self.context_contributors))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "lifecycle_participants", tuple(self.lifecycle_participants))
        object.__setattr__(self, "host_facets", tuple(self.host_facets))
        object.__setattr__(self, "ingress_receipt_handlers", tuple(self.ingress_receipt_handlers))
        object.__setattr__(self, "store_bindings", tuple(self.store_bindings))
        object.__setattr__(self, "model_providers", tuple(self.model_providers))
        object.__setattr__(self, "model_routes", tuple(self.model_routes))
        object.__setattr__(self, "job_executors", tuple(self.job_executors))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "metadata", dict(self.metadata))


class PackageAssembler(Protocol):
    def __call__(self, context: "PackageContext") -> PackageContribution: ...


@dataclass(frozen=True, slots=True)
class RuntimePackageManifest:
    name: str
    role: str
    description: str = ""
    dependencies: tuple[str, ...] = ()
    assembly_entrypoint: str | PackageAssembler | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            canonical_first_party_name(_require_non_empty(self.name, "name")),
        )
        object.__setattr__(self, "role", _require_non_empty(self.role, "role"))
        object.__setattr__(self, "description", str(self.description))
        object.__setattr__(
            self,
            "dependencies",
            tuple(canonical_first_party_name(str(name)) for name in self.dependencies),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def assemble(self, context: "PackageContext") -> PackageContribution:
        entrypoint = self.assembly_entrypoint
        if entrypoint is None:
            return PackageContribution()
        factory = load_object(entrypoint) if isinstance(entrypoint, str) else entrypoint
        contribution = factory(context)
        if contribution is None:
            return PackageContribution()
        if not isinstance(contribution, PackageContribution):
            raise TypeError(
                f"Package manifest '{self.name}' returned {type(contribution)!r}; "
                "expected PackageContribution"
            )
        return contribution


@dataclass(frozen=True, slots=True)
class PackageContext:
    manifest: RuntimePackageManifest
    stage: PackageAssemblyStage | str
    distribution: str
    selected_packages: tuple[str, ...]
    working_directory: Path
    config: Any = None
    resources: Mapping[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", PackageAssemblyStage(self.stage))
        object.__setattr__(
            self,
            "distribution",
            canonical_distribution_name(_require_non_empty(self.distribution, "distribution")),
        )
        object.__setattr__(
            self,
            "selected_packages",
            tuple(canonical_first_party_name(str(name)) for name in self.selected_packages),
        )
        object.__setattr__(self, "working_directory", Path(self.working_directory))
        object.__setattr__(self, "resources", dict(self.resources))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def resource(self, name: str, default: Any = None) -> Any:
        return self.resources.get(name, default)

    def require_resource(self, name: str) -> Any:
        if name not in self.resources:
            raise KeyError(
                f"Package '{self.manifest.name}' requires assembly resource '{name}' during "
                f"{self.stage.value}"
            )
        return self.resources[name]

    def ownership(self, surface: str, **metadata: Any) -> PackageOwnership:
        return PackageOwnership(
            package_name=self.manifest.name,
            package_role=self.manifest.role,
            surface=surface,
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class CapabilityPackageBindingSpec:
    key: str
    value: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", canonical_public_namespace(_require_non_empty(self.key, "key")))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ContextContributorPackageBindingSpec:
    name: str
    stage: ContextContributorStage | str
    contributor: Any
    order: int = 0
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "stage", ContextContributorStage(self.stage))
        object.__setattr__(self, "order", int(self.order))
        if self.contributor is None:
            raise ValueError("ContextContributorPackageBindingSpec.contributor must not be None")
        if self.timeout_seconds is not None:
            normalized_timeout = float(self.timeout_seconds)
            if normalized_timeout < 0:
                raise ValueError("ContextContributorPackageBindingSpec.timeout_seconds must be >= 0")
            object.__setattr__(self, "timeout_seconds", normalized_timeout)
        object.__setattr__(self, "metadata", dict(self.metadata))


def build_capability_only_package_manifest(
    *,
    name: str,
    capabilities: Sequence[CapabilityPackageBindingSpec],
    description: str = "Capability-only runtime package.",
    role: str = "capability",
    dependencies: Sequence[str] = ("weavert-core",),
    manifest_metadata: Mapping[str, Any] | None = None,
) -> RuntimePackageManifest:
    """Build the minimal ordinary runtime package shape for a capability-only package."""
    normalized_capabilities = _normalize_capability_builder_specs(capabilities)
    return _build_manifest_backed_service_package(
        name=name,
        role=role,
        description=description,
        dependencies=dependencies,
        manifest_metadata=manifest_metadata,
        default_manifest_metadata={
            "package_pattern": "capability-only",
            "capabilities": [spec.key for spec in normalized_capabilities],
            "capability_registration_path": "PackageContribution.capabilities",
        },
        contribution_builder=lambda context: PackageContribution(
            capabilities=tuple(
                CapabilityBinding(
                    key=spec.key,
                    value=spec.value,
                    owner=context.ownership(
                        "capability",
                        capability_key=spec.key,
                        package_pattern="capability-only",
                    ),
                    metadata=_builder_binding_metadata(
                        spec.metadata,
                        package_pattern="capability-only",
                    ),
                )
                for spec in normalized_capabilities
            ),
            metadata=_builder_package_contribution_metadata(
                package_pattern="capability-only",
                registration_path="PackageContribution.capabilities",
            ),
        ),
    )


def build_context_contributor_only_package_manifest(
    *,
    name: str,
    context_contributors: Sequence[ContextContributorPackageBindingSpec],
    description: str = "Context-contributor-only runtime package.",
    role: str = "capability",
    dependencies: Sequence[str] = ("weavert-core",),
    manifest_metadata: Mapping[str, Any] | None = None,
) -> RuntimePackageManifest:
    """Build the minimal ordinary runtime package shape for a context-contributor-only package."""
    normalized_contributors = _normalize_context_contributor_builder_specs(context_contributors)
    return _build_manifest_backed_service_package(
        name=name,
        role=role,
        description=description,
        dependencies=dependencies,
        manifest_metadata=manifest_metadata,
        default_manifest_metadata={
            "package_pattern": "context-contributor-only",
            "context_contributors": [spec.name for spec in normalized_contributors],
            "context_contributor_registration_path": "PackageContribution.context_contributors",
            "context_contributor_stages": [
                {
                    "name": spec.name,
                    "stage": spec.stage.value,
                    "order": spec.order,
                }
                for spec in normalized_contributors
            ],
        },
        contribution_builder=lambda context: PackageContribution(
            context_contributors=tuple(
                ContextContributorBinding(
                    name=spec.name,
                    stage=spec.stage,
                    contributor=spec.contributor,
                    owner=context.ownership(
                        "context_contributor",
                        contributor_name=spec.name,
                        contributor_stage=spec.stage.value,
                        package_pattern="context-contributor-only",
                    ),
                    order=spec.order,
                    timeout_seconds=spec.timeout_seconds,
                    metadata=_builder_binding_metadata(
                        spec.metadata,
                        package_pattern="context-contributor-only",
                    ),
                )
                for spec in normalized_contributors
            ),
            metadata=_builder_package_contribution_metadata(
                package_pattern="context-contributor-only",
                registration_path="PackageContribution.context_contributors",
            ),
        ),
    )


def build_provider_only_invocation_package_manifest(
    *,
    name: str,
    provider_name: str,
    provider: InvocationProvider | None = None,
    factory: Callable[[InvocationProviderFactoryContext], InvocationProvider] | None = None,
    description: str = "Provider-only runtime package.",
    role: str = "provider",
    dependencies: Sequence[str] = ("weavert-core",),
    order: int = 0,
    manifest_metadata: Mapping[str, Any] | None = None,
    contribution_metadata: Mapping[str, Any] | None = None,
) -> RuntimePackageManifest:
    """Build the minimal ordinary runtime package shape for a provider-only package."""
    normalized_provider_name = _require_non_empty(provider_name, "provider_name")
    if (provider is None) == (factory is None):
        raise ValueError("Provider-only package template requires exactly one of provider or factory")
    return _build_manifest_backed_service_package(
        name=name,
        role=role,
        description=description,
        dependencies=dependencies,
        manifest_metadata=manifest_metadata,
        default_manifest_metadata={
            "invocation_providers": [normalized_provider_name],
            "package_pattern": "provider-only",
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
        contribution_builder=lambda context: PackageContribution(
            invocation_providers=(
                InvocationProviderContribution(
                    name=normalized_provider_name,
                    owner=context.ownership(
                        "invocation_provider",
                        provider_name=normalized_provider_name,
                        package_pattern="provider-only",
                    ),
                    provider=provider,
                    factory=factory,
                    order=order,
                    metadata=_builder_binding_metadata(
                        contribution_metadata,
                        package_pattern="provider-only",
                    ),
                ),
            ),
            metadata=_builder_package_contribution_metadata(
                package_pattern="provider-only",
                registration_path="PackageContribution.invocation_providers",
            ),
        ),
    )


def _build_manifest_backed_service_package(
    *,
    name: str,
    role: str,
    description: str,
    dependencies: Sequence[str],
    manifest_metadata: Mapping[str, Any] | None,
    default_manifest_metadata: Mapping[str, Any],
    contribution_builder: Callable[[PackageContext], PackageContribution],
) -> RuntimePackageManifest:
    normalized_dependencies = _normalize_package_builder_dependencies(dependencies)

    def _assemble_package(context: PackageContext) -> PackageContribution:
        if context.stage != PackageAssemblyStage.SERVICES:
            return PackageContribution()
        return contribution_builder(context)

    return RuntimePackageManifest(
        name=_require_non_empty(name, "name"),
        role=_require_non_empty(role, "role"),
        description=str(description),
        dependencies=normalized_dependencies,
        assembly_entrypoint=_assemble_package,
        metadata=_builder_manifest_metadata(
            normalized_dependencies,
            default_metadata=default_manifest_metadata,
            manifest_metadata=manifest_metadata,
        ),
    )


def _normalize_package_builder_dependencies(dependencies: Sequence[str]) -> tuple[str, ...]:
    if dependencies is None:
        dependencies = ("weavert-core",)
    return tuple(
        canonical_first_party_name(str(item))
        for item in dependencies
    )


def _normalize_capability_builder_specs(
    capabilities: Sequence[CapabilityPackageBindingSpec],
) -> tuple[CapabilityPackageBindingSpec, ...]:
    normalized = tuple(capabilities)
    if not normalized:
        raise ValueError("Capability-only package builder requires at least one capability binding")
    return normalized


def _normalize_context_contributor_builder_specs(
    context_contributors: Sequence[ContextContributorPackageBindingSpec],
) -> tuple[ContextContributorPackageBindingSpec, ...]:
    normalized = tuple(context_contributors)
    if not normalized:
        raise ValueError(
            "Context-contributor-only package builder requires at least one context contributor binding"
        )
    return normalized


def _builder_manifest_metadata(
    dependencies: Sequence[str],
    *,
    default_metadata: Mapping[str, Any],
    manifest_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    metadata = dict(manifest_metadata or {})
    builder_owned_metadata = {
        "baseline_dependencies": list(dependencies),
        **dict(default_metadata),
    }
    conflicting_keys = sorted(
        key
        for key, value in builder_owned_metadata.items()
        if key in metadata and metadata[key] != value
    )
    if conflicting_keys:
        raise ValueError(
            "manifest_metadata must not override builder-owned keys: "
            + ", ".join(conflicting_keys)
        )
    metadata.update(builder_owned_metadata)
    return metadata


def _builder_binding_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    package_pattern: str,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    normalized.setdefault("package_pattern", package_pattern)
    return normalized


def _builder_package_contribution_metadata(
    *,
    package_pattern: str,
    registration_path: str,
) -> dict[str, Any]:
    return {
        "package_pattern": package_pattern,
        "registration_path": registration_path,
    }


@dataclass(slots=True)
class CapabilityRegistry:
    _bindings: dict[str, CapabilityBinding] = field(default_factory=dict)

    def bind(self, binding: CapabilityBinding, *, override: bool = True) -> CapabilityBinding | None:
        normalized = canonical_public_namespace(_require_non_empty(binding.key, "binding.key"))
        previous = self._bindings.get(normalized)
        if previous is not None and not override:
            raise ValueError(f"Capability '{normalized}' is already registered")
        self._bindings[normalized] = binding
        return previous

    def binding(self, key: str) -> CapabilityBinding | None:
        return self._bindings.get(canonical_public_namespace(_require_non_empty(key, "key")))

    def resolve(self, key: str, default: Any = None) -> Any:
        binding = self.binding(key)
        return default if binding is None else binding.value

    def require(self, key: str) -> Any:
        binding = self.binding(key)
        if binding is None:
            raise KeyError(f"Capability '{key}' is not registered")
        return binding.value

    def owner(self, key: str) -> PackageOwnership | None:
        binding = self.binding(key)
        return None if binding is None else binding.owner

    def bindings(self) -> tuple[CapabilityBinding, ...]:
        return tuple(self._bindings[key] for key in sorted(self._bindings))


@dataclass(slots=True)
class ContextContributorRegistry:
    _stages: dict[str, ContextContributorStageDefinition] = field(
        default_factory=lambda: {
            stage.name.value: stage for stage in DEFAULT_CONTEXT_CONTRIBUTOR_STAGES
        }
    )
    _bindings: dict[str, tuple[int, ContextContributorBinding]] = field(default_factory=dict)
    _sequence: int = 0

    def register_stage(
        self,
        definition: ContextContributorStageDefinition,
        *,
        override: bool = False,
    ) -> ContextContributorStageDefinition | None:
        key = definition.name.value
        previous = self._stages.get(key)
        if previous is not None and not override:
            raise ValueError(f"Context contributor stage '{key}' is already registered")
        self._stages[key] = definition
        return previous

    def stage(self, name: ContextContributorStage | str) -> ContextContributorStageDefinition:
        normalized = ContextContributorStage(name).value
        try:
            return self._stages[normalized]
        except KeyError as exc:  # pragma: no cover - defensive boundary
            raise KeyError(f"Unknown context contributor stage '{normalized}'") from exc

    def stage_catalog(self) -> tuple[ContextContributorStageDefinition, ...]:
        return tuple(sorted(self._stages.values(), key=lambda entry: (entry.order, entry.name.value)))

    def register(
        self,
        binding: ContextContributorBinding,
        *,
        override: bool = True,
    ) -> ContextContributorBinding | None:
        stage = self.stage(binding.stage)
        previous_record = self._bindings.get(binding.name)
        if previous_record is not None and not override:
            raise ValueError(f"Context contributor '{binding.name}' is already registered")
        self._bindings[binding.name] = (self._sequence, binding)
        self._sequence += 1
        _ = stage
        return None if previous_record is None else previous_record[1]

    def binding(self, name: str) -> ContextContributorBinding | None:
        record = self._bindings.get(_require_non_empty(name, "name"))
        return None if record is None else record[1]

    def bindings(
        self,
        stage: ContextContributorStage | str | None = None,
    ) -> tuple[ContextContributorBinding, ...]:
        return tuple(
            entry.binding
            for entry in self.execution_plan(stage=stage)
        )

    def execution_plan(
        self,
        stage: ContextContributorStage | str | None = None,
    ) -> tuple[ContextContributorExecutionEntry, ...]:
        normalized_stage = ContextContributorStage(stage) if stage is not None else None
        records: list[ContextContributorExecutionEntry] = []
        for sequence, binding in self._bindings.values():
            stage_definition = self.stage(binding.stage)
            if normalized_stage is not None and stage_definition.name != normalized_stage:
                continue
            records.append(
                ContextContributorExecutionEntry(
                    binding=binding,
                    stage=stage_definition,
                    sequence=sequence,
                )
            )
        return tuple(
            sorted(
                records,
                key=lambda record: record.ordering_key,
            )
        )


@dataclass(slots=True)
class PackageLifecycleRegistry:
    _entries: list[tuple[int, PackageLifecycleParticipant]] = field(default_factory=list)
    _sequence: int = 0

    def register(self, participant: PackageLifecycleParticipant) -> None:
        self._entries.append((self._sequence, participant))
        self._sequence += 1

    def participants(
        self,
        phase: PackageLifecyclePhase | str | None = None,
    ) -> tuple[PackageLifecycleParticipant, ...]:
        normalized_phase = PackageLifecyclePhase(phase) if phase is not None else None
        ordered = sorted(self._entries, key=lambda entry: (entry[1].order, entry[0], entry[1].name))
        result = [
            participant
            for _, participant in ordered
            if normalized_phase is None or participant.phase == normalized_phase
        ]
        return tuple(result)


@dataclass(slots=True)
class HostFacetRegistry:
    _bindings: dict[str, HostFacetBinding] = field(default_factory=dict)

    def register(self, binding: HostFacetBinding, *, override: bool = True) -> HostFacetBinding | None:
        normalized = canonical_public_namespace(_require_non_empty(binding.name, "binding.name"))
        previous = self._bindings.get(normalized)
        if previous is not None and not override:
            raise ValueError(f"Host facet '{normalized}' is already registered")
        self._bindings[normalized] = binding
        return previous

    def binding(self, name: str) -> HostFacetBinding | None:
        return self._bindings.get(canonical_public_namespace(_require_non_empty(name, "name")))

    def resolve(self, name: str) -> HostFacetResolution:
        binding = self.binding(name)
        if binding is None:
            return HostFacetResolution(
                name=name,
                available=False,
                code="not_available",
                message=f"Host facet '{name}' is not available in the active runtime",
            )
        return HostFacetResolution(
            name=name,
            available=True,
            facet=binding.facet,
            owner=binding.owner,
        )

    def require(self, name: str) -> Any:
        resolution = self.resolve(name)
        if not resolution.available:
            raise LookupError(resolution.message)
        return resolution.facet

    def bindings(self) -> tuple[HostFacetBinding, ...]:
        return tuple(self._bindings[key] for key in sorted(self._bindings))


@dataclass(slots=True)
class IngressReceiptRegistry:
    _bindings: dict[str, IngressReceiptHandlerBinding] = field(default_factory=dict)

    def register(
        self,
        binding: IngressReceiptHandlerBinding,
        *,
        override: bool = True,
    ) -> IngressReceiptHandlerBinding | None:
        normalized = canonical_public_namespace(_require_non_empty(binding.kind, "binding.kind"))
        previous = self._bindings.get(normalized)
        if previous is not None and not override:
            raise ValueError(f"Ingress receipt handler '{normalized}' is already registered")
        self._bindings[normalized] = binding
        return previous

    def binding(self, kind: str) -> IngressReceiptHandlerBinding | None:
        return self._bindings.get(canonical_public_namespace(_require_non_empty(kind, "kind")))

    def resolve(self, kind: str) -> Callable[..., Any] | None:
        binding = self.binding(kind)
        return None if binding is None else binding.handler

    def owner(self, kind: str) -> PackageOwnership | None:
        binding = self.binding(kind)
        return None if binding is None else binding.owner

    def bindings(self) -> tuple[IngressReceiptHandlerBinding, ...]:
        return tuple(self._bindings[key] for key in sorted(self._bindings))


def order_package_manifests(
    package_names: Sequence[str],
    manifest_catalog: Mapping[str, RuntimePackageManifest],
) -> tuple[RuntimePackageManifest, ...]:
    requested = tuple(canonical_first_party_name(str(name)) for name in package_names)
    requested_set = set(requested)
    ordered: list[RuntimePackageManifest] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"Cyclic package dependency detected at '{name}'")
        manifest = manifest_catalog.get(name)
        if manifest is None:
            raise KeyError(f"Unknown runtime package manifest '{name}'")
        visiting.add(name)
        for dependency in manifest.dependencies:
            if dependency not in requested_set:
                raise ValueError(
                    f"Package '{name}' requires dependency '{dependency}' to be selected"
                )
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(manifest)

    for package_name in requested:
        visit(package_name)
    return tuple(ordered)


def annotate_builtin_owner(
    definition: ToolDefinition | AgentDefinition | SkillDefinition,
    *,
    package_name: str,
    package_role: str,
) -> ToolDefinition | AgentDefinition | SkillDefinition:
    metadata = dict(definition.metadata)
    metadata["builtin_owner"] = package_name
    metadata["builtin_owner_role"] = package_role
    return replace(definition, metadata=metadata)


def preserve_builtin_owner(
    replacement_definition: ToolDefinition | AgentDefinition | SkillDefinition,
    *,
    original_definition: ToolDefinition | AgentDefinition | SkillDefinition,
) -> ToolDefinition | AgentDefinition | SkillDefinition:
    original_owner = {
        "builtin_owner": original_definition.metadata.get("builtin_owner"),
        "builtin_owner_role": original_definition.metadata.get("builtin_owner_role"),
    }
    metadata = dict(replacement_definition.metadata)
    for key, value in original_owner.items():
        if value is not None and key not in metadata:
            metadata[key] = value
    return replace(replacement_definition, metadata=metadata)


def _require_non_empty(value: Any, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


__all__ = [
    "CapabilityBinding",
    "CapabilityPackageBindingSpec",
    "CapabilityRegistry",
    "build_capability_only_package_manifest",
    "build_context_contributor_only_package_manifest",
    "build_provider_only_invocation_package_manifest",
    "ContextContributorBinding",
    "ContextContributorExecutionEntry",
    "ContextContributorPackageBindingSpec",
    "ContextContributorPromptChannel",
    "ContextContributorRegistry",
    "ContextContributorStage",
    "ContextContributorStageDefinition",
    "DEFAULT_CONTEXT_CONTRIBUTOR_STAGES",
    "HostFacetBinding",
    "HostFacetRegistry",
    "HostFacetResolution",
    "IngressReceiptHandlerBinding",
    "IngressReceiptRegistry",
    "InvocationProviderContribution",
    "InvocationProviderFactoryContext",
    "JobExecutorContribution",
    "ModelProviderContribution",
    "ModelRouteContribution",
    "PackageAssembler",
    "PackageAssemblyStage",
    "PackageContext",
    "PackageContribution",
    "PackageLifecycleParticipant",
    "PackageLifecyclePhase",
    "PackageLifecycleRegistry",
    "PackageOwnership",
    "RuntimeCapabilityKey",
    "RuntimeHostFacetKey",
    "RuntimePackageManifest",
    "StoreBinding",
    "annotate_builtin_owner",
    "order_package_manifests",
    "preserve_builtin_owner",
]
