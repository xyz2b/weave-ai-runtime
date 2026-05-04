import asyncio
from dataclasses import dataclass
from typing import Any

from weavert.control_plane import RuntimeControlPlaneContext
from weavert.definitions import (
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    ToolClassifierInput,
    ToolDefinition,
    ToolExecutionSemantics,
    ToolRiskLevel,
)
from weavert.permissions import (
    PermissionContext,
    PermissionEngine,
    PermissionPolicy,
    PermissionRequest,
    PermissionRule,
    PermissionTarget,
    allow_all_policy,
)
from weavert.runtime_services import RuntimeServices


@dataclass(slots=True)
class ToolPermissionContext:
    session_id: str
    turn_id: str
    permission_context: PermissionContext
    runtime_services: RuntimeServices
    pending_hook_effect: Any = None


def test_scope_based_policy_matching_uses_permission_context_scopes() -> None:
    engine = PermissionEngine()
    matching_context = PermissionContext(
        session_id="session",
        mode=PermissionMode.DEFAULT,
        metadata={"policy_scopes": ("workspace:docs",)},
        policies=(
            allow_all_policy(),
            PermissionPolicy(
                name="docs-writes",
                rules=(
                    PermissionRule(
                        selector="workspace.write",
                        target=PermissionTarget.TOOL,
                        scopes=("workspace:docs",),
                        behavior=PermissionBehavior.DENY,
                        message="docs writes require approval",
                    ),
                ),
            ),
        ),
    )
    non_matching_context = PermissionContext(
        session_id="session",
        mode=PermissionMode.DEFAULT,
        metadata={"policy_scopes": ("workspace:src",)},
        policies=matching_context.policies,
    )

    matching_decision = asyncio.run(
        engine.authorize(
            _tool_definition("workspace.write", risk_level=ToolRiskLevel.WRITE),
            {"path": "docs/guide.md"},
            PermissionDecision(PermissionBehavior.ALLOW),
            ToolPermissionContext(
                session_id="session",
                turn_id="turn",
                permission_context=matching_context,
                runtime_services=RuntimeServices(permissions=engine),
            ),
        )
    )
    non_matching_decision = asyncio.run(
        engine.authorize(
            _tool_definition("workspace.write", risk_level=ToolRiskLevel.WRITE),
            {"path": "src/app.py"},
            PermissionDecision(PermissionBehavior.ALLOW),
            ToolPermissionContext(
                session_id="session",
                turn_id="turn",
                permission_context=non_matching_context,
                runtime_services=RuntimeServices(permissions=engine),
            ),
        )
    )

    assert matching_decision.behavior == PermissionBehavior.DENY
    assert non_matching_decision.behavior == PermissionBehavior.ALLOW
    assert matching_decision.details["policy_explanation"]["winner"]["policy_name"] == "docs-writes"
    assert matching_decision.details["policy_explanation"]["winner"]["winning_rule"]["scopes"] == [
        "workspace:docs"
    ]


def test_risk_based_policy_matching_uses_runtime_tool_risk_classification() -> None:
    engine = PermissionEngine()
    policy = PermissionPolicy(
        name="read-risk-only",
        rules=(
            PermissionRule(
                selector="*",
                target=PermissionTarget.TOOL,
                risk_levels=(ToolRiskLevel.READ,),
                behavior=PermissionBehavior.ALLOW,
                metadata={"risk_rule": "read"},
            ),
        ),
        fallback_behavior=PermissionBehavior.DENY,
        fallback_message="Only read-classified tools are allowed",
    )
    permission_context = PermissionContext(session_id="session", policies=(policy,))
    tool_context = ToolPermissionContext(
        session_id="session",
        turn_id="turn",
        permission_context=permission_context,
        runtime_services=RuntimeServices(permissions=engine),
    )

    read_decision = asyncio.run(
        engine.authorize(
            _tool_definition("workspace.read", risk_level=ToolRiskLevel.READ),
            {"path": "README.md"},
            PermissionDecision(PermissionBehavior.ALLOW),
            tool_context,
        )
    )
    write_decision = asyncio.run(
        engine.authorize(
            _tool_definition("workspace.write", risk_level=ToolRiskLevel.WRITE),
            {"path": "README.md"},
            PermissionDecision(PermissionBehavior.ALLOW),
            tool_context,
        )
    )

    assert read_decision.behavior == PermissionBehavior.ALLOW
    assert read_decision.details["policy_explanation"]["request"]["risk_level"] == ToolRiskLevel.READ.value
    assert write_decision.behavior == PermissionBehavior.DENY
    assert write_decision.details["policy_explanation"]["request"]["risk_level"] == ToolRiskLevel.WRITE.value
    assert write_decision.details["policy_explanation"]["winner"]["fallback_used"] is True


