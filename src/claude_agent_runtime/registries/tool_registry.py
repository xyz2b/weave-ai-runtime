from __future__ import annotations

from dataclasses import replace

from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..definitions import ToolDefinition
from .base import DefinitionRegistry


class ToolRegistry(DefinitionRegistry[ToolDefinition]):
    definition_type = "tool"

    def __init__(self) -> None:
        super().__init__()
        self._aliases: dict[str, str] = {}

    def _prepare_definition(
        self,
        definition: ToolDefinition,
    ) -> tuple[ToolDefinition, tuple[Diagnostic, ...]]:
        diagnostics: list[Diagnostic] = []
        filtered_aliases: list[str] = []

        for alias in definition.aliases:
            if not alias or alias == definition.name or alias in filtered_aliases:
                continue

            owner = self._aliases.get(alias)
            if owner is not None and owner != definition.name:
                existing = self._entries.get(owner)
                if (
                    existing is not None
                    and definition.origin.priority > existing.origin.priority
                    and alias != existing.definition.name
                ):
                    diagnostics.append(
                        Diagnostic(
                            severity=DiagnosticSeverity.WARNING,
                            code="tool_alias_replaced",
                            message=(
                                f"Alias '{alias}' now resolves to tool '{definition.name}' "
                                f"instead of '{owner}' due to higher source priority."
                            ),
                            definition_type="tool",
                            source=definition.origin.source.value,
                            location=definition.origin.label,
                        )
                    )
                    self._aliases.pop(alias, None)
                    filtered_aliases.append(alias)
                    continue

                diagnostics.append(
                    Diagnostic(
                        severity=DiagnosticSeverity.WARNING,
                        code="tool_alias_dropped",
                        message=(
                            f"Dropped alias '{alias}' from tool '{definition.name}' "
                            f"because it conflicts with '{owner}'."
                        ),
                        definition_type="tool",
                        source=definition.origin.source.value,
                        location=definition.origin.label,
                    )
                )
                continue

            existing_name_owner = self._entries.get(alias)
            if existing_name_owner is not None and alias != definition.name:
                diagnostics.append(
                    Diagnostic(
                        severity=DiagnosticSeverity.WARNING,
                        code="tool_alias_name_conflict",
                        message=(
                            f"Dropped alias '{alias}' from tool '{definition.name}' "
                            f"because it conflicts with an existing tool name."
                        ),
                        definition_type="tool",
                        source=definition.origin.source.value,
                        location=definition.origin.label,
                    )
                )
                continue

            filtered_aliases.append(alias)

        if tuple(filtered_aliases) != definition.aliases:
            definition = replace(definition, aliases=tuple(filtered_aliases))

        return definition, tuple(diagnostics)

    def _on_add(self, definition: ToolDefinition) -> None:
        for alias in definition.aliases:
            self._aliases[alias] = definition.name

    def _on_remove(self, definition: ToolDefinition) -> None:
        for alias in definition.aliases:
            if self._aliases.get(alias) == definition.name:
                self._aliases.pop(alias, None)

    def get(self, name: str) -> ToolDefinition | None:
        direct = super().get(name)
        if direct is not None:
            return direct
        owner = self._aliases.get(name)
        if owner is None:
            return None
        return super().get(owner)

