from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from itertools import zip_longest
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from .diagnostics import Diagnostic, DiagnosticSeverity
from .public_contract import canonical_distribution_name, canonical_first_party_name
from .runtime_package_manifests import RuntimePackageRegistrationReport
from .runtime_package_protocols import RuntimePackageManifest, order_package_manifests

PACKAGE_CANDIDATE_METADATA_KEY = "package_candidate"
REQUESTED_PACKAGES_PATH = "RuntimeConfig.requested_packages"


@dataclass(frozen=True, slots=True)
class RuntimePackageDependencyConstraint:
    package_name: str
    candidate_id: str | None = None
    version: str | None = None
    minimum_version: str | None = None
    maximum_version: str | None = None
    include_minimum: bool = True
    include_maximum: bool = False
    kind: str = "legacy"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "package_name",
            canonical_first_party_name(_require_non_empty(self.package_name, "package_name")),
        )
        object.__setattr__(self, "candidate_id", _normalize_optional_string(self.candidate_id))
        object.__setattr__(self, "version", _normalize_optional_string(self.version))
        object.__setattr__(self, "minimum_version", _normalize_optional_string(self.minimum_version))
        object.__setattr__(self, "maximum_version", _normalize_optional_string(self.maximum_version))
        object.__setattr__(self, "include_minimum", bool(self.include_minimum))
        object.__setattr__(self, "include_maximum", bool(self.include_maximum))
        object.__setattr__(self, "kind", _require_non_empty(self.kind, "kind"))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def matches(self, candidate: "RuntimePackageCandidateDescriptor") -> bool:
        if candidate.package_name != self.package_name:
            return False
        if self.candidate_id is not None and candidate.candidate_id != self.candidate_id:
            return False
        if self.version is not None and candidate.version != self.version:
            return False
        if self.minimum_version is not None:
            if candidate.version is None:
                return False
            comparison = _compare_versions(candidate.version, self.minimum_version)
            if comparison < 0 or (comparison == 0 and not self.include_minimum):
                return False
        if self.maximum_version is not None:
            if candidate.version is None:
                return False
            comparison = _compare_versions(candidate.version, self.maximum_version)
            if comparison > 0 or (comparison == 0 and not self.include_maximum):
                return False
        return True

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "package_name": self.package_name,
            "kind": self.kind,
        }
        if self.candidate_id is not None:
            metadata["candidate_id"] = self.candidate_id
        if self.version is not None:
            metadata["version"] = self.version
        if self.minimum_version is not None or self.maximum_version is not None:
            metadata["version_range"] = {
                "minimum_version": self.minimum_version,
                "maximum_version": self.maximum_version,
                "include_minimum": self.include_minimum,
                "include_maximum": self.include_maximum,
            }
        if self.metadata:
            metadata["metadata"] = dict(self.metadata)
        return metadata


@dataclass(frozen=True, slots=True)
class RuntimePackageCandidateDescriptor:
    package_name: str
    candidate_id: str
    manifest: RuntimePackageManifest
    source: dict[str, Any]
    dependency_constraints: tuple[RuntimePackageDependencyConstraint, ...] = ()
    version: str | None = None
    compatibility: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "package_name",
            canonical_first_party_name(_require_non_empty(self.package_name, "package_name")),
        )
        object.__setattr__(self, "candidate_id", _require_non_empty(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "dependency_constraints", tuple(self.dependency_constraints))
        object.__setattr__(self, "version", _normalize_optional_string(self.version))
        object.__setattr__(self, "source", dict(self.source))
        object.__setattr__(self, "compatibility", dict(self.compatibility))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def supports_distribution(self, distribution: str) -> bool:
        normalized_distribution = canonical_distribution_name(distribution)
        allowed = tuple(
            canonical_distribution_name(item)
            for item in (
                _normalize_optional_string(raw)
                for raw in self.compatibility.get("distributions", ())
            )
            if item is not None
        )
        denied = tuple(
            canonical_distribution_name(item)
            for item in (
                _normalize_optional_string(raw)
                for raw in self.compatibility.get("excluded_distributions", ())
            )
            if item is not None
        )
        if allowed and normalized_distribution not in allowed:
            return False
        if normalized_distribution in denied:
            return False
        return True

    def compatibility_metadata(self) -> dict[str, Any]:
        allowed = tuple(
            canonical_distribution_name(item)
            for item in (
                _normalize_optional_string(raw)
                for raw in self.compatibility.get("distributions", ())
            )
            if item is not None
        )
        denied = tuple(
            canonical_distribution_name(item)
            for item in (
                _normalize_optional_string(raw)
                for raw in self.compatibility.get("excluded_distributions", ())
            )
            if item is not None
        )
        metadata: dict[str, Any] = {}
        if allowed:
            metadata["distributions"] = list(allowed)
        if denied:
            metadata["excluded_distributions"] = list(denied)
        return metadata

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "package_name": self.package_name,
            "candidate_id": self.candidate_id,
            "source": dict(self.source),
            "manifest": _serialize_manifest_summary(self.manifest),
            "dependency_constraints": [
                constraint.to_metadata() for constraint in self.dependency_constraints
            ],
        }
        if self.version is not None:
            metadata["version"] = self.version
        compatibility = self.compatibility_metadata()
        if compatibility:
            metadata["compatibility"] = compatibility
        return metadata


