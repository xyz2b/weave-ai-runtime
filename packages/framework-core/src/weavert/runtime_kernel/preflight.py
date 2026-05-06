from __future__ import annotations

import inspect
import os
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol

from ..turn_engine.models import NormalizedModelCapabilities
from .config import ModelProviderBinding, ModelRouteBinding, RuntimeConfig, _resolve_route_default_model


class ModelRoutePreflightFailureClass(StrEnum):
    NONE = "none"
    UNKNOWN_ROUTE = "unknown_route"
    MISSING_PROVIDER_BINDING = "missing_provider_binding"
    MISSING_ENV = "missing_env"
    PROVIDER_PROBE_FAILED = "provider_probe_failed"


@dataclass(frozen=True, slots=True)
class ModelRouteEnvironmentRequirement:
    name: str
    required: bool = True
    present: bool = False
    kind: str = "generic"
    source: str = "metadata"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "kind", _coerce_optional_string(self.kind) or "generic")
        object.__setattr__(self, "source", _coerce_optional_string(self.source) or "metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "required": self.required,
            "present": self.present,
            "kind": self.kind,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ModelRoutePreflightDiagnostic:
    code: str
    message: str
    severity: str = "info"
    failure_class: ModelRoutePreflightFailureClass | str = ModelRoutePreflightFailureClass.NONE
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_non_empty(self.code, "code"))
        object.__setattr__(self, "message", _require_non_empty(self.message, "message"))
        object.__setattr__(self, "severity", _coerce_optional_string(self.severity) or "info")
        object.__setattr__(self, "failure_class", _coerce_failure_class(self.failure_class))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "failure_class": self.failure_class.value,
        }
        if self.metadata:
            payload["metadata"] = deepcopy(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class ModelRoutePreflightProbeRequest:
    route_name: str
    provider_name: str | None = None
    provider_binding: str | None = None
    resolved_default_model: str | None = None
    environment: tuple[ModelRouteEnvironmentRequirement, ...] = ()
    route_metadata: dict[str, Any] = field(default_factory=dict)
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "route_name", _require_non_empty(self.route_name, "route_name"))
        object.__setattr__(self, "provider_name", _coerce_optional_string(self.provider_name))
        object.__setattr__(self, "provider_binding", _coerce_optional_string(self.provider_binding))
        object.__setattr__(self, "resolved_default_model", _coerce_optional_string(self.resolved_default_model))
        object.__setattr__(self, "environment", tuple(self.environment))
        object.__setattr__(self, "route_metadata", deepcopy(dict(self.route_metadata)))
        object.__setattr__(self, "provider_metadata", deepcopy(dict(self.provider_metadata)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_name": self.route_name,
            "provider_name": self.provider_name,
            "provider_binding": self.provider_binding,
            "resolved_default_model": self.resolved_default_model,
            "environment": [entry.to_dict() for entry in self.environment],
            "route_metadata": deepcopy(self.route_metadata),
            "provider_metadata": deepcopy(self.provider_metadata),
        }


@dataclass(frozen=True, slots=True)
class ModelRoutePreflightProbeResult:
    ready: bool = True
    failure_class: ModelRoutePreflightFailureClass | str = ModelRoutePreflightFailureClass.NONE
    diagnostics: tuple[ModelRoutePreflightDiagnostic, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_class", _coerce_failure_class(self.failure_class))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ready": self.ready,
            "failure_class": self.failure_class.value,
            "diagnostics": [entry.to_dict() for entry in self.diagnostics],
        }
        if self.metadata:
            payload["metadata"] = deepcopy(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class ModelRoutePreflightProbeReport:
    requested: bool = False
    attempted: bool = False
    supported: bool = False
    result: ModelRoutePreflightProbeResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "attempted": self.attempted,
            "supported": self.supported,
            "result": self.result.to_dict() if self.result is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ModelRoutePreflightReport:
    requested_route: str | None
    resolved_route: str | None
    used_default_route: bool = False
    ready: bool = False
    failure_class: ModelRoutePreflightFailureClass | str = ModelRoutePreflightFailureClass.NONE
    provider_name: str | None = None
    provider_binding: str | None = None
    provider_client_type: str | None = None
    resolved_default_model: str | None = None
    environment: tuple[ModelRouteEnvironmentRequirement, ...] = ()
    capability_hints: dict[str, Any] = field(default_factory=dict)
    route_metadata: dict[str, Any] = field(default_factory=dict)
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[ModelRoutePreflightDiagnostic, ...] = ()
    probe: ModelRoutePreflightProbeReport = field(default_factory=ModelRoutePreflightProbeReport)

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested_route", _coerce_optional_string(self.requested_route))
        object.__setattr__(self, "resolved_route", _coerce_optional_string(self.resolved_route))
        object.__setattr__(self, "failure_class", _coerce_failure_class(self.failure_class))
        object.__setattr__(self, "provider_name", _coerce_optional_string(self.provider_name))
        object.__setattr__(self, "provider_binding", _coerce_optional_string(self.provider_binding))
        object.__setattr__(self, "provider_client_type", _coerce_optional_string(self.provider_client_type))
        object.__setattr__(self, "resolved_default_model", _coerce_optional_string(self.resolved_default_model))
        object.__setattr__(self, "environment", tuple(self.environment))
        object.__setattr__(self, "capability_hints", deepcopy(dict(self.capability_hints)))
        object.__setattr__(self, "route_metadata", deepcopy(dict(self.route_metadata)))
        object.__setattr__(self, "provider_metadata", deepcopy(dict(self.provider_metadata)))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_route": self.requested_route,
            "resolved_route": self.resolved_route,
            "used_default_route": self.used_default_route,
            "ready": self.ready,
            "failure_class": self.failure_class.value,
            "provider_name": self.provider_name,
            "provider_binding": self.provider_binding,
            "provider_client_type": self.provider_client_type,
            "resolved_default_model": self.resolved_default_model,
            "environment": [entry.to_dict() for entry in self.environment],
            "capability_hints": deepcopy(self.capability_hints),
            "route_metadata": deepcopy(self.route_metadata),
            "provider_metadata": deepcopy(self.provider_metadata),
            "diagnostics": [entry.to_dict() for entry in self.diagnostics],
            "probe": self.probe.to_dict(),
        }


class ModelRoutePreflightProbeProvider(Protocol):
    def preflight_model_route_probe(
        self,
        request: ModelRoutePreflightProbeRequest,
    ) -> ModelRoutePreflightProbeResult | Mapping[str, Any] | Any: ...


async def preflight_model_route(
    config: RuntimeConfig,
    *,
    route_name: str | None = None,
    deeper_probe: bool = False,
) -> ModelRoutePreflightReport:
    requested_route = _coerce_optional_string(route_name)
    resolved_route = requested_route or _coerce_optional_string(config.default_model_route)
    used_default_route = requested_route is None
    diagnostics: list[ModelRoutePreflightDiagnostic] = []

    if resolved_route is None:
        diagnostics.append(
            ModelRoutePreflightDiagnostic(
                code="default_route_missing",
                message="Runtime has no default model route configured for preflight.",
                severity="error",
                failure_class=ModelRoutePreflightFailureClass.UNKNOWN_ROUTE,
            )
        )
        return ModelRoutePreflightReport(
            requested_route=requested_route,
            resolved_route=None,
            used_default_route=used_default_route,
            ready=False,
            failure_class=ModelRoutePreflightFailureClass.UNKNOWN_ROUTE,
            diagnostics=tuple(diagnostics),
            probe=ModelRoutePreflightProbeReport(requested=deeper_probe, attempted=False, supported=False),
        )

    route_binding = config.model_routes.get(resolved_route)
    if route_binding is None:
        diagnostics.append(
            ModelRoutePreflightDiagnostic(
                code="unknown_route",
                message=f"Model route '{resolved_route}' is not configured in this runtime.",
                severity="error",
                failure_class=ModelRoutePreflightFailureClass.UNKNOWN_ROUTE,
                metadata={"requested_route": requested_route, "resolved_route": resolved_route},
            )
        )
        return ModelRoutePreflightReport(
            requested_route=requested_route,
            resolved_route=resolved_route,
            used_default_route=used_default_route,
            ready=False,
            failure_class=ModelRoutePreflightFailureClass.UNKNOWN_ROUTE,
            diagnostics=tuple(diagnostics),
            probe=ModelRoutePreflightProbeReport(requested=deeper_probe, attempted=False, supported=False),
        )

    provider_binding_name = _coerce_optional_string(route_binding.provider_binding)
    provider_binding = (
        config.model_providers.get(provider_binding_name)
        if provider_binding_name is not None
        else None
    )
    provider_metadata = dict(provider_binding.metadata) if provider_binding is not None else {}
    route_metadata = dict(route_binding.metadata)
    merged_metadata = {
        **provider_metadata,
        **route_metadata,
        "provider_binding": provider_binding_name,
    }
    resolved_default_model = _resolve_route_default_model(route_binding.default_model, merged_metadata)
    environment = _collect_environment_requirements(
        route_binding=route_binding,
        provider_binding=provider_binding,
    )
    capabilities = _capabilities_to_dict(
        route_binding.capabilities or (provider_binding.capabilities if provider_binding is not None else None)
    )
    provider_name = (
        _coerce_optional_string(route_binding.provider_name)
        or (
            _coerce_optional_string(provider_binding.provider_name)
            if provider_binding is not None
            else None
        )
    )
    client = route_binding.client or (provider_binding.client if provider_binding is not None else None)
    provider_client_type = _client_type_name(client)

    failure_class = ModelRoutePreflightFailureClass.NONE
    if client is None:
        failure_class = ModelRoutePreflightFailureClass.MISSING_PROVIDER_BINDING
        diagnostics.append(
            ModelRoutePreflightDiagnostic(
                code="missing_provider_binding",
                message=(
                    f"Model route '{resolved_route}' does not resolve a provider-backed model client."
                ),
                severity="error",
                failure_class=failure_class,
                metadata={
                    "resolved_route": resolved_route,
                    "provider_binding": provider_binding_name,
                },
            )
        )

    missing_required_env = [entry.name for entry in environment if entry.required and not entry.present]
    if missing_required_env:
        if failure_class is ModelRoutePreflightFailureClass.NONE:
            failure_class = ModelRoutePreflightFailureClass.MISSING_ENV
        diagnostics.append(
            ModelRoutePreflightDiagnostic(
                code="missing_environment",
                message=(
                    "Model route '"
                    f"{resolved_route}' is missing required environment variables: "
                    f"{', '.join(missing_required_env)}"
                ),
                severity="error",
                failure_class=ModelRoutePreflightFailureClass.MISSING_ENV,
                metadata={
                    "resolved_route": resolved_route,
                    "missing": missing_required_env,
                },
            )
        )

    if resolved_default_model is None:
        diagnostics.append(
            ModelRoutePreflightDiagnostic(
                code="default_model_unresolved",
                message=(
                    f"Model route '{resolved_route}' does not resolve a default model; callers must "
                    "supply one per request."
                ),
                severity="warning",
                metadata={"resolved_route": resolved_route},
            )
        )

    ready = failure_class is ModelRoutePreflightFailureClass.NONE
    probe_supported = callable(getattr(client, "preflight_model_route_probe", None)) if client is not None else False
    probe_report = ModelRoutePreflightProbeReport(
        requested=deeper_probe,
        attempted=False,
        supported=probe_supported,
    )

    if deeper_probe and ready and probe_supported and client is not None:
        probe_result = await _run_provider_probe(
            client=client,
            request=ModelRoutePreflightProbeRequest(
                route_name=resolved_route,
                provider_name=provider_name,
                provider_binding=provider_binding_name,
                resolved_default_model=resolved_default_model,
                environment=environment,
                route_metadata=route_metadata,
                provider_metadata=provider_metadata,
            ),
        )
        probe_report = ModelRoutePreflightProbeReport(
            requested=True,
            attempted=True,
            supported=True,
            result=probe_result,
        )
        if not probe_result.ready:
            ready = False
            if failure_class is ModelRoutePreflightFailureClass.NONE:
                failure_class = (
                    probe_result.failure_class
                    if probe_result.failure_class is not ModelRoutePreflightFailureClass.NONE
                    else ModelRoutePreflightFailureClass.PROVIDER_PROBE_FAILED
                )
            diagnostics.extend(probe_result.diagnostics)

    return ModelRoutePreflightReport(
        requested_route=requested_route,
        resolved_route=resolved_route,
        used_default_route=used_default_route,
        ready=ready,
        failure_class=failure_class,
        provider_name=provider_name,
        provider_binding=provider_binding_name,
        provider_client_type=provider_client_type,
        resolved_default_model=resolved_default_model,
        environment=environment,
        capability_hints=capabilities,
        route_metadata=route_metadata,
        provider_metadata=provider_metadata,
        diagnostics=tuple(diagnostics),
        probe=probe_report,
    )


async def _run_provider_probe(
    *,
    client: Any,
    request: ModelRoutePreflightProbeRequest,
) -> ModelRoutePreflightProbeResult:
    probe = getattr(client, "preflight_model_route_probe", None)
    if not callable(probe):
        return ModelRoutePreflightProbeResult(ready=True)
    try:
        result = probe(request)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:  # pragma: no cover - defensive boundary
        return ModelRoutePreflightProbeResult(
            ready=False,
            failure_class=ModelRoutePreflightFailureClass.PROVIDER_PROBE_FAILED,
            diagnostics=(
                ModelRoutePreflightDiagnostic(
                    code="provider_probe_failed",
                    message=(
                        f"Provider-specific preflight probe for route '{request.route_name}' failed: {exc}"
                    ),
                    severity="error",
                    failure_class=ModelRoutePreflightFailureClass.PROVIDER_PROBE_FAILED,
                    metadata={"error_type": type(exc).__name__},
                ),
            ),
        )
    coerced = _coerce_probe_result(result)
    if not coerced.ready and coerced.failure_class is ModelRoutePreflightFailureClass.NONE:
        return ModelRoutePreflightProbeResult(
            ready=False,
            failure_class=ModelRoutePreflightFailureClass.PROVIDER_PROBE_FAILED,
            diagnostics=coerced.diagnostics,
            metadata=coerced.metadata,
        )
    return coerced


def _coerce_probe_result(value: Any) -> ModelRoutePreflightProbeResult:
    if isinstance(value, ModelRoutePreflightProbeResult):
        return value
    if isinstance(value, Mapping):
        diagnostics = tuple(_coerce_probe_diagnostic(item) for item in value.get("diagnostics", ()))
        return ModelRoutePreflightProbeResult(
            ready=bool(value.get("ready", True)),
            failure_class=_coerce_failure_class(value.get("failure_class")),
            diagnostics=diagnostics,
            metadata=_coerce_mapping(value.get("metadata")),
        )
    if value is None:
        return ModelRoutePreflightProbeResult(ready=True)
    raise TypeError("Provider preflight probe must return a mapping or ModelRoutePreflightProbeResult")


def _coerce_probe_diagnostic(value: Any) -> ModelRoutePreflightDiagnostic:
    if isinstance(value, ModelRoutePreflightDiagnostic):
        return value
    if isinstance(value, Mapping):
        return ModelRoutePreflightDiagnostic(
            code=_coerce_optional_string(value.get("code")) or "provider_probe",
            message=_coerce_optional_string(value.get("message")) or "Provider probe reported a diagnostic.",
            severity=_coerce_optional_string(value.get("severity")) or "info",
            failure_class=_coerce_failure_class(value.get("failure_class")),
            metadata=_coerce_mapping(value.get("metadata")),
        )
    raise TypeError("Provider preflight diagnostics must be mappings or ModelRoutePreflightDiagnostic")


def _collect_environment_requirements(
    *,
    route_binding: ModelRouteBinding,
    provider_binding: ModelProviderBinding | None,
) -> tuple[ModelRouteEnvironmentRequirement, ...]:
    records: dict[str, dict[str, Any]] = {}
    provider_metadata = dict(provider_binding.metadata) if provider_binding is not None else {}
    route_metadata = dict(route_binding.metadata)

    def register(*, name: str | None, required: bool, kind: str, source: str) -> None:
        normalized_name = _coerce_optional_string(name)
        if normalized_name is None:
            return
        existing = records.get(normalized_name)
        if existing is None:
            records[normalized_name] = {
                "required": required,
                "kind": kind,
                "sources": [source],
            }
            return
        existing["required"] = bool(existing["required"] or required)
        if kind != "generic" and existing.get("kind") == "generic":
            existing["kind"] = kind
        sources = existing.setdefault("sources", [])
        if source not in sources:
            sources.append(source)

    register(
        name=_coerce_optional_string(provider_metadata.get("credential_env")),
        required=True,
        kind="credential",
        source="provider_metadata",
    )
    register(
        name=_coerce_optional_string(provider_metadata.get("base_url_env")),
        required=False,
        kind="base_url",
        source="provider_metadata",
    )
    register(
        name=_coerce_optional_string(provider_metadata.get("model_env")),
        required=False,
        kind="model",
        source="provider_metadata",
    )
    register(
        name=_coerce_optional_string(route_metadata.get("default_model_env")),
        required=False,
        kind="default_model",
        source="route_metadata",
    )
    for env_name in _coerce_env_names(provider_metadata.get("required_envs")):
        register(name=env_name, required=True, kind="required", source="provider_metadata")
    for env_name in _coerce_env_names(provider_metadata.get("required_env")):
        register(name=env_name, required=True, kind="required", source="provider_metadata")
    for env_name in _coerce_env_names(provider_metadata.get("optional_envs")):
        register(name=env_name, required=False, kind="optional", source="provider_metadata")
    for env_name in _coerce_env_names(provider_metadata.get("optional_env")):
        register(name=env_name, required=False, kind="optional", source="provider_metadata")
    for env_name in _coerce_env_names(route_metadata.get("required_envs")):
        register(name=env_name, required=True, kind="required", source="route_metadata")
    for env_name in _coerce_env_names(route_metadata.get("required_env")):
        register(name=env_name, required=True, kind="required", source="route_metadata")
    for env_name in _coerce_env_names(route_metadata.get("optional_envs")):
        register(name=env_name, required=False, kind="optional", source="route_metadata")
    for env_name in _coerce_env_names(route_metadata.get("optional_env")):
        register(name=env_name, required=False, kind="optional", source="route_metadata")

    requirements: list[ModelRouteEnvironmentRequirement] = []
    for name, record in records.items():
        requirements.append(
            ModelRouteEnvironmentRequirement(
                name=name,
                required=bool(record.get("required")),
                present=bool(os.environ.get(name, "").strip()),
                kind=_coerce_optional_string(record.get("kind")) or "generic",
                source=",".join(str(item) for item in record.get("sources", ()) if str(item).strip()),
            )
        )
    return tuple(requirements)


def _coerce_env_names(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = _coerce_optional_string(value)
        return (normalized,) if normalized is not None else ()
    if isinstance(value, Mapping):
        return ()
    normalized: list[str] = []
    try:
        iterator = iter(value)
    except TypeError:
        return ()
    for item in iterator:
        name = _coerce_optional_string(item)
        if name is not None and name not in normalized:
            normalized.append(name)
    return tuple(normalized)


def _capabilities_to_dict(capabilities: NormalizedModelCapabilities | None) -> dict[str, Any]:
    if capabilities is None:
        return {}
    if is_dataclass(capabilities):
        return {
            field_info.name: deepcopy(getattr(capabilities, field_info.name))
            for field_info in fields(capabilities)
        }
    return {}


def _client_type_name(client: Any) -> str | None:
    if client is None:
        return None
    client_type = type(client)
    module = _coerce_optional_string(getattr(client_type, "__module__", None)) or "builtins"
    qualname = _coerce_optional_string(getattr(client_type, "__qualname__", None)) or client_type.__name__
    return f"{module}.{qualname}"


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): deepcopy(item) for key, item in value.items()}


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_failure_class(
    value: ModelRoutePreflightFailureClass | str | None,
) -> ModelRoutePreflightFailureClass:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return ModelRoutePreflightFailureClass.NONE
    try:
        return ModelRoutePreflightFailureClass(normalized)
    except ValueError:
        return ModelRoutePreflightFailureClass.PROVIDER_PROBE_FAILED


def _require_non_empty(value: Any, field_name: str) -> str:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


__all__ = [
    "ModelRouteEnvironmentRequirement",
    "ModelRoutePreflightDiagnostic",
    "ModelRoutePreflightFailureClass",
    "ModelRoutePreflightProbeProvider",
    "ModelRoutePreflightProbeReport",
    "ModelRoutePreflightProbeRequest",
    "ModelRoutePreflightProbeResult",
    "ModelRoutePreflightReport",
    "preflight_model_route",
]
