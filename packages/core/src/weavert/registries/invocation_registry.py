from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..definitions import InvocationDefinition, InvocationProvider, InvocationResolutionContext, ResolvedInvocationCatalog
from ..package_system.protocols import PackageOwnership


@dataclass(frozen=True, slots=True)
class InvocationProviderRegistration:
    name: str
    provider: InvocationProvider
    origin: str
    owner: PackageOwnership | None = None
    order: int = 0
    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name).strip())
        object.__setattr__(self, "origin", str(self.origin).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))


class InvocationRegistry:
    def __init__(self, providers: Sequence[InvocationProvider] = ()) -> None:
        self._providers: dict[str, InvocationProviderRegistration] = {}
        self._provider_diagnostics: list[Diagnostic] = []
        self._registration_sequence = 0
        for provider in providers:
            self.register_provider(provider)

    def register_provider(
        self,
        provider: InvocationProvider,
        *,
        origin: str = "runtime",
        owner: PackageOwnership | None = None,
        order: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> InvocationProvider:
        provider_name = str(getattr(provider, "name", "")).strip()
        if not provider_name:
            raise ValueError("Invocation providers must declare a non-empty name")
        registration = InvocationProviderRegistration(
            name=provider_name,
            provider=provider,
            origin=origin,
            owner=owner,
            order=order,
            sequence=self._registration_sequence,
            metadata=dict(metadata or {}),
        )
        self._registration_sequence += 1
        existing = self._providers.get(provider_name)
        if existing is not None and existing.provider is not provider:
            self._provider_diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    code="invocation_provider_replaced",
                    message=(
                        f"Invocation provider '{provider_name}' replaced an existing provider registration."
                    ),
                    definition_type="invocation_provider",
                    source=registration.origin,
                    location=provider_name,
                    details={
                        "replaced_origin": existing.origin,
                        "replacement_origin": registration.origin,
                        "replaced_owner": _serialize_owner(existing.owner),
                        "replacement_owner": _serialize_owner(registration.owner),
                        "replaced_registration_path": _registration_metadata_value(
                            existing.metadata,
                            "registration_path",
                        ),
                        "replacement_registration_path": _registration_metadata_value(
                            registration.metadata,
                            "registration_path",
                        ),
                        "replaced_provider_tier": _registration_metadata_value(
                            existing.metadata,
                            "provider_tier",
                        ),
                        "replacement_provider_tier": _registration_metadata_value(
                            registration.metadata,
                            "provider_tier",
                        ),
                    },
                )
            )
        self._providers[provider_name] = registration
        return provider

    def remove_provider(self, name: str) -> InvocationProvider | None:
        registration = self._providers.pop(name, None)
        return None if registration is None else registration.provider

    def providers(self) -> tuple[InvocationProvider, ...]:
        return tuple(record.provider for record in self.registrations())

    def registrations(self) -> tuple[InvocationProviderRegistration, ...]:
        return tuple(sorted(self._providers.values(), key=lambda record: record.sequence))

    def definitions(self) -> tuple[InvocationDefinition, ...]:
        definitions, _ = self._collect_definitions()
        return definitions

    def diagnostics(self) -> tuple[Diagnostic, ...]:
        _, diagnostics = self._collect_definitions()
        return diagnostics

    def _collect_definitions(
        self,
        context: InvocationResolutionContext | None = None,
    ) -> tuple[tuple[InvocationDefinition, ...], tuple[Diagnostic, ...]]:
        collected: dict[str, InvocationDefinition] = {}
        diagnostics = list(self._provider_diagnostics)
        for registration in self.registrations():
            provider = registration.provider
            if context is not None and hasattr(provider, "list_invocations_for_context"):
                definitions = provider.list_invocations_for_context(context)
            else:
                definitions = provider.list_invocations()
            for definition in definitions:
                definition = _annotate_provider_metadata(definition, registration)
                existing = collected.get(definition.name)
                if existing is None:
                    collected[definition.name] = definition
                    continue
                winner, diagnostic = _resolve_invocation_conflict(existing, definition)
                collected[definition.name] = winner
                if diagnostic is not None:
                    diagnostics.append(diagnostic)
        ordered = tuple(collected[name] for name in sorted(collected))
        return ordered, tuple(diagnostics)

    def resolve(self, context: InvocationResolutionContext) -> ResolvedInvocationCatalog:
        from ..invocation_catalog import resolve_invocation_catalog

        definitions, _ = self._collect_definitions(context)
        return resolve_invocation_catalog(definitions, context)


