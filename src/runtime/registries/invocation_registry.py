from __future__ import annotations

from typing import Sequence

from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..definitions import InvocationDefinition, InvocationProvider, InvocationResolutionContext, ResolvedInvocationCatalog


class InvocationRegistry:
    def __init__(self, providers: Sequence[InvocationProvider] = ()) -> None:
        self._providers: dict[str, InvocationProvider] = {}
        self._provider_diagnostics: list[Diagnostic] = []
        for provider in providers:
            self.register_provider(provider)

    def register_provider(self, provider: InvocationProvider) -> InvocationProvider:
        existing = self._providers.get(provider.name)
        if existing is not None and existing is not provider:
            self._provider_diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    code="invocation_provider_replaced",
                    message=(
                        f"Invocation provider '{provider.name}' replaced an existing provider registration."
                    ),
                    definition_type="invocation_provider",
                    location=provider.name,
                )
            )
        self._providers[provider.name] = provider
        return provider

    def remove_provider(self, name: str) -> InvocationProvider | None:
        return self._providers.pop(name, None)

    def providers(self) -> tuple[InvocationProvider, ...]:
        return tuple(self._providers.values())

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
        for provider in self._providers.values():
            if context is not None and hasattr(provider, "list_invocations_for_context"):
                definitions = provider.list_invocations_for_context(context)
            else:
                definitions = provider.list_invocations()
            for definition in definitions:
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


__all__ = ["InvocationRegistry"]