@dataclass(frozen=True, slots=True)
class RuntimePackageCatalog:
    candidates: tuple[RuntimePackageCandidateDescriptor, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))

    def by_package_name(self) -> dict[str, tuple[RuntimePackageCandidateDescriptor, ...]]:
        grouped: dict[str, list[RuntimePackageCandidateDescriptor]] = defaultdict(list)
        for candidate in sorted(self.candidates, key=_candidate_sort_key):
            grouped[candidate.package_name].append(candidate)
        return {
            package_name: tuple(entries)
            for package_name, entries in grouped.items()
        }

    def candidates_for(self, package_name: str) -> tuple[RuntimePackageCandidateDescriptor, ...]:
        return self.by_package_name().get(str(package_name), ())

    def to_metadata(self) -> dict[str, list[dict[str, Any]]]:
        return {
            package_name: [candidate.to_metadata() for candidate in entries]
            for package_name, entries in self.by_package_name().items()
        }


@dataclass(frozen=True, slots=True)
class RuntimePackageRequest:
    distribution: str
    baseline_packages: tuple[str, ...] = ()
    enabled_first_party_packages: tuple[str, ...] = ()
    disabled_first_party_packages: tuple[str, ...] = ()
    explicit_package_requests: tuple[str, ...] = ()
    requested_packages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "distribution",
            canonical_distribution_name(_require_non_empty(self.distribution, "distribution")),
        )
        object.__setattr__(
            self,
            "baseline_packages",
            tuple(canonical_first_party_name(str(name)) for name in self.baseline_packages),
        )
        object.__setattr__(
            self,
            "enabled_first_party_packages",
            tuple(canonical_first_party_name(str(name)) for name in self.enabled_first_party_packages),
        )
        object.__setattr__(
            self,
            "disabled_first_party_packages",
            tuple(canonical_first_party_name(str(name)) for name in self.disabled_first_party_packages),
        )
        object.__setattr__(
            self,
            "explicit_package_requests",
            tuple(canonical_first_party_name(str(name)) for name in self.explicit_package_requests),
        )
        object.__setattr__(
            self,
            "requested_packages",
            tuple(canonical_first_party_name(str(name)) for name in self.requested_packages),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "distribution": self.distribution,
            "baseline_packages": list(self.baseline_packages),
            "enabled_first_party_packages": list(self.enabled_first_party_packages),
            "disabled_first_party_packages": list(self.disabled_first_party_packages),
            "explicit_package_requests": list(self.explicit_package_requests),
            "requested_packages": list(self.requested_packages),
        }