def _resolve_invocation_conflict(
    existing: InvocationDefinition,
    incoming: InvocationDefinition,
) -> tuple[InvocationDefinition, Diagnostic | None]:
    if incoming.origin.priority > existing.origin.priority:
        return incoming, Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="definition_shadowed",
            message=(
                f"Invocation '{incoming.name}' from {incoming.origin.source.value} overrides the "
                f"lower-priority definition from {existing.origin.source.value}."
            ),
            definition_type="invocation",
            source=incoming.origin.source.value,
            location=incoming.origin.label,
            details={"replaced": existing.origin.label},
        )
    if incoming.origin.priority < existing.origin.priority:
        return existing, Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="definition_skipped",
            message=(
                f"Skipped invocation '{incoming.name}' from {incoming.origin.source.value} "
                f"because a higher-priority definition already exists."
            ),
            definition_type="invocation",
            source=incoming.origin.source.value,
            location=incoming.origin.label,
            details={"kept": existing.origin.label},
        )
    if incoming.origin.label == existing.origin.label and incoming.source_kind == existing.source_kind:
        return incoming, None
    winner, loser = sorted((existing, incoming), key=_invocation_tiebreak_key)
    return winner, Diagnostic(
        severity=DiagnosticSeverity.WARNING,
        code="invocation_definition_conflict",
        message=(
            f"Conflicting invocation definitions for '{winner.name}' share the same priority; "
            f"keeping {winner.origin.label} and ignoring {loser.origin.label}."
        ),
        definition_type="invocation",
        source=winner.origin.source.value,
        location=winner.origin.label,
        details={"ignored": loser.origin.label},
    )


def _invocation_tiebreak_key(definition: InvocationDefinition) -> tuple[str, str, str]:
    target_name = definition.execution_policy.target_name if definition.execution_policy is not None else ""
    return (definition.origin.label, definition.source_kind.value, target_name)


def _serialize_owner(owner: PackageOwnership | None) -> dict[str, Any] | None:
    if owner is None:
        return None
    return {
        "package_name": owner.package_name,
        "package_role": owner.package_role,
        "surface": owner.surface,
        "metadata": dict(owner.metadata),
    }


def _annotate_provider_metadata(
    definition: InvocationDefinition,
    registration: InvocationProviderRegistration,
) -> InvocationDefinition:
    metadata = dict(definition.metadata)
    owner = _serialize_owner(registration.owner)
    registration_path = _registration_metadata_value(registration.metadata, "registration_path")
    provider_tier = _registration_metadata_value(registration.metadata, "provider_tier")
    registration_metadata = {
        "name": registration.name,
        "origin": registration.origin,
        "order": registration.order,
        "sequence": registration.sequence,
        "registration_path": registration_path,
        "provider_tier": provider_tier,
        "owner": owner,
        "metadata": dict(registration.metadata),
    }
    metadata["invocation_provider_registration"] = registration_metadata
    metadata["invocation_provider_name"] = registration.name
    metadata["invocation_provider_origin"] = registration.origin
    if registration_path:
        metadata["invocation_provider_registration_path"] = registration_path
    if provider_tier:
        metadata["invocation_provider_tier"] = provider_tier
    if owner is not None:
        metadata["invocation_provider_owner"] = owner
    return replace(definition, metadata=metadata)


def _registration_metadata_value(metadata: Mapping[str, Any], key: str) -> str:
    value = metadata.get(key)
    return "" if value is None else str(value)


__all__ = ["InvocationProviderRegistration", "InvocationRegistry"]
