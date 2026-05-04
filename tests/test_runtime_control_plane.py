import asyncio
from pathlib import Path

from weavert.agent_runtime import AgentInvocation, AgentRuntime
from weavert.agent_execution import SpawnMode
from weavert.control_plane import RuntimeControlPlaneContext
from weavert.definitions import (
    AgentDefinition,
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    SkillDefinition,
)
from weavert.elicitation import ElicitationRequest, SharedElicitationService
from weavert.hooks import HookEffect, RuntimeHookPhase
from weavert.permissions import (
    AllowAllPermissionService,
    PermissionContext,
    PermissionEngine,
    PermissionPolicy,
    PermissionRequest,
    PermissionRule,
    PermissionTarget,
)
from weavert.registries import AgentRegistry, SkillRegistry, ToolRegistry
from weavert.runtime_services import RuntimeServices
from weavert.skill_runtime import SkillExecutor
from weavert.tasking import TaskManager
from weavert.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, TurnEngine


class FakeModelClient:
    def __init__(self, event_batches: list[list[ModelStreamEvent]]) -> None:
        self._event_batches = [list(batch) for batch in event_batches]
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        batch = self._event_batches.pop(0)
        for event in batch:
            yield event


class RecordingPermissionHost:
    def __init__(self) -> None:
        self.requests: list[PermissionRequest] = []

    async def request_permission(self, request: PermissionRequest):
        self.requests.append(request)
        return PermissionDecision(PermissionBehavior.ALLOW, "approved")


class CapturingPermissionService:
    def __init__(self) -> None:
        self.contexts: list[object] = []

    async def evaluate(self, request, *, initial_decision=None, hook_result=None, runtime_context=None):
        _ = request, initial_decision, hook_result
        self.contexts.append(runtime_context)
        return PermissionDecision(PermissionBehavior.ALLOW)

    async def authorize(self, definition, tool_input, decision, context):  # pragma: no cover - protocol completeness
        _ = definition, tool_input, decision, context
        return PermissionDecision(PermissionBehavior.ALLOW)


def test_permission_engine_uses_runtime_control_plane_context_host() -> None:
    host = RecordingPermissionHost()
    services = RuntimeServices(host=host)
    engine = PermissionEngine()
    context = RuntimeControlPlaneContext(
        runtime_services=services,
        permission_context=PermissionContext(session_id="session", mode=PermissionMode.DEFAULT),
    )

    outcome = asyncio.run(
        engine.evaluate(
            PermissionRequest(
                session_id="session",
                turn_id="turn",
                target=PermissionTarget.AGENT,
                name="verification",
                payload={"prompt": "run checks"},
                context=context.permission_context,
                message="permission needed",
            ),
            initial_decision=PermissionDecision(PermissionBehavior.ASK, "permission needed"),
            runtime_context=context,
        )
    )

    assert outcome.behavior == PermissionBehavior.ALLOW
    assert host.requests[0].session_id == "session"
    assert host.requests[0].name == "verification"


def test_shared_elicitation_service_uses_runtime_control_plane_context_hooks() -> None:
    services = RuntimeServices()
    services.hook_bus.register(
        session_id="session",
        owner="test",
        phase=RuntimeHookPhase.ELICITATION,
        handler=lambda _payload: HookEffect(elicitation_result={"response": "hooked"}),
    )
    context = RuntimeControlPlaneContext(runtime_services=services)

    response = asyncio.run(
        SharedElicitationService().request(
            ElicitationRequest(
                session_id="session",
                turn_id="turn",
                prompt="Need input?",
            ),
            runtime_context=context,
        )
    )

    assert response.response == {"response": "hooked"}
    assert response.source == "hook"


def test_agent_and_skill_permission_paths_use_runtime_control_plane_context(tmp_path: Path) -> None:
    permission_service = CapturingPermissionService()
    services = RuntimeServices(permissions=permission_service)
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agent"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentDefinition(name="verification", description="verify", prompt="verify")
    )
    skill_registry = SkillRegistry()
    skill_registry.register(
        SkillDefinition(name="inline-skill", description="inline", content="inline content")
    )
    turn_engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        task_manager=TaskManager(),
        runtime_services=services,
    )
    runtime = AgentRuntime(
        turn_engine=turn_engine,
        agent_registry=agent_registry,
        tool_registry=ToolRegistry(),
        skill_registry=skill_registry,
        task_manager=TaskManager(),
        runtime_services=services,
    )
    skill_executor = SkillExecutor(
        skill_registry=skill_registry,
        agent_runtime=runtime,
        runtime_services=services,
    )

    async def scenario() -> None:
        await runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="run checks",
                session_id="session",
                cwd=tmp_path,
                query_source="skill_fork",
                spawn_mode=SpawnMode.FORK,
            )
        )
        await skill_executor.execute(
            "inline-skill",
            arguments=(),
            session_id="session",
            cwd=tmp_path,
            runtime_metadata={
                "agent_name": "planner",
                "query_source": "tool",
                "spawn_mode": "sync",
                "delegation_depth": 1,
            },
        )

    asyncio.run(scenario())

    assert len(permission_service.contexts) == 2
    assert all(isinstance(context, RuntimeControlPlaneContext) for context in permission_service.contexts)
    assert {
        getattr(context.permission_context, "session_id", None)
        for context in permission_service.contexts
    } == {"session"}
    agent_context, skill_context = permission_service.contexts
    assert agent_context.metadata["agent_name"] == "verification"
    assert agent_context.metadata["query_source"] == "skill_fork"
    assert agent_context.metadata["spawn_mode"] == SpawnMode.FORK
    assert agent_context.metadata["delegation_depth"] == 1
    assert skill_context.metadata["agent_name"] == "planner"
    assert skill_context.metadata["query_source"] == "tool"
    assert skill_context.metadata["spawn_mode"] == "sync"
    assert skill_context.metadata["delegation_depth"] == 1


