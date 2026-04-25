from __future__ import annotations

from dataclasses import replace

from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..definitions import AgentDefinition
from .base import DefinitionRegistry


class AgentRegistry(DefinitionRegistry[AgentDefinition]):
    definition_type = "agent"

    def _prepare_definition(
        self,
        definition: AgentDefinition,
    ) -> tuple[AgentDefinition, tuple[Diagnostic, ...]]:
        if not definition.hooks:
            return definition, ()
        metadata = dict(definition.metadata)
        metadata["ignored_agent_hooks"] = tuple(sorted(str(phase) for phase in definition.hooks))
        metadata["hook_surface_status"] = "compatibility-only"
        stripped = replace(definition, hooks={}, metadata=metadata)
        warning = Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="agent_hooks_ignored",
            message=(
                f"Agent '{definition.name}' declares hooks, but agent-owned hook definitions are "
                "compatibility-only and are ignored; use runtime config, host, skill, or "
                "session hook registration instead."
            ),
            definition_type=self.definition_type,
            source=definition.origin.source.value,
            location=definition.origin.label,
            details={"phases": list(metadata["ignored_agent_hooks"])},
        )
        return stripped, (warning,)
