import asyncio
from dataclasses import dataclass
from typing import Any

from weavert.control_plane import RuntimeControlPlaneContext
from weavert.definitions import (
    PermissionBehavior,
    PermissionDecision,
    ToolClassifierInput,
    ToolDefinition,
    ToolExecutionSemantics,
    ToolRiskLevel,
)
from weavert.permissions import (
    AllowAllPermissionService,
    DenyAllPermissionService,
    PermissionContext,
    PermissionOutcome,
    PermissionRequest,
    PermissionTarget,
    ReadOnlyPermissionService,
    SelectiveAutoApprovePermissionService,
)
from weavert.runtime_services import RuntimeServices


@dataclass(slots=True)
class ToolPermissionContext:
    session_id: str
    turn_id: str
    permission_context: PermissionContext
    runtime_services: RuntimeServices
    pending_hook_effect: Any = None


class ApprovingHost:
    def __init__(self) -> None:
        self.requests: list[PermissionRequest] = []

    async def request_permission(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return PermissionDecision(PermissionBehavior.ALLOW, "approved", details={"approved": True})


def test_allow_all_preset_flows_through_tool_skill_and_agent_requests() -> None:
    service = AllowAllPermissionService()
    permission_context = PermissionContext(session_id="session")
    runtime_services = RuntimeServices(permissions=service)
    runtime_context = RuntimeControlPlaneContext(
        runtime_services=runtime_services,
        permission_context=permission_context,
    )
    tool_context = ToolPermissionContext(
        session_id="session",
        turn_id="turn",
        permission_context=permission_context,
        runtime_services=runtime_services,
    )

    tool_decision = asyncio.run(
        service.authorize(
            _tool_definition("workspace.read", risk_level=ToolRiskLevel.WRITE),
            {"path": "README.md"},
            PermissionDecision(PermissionBehavior.ASK, "approval required"),
            tool_context,
        )
    )
    skill_outcome = asyncio.run(
        service.evaluate(
            PermissionRequest(
                session_id="session",
                turn_id="turn",
                target=PermissionTarget.SKILL,
                name="review-change",
                payload={"arguments": ["summary"]},
                context=permission_context,
                message="skill permission required",
            ),
            initial_decision=PermissionDecision(PermissionBehavior.ASK, "skill permission required"),
            runtime_context=runtime_context,
        )
    )
    agent_outcome = asyncio.run(
        service.evaluate(
            PermissionRequest(
                session_id="session",
                turn_id="turn",
                target=PermissionTarget.AGENT,
                name="background-worker",
                payload={"prompt": "verify"},
                context=permission_context,
                message="agent permission required",
            ),
            initial_decision=PermissionDecision(PermissionBehavior.ASK, "agent permission required"),
            runtime_context=runtime_context,
        )
    )

    assert tool_decision.behavior == PermissionBehavior.ALLOW
    assert tool_decision.details["preset"] == "allow-all"
    assert tool_decision.details["preset_path"] == "preset:allow-all"
    assert tool_decision.details["source"] == "preset"

    assert skill_outcome.behavior == PermissionBehavior.ALLOW
    assert skill_outcome.details["preset"] == "allow-all"
    assert skill_outcome.details["preset_target"] == "skill"

    assert agent_outcome.behavior == PermissionBehavior.ALLOW
    assert agent_outcome.details["preset"] == "allow-all"
    assert agent_outcome.details["preset_target"] == "agent"


def test_deny_all_preset_denies_without_host_prompting() -> None:
    service = DenyAllPermissionService()
    permission_context = PermissionContext(session_id="session")

    outcome = asyncio.run(
        service.evaluate(
            PermissionRequest(
                session_id="session",
                turn_id="turn",
                target=PermissionTarget.SKILL,
                name="release-summary",
                payload={},
                context=permission_context,
                message="permission required",
            ),
            initial_decision=PermissionDecision(PermissionBehavior.ASK, "permission required"),
        )
    )

    assert outcome.behavior == PermissionBehavior.DENY
    assert outcome.details["preset"] == "deny-all"
    assert outcome.details["preset_path"] == "preset:deny-all"


def test_read_only_preset_covers_read_write_and_delegate_tool_behavior() -> None:
    service = ReadOnlyPermissionService()
    permission_context = PermissionContext(session_id="session")
    runtime_services = RuntimeServices(permissions=service)
    tool_context = ToolPermissionContext(
        session_id="session",
        turn_id="turn",
        permission_context=permission_context,
        runtime_services=runtime_services,
    )

    read_decision = asyncio.run(
        service.authorize(
            _tool_definition("workspace.read", risk_level=ToolRiskLevel.READ, read_only=True),
            {"path": "README.md"},
            PermissionDecision(PermissionBehavior.ASK, "approval required"),
            tool_context,
        )
    )
    write_decision = asyncio.run(
        service.authorize(
            _tool_definition("workspace.write", risk_level=ToolRiskLevel.WRITE),
            {"path": "README.md"},
            PermissionDecision(PermissionBehavior.ALLOW),
            tool_context,
        )
    )
    delegate_decision = asyncio.run(
        service.authorize(
            _tool_definition("agent.spawn", risk_level=ToolRiskLevel.DELEGATE),
            {"prompt": "run verification"},
            PermissionDecision(PermissionBehavior.ALLOW),
            tool_context,
        )
    )

    assert read_decision.behavior == PermissionBehavior.ALLOW
    assert read_decision.details["preset"] == "read-only"
    assert read_decision.details["preset_path"] == "tool-risk:read"

    assert write_decision.behavior == PermissionBehavior.DENY
    assert write_decision.details["preset"] == "read-only"
    assert write_decision.details["preset_risk"] == "write"
    assert write_decision.details["preset_path"] == "tool-risk:write"

    assert delegate_decision.behavior == PermissionBehavior.DENY
    assert delegate_decision.details["preset"] == "read-only"
    assert delegate_decision.details["preset_risk"] == "delegate"
    assert delegate_decision.details["preset_path"] == "tool-risk:delegate"


def test_read_only_preset_does_not_let_selectors_override_side_effecting_tool_risk() -> None:
    service = ReadOnlyPermissionService(tool_selectors=("workspace.write",))
    permission_context = PermissionContext(session_id="session")
    runtime_services = RuntimeServices(permissions=service)
    tool_context = ToolPermissionContext(
        session_id="session",
        turn_id="turn",
        permission_context=permission_context,
        runtime_services=runtime_services,
    )

    write_decision = asyncio.run(
        service.authorize(
            _tool_definition("workspace.write", risk_level=ToolRiskLevel.WRITE),
            {"path": "README.md"},
            PermissionDecision(PermissionBehavior.ASK, "approval required"),
            tool_context,
        )
    )

    assert write_decision.behavior == PermissionBehavior.DENY
    assert write_decision.details["preset"] == "read-only"
    assert write_decision.details["preset_risk"] == "write"
    assert write_decision.details["preset_path"] == "tool-risk:write"
    assert "preset_selector" not in write_decision.details


def test_selective_auto_approve_supports_risk_selector_and_unmatched_fallback_metadata() -> None:
    host = ApprovingHost()
    service = SelectiveAutoApprovePermissionService(
        tool_selectors=("safe-alias",),
        agent_selectors=("worker-*",),
        risk_levels=(ToolRiskLevel.READ,),
        fallback_behavior=PermissionBehavior.ASK,
    )
    permission_context = PermissionContext(session_id="session")
    runtime_services = RuntimeServices(permissions=service, host=host)
    runtime_context = RuntimeControlPlaneContext(
        runtime_services=runtime_services,
        permission_context=permission_context,
    )
    tool_context = ToolPermissionContext(
        session_id="session",
        turn_id="turn",
        permission_context=permission_context,
        runtime_services=runtime_services,
    )

    risk_decision = asyncio.run(
        service.authorize(
            _tool_definition("workspace.read", risk_level=ToolRiskLevel.READ),
            {"path": "README.md"},
            PermissionDecision(PermissionBehavior.ASK, "approval required"),
            tool_context,
        )
    )
    selector_decision = asyncio.run(
        service.authorize(
            _tool_definition("workspace.custom", risk_level=ToolRiskLevel.WRITE, aliases=("safe-alias",)),
            {"path": "README.md"},
            PermissionDecision(PermissionBehavior.ASK, "approval required"),
            tool_context,
        )
    )
    agent_outcome = asyncio.run(
        service.evaluate(
            PermissionRequest(
                session_id="session",
                turn_id="turn",
                target=PermissionTarget.AGENT,
                name="worker-review",
                payload={"prompt": "review"},
                context=permission_context,
                message="agent permission required",
            ),
            initial_decision=PermissionDecision(PermissionBehavior.ASK, "agent permission required"),
            runtime_context=runtime_context,
        )
    )
    unmatched_outcome = asyncio.run(
        service.evaluate(
            PermissionRequest(
                session_id="session",
                turn_id="turn",
                target=PermissionTarget.SKILL,
                name="dangerous-skill",
                payload={"arguments": []},
                context=permission_context,
                message="skill permission required",
            ),
            initial_decision=PermissionDecision(PermissionBehavior.ASK, "skill permission required"),
            runtime_context=runtime_context,
        )
    )

    assert risk_decision.behavior == PermissionBehavior.ALLOW
    assert risk_decision.details["preset"] == "selective-auto-approve"
    assert risk_decision.details["preset_risk"] == "read"
    assert risk_decision.details["preset_path"] == "risk:read"

    assert selector_decision.behavior == PermissionBehavior.ALLOW
    assert selector_decision.details["preset"] == "selective-auto-approve"
    assert selector_decision.details["preset_selector"] == "safe-alias"
    assert selector_decision.details["preset_path"] == "selector:safe-alias"

    assert agent_outcome.behavior == PermissionBehavior.ALLOW
    assert agent_outcome.details["preset"] == "selective-auto-approve"
    assert agent_outcome.details["preset_selector"] == "worker-*"
    assert agent_outcome.details["preset_target"] == "agent"

    assert unmatched_outcome.behavior == PermissionBehavior.ALLOW
    assert unmatched_outcome.details["preset"] == "selective-auto-approve"
    assert unmatched_outcome.details["preset_path"] == "fallback:ask"
    assert unmatched_outcome.details["preset_fallback"] == "ask"
    assert unmatched_outcome.details["approved"] is True
    assert unmatched_outcome.source == "host"
    assert host.requests[0].name == "dangerous-skill"


def _tool_definition(
    name: str,
    *,
    risk_level: ToolRiskLevel,
    read_only: bool = False,
    aliases: tuple[str, ...] = (),
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        aliases=aliases,
        semantics=ToolExecutionSemantics(
            is_read_only=lambda _tool_input, _context: read_only,
            to_classifier_input=lambda _tool_input, _context: ToolClassifierInput(
                operation=name,
                summary=name,
                risk_level=risk_level,
                side_effects=risk_level != ToolRiskLevel.READ,
            ),
        ),
    )