@dataclass(frozen=True, slots=True)
class RuntimePackageResolutionDiagnostic:
    severity: DiagnosticSeverity
    code: str
    message: str
    package_name: str | None = None
    candidate_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_non_empty(self.code, "code"))
        object.__setattr__(self, "message", str(self.message))
        object.__setattr__(self, "package_name", _normalize_optional_string(self.package_name))
        object.__setattr__(self, "candidate_id", _normalize_optional_string(self.candidate_id))
        object.__setattr__(self, "details", dict(self.details))

    def to_diagnostic(self) -> Diagnostic:
        return Diagnostic(
            severity=self.severity,
            code=self.code,
            message=self.message,
            definition_type="runtime_package_resolution",
            source="runtime_package_resolver",
            location=self.candidate_id or self.package_name,
            details={
                "package_name": self.package_name,
                "candidate_id": self.candidate_id,
                **dict(self.details),
            },
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "package_name": self.package_name,
            "candidate_id": self.candidate_id,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class RuntimePackageResolutionReport:
    request: RuntimePackageRequest
    catalog: RuntimePackageCatalog = field(default_factory=RuntimePackageCatalog)
    resolved_candidates: tuple[RuntimePackageCandidateDescriptor, ...] = ()
    resolved_manifests: tuple[RuntimePackageManifest, ...] = ()
    diagnostics: tuple[RuntimePackageResolutionDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved_candidates", tuple(self.resolved_candidates))
        object.__setattr__(self, "resolved_manifests", tuple(self.resolved_manifests))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def success(self) -> bool:
        return not self.diagnostics

    def as_diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(diagnostic.to_diagnostic() for diagnostic in self.diagnostics)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "candidate_catalog": self.catalog.to_metadata(),
            "request": self.request.to_metadata(),
            "resolved_graph": {
                "order": [manifest.name for manifest in self.resolved_manifests],
                "packages": {
                    candidate.package_name: candidate.to_metadata()
                    for candidate in self.resolved_candidates
                },
            },
            "diagnostics": [diagnostic.to_metadata() for diagnostic in self.diagnostics],
        }


class RuntimePackageResolutionError(RuntimeError):
    def __init__(self, report: RuntimePackageResolutionReport) -> None:
        self.report = report
        message = (
            report.diagnostics[0].message
            if report.diagnostics
            else "Runtime package resolution failed"
        )
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _ResolutionRequirement:
    constraint: RuntimePackageDependencyConstraint
    source: str
    requester: str
    requester_candidate_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _require_non_empty(self.source, "source"))
        object.__setattr__(self, "requester", _require_non_empty(self.requester, "requester"))
        object.__setattr__(
            self,
            "requester_candidate_id",
            _normalize_optional_string(self.requester_candidate_id),
        )

    def to_metadata(self) -> dict[str, Any]:
        metadata = {
            "source": self.source,
            "requester": self.requester,
            "constraint": self.constraint.to_metadata(),
        }
        if self.requester_candidate_id is not None:
            metadata["requester_candidate_id"] = self.requester_candidate_id
        return metadata


def build_runtime_package_request(
    *,
    distribution: str,
    baseline_packages: Iterable[str] = (),
    enabled_packages: Iterable[str] = (),
    disabled_packages: Iterable[str] = (),
    explicit_package_requests: Iterable[str] = (),
    selected_first_party_packages: Iterable[str] = (),
    first_party_package_names: Iterable[str] = (),
) -> RuntimePackageRequest:
    normalized_baseline = tuple(canonical_first_party_name(str(name)) for name in baseline_packages)
    normalized_enabled = tuple(
        sorted(
            {
                canonical_first_party_name(_require_non_empty(name, "enabled_package"))
                for name in enabled_packages
            }
        )
    )
    normalized_disabled = tuple(
        sorted(
            {
                canonical_first_party_name(_require_non_empty(name, "disabled_package"))
                for name in disabled_packages
            }
        )
    )
    normalized_selected = tuple(canonical_first_party_name(str(name)) for name in selected_first_party_packages)
    normalized_explicit = tuple(
        sorted(
            {
                canonical_first_party_name(_require_non_empty(name, "explicit_package_request"))
                for name in explicit_package_requests
            }
        )
    )
    first_party_names = {canonical_first_party_name(str(name)) for name in first_party_package_names}
    conflicting_first_party_requests = sorted(
        package_name
        for package_name in normalized_explicit
        if package_name in first_party_names and package_name not in set(normalized_selected)
    )
    if conflicting_first_party_requests:
        raise ValueError(
            "Explicit package requests must target admitted external package names; "
            "use enabled_packages/disabled_packages for first-party packages: "
            + ", ".join(conflicting_first_party_requests)
        )
    requested_packages = _stable_unique_names((*normalized_selected, *normalized_explicit))
    return RuntimePackageRequest(
        distribution=distribution,
        baseline_packages=normalized_baseline,
        enabled_first_party_packages=normalized_enabled,
        disabled_first_party_packages=normalized_disabled,
        explicit_package_requests=normalized_explicit,
        requested_packages=requested_packages,
    )


