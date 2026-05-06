from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Sequence

from ..definitions import PermissionBehavior, ToolRiskLevel
from .engine import PermissionEngine
from .models import PermissionPolicy, PermissionRule, PermissionTarget

_PRESET_SOURCE = "preset"
_SIDE_EFFECT_RISKS = (
    ToolRiskLevel.WRITE,
    ToolRiskLevel.EXEC,
    ToolRiskLevel.NETWORK,
    ToolRiskLevel.DELEGATE,
)


@dataclass(slots=True)
class _PresetPermissionService(PermissionEngine):
    preset_name: ClassVar[str]

    def __post_init__(self) -> None:
        PermissionEngine.__post_init__(self)
        self.default_policies = (*self.default_policies, self.build_policy())

    def build_policy(self) -> PermissionPolicy:
        raise NotImplementedError


@dataclass(slots=True)
class AllowAllPermissionService(_PresetPermissionService):
    preset_name: ClassVar[str] = "allow-all"

    def build_policy(self) -> PermissionPolicy:
        return allow_all_policy()


@dataclass(slots=True)
class DenyAllPermissionService(_PresetPermissionService):
    preset_name: ClassVar[str] = "deny-all"
    deny_message: str = "Permission denied by the deny-all preset"

    def build_policy(self) -> PermissionPolicy:
        return deny_all_policy(message=self.deny_message)


@dataclass(slots=True)
class ReadOnlyPermissionService(_PresetPermissionService):
    preset_name: ClassVar[str] = "read-only"
    tool_selectors: Sequence[str] = ()
    skill_selectors: Sequence[str] = ()
    agent_selectors: Sequence[str] = ()
    fallback_behavior: PermissionBehavior | str = PermissionBehavior.DENY
    fallback_message: str = "Request denied by the read-only preset"

    def __post_init__(self) -> None:
        self.tool_selectors = tuple(self.tool_selectors)
        self.skill_selectors = tuple(self.skill_selectors)
        self.agent_selectors = tuple(self.agent_selectors)
        self.fallback_behavior = _coerce_fallback_behavior(self.fallback_behavior)
        _PresetPermissionService.__post_init__(self)

    def build_policy(self) -> PermissionPolicy:
        return read_only_policy(
            tool_selectors=self.tool_selectors,
            skill_selectors=self.skill_selectors,
            agent_selectors=self.agent_selectors,
            fallback_behavior=self.fallback_behavior,
            fallback_message=self.fallback_message,
        )


@dataclass(slots=True)
class SelectiveAutoApprovePermissionService(_PresetPermissionService):
    preset_name: ClassVar[str] = "selective-auto-approve"
    tool_selectors: Sequence[str] = ()
    skill_selectors: Sequence[str] = ()
    agent_selectors: Sequence[str] = ()
    risk_levels: Sequence[ToolRiskLevel | str] = ()
    fallback_behavior: PermissionBehavior | str = PermissionBehavior.DENY
    fallback_message: str = "Request denied by the selective auto-approve preset"

    def __post_init__(self) -> None:
        self.tool_selectors = tuple(self.tool_selectors)
        self.skill_selectors = tuple(self.skill_selectors)
        self.agent_selectors = tuple(self.agent_selectors)
        self.risk_levels = tuple(_coerce_risk_level(value) for value in self.risk_levels)
        self.fallback_behavior = _coerce_fallback_behavior(self.fallback_behavior)
        _PresetPermissionService.__post_init__(self)

    def build_policy(self) -> PermissionPolicy:
        return selective_auto_approve_policy(
            tool_selectors=self.tool_selectors,
            skill_selectors=self.skill_selectors,
            agent_selectors=self.agent_selectors,
            risk_levels=self.risk_levels,
            fallback_behavior=self.fallback_behavior,
            fallback_message=self.fallback_message,
        )


def allow_all_policy() -> PermissionPolicy:
    return PermissionPolicy(
        name="preset:allow-all",
        fallback_behavior=PermissionBehavior.ALLOW,
        metadata={"preset": "allow-all"},
        fallback_metadata={"preset_path": "preset:allow-all"},
        source=_PRESET_SOURCE,
    )


