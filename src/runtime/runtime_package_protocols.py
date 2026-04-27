from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .definitions import AgentDefinition, InvocationProvider, SkillDefinition, ToolDefinition
from .diagnostics import Diagnostic
from .first_party_loading import load_object
from .jobs import JobExecutorBinding


class PackageAssemblyStage(StrEnum):
    BUILTINS = "builtins"
    SERVICES = "services"
    RUNTIME = "runtime"


class PackageLifecyclePhase(StrEnum):
    RUNTIME_START = "runtime_start"
    RUNTIME_RECOVERY = "runtime_recovery"
    SESSION_OPEN = "session_open"
    SESSION_CLOSE = "session_close"


class RuntimeCapabilityKey(StrEnum):
    MEMORY_SERVICE = "runtime.memory.service"
    COMPACTION_MANAGER = "runtime.compaction.manager"
    ISOLATION_MANAGER = "runtime.isolation.manager"
    REFERENCE_HOST_TYPES = "runtime.hosts.reference_types"
    TEAMMATES = "runtime.team.teammates"
    TEAM_CONTROL_PLANE = "runtime.team.control_plane"
    TEAM_MESSAGE_BUS = "runtime.team.message_bus"
    TEAM_WORKFLOWS = "runtime.team.workflows"


class RuntimeHostFacetKey(StrEnum):
    TEAM_WORKFLOWS = "runtime.team.workflows"


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
class InvocationProviderFactoryContext:
    manifest: "RuntimePackageManifest"
    owner: PackageOwnership
    distribution: str
    working_directory: Path
    config: Any = None
    resources: Mapping[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "distribution", _require_non_empty(self.distribution, "distribution"))
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
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "role", _require_non_empty(self.role, "role"))
        object.__setattr__(self, "description", str(self.description))
        object.__setattr__(self, "dependencies", tuple(str(name) for name in self.dependencies))
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
        object.__setattr__(self, "distribution", _require_non_empty(self.distribution, "distribution"))
        object.__setattr__(self, "selected_packages", tuple(str(name) for name in self.selected_packages))
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


@dataclass(slots=True)
class CapabilityRegistry:
    _bindings: dict[str, CapabilityBinding] = field(default_factory=dict)

    def bind(self, binding: CapabilityBinding, *, override: bool = True) -> CapabilityBinding | None:
        normalized = _require_non_empty(binding.key, "binding.key")
        previous = self._bindings.get(normalized)
        if previous is not None and not override:
            raise ValueError(f"Capability '{normalized}' is already registered")
        self._bindings[normalized] = binding
        return previous

    def binding(self, key: str) -> CapabilityBinding | None:
        return self._bindings.get(_require_non_empty(key, "key"))

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
        normalized = _require_non_empty(binding.name, "binding.name")
        previous = self._bindings.get(normalized)
        if previous is not None and not override:
            raise ValueError(f"Host facet '{normalized}' is already registered")
        self._bindings[normalized] = binding
        return previous

    def binding(self, name: str) -> HostFacetBinding | None:
        return self._bindings.get(_require_non_empty(name, "name"))

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
        normalized = _require_non_empty(binding.kind, "binding.kind")
        previous = self._bindings.get(normalized)
        if previous is not None and not override:
            raise ValueError(f"Ingress receipt handler '{normalized}' is already registered")
        self._bindings[normalized] = binding
        return previous

    def binding(self, kind: str) -> IngressReceiptHandlerBinding | None:
        return self._bindings.get(_require_non_empty(kind, "kind"))

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
    requested = tuple(str(name) for name in package_names)
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
    "CapabilityRegistry",
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