def build_runtime_package_catalog(
    first_party_manifests: Sequence[RuntimePackageManifest],
    registration_report: RuntimePackageRegistrationReport,
) -> RuntimePackageCatalog:
    candidates: list[RuntimePackageCandidateDescriptor] = []
    for manifest in first_party_manifests:
        candidates.append(
            _candidate_descriptor(
                manifest,
                source={
                    "origin": "first_party",
                    "source_kind": "official-catalog",
                    "source_ref": (
                        "weavert.runtime_package_catalog:"
                        f"OFFICIAL_RUNTIME_PACKAGE_CATALOG['{manifest.name}']"
                    ),
                },
            )
        )
    for record in registration_report.accepted:
        candidates.append(
            _candidate_descriptor(
                record.manifest,
                source=record.provenance(),
                default_candidate_id=(
                    f"external::{record.manifest.name}"
                    f"#{record.registration_index}"
                ),
            )
        )
    return RuntimePackageCatalog(candidates=tuple(candidates))


def resolve_runtime_package_graph(
    request: RuntimePackageRequest,
    catalog: RuntimePackageCatalog,
) -> RuntimePackageResolutionReport:
    catalog_by_name = catalog.by_package_name()
    catalog_diagnostics = _catalog_diagnostics(catalog_by_name)
    if catalog_diagnostics:
        return RuntimePackageResolutionReport(
            request=request,
            catalog=catalog,
            diagnostics=tuple(catalog_diagnostics),
        )
    selected: dict[str, RuntimePackageCandidateDescriptor] = {}
    constraints_by_package: dict[str, list[_ResolutionRequirement]] = defaultdict(list)

    for package_name in request.requested_packages:
        constraints_by_package[package_name].append(
            _ResolutionRequirement(
                constraint=RuntimePackageDependencyConstraint(
                    package_name=package_name,
                    kind="request",
                ),
                source="runtime_request",
                requester=REQUESTED_PACKAGES_PATH,
            )
        )

    failure = _resolve_requested_packages(
        requested_packages=request.requested_packages,
        index=0,
        distribution=request.distribution,
        catalog_by_name=catalog_by_name,
        selected=selected,
        constraints_by_package=constraints_by_package,
    )
    if failure is not None:
        return RuntimePackageResolutionReport(
            request=request,
            catalog=catalog,
            diagnostics=(failure,),
        )

    manifest_catalog = {
        package_name: candidate.manifest
        for package_name, candidate in selected.items()
    }
    ordered_manifests = order_package_manifests(tuple(selected), manifest_catalog)
    ordered_candidates = tuple(selected[manifest.name] for manifest in ordered_manifests)
    return RuntimePackageResolutionReport(
        request=request,
        catalog=catalog,
        resolved_candidates=ordered_candidates,
        resolved_manifests=ordered_manifests,
    )


def _resolve_requested_packages(
    *,
    requested_packages: Sequence[str],
    index: int,
    distribution: str,
    catalog_by_name: Mapping[str, tuple[RuntimePackageCandidateDescriptor, ...]],
    selected: dict[str, RuntimePackageCandidateDescriptor],
    constraints_by_package: dict[str, list[_ResolutionRequirement]],
) -> RuntimePackageResolutionDiagnostic | None:
    if index >= len(requested_packages):
        return None
    return _resolve_package(
        requested_packages[index],
        distribution=distribution,
        catalog_by_name=catalog_by_name,
        selected=selected,
        constraints_by_package=constraints_by_package,
        stack=(),
        on_success=lambda: _resolve_requested_packages(
            requested_packages=requested_packages,
            index=index + 1,
            distribution=distribution,
            catalog_by_name=catalog_by_name,
            selected=selected,
            constraints_by_package=constraints_by_package,
        ),
    )


