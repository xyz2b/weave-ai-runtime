from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ClosureActivationState(StrEnum):
    RETIRED = "retired"
    LEGACY_MODE_ONLY = "legacy_mode_only"
    LEGACY_MODE_ENABLED = "legacy_mode_enabled"


class PersistenceDurabilityState(StrEnum):
    DURABLE = "durable"
    NON_DURABLE = "non_durable"
    HOST_PROVIDED = "host_provided"


class ClosureStatus(StrEnum):
    GREEN = "closure-green"
    RED = "closure-red"


@dataclass(frozen=True, slots=True)
class CompatibilityRetirementFamilyDefinition:
    family: str
    summary: str
    default_activation: ClosureActivationState
    migration_target: str
    surfaces: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "summary": self.summary,
            "default_activation": self.default_activation.value,
            "migration_target": self.migration_target,
            "surfaces": list(self.surfaces),
        }


LEGACY_COMPATIBILITY_FAMILIES: tuple[CompatibilityRetirementFamilyDefinition, ...] = (
    CompatibilityRetirementFamilyDefinition(
        family="task_manager",
        summary="TaskManager no longer acts as the canonical runtime control-plane dependency.",
        default_activation=ClosureActivationState.RETIRED,
        migration_target="RuntimeServices.job_service / RuntimeServices.task_list_service",
        surfaces=(
            "RuntimeServices.task_manager",
            "RuntimeAssembly.task_manager",
            "RuntimeServices.bind_task_manager",
            "TurnEngine.__init__(task_manager=...)",
            "AgentRuntime.__init__(task_manager=...)",
        ),
    ),
    CompatibilityRetirementFamilyDefinition(
        family="runtime_context_authority",
        summary="Shared runtime_context remains a bridge input only and no longer owns authoritative coordination.",
        default_activation=ClosureActivationState.LEGACY_MODE_ONLY,
        migration_target="PromptContextEnvelope / RuntimePrivateContext",
        surfaces=("runtime_context",),
    ),
    CompatibilityRetirementFamilyDefinition(
        family="context_contributor_adapters",
        summary="Legacy collect-style contributor helpers are compatibility adapters rather than primary extension points.",
        default_activation=ClosureActivationState.RETIRED,
        migration_target="PackageContribution.context_contributors",
        surfaces=(
            "RuntimeServices.memory.collect",
            "RuntimeServices.hooks.collect",
            "RuntimeServices.task_discipline.collect",
        ),
    ),
    CompatibilityRetirementFamilyDefinition(
        family="memory_projection",
        summary="RuntimeServices.memory is a retained compatibility projection only.",
        default_activation=ClosureActivationState.RETIRED,
        migration_target="RuntimeServices.resolve_memory_service()",
        surfaces=(
            "RuntimeServices.memory",
            "RuntimeServices.memory.collect",
        ),
    ),
    CompatibilityRetirementFamilyDefinition(
        family="compaction_projection",
        summary="RuntimeServices.compaction is a retained compatibility projection only.",
        default_activation=ClosureActivationState.RETIRED,
        migration_target="RuntimeServices.resolve_compaction_service()",
        surfaces=(
            "RuntimeServices.compaction",
            "RuntimeServices.compaction.prepare_turn",
            "RuntimeServices.compaction.collect",
        ),
    ),
    CompatibilityRetirementFamilyDefinition(
        family="isolation_projection",
        summary="RuntimeServices.isolation is a retained compatibility projection only.",
        default_activation=ClosureActivationState.RETIRED,
        migration_target="RuntimeServices.resolve_isolation_service()",
        surfaces=("RuntimeServices.isolation",),
    ),
    CompatibilityRetirementFamilyDefinition(
        family="teammates_projection",
        summary="Legacy teammates projections remain compatibility wrappers rather than canonical discovery paths.",
        default_activation=ClosureActivationState.RETIRED,
        migration_target="RuntimeAssembly.resolve_capability(RuntimeCapabilityKey.TEAMMATES.value)",
        surfaces=(
            "RuntimeServices.teammates",
            "RuntimeAssembly.teammates",
        ),
    ),
    CompatibilityRetirementFamilyDefinition(
        family="agent_owned_hooks",
        summary="Agent-owned legacy hooks are rejected by default and only tolerated through explicit legacy compatibility mode.",
        default_activation=ClosureActivationState.LEGACY_MODE_ONLY,
        migration_target="runtime config / host / session / skill hook registration",
        surfaces=("AgentDefinition.hooks",),
    ),
)