def test_composed_policy_explanations_preserve_preset_layers_and_winner_path() -> None:
    engine = PermissionEngine()
    permission_context = PermissionContext(
        session_id="session",
        policies=(
            allow_all_policy(),
            PermissionPolicy(
                name="deny-workers",
                rules=(
                    PermissionRule(
                        selector="worker-*",
                        target=PermissionTarget.AGENT,
                        behavior=PermissionBehavior.DENY,
                        message="worker agents stay manual",
                    ),
                ),
            ),
        ),
    )

    outcome = asyncio.run(
        engine.evaluate(
            PermissionRequest(
                session_id="session",
                turn_id="turn",
                target=PermissionTarget.AGENT,
                name="worker-review",
                payload={"prompt": "review"},
                context=permission_context,
                message="agent permission required",
            ),
            initial_decision=PermissionDecision(PermissionBehavior.ALLOW),
        )
    )

    explanation = outcome.details["policy_explanation"]

    assert outcome.behavior == PermissionBehavior.DENY
    assert [layer["policy_name"] for layer in explanation["layers"]] == [
        "preset:allow-all",
        "deny-workers",
    ]
    assert explanation["winner"]["policy_name"] == "deny-workers"
    assert explanation["layers"][0]["source"] == "preset"
    assert explanation["layers"][0]["metadata"]["preset"] == "allow-all"
    assert explanation["winner"]["winning_rule"]["selector"] == "worker-*"


def test_runtime_control_plane_metadata_contributes_delegated_agent_scopes() -> None:
    engine = PermissionEngine()
    permission_context = PermissionContext(
        session_id="session",
        policies=(
            PermissionPolicy(
                name="deny-delegated-agents",
                rules=(
                    PermissionRule(
                        selector="worker",
                        target=PermissionTarget.AGENT,
                        scopes=("delegated",),
                        behavior=PermissionBehavior.DENY,
                        message="delegated agents require approval",
                    ),
                ),
            ),
        ),
    )

    outcome = asyncio.run(
        engine.evaluate(
            PermissionRequest(
                session_id="session",
                turn_id="turn",
                target=PermissionTarget.AGENT,
                name="worker",
                payload={"prompt": "review"},
                context=permission_context,
            ),
            initial_decision=PermissionDecision(PermissionBehavior.ALLOW),
            runtime_context=RuntimeControlPlaneContext(
                runtime_services=RuntimeServices(),
                permission_context=permission_context,
                metadata={
                    "agent_name": "planner",
                    "query_source": "skill_fork",
                    "spawn_mode": "fork",
                    "delegation_depth": 1,
                },
            ),
        )
    )

    assert outcome.behavior == PermissionBehavior.DENY
    scopes = outcome.details["policy_explanation"]["request"]["scopes"]
    assert "agent:planner" in scopes
    assert "delegated" in scopes
    assert "query:skill_fork" in scopes
    assert "spawn:fork" in scopes


def test_policy_override_does_not_keep_stale_message_when_behavior_changes() -> None:
    engine = PermissionEngine()
    permission_context = PermissionContext(
        session_id="session",
        policies=(
            PermissionPolicy(
                name="allow-worker",
                rules=(
                    PermissionRule(
                        selector="worker",
                        target=PermissionTarget.AGENT,
                        behavior=PermissionBehavior.ALLOW,
                    ),
                ),
            ),
        ),
    )

    outcome = asyncio.run(
        engine.evaluate(
            PermissionRequest(
                session_id="session",
                turn_id="turn",
                target=PermissionTarget.AGENT,
                name="worker",
                payload={"prompt": "review"},
                context=permission_context,
            ),
            initial_decision=PermissionDecision(PermissionBehavior.ASK, "needs approval"),
        )
    )

    assert outcome.behavior == PermissionBehavior.ALLOW
    assert outcome.message is None
    assert outcome.details["policy_explanation"]["winner"]["policy_name"] == "allow-worker"


def _tool_definition(
    name: str,
    *,
    risk_level: ToolRiskLevel,
    read_only: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
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