def _candidate_descriptor(
    manifest: RuntimePackageManifest,
    *,
    source: Mapping[str, Any],
    default_candidate_id: str | None = None,
) -> RuntimePackageCandidateDescriptor:
    candidate_metadata = _candidate_metadata(manifest)
    dependency_constraints = _normalized_dependency_constraints(manifest, candidate_metadata)
    dependency_names = _stable_unique_names(
        (
            *manifest.dependencies,
            *(constraint.package_name for constraint in dependency_constraints),
        )
    )
    normalized_manifest = (
        manifest
        if dependency_names == tuple(manifest.dependencies)
        else replace(manifest, dependencies=dependency_names)
    )
    candidate_id = _normalize_optional_string(candidate_metadata.get("candidate_id")) or (
        default_candidate_id
        or f"official::{manifest.name}"
    )
    version = _normalize_optional_string(candidate_metadata.get("version"))
    if version is not None and "@" not in candidate_id and candidate_id.startswith("official::"):
        candidate_id = f"{candidate_id}@{version}"
    compatibility = dict(candidate_metadata.get("compatibility", {}))
    return RuntimePackageCandidateDescriptor(
        package_name=manifest.name,
        candidate_id=candidate_id,
        manifest=normalized_manifest,
        source=dict(source),
        dependency_constraints=dependency_constraints,
        version=version,
        compatibility=compatibility,
        metadata=candidate_metadata,
    )


def _candidate_metadata(manifest: RuntimePackageManifest) -> dict[str, Any]:
    raw = manifest.metadata.get(PACKAGE_CANDIDATE_METADATA_KEY, {})
    return dict(raw) if isinstance(raw, Mapping) else {}


def _normalized_dependency_constraints(
    manifest: RuntimePackageManifest,
    candidate_metadata: Mapping[str, Any],
) -> tuple[RuntimePackageDependencyConstraint, ...]:
    constraints: list[RuntimePackageDependencyConstraint] = [
        RuntimePackageDependencyConstraint(
            package_name=dependency,
            kind="legacy",
        )
        for dependency in manifest.dependencies
    ]
    structured_dependencies = candidate_metadata.get("dependencies", ())
    if not isinstance(structured_dependencies, Sequence) or isinstance(structured_dependencies, (str, bytes)):
        return tuple(constraints)
    for raw_dependency in structured_dependencies:
        if not isinstance(raw_dependency, Mapping):
            raise ValueError(
                f"Structured package dependency for '{manifest.name}' must be a mapping"
            )
        package_name = _normalize_optional_string(
            raw_dependency.get("package_name") or raw_dependency.get("name")
        )
        if package_name is None:
            raise ValueError(
                f"Structured package dependency for '{manifest.name}' must declare package_name"
            )
        version_range = raw_dependency.get("version_range", {})
        if version_range is not None and not isinstance(version_range, Mapping):
            raise ValueError(
                f"Structured package dependency for '{manifest.name}' has invalid version_range"
            )
        constraints.append(
            RuntimePackageDependencyConstraint(
                package_name=package_name,
                candidate_id=_normalize_optional_string(raw_dependency.get("candidate_id")),
                version=_normalize_optional_string(raw_dependency.get("version")),
                minimum_version=_normalize_optional_string(
                    raw_dependency.get("minimum_version")
                    or version_range.get("minimum_version")
                ),
                maximum_version=_normalize_optional_string(
                    raw_dependency.get("maximum_version")
                    or version_range.get("maximum_version")
                ),
                include_minimum=bool(
                    raw_dependency.get(
                        "include_minimum",
                        version_range.get("include_minimum", True),
                    )
                ),
                include_maximum=bool(
                    raw_dependency.get(
                        "include_maximum",
                        version_range.get("include_maximum", False),
                    )
                ),
                kind="structured",
                metadata={
                    key: value
                    for key, value in raw_dependency.items()
                    if key
                    not in {
                        "package_name",
                        "name",
                        "candidate_id",
                        "version",
                        "minimum_version",
                        "maximum_version",
                        "include_minimum",
                        "include_maximum",
                        "version_range",
                    }
                },
            )
        )
    return tuple(constraints)