LEGACY_COMPATIBILITY_FAMILY_INDEX = {
    definition.family: definition for definition in LEGACY_COMPATIBILITY_FAMILIES
}

LEGACY_RUNTIME_CONTEXT_AUTHORITATIVE_KEYS = frozenset(
    {
        "team_id",
        "team_role",
        "team_member_id",
        "team_member_name",
        "leader_session_id",
        "resolved_task_list_id",
        "permission_context",
        "execution_policy_state",
        "run_id",
        "parent_run_id",
        "delegation_depth",
        "requested_model_route",
        "resolved_model_route",
        "provider_name",
        "invocation_mode",
    }
)


@dataclass(frozen=True, slots=True)
class LegacyCompatibilityProfile:
    enabled_families: tuple[str, ...] = ()
    preset: str = "none"
    unknown_families: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def is_enabled(self, family: str) -> bool:
        return family in self.enabled_families

    def to_metadata(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "enabled_families": list(self.enabled_families),
            "unknown_families": list(self.unknown_families),
            "known_families": [definition.family for definition in LEGACY_COMPATIBILITY_FAMILIES],
            "raw": dict(self.raw),
        }


def resolve_legacy_compatibility_profile(value: Any) -> LegacyCompatibilityProfile:
    enabled: set[str] = set()
    unknown: set[str] = set()
    preset = "none"
    raw: dict[str, Any] = {}

    if value is None:
        return LegacyCompatibilityProfile()
    if isinstance(value, bool):
        preset = "all" if value else "none"
        if value:
            enabled.update(LEGACY_COMPATIBILITY_FAMILY_INDEX)
        return LegacyCompatibilityProfile(
            enabled_families=tuple(sorted(enabled)),
            preset=preset,
            raw={"legacy_compatibility": value},
        )

    if isinstance(value, Mapping):
        raw = {str(key): item for key, item in value.items()}
        preset = str(raw.get("preset") or "none").strip().lower() or "none"
        if preset == "all":
            enabled.update(LEGACY_COMPATIBILITY_FAMILY_INDEX)
        elif preset not in {"none", "default"}:
            unknown.add(preset)
        families = raw.get("families", ())
        enabled.update(_coerce_family_names(families, unknown))
        for family in LEGACY_COMPATIBILITY_FAMILY_INDEX:
            if bool(raw.get(family)):
                enabled.add(family)
        disabled = raw.get("disabled_families", ())
        enabled.difference_update(_coerce_family_names(disabled, unknown, allow_unknown=False))
    else:
        enabled.update(_coerce_family_names(value, unknown))

    return LegacyCompatibilityProfile(
        enabled_families=tuple(sorted(enabled)),
        preset=preset,
        unknown_families=tuple(sorted(unknown)),
        raw=raw,
    )


def family_activation_state(
    family: str,
    profile: LegacyCompatibilityProfile,
) -> ClosureActivationState:
    definition = LEGACY_COMPATIBILITY_FAMILY_INDEX[family]
    if profile.is_enabled(family):
        return ClosureActivationState.LEGACY_MODE_ENABLED
    return definition.default_activation


def _coerce_family_names(
    value: Any,
    unknown: set[str],
    *,
    allow_unknown: bool = True,
) -> set[str]:
    if isinstance(value, str):
        items: Sequence[Any] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, str)):
        items = value
    else:
        return set()

    normalized: set[str] = set()
    for item in items:
        name = str(item).strip()
        if not name:
            continue
        if name in LEGACY_COMPATIBILITY_FAMILY_INDEX:
            normalized.add(name)
        elif allow_unknown:
            unknown.add(name)
    return normalized


__all__ = [
    "ClosureActivationState",
    "ClosureStatus",
    "CompatibilityRetirementFamilyDefinition",
    "LEGACY_COMPATIBILITY_FAMILIES",
    "LEGACY_COMPATIBILITY_FAMILY_INDEX",
    "LEGACY_RUNTIME_CONTEXT_AUTHORITATIVE_KEYS",
    "LegacyCompatibilityProfile",
    "PersistenceDurabilityState",
    "family_activation_state",
    "resolve_legacy_compatibility_profile",
]
