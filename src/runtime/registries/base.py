from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Iterable, Protocol, TypeVar

from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..definitions import DefinitionOrigin
from ..errors import RegistryConflictError


class RegisteredDefinition(Protocol):
    name: str
    origin: DefinitionOrigin


T = TypeVar("T", bound=RegisteredDefinition)


@dataclass(frozen=True, slots=True)
class RegistryEntry(Generic[T]):
    definition: T

    @property
    def origin(self) -> DefinitionOrigin:
        return self.definition.origin


@dataclass(frozen=True, slots=True)
class RegistryRegistration(Generic[T]):
    action: str
    entry: RegistryEntry[T]
    replaced: RegistryEntry[T] | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


class DefinitionRegistry(Generic[T]):
    definition_type = "definition"

    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry[T]] = {}

    def _prepare_definition(
        self,
        definition: T,
    ) -> tuple[T, tuple[Diagnostic, ...]]:
        return definition, ()

    def _on_add(self, definition: T) -> None:
        return None

    def _on_remove(self, definition: T) -> None:
        return None

    def register(self, definition: T) -> RegistryRegistration[T]:
        definition, diagnostics = self._prepare_definition(definition)
        incoming = RegistryEntry(definition)
        existing = self._entries.get(definition.name)

        if existing is None:
            self._entries[definition.name] = incoming
            self._on_add(definition)
            return RegistryRegistration(
                action="registered",
                entry=incoming,
                diagnostics=diagnostics,
            )

        old_priority = existing.origin.priority
        new_priority = incoming.origin.priority

        if new_priority > old_priority:
            self._on_remove(existing.definition)
            self._entries[definition.name] = incoming
            self._on_add(definition)
            warning = Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="definition_shadowed",
                message=(
                    f"{self.definition_type} '{definition.name}' from "
                    f"{incoming.origin.source.value} overrides the lower-priority "
                    f"definition from {existing.origin.source.value}."
                ),
                definition_type=self.definition_type,
                source=incoming.origin.source.value,
                location=incoming.origin.label,
            )
            return RegistryRegistration(
                action="replaced",
                entry=incoming,
                replaced=existing,
                diagnostics=diagnostics + (warning,),
            )

        if new_priority < old_priority:
            warning = Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                code="definition_skipped",
                message=(
                    f"Skipped {self.definition_type} '{definition.name}' from "
                    f"{incoming.origin.source.value} because a higher-priority "
                    f"definition already exists."
                ),
                definition_type=self.definition_type,
                source=incoming.origin.source.value,
                location=incoming.origin.label,
            )
            return RegistryRegistration(
                action="skipped",
                entry=existing,
                diagnostics=diagnostics + (warning,),
            )

        if incoming.origin.source != existing.origin.source:
            raise RegistryConflictError(
                f"Conflicting {self.definition_type} definitions for '{definition.name}'",
                current=existing.origin.label,
                incoming=incoming.origin.label,
            )

        if incoming.origin.path != existing.origin.path:
            raise RegistryConflictError(
                f"Duplicate {self.definition_type} definitions for '{definition.name}' "
                f"from the same source",
                current=existing.origin.label,
                incoming=incoming.origin.label,
            )

        self._on_remove(existing.definition)
        self._entries[definition.name] = incoming
        self._on_add(definition)
        return RegistryRegistration(
            action="replaced",
            entry=incoming,
            replaced=existing,
            diagnostics=diagnostics,
        )

    def get(self, name: str) -> T | None:
        entry = self._entries.get(name)
        return None if entry is None else entry.definition

    def remove(self, name: str) -> T | None:
        entry = self._entries.pop(name, None)
        if entry is None:
            return None
        self._on_remove(entry.definition)
        return entry.definition

    def definitions(self) -> tuple[T, ...]:
        return tuple(entry.definition for entry in self._entries.values())

    def entries(self) -> tuple[RegistryEntry[T], ...]:
        return tuple(self._entries.values())

    def items(self) -> Iterable[tuple[str, T]]:
        for name, entry in self._entries.items():
            yield name, entry.definition