def _resolve_package(
    package_name: str,
    *,
    distribution: str,
    catalog_by_name: Mapping[str, tuple[RuntimePackageCandidateDescriptor, ...]],
    selected: dict[str, RuntimePackageCandidateDescriptor],
    constraints_by_package: dict[str, list[_ResolutionRequirement]],
    stack: tuple[str, ...],
    on_success: Callable[[], RuntimePackageResolutionDiagnostic | None],
) -> RuntimePackageResolutionDiagnostic | None:
    if package_name in stack:
        cycle_start = stack.index(package_name)
        cycle_path = stack[cycle_start:] + (package_name,)
        return RuntimePackageResolutionDiagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="runtime_package_cyclic_dependency",
            message=(
                f"Package resolution detected a cyclic dependency: {' -> '.join(cycle_path)}"
            ),
            package_name=package_name,
            candidate_id=(selected.get(package_name).candidate_id if package_name in selected else None),
            details={
                "cycle_members": list(cycle_path[:-1]),
                "cycle_path": list(cycle_path),
                "constraints": [
                    requirement.to_metadata()
                    for requirement in constraints_by_package.get(package_name, ())
                ],
            },
        )

    requirements = tuple(constraints_by_package.get(package_name, ()))
    existing = selected.get(package_name)
    if existing is not None:
        if _candidate_satisfies(existing, requirements, distribution):
            return on_success()
        return _constraint_failure(
            package_name=package_name,
            requirements=requirements,
            candidates=catalog_by_name.get(package_name, ()),
            distribution=distribution,
        )

    candidates = catalog_by_name.get(package_name, ())
    if not candidates:
        return _missing_package_failure(
            package_name=package_name,
            requirements=requirements,
        )

    matching = [
        candidate
        for candidate in candidates
        if _candidate_satisfies(candidate, requirements, distribution)
    ]
    if not matching:
        return _constraint_failure(
            package_name=package_name,
            requirements=requirements,
            candidates=candidates,
            distribution=distribution,
        )

    branch_failures: list[RuntimePackageResolutionDiagnostic] = []
    for candidate in matching:
        selected_snapshot = dict(selected)
        constraints_snapshot = {
            name: list(entries)
            for name, entries in constraints_by_package.items()
        }
        selected[package_name] = candidate
        failure = _resolve_candidate_dependencies(
            candidate=candidate,
            dependency_index=0,
            distribution=distribution,
            catalog_by_name=catalog_by_name,
            selected=selected,
            constraints_by_package=constraints_by_package,
            stack=stack + (package_name,),
            on_success=on_success,
        )
        if failure is None:
            return None
        branch_failures.append(failure)
        selected.clear()
        selected.update(selected_snapshot)
        constraints_by_package.clear()
        constraints_by_package.update(
            {
                name: list(entries)
                for name, entries in constraints_snapshot.items()
            }
        )

    return branch_failures[0]


def _resolve_candidate_dependencies(
    *,
    candidate: RuntimePackageCandidateDescriptor,
    dependency_index: int,
    distribution: str,
    catalog_by_name: Mapping[str, tuple[RuntimePackageCandidateDescriptor, ...]],
    selected: dict[str, RuntimePackageCandidateDescriptor],
    constraints_by_package: dict[str, list[_ResolutionRequirement]],
    stack: tuple[str, ...],
    on_success: Callable[[], RuntimePackageResolutionDiagnostic | None],
) -> RuntimePackageResolutionDiagnostic | None:
    if dependency_index >= len(candidate.dependency_constraints):
        return on_success()
    dependency = candidate.dependency_constraints[dependency_index]
    constraints_by_package.setdefault(dependency.package_name, []).append(
        _ResolutionRequirement(
            constraint=dependency,
            source="dependency",
            requester=candidate.package_name,
            requester_candidate_id=candidate.candidate_id,
        )
    )
    return _resolve_package(
        dependency.package_name,
        distribution=distribution,
        catalog_by_name=catalog_by_name,
        selected=selected,
        constraints_by_package=constraints_by_package,
        stack=stack,
        on_success=lambda: _resolve_candidate_dependencies(
            candidate=candidate,
            dependency_index=dependency_index + 1,
            distribution=distribution,
            catalog_by_name=catalog_by_name,
            selected=selected,
            constraints_by_package=constraints_by_package,
            stack=stack,
            on_success=on_success,
        ),
    )