def deny_all_policy(
    *,
    message: str = "Permission denied by the deny-all preset",
) -> PermissionPolicy:
    return PermissionPolicy(
        name="preset:deny-all",
        fallback_behavior=PermissionBehavior.DENY,
        fallback_message=message,
        metadata={"preset": "deny-all"},
        fallback_metadata={"preset_path": "preset:deny-all"},
        source=_PRESET_SOURCE,
    )


def read_only_policy(
    *,
    tool_selectors: Sequence[str] = (),
    skill_selectors: Sequence[str] = (),
    agent_selectors: Sequence[str] = (),
    fallback_behavior: PermissionBehavior | str = PermissionBehavior.DENY,
    fallback_message: str = "Request denied by the read-only preset",
) -> PermissionPolicy:
    resolved_fallback = _coerce_fallback_behavior(fallback_behavior)
    rules = [
        *_selector_rules(
            target=PermissionTarget.TOOL,
            selectors=tool_selectors,
            behavior=PermissionBehavior.ALLOW,
            detail_key="preset_selector",
        ),
        *_selector_rules(
            target=PermissionTarget.SKILL,
            selectors=skill_selectors,
            behavior=PermissionBehavior.ALLOW,
            detail_key="preset_selector",
        ),
        *_selector_rules(
            target=PermissionTarget.AGENT,
            selectors=agent_selectors,
            behavior=PermissionBehavior.ALLOW,
            detail_key="preset_selector",
        ),
        PermissionRule(
            selector="*",
            target=PermissionTarget.TOOL,
            behavior=PermissionBehavior.ALLOW,
            read_only=True,
            metadata={"preset_path": "tool-traits:read-only", "preset_match": "read_only_traits"},
        ),
        PermissionRule(
            selector="*",
            target=PermissionTarget.TOOL,
            behavior=PermissionBehavior.ALLOW,
            risk_levels=(ToolRiskLevel.READ,),
            metadata={"preset_path": "tool-risk:read", "preset_risk": ToolRiskLevel.READ.value},
        ),
        *[
            PermissionRule(
                selector="*",
                target=PermissionTarget.TOOL,
                behavior=resolved_fallback,
                risk_levels=(risk,),
                message=f"Read-only preset blocks {risk.value} requests",
                metadata={
                    "preset_path": f"tool-risk:{risk.value}",
                    "preset_risk": risk.value,
                    "preset_fallback": resolved_fallback.value,
                },
            )
            for risk in _SIDE_EFFECT_RISKS
        ],
    ]
    return PermissionPolicy(
        name="preset:read-only",
        rules=tuple(rules),
        fallback_behavior=resolved_fallback,
        fallback_message=fallback_message if resolved_fallback == PermissionBehavior.DENY else None,
        metadata={"preset": "read-only"},
        fallback_metadata={
            "preset_path": f"fallback:{resolved_fallback.value}",
            "preset_fallback": resolved_fallback.value,
        },
        source=_PRESET_SOURCE,
    )


def selective_auto_approve_policy(
    *,
    tool_selectors: Sequence[str] = (),
    skill_selectors: Sequence[str] = (),
    agent_selectors: Sequence[str] = (),
    risk_levels: Sequence[ToolRiskLevel | str] = (),
    fallback_behavior: PermissionBehavior | str = PermissionBehavior.DENY,
    fallback_message: str = "Request denied by the selective auto-approve preset",
) -> PermissionPolicy:
    resolved_fallback = _coerce_fallback_behavior(fallback_behavior)
    resolved_risks = tuple(_coerce_risk_level(value) for value in risk_levels)
    rules = [
        *_selector_rules(
            target=PermissionTarget.TOOL,
            selectors=tool_selectors,
            behavior=PermissionBehavior.ALLOW,
            detail_key="preset_selector",
        ),
        *_selector_rules(
            target=PermissionTarget.SKILL,
            selectors=skill_selectors,
            behavior=PermissionBehavior.ALLOW,
            detail_key="preset_selector",
        ),
        *_selector_rules(
            target=PermissionTarget.AGENT,
            selectors=agent_selectors,
            behavior=PermissionBehavior.ALLOW,
            detail_key="preset_selector",
        ),
        *[
            PermissionRule(
                selector="*",
                target=PermissionTarget.TOOL,
                behavior=PermissionBehavior.ALLOW,
                risk_levels=(risk,),
                metadata={"preset_path": f"risk:{risk.value}", "preset_risk": risk.value},
            )
            for risk in resolved_risks
        ],
    ]
    return PermissionPolicy(
        name="preset:selective-auto-approve",
        rules=tuple(rules),
        fallback_behavior=resolved_fallback,
        fallback_message=fallback_message if resolved_fallback == PermissionBehavior.DENY else None,
        metadata={"preset": "selective-auto-approve"},
        fallback_metadata={
            "preset_path": f"fallback:{resolved_fallback.value}",
            "preset_fallback": resolved_fallback.value,
        },
        source=_PRESET_SOURCE,
    )


