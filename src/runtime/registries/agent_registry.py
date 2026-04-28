from __future__ import annotations

from dataclasses import replace

from ..diagnostics import Diagnostic, DiagnosticSeverity
from ..definitions import AgentDefinition
from .base import DefinitionRegistry


class AgentRegistry(DefinitionRegistry[AgentDefinition]):
    definition_type = "agent"

    def __init__(self, *, allow_legacy_agent_hooks: bool = False) -> None:
        super().__init__()
        self._allow_legacy_agent_hooks = bool(allow_legacy_agent_hooks)

    def _prepare_definition(
        self,
        definition: AgentDefinition,
    ) -> tuple[AgentDefinition, tuple[Diagnostic, ...]]:
        if not definition.hooks:
            return definition, ()
        metadata = dict(definition.metadata)
        hook_phases = tuple(sorted(str(phase) for phase in definition.hooks))
        metadata["ignored_agent_hooks"] = hook_phases
        metadata["hook_surface_status"] = (
            "legacy-mode-enabled" if self._allow_legacy_agent_hooks else "rejected-by-default"
        )
        stripped = replace(definition, hooks={}, metadata=metadata)
        warning = Diagnostic(
            severity=(
                DiagnosticSeverity.WARNING
                if self._allow_legacy_agent_hooks
                else DiagnosticSeverity.ERROR
            ),
            code=(
                "agent_hooks_legacy_gated"
                if self._allow_legacy_agent_hooks
                else "agent_hooks_rejected"
            ),
            message=(
                f"Agent '{definition.name}' declares hooks, but agent-owned hook definitions are "
                + (
                    "legacy-gated and ignored in the active compatibility profile; "
                    if self._allow_legacy_agent_hooks
                    else "rejected by default; "
                )
                + "use runtime config, host, skill, or session hook registration instead."
            ),
            definition_type=self.definition_type,
            source=definition.origin.source.value,
            location=definition.origin.label,
            details={"phases": list(hook_phases)},
        )
        return stripped, (warning,)