def test_delegated_agent_permission_scope_rules_use_runtime_control_plane_metadata(tmp_path: Path) -> None:
    services = RuntimeServices(permissions=PermissionEngine())
    model_client = FakeModelClient([])
    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentDefinition(name="worker", description="worker", prompt="verify")
    )
    turn_engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        agent_registry=agent_registry,
        skill_registry=SkillRegistry(),
        task_manager=TaskManager(),
        runtime_services=services,
    )
    runtime = AgentRuntime(
        turn_engine=turn_engine,
        agent_registry=agent_registry,
        tool_registry=ToolRegistry(),
        skill_registry=SkillRegistry(),
        task_manager=TaskManager(),
        runtime_services=services,
    )
    permission_context = PermissionContext(
        session_id="session",
        policies=(
            PermissionPolicy(
                name="deny-delegated-workers",
                rules=(
                    PermissionRule(
                        selector="worker",
                        target=PermissionTarget.AGENT,
                        scopes=("delegated",),
                        behavior=PermissionBehavior.DENY,
                        message="delegated workers require approval",
                    ),
                ),
            ),
        ),
    )

    result = asyncio.run(
        runtime.invoke(
            AgentInvocation(
                agent_name="worker",
                prompt="run checks",
                session_id="session",
                cwd=tmp_path,
                query_source="skill_fork",
                spawn_mode=SpawnMode.FORK,
                metadata={
                    "permission_context": permission_context,
                },
            )
        )
    )

    assert result.status == "denied"
    assert result.run_record is not None
    assert result.run_record.terminal_metadata["error"] == "delegated workers require approval"


def test_delegated_skill_permission_scope_rules_use_runtime_control_plane_metadata(tmp_path: Path) -> None:
    services = RuntimeServices(permissions=PermissionEngine())
    agent_registry = AgentRegistry()
    skill_registry = SkillRegistry()
    skill_registry.register(
        SkillDefinition(name="inline-skill", description="inline", content="inline content")
    )
    turn_engine = TurnEngine(
        model_client=FakeModelClient([]),
        tool_registry=ToolRegistry(),
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        task_manager=TaskManager(),
        runtime_services=services,
    )
    runtime = AgentRuntime(
        turn_engine=turn_engine,
        agent_registry=agent_registry,
        tool_registry=ToolRegistry(),
        skill_registry=skill_registry,
        task_manager=TaskManager(),
        runtime_services=services,
    )
    skill_executor = SkillExecutor(
        skill_registry=skill_registry,
        agent_runtime=runtime,
        runtime_services=services,
    )
    permission_context = PermissionContext(
        session_id="session",
        policies=(
            PermissionPolicy(
                name="deny-delegated-inline-skills",
                rules=(
                    PermissionRule(
                        selector="inline-skill",
                        target=PermissionTarget.SKILL,
                        scopes=("delegated",),
                        behavior=PermissionBehavior.DENY,
                        message="delegated inline skills require approval",
                    ),
                ),
            ),
        ),
    )

    try:
        asyncio.run(
            skill_executor.execute(
                "inline-skill",
                arguments=(),
                session_id="session",
                cwd=tmp_path,
                permission_context=permission_context,
                runtime_metadata={
                    "agent_name": "planner",
                    "query_source": "tool",
                    "delegation_depth": 1,
                },
            )
        )
    except PermissionError as exc:
        assert str(exc) == "delegated inline skills require approval"
    else:  # pragma: no cover - regression guard
        raise AssertionError("expected delegated skill policy to deny execution")


def test_runtime_policy_trace_includes_effective_default_preset_layers(tmp_path: Path) -> None:
    services = RuntimeServices(permissions=AllowAllPermissionService())
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agent"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    agent_registry = AgentRegistry()
    agent_registry.register(
        AgentDefinition(name="verification", description="verify", prompt="verify")
    )
    turn_engine = TurnEngine(
        model_client=model_client,
        tool_registry=ToolRegistry(),
        agent_registry=agent_registry,
        skill_registry=SkillRegistry(),
        task_manager=TaskManager(),
        runtime_services=services,
    )
    runtime = AgentRuntime(
        turn_engine=turn_engine,
        agent_registry=agent_registry,
        tool_registry=ToolRegistry(),
        skill_registry=SkillRegistry(),
        task_manager=TaskManager(),
        runtime_services=services,
    )

    result = asyncio.run(
        runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="run checks",
                session_id="session",
                cwd=tmp_path,
            )
        )
    )

    assert result.status == "completed"
    assert [layer["name"] for layer in model_client.requests[0].metadata["policy"]["effective"]["permission_policies"]] == [
        "preset:allow-all",
    ]