def allow_all_permissions() -> AllowAllPermissionService:
    return AllowAllPermissionService()


def deny_all_permissions(*, message: str = "Permission denied by the deny-all preset") -> DenyAllPermissionService:
    return DenyAllPermissionService(deny_message=message)


def read_only_permissions(
    *,
    tool_selectors: Sequence[str] = (),
    skill_selectors: Sequence[str] = (),
    agent_selectors: Sequence[str] = (),
    fallback_behavior: PermissionBehavior | str = PermissionBehavior.DENY,
    fallback_message: str = "Request denied by the read-only preset",
) -> ReadOnlyPermissionService:
    return ReadOnlyPermissionService(
        tool_selectors=tool_selectors,
        skill_selectors=skill_selectors,
        agent_selectors=agent_selectors,
        fallback_behavior=fallback_behavior,
        fallback_message=fallback_message,
    )


def selective_auto_approve_permissions(
    *,
    tool_selectors: Sequence[str] = (),
    skill_selectors: Sequence[str] = (),
    agent_selectors: Sequence[str] = (),
    risk_levels: Sequence[ToolRiskLevel | str] = (),
    fallback_behavior: PermissionBehavior | str = PermissionBehavior.DENY,
    fallback_message: str = "Request denied by the selective auto-approve preset",
) -> SelectiveAutoApprovePermissionService:
    return SelectiveAutoApprovePermissionService(
        tool_selectors=tool_selectors,
        skill_selectors=skill_selectors,
        agent_selectors=agent_selectors,
        risk_levels=risk_levels,
        fallback_behavior=fallback_behavior,
        fallback_message=fallback_message,
    )


def _selector_rules(
    *,
    target: PermissionTarget,
    selectors: Sequence[str],
    behavior: PermissionBehavior,
    detail_key: str,
) -> tuple[PermissionRule, ...]:
    rules: list[PermissionRule] = []
    for selector in selectors:
        rules.append(
            PermissionRule(
                selector=selector,
                target=target,
                behavior=behavior,
                metadata={"preset_path": f"selector:{selector}", detail_key: selector},
            )
        )
    return tuple(rules)


def _coerce_risk_level(value: ToolRiskLevel | str) -> ToolRiskLevel:
    if isinstance(value, ToolRiskLevel):
        return value
    return ToolRiskLevel(str(value))


def _coerce_fallback_behavior(value: PermissionBehavior | str) -> PermissionBehavior:
    behavior = value if isinstance(value, PermissionBehavior) else PermissionBehavior(str(value))
    if behavior not in {PermissionBehavior.ASK, PermissionBehavior.DENY}:
        raise ValueError("Preset fallback_behavior must be 'ask' or 'deny'")
    return behavior


__all__ = [
    "AllowAllPermissionService",
    "DenyAllPermissionService",
    "ReadOnlyPermissionService",
    "SelectiveAutoApprovePermissionService",
    "allow_all_permissions",
    "allow_all_policy",
    "deny_all_permissions",
    "deny_all_policy",
    "read_only_permissions",
    "read_only_policy",
    "selective_auto_approve_permissions",
    "selective_auto_approve_policy",
]