def _catalog_diagnostics(
    catalog_by_name: Mapping[str, tuple[RuntimePackageCandidateDescriptor, ...]],
) -> tuple[RuntimePackageResolutionDiagnostic, ...]:
    diagnostics: list[RuntimePackageResolutionDiagnostic] = []
    for package_name, candidates in catalog_by_name.items():
        duplicates: dict[str, list[RuntimePackageCandidateDescriptor]] = defaultdict(list)
        for candidate in candidates:
            duplicates[candidate.candidate_id].append(candidate)
        for candidate_id, entries in duplicates.items():
            if len(entries) < 2:
                continue
            diagnostics.append(
                RuntimePackageResolutionDiagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    code="runtime_package_duplicate_candidate_id",
                    message=(
                        f"Package catalog defines duplicate candidate_id '{candidate_id}' "
                        f"for '{package_name}'"
                    ),
                    package_name=package_name,
                    candidate_id=candidate_id,
                    details={
                        "duplicate_candidates": [
                            candidate.to_metadata() for candidate in entries
                        ],
                    },
                )
            )
    return tuple(diagnostics)


def _missing_package_failure(
    *,
    package_name: str,
    requirements: Sequence[_ResolutionRequirement],
) -> RuntimePackageResolutionDiagnostic:
    return RuntimePackageResolutionDiagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="runtime_package_missing",
        message=f"Package resolution could not find any candidate for '{package_name}'",
        package_name=package_name,
        details={
            "constraints": [requirement.to_metadata() for requirement in requirements],
        },
    )


def _constraint_failure(
    *,
    package_name: str,
    requirements: Sequence[_ResolutionRequirement],
    candidates: Sequence[RuntimePackageCandidateDescriptor],
    distribution: str,
) -> RuntimePackageResolutionDiagnostic:
    compatible = [candidate for candidate in candidates if candidate.supports_distribution(distribution)]
    if not compatible:
        return RuntimePackageResolutionDiagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="runtime_package_incompatible_candidate",
            message=(
                f"Package resolution found candidates for '{package_name}', "
                f"but none are compatible with distribution '{distribution}'"
            ),
            package_name=package_name,
            details={
                "distribution": distribution,
                "constraints": [requirement.to_metadata() for requirement in requirements],
                "available_candidates": [
                    candidate.to_metadata() for candidate in candidates
                ],
            },
        )

    per_requirement_matches = [
        (
            requirement,
            [
                candidate
                for candidate in compatible
                if requirement.constraint.matches(candidate)
            ],
        )
        for requirement in requirements
    ]
    if requirements and all(matches for _, matches in per_requirement_matches):
        return RuntimePackageResolutionDiagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="runtime_package_conflicting_constraints",
            message=(
                f"Package resolution could not satisfy all constraints for '{package_name}' "
                "with one concrete candidate"
            ),
            package_name=package_name,
            details={
                "distribution": distribution,
                "constraints": [
                    requirement.to_metadata()
                    for requirement, _ in per_requirement_matches
                ],
                "available_candidates": [
                    candidate.to_metadata() for candidate in compatible
                ],
                "constraint_matches": [
                    {
                        "constraint": requirement.to_metadata(),
                        "matching_candidate_ids": [
                            candidate.candidate_id for candidate in matches
                        ],
                    }
                    for requirement, matches in per_requirement_matches
                ],
            },
        )

    return RuntimePackageResolutionDiagnostic(
        severity=DiagnosticSeverity.ERROR,
        code="runtime_package_incompatible_candidate",
        message=(
            f"Package resolution found candidates for '{package_name}', "
            "but none satisfy the active constraints"
        ),
        package_name=package_name,
        details={
            "distribution": distribution,
            "constraints": [requirement.to_metadata() for requirement in requirements],
            "available_candidates": [candidate.to_metadata() for candidate in compatible],
        },
    )


