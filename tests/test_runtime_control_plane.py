import asyncio
from pathlib import Path

from runtime.agent_runtime import AgentInvocation, AgentRuntime
from runtime.control_plane import RuntimeControlPlaneContext
from runtime.definitions import (
    AgentDefinition,
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    SkillDefinition,
)
from runtime.elicitation import ElicitationRequest, SharedElicitationService
from runtime.hooks import HookEffect, RuntimeHookPhase
from runtime.permissions import (
    PermissionContext,
    PermissionEngine,
    PermissionRequest,
    PermissionTarget,
)
from runtime.registries import AgentRegistry, SkillRegistry, ToolRegistry
from runtime.runtime_services import RuntimeServices
from runtime.skill_runtime import SkillExecutor
from runtime.tasking import TaskManager
from runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, TurnEngine


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
            )
        )
        await skill_executor.execute(
            "inline-skill",
            arguments=(),
            session_id="session",
            cwd=tmp_path,
        )

    asyncio.run(scenario())

    assert len(permission_service.contexts) == 2
    assert all(isinstance(context, RuntimeControlPlaneContext) for context in permission_service.contexts)
    assert {
        getattr(context.permission_context, "session_id", None)
        for context in permission_service.contexts
    } == {"session"}
