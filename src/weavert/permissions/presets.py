from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, ClassVar, Sequence

from ..definitions import (
    PermissionBehavior,
    ToolClassifierInput,
    ToolDefinition,
    ToolRiskLevel,
)
from .engine import PermissionEngine
from .models import PermissionOutcome, PermissionRequest, PermissionTarget, coerce_permission_outcome

_PRESET_SOURCE = "preset"
_SIDE_EFFECT_RISKS = {
    ToolRiskLevel.WRITE,
    ToolRiskLevel.EXEC,
    ToolRiskLevel.NETWORK,
    ToolRiskLevel.DELEGATE,
}


@dataclass(frozen=True, slots=True)
class _ToolRequestProfile:
    definition: ToolDefinition
    read_only: bool
    risk_level: ToolRiskLevel | None


@dataclass(slots=True)
class _PresetPermissionService(PermissionEngine):
    preset_name: ClassVar[str]

    async def evaluate(
        self,
        request: PermissionRequest,
        *,
        initial_decision: Any = None,
        hook_result: Any = None,
        runtime_context: Any = None,
    ) -> PermissionOutcome:
        initial_outcome = coerce_permission_outcome(initial_decision)
        if initial_outcome.behavior == PermissionBehavior.DENY:
            return await PermissionEngine.evaluate(
                self,
                request,
                initial_decision=initial_outcome,
                hook_result=hook_result,
                runtime_context=runtime_context,
            )

        preset_outcome = await self._resolve_preset_outcome(
            request,
            initial_outcome=initial_outcome,
            runtime_context=runtime_context,
        )
        return await PermissionEngine.evaluate(
            self,
            request,
            initial_decision=self._merge_preset_outcome(initial_outcome, preset_outcome),
            hook_result=hook_result,
            runtime_context=runtime_context,
        )

    async def _resolve_preset_outcome(
        self,
        request: PermissionRequest,
        *,
        initial_outcome: PermissionOutcome,
        runtime_context: Any,
    ) -> PermissionOutcome:
        raise NotImplementedError

    @staticmethod
    def _merge_preset_outcome(
        initial_outcome: PermissionOutcome,
        preset_outcome: PermissionOutcome,
    ) -> PermissionOutcome:
        updated_input = preset_outcome.updated_input
        if updated_input is None and initial_outcome.updated_input is not None:
            updated_input = dict(initial_outcome.updated_input)
        return PermissionOutcome(
            behavior=preset_outcome.behavior,
            message=preset_outcome.message,
            updated_input=updated_input,
            details={**dict(initial_outcome.details), **dict(preset_outcome.details)},
            source=preset_outcome.source,
        )

    def _preset_outcome(
        self,
        request: PermissionRequest,
        behavior: PermissionBehavior,
        *,
        path: str,
        message: str | None = None,
        **details: Any,
    ) -> PermissionOutcome:
        return PermissionOutcome(
            behavior=behavior,
            message=message,
            details={
                "preset": self.preset_name,
                "preset_path": path,
                "preset_target": request.target.value,
                **details,
            },
            source=_PRESET_SOURCE,
        )

    async def _tool_request_profile(
        self,
        request: PermissionRequest,
        *,
        runtime_context: Any,
    ) -> _ToolRequestProfile | None:
        if request.target != PermissionTarget.TOOL:
            return None
        definition = request.metadata.get("definition")
        if not isinstance(definition, ToolDefinition):
            return None
        call_context = request.metadata.get("runtime_context", runtime_context)
        read_only_value = await _maybe_await(
            definition.execution_semantics.is_read_only(request.payload, call_context)
        )
        classifier_input = await _maybe_await(
            definition.execution_semantics.to_classifier_input(request.payload, call_context)
        )
        risk_level = None
        if isinstance(classifier_input, ToolClassifierInput):
            risk_level = classifier_input.risk_level
        return _ToolRequestProfile(
            definition=definition,
            read_only=bool(read_only_value),
            risk_level=risk_level,
        )


@dataclass(slots=True)
class AllowAllPermissionService(_PresetPermissionService):
    preset_name: ClassVar[str] = "allow-all"

    async def _resolve_preset_outcome(
        self,
        request: PermissionRequest,
        *,
        initial_outcome: PermissionOutcome,
        runtime_context: Any,
    ) -> PermissionOutcome:
        _ = initial_outcome, runtime_context
        return self._preset_outcome(request, PermissionBehavior.ALLOW, path="preset:allow-all")