def _candidate_satisfies(
    candidate: RuntimePackageCandidateDescriptor,
    requirements: Sequence[_ResolutionRequirement],
    distribution: str,
) -> bool:
    return candidate.supports_distribution(distribution) and all(
        requirement.constraint.matches(candidate)
        for requirement in requirements
    )


def _candidate_sort_key(candidate: RuntimePackageCandidateDescriptor) -> tuple[int, str, str]:
    origin = str(candidate.source.get("origin", "external")).strip()
    origin_rank = 0 if origin == "first_party" else 1
    return (origin_rank, candidate.package_name, candidate.candidate_id)


def _serialize_manifest_summary(manifest: RuntimePackageManifest) -> dict[str, Any]:
    summary = {
        "name": manifest.name,
        "role": manifest.role,
        "description": manifest.description,
        "dependencies": list(manifest.dependencies),
        "invocation_providers": list(manifest.metadata.get("invocation_providers", ())),
    }
    metadata = dict(manifest.metadata)
    for key in (
        "package_pattern",
        "baseline_dependencies",
        "invocation_providers",
        "provider_registration_path",
        "provider_registration_order",
        "provider_package_ordering",
        "capabilities",
        "capability_registration_path",
        "context_contributors",
        "context_contributor_registration_path",
        "context_contributor_stages",
        "package_candidate",
        "reference_kind",
        "shared_surface_family",
        "intended_profiles",
        "shared_surfaces",
        "tool_ids",
        "agent_ids",
        "skill_ids",
        "scenario_profile",
        "recommended_distribution",
        "recommended_first_party_packages",
        "shared_package_dependencies",
        "expected_tools",
        "expected_agents",
        "expected_skills",
        "default_boundaries",
        "app_owned_wiring",
        "host_assumptions",
        "permission_policy_posture",
        "profile_prompt_fragments",
        "staged_scope_boundaries",
        "notes",
    ):
        if key in metadata:
            value = metadata[key]
            if isinstance(value, tuple):
                summary[key] = list(value)
            elif isinstance(value, list):
                summary[key] = list(value)
            elif isinstance(value, dict):
                summary[key] = dict(value)
            else:
                summary[key] = value
    return summary


def _stable_unique_names(values: Iterable[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in values:
        package_name = _normalize_optional_string(raw)
        if package_name is None or package_name in seen:
            continue
        seen.add(package_name)
        ordered.append(package_name)
    return tuple(ordered)


def _compare_versions(left: str, right: str) -> int:
    left_parts = _version_parts(left)
    right_parts = _version_parts(right)
    for left_part, right_part in zip_longest(left_parts, right_parts, fillvalue=(0, 0)):
        if left_part == right_part:
            continue
        return -1 if left_part < right_part else 1
    return 0


def _version_parts(value: str) -> tuple[tuple[int, int | str], ...]:
    parts: list[tuple[int, int | str]] = []
    for token in re.split(r"[.\-_+]", str(value).strip()):
        if not token:
            continue
        if token.isdigit():
            parts.append((0, int(token)))
            continue
        parts.append((1, token.lower()))
    return tuple(parts)


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _require_non_empty(value: Any, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


__all__ = [
    "PACKAGE_CANDIDATE_METADATA_KEY",
    "REQUESTED_PACKAGES_PATH",
    "RuntimePackageCandidateDescriptor",
    "RuntimePackageCatalog",
    "RuntimePackageDependencyConstraint",
    "RuntimePackageRequest",
    "RuntimePackageResolutionDiagnostic",
    "RuntimePackageResolutionError",
    "RuntimePackageResolutionReport",
    "build_runtime_package_catalog",
    "build_runtime_package_request",
    "resolve_runtime_package_graph",
]