@dataclass(slots=True)
class DenyAllPermissionService(_PresetPermissionService):
    preset_name: ClassVar[str] = "deny-all"
    deny_message: str = "Permission denied by the deny-all preset"

    async def _resolve_preset_outcome(
        self,
        request: PermissionRequest,
        *,
        initial_outcome: PermissionOutcome,
        runtime_context: Any,
    ) -> PermissionOutcome:
        _ = initial_outcome, runtime_context
        return self._preset_outcome(
            request,
            PermissionBehavior.DENY,
            path="preset:deny-all",
            message=self.deny_message,
        )


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

    async def _resolve_preset_outcome(
        self,
        request: PermissionRequest,
        *,
        initial_outcome: PermissionOutcome,
        runtime_context: Any,
    ) -> PermissionOutcome:
        _ = initial_outcome
        profile = await self._tool_request_profile(request, runtime_context=runtime_context)
        if profile is not None and profile.risk_level == ToolRiskLevel.READ:
            return self._preset_outcome(
                request,
                PermissionBehavior.ALLOW,
                path="tool-risk:read",
                preset_risk=ToolRiskLevel.READ.value,
            )
        if profile is not None and profile.risk_level is None and profile.read_only:
            return self._preset_outcome(
                request,
                PermissionBehavior.ALLOW,
                path="tool-traits:read-only",
                preset_match="read_only_traits",
            )

        if profile is not None and profile.risk_level in _SIDE_EFFECT_RISKS:
            return self._fallback_outcome(
                request,
                path=f"tool-risk:{profile.risk_level.value}",
                message=f"Read-only preset blocks {profile.risk_level.value} requests",
                preset_risk=profile.risk_level.value,
            )

        selector_match = _match_request_selector(
            request,
            tool_definition=profile.definition if profile is not None else None,
            tool_selectors=self.tool_selectors,
            skill_selectors=self.skill_selectors,
            agent_selectors=self.agent_selectors,
        )
        if selector_match is not None:
            return self._preset_outcome(
                request,
                PermissionBehavior.ALLOW,
                path=f"selector:{selector_match}",
                preset_selector=selector_match,
            )

        return self._fallback_outcome(request, path=f"fallback:{self.fallback_behavior.value}")

    def _fallback_outcome(
        self,
        request: PermissionRequest,
        *,
        path: str,
        message: str | None = None,
        **details: Any,
    ) -> PermissionOutcome:
        fallback_message = message
        if self.fallback_behavior == PermissionBehavior.DENY:
            fallback_message = fallback_message or self.fallback_message
        return self._preset_outcome(
            request,
            self.fallback_behavior,
            path=path,
            message=fallback_message,
            preset_fallback=self.fallback_behavior.value,
            **details,
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

    async def _resolve_preset_outcome(
        self,
        request: PermissionRequest,
        *,
        initial_outcome: PermissionOutcome,
        runtime_context: Any,
    ) -> PermissionOutcome:
        _ = initial_outcome
        profile = await self._tool_request_profile(request, runtime_context=runtime_context)
        if profile is not None and profile.risk_level in self.risk_levels:
            return self._preset_outcome(
                request,
                PermissionBehavior.ALLOW,
                path=f"risk:{profile.risk_level.value}",
                preset_risk=profile.risk_level.value,
            )

        selector_match = _match_request_selector(
            request,
            tool_definition=profile.definition if profile is not None else None,
            tool_selectors=self.tool_selectors,
            skill_selectors=self.skill_selectors,
            agent_selectors=self.agent_selectors,
        )
        if selector_match is not None:
            return self._preset_outcome(
                request,
                PermissionBehavior.ALLOW,
                path=f"selector:{selector_match}",
                preset_selector=selector_match,
            )

        return self._fallback_outcome(request)

    def _fallback_outcome(self, request: PermissionRequest) -> PermissionOutcome:
        fallback_message: str | None = None
        if self.fallback_behavior == PermissionBehavior.DENY:
            fallback_message = self.fallback_message
        return self._preset_outcome(
            request,
            self.fallback_behavior,
            path=f"fallback:{self.fallback_behavior.value}",
            message=fallback_message,
            preset_fallback=self.fallback_behavior.value,
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


def _match_request_selector(
    request: PermissionRequest,
    *,
    tool_definition: ToolDefinition | None,
    tool_selectors: Sequence[str],
    skill_selectors: Sequence[str],
    agent_selectors: Sequence[str],
) -> str | None:
    if request.target == PermissionTarget.TOOL:
        for selector in tool_selectors:
            if tool_definition is not None and _matches_tool_selector(tool_definition, selector):
                return selector
            if tool_definition is None and _matches_name_selector(request.name, selector):
                return selector
        return None
    if request.target == PermissionTarget.SKILL:
        for selector in skill_selectors:
            if _matches_name_selector(request.name, selector):
                return selector
        return None
    if request.target == PermissionTarget.AGENT:
        for selector in agent_selectors:
            if _matches_name_selector(request.name, selector):
                return selector
        return None
    return None


def _matches_tool_selector(definition: ToolDefinition, selector: str) -> bool:
    if selector == "*":
        return True
    if any(char in selector for char in "*?[]"):
        return any(fnmatch(candidate, selector) for candidate in (definition.name, *definition.aliases))
    return definition.matches(selector)


def _matches_name_selector(name: str, selector: str) -> bool:
    if selector == "*":
        return True
    if any(char in selector for char in "*?[]"):
        return fnmatch(name, selector)
    return name == selector


def _coerce_risk_level(value: ToolRiskLevel | str) -> ToolRiskLevel:
    if isinstance(value, ToolRiskLevel):
        return value
    return ToolRiskLevel(str(value))


def _coerce_fallback_behavior(value: PermissionBehavior | str) -> PermissionBehavior:
    behavior = value if isinstance(value, PermissionBehavior) else PermissionBehavior(str(value))
    if behavior not in {PermissionBehavior.ASK, PermissionBehavior.DENY}:
        raise ValueError("Preset fallback_behavior must be 'ask' or 'deny'")
    return behavior


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


__all__ = [
    "AllowAllPermissionService",
    "DenyAllPermissionService",
    "ReadOnlyPermissionService",
    "SelectiveAutoApprovePermissionService",
    "allow_all_permissions",
    "deny_all_permissions",
    "read_only_permissions",
    "selective_auto_approve_permissions",
]
