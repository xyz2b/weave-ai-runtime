import asyncio
from pathlib import Path

from claude_agent_runtime.agent_execution import AgentRunStatus, SpawnMode
from claude_agent_runtime.agent_runtime import AgentInvocation, AgentRuntime
from claude_agent_runtime.contracts import MessageRole
from claude_agent_runtime.definitions import AgentDefinition, PermissionBehavior, PermissionDecision
from claude_agent_runtime.registries import AgentRegistry, SkillRegistry, ToolRegistry
from claude_agent_runtime.runtime_services import RuntimeServices
from claude_agent_runtime.tasking import TaskManager, TaskStatus
from claude_agent_runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, TurnEngine


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


class DenyingPermissionService:
    async def evaluate(self, request, *, initial_decision=None, hook_result=None, runtime_context=None):
        _ = request, initial_decision, hook_result, runtime_context
        return PermissionDecision(PermissionBehavior.DENY, "blocked by policy")

    async def authorize(self, definition, tool_input, decision, context):  # pragma: no cover - protocol completeness
        _ = definition, tool_input, decision, context
        return PermissionDecision(PermissionBehavior.DENY, "blocked by policy")


class FailingIsolationService:
    async def prepare(self, **kwargs):
        _ = kwargs
        raise RuntimeError("isolation prepare failed")

    async def cleanup(self, lease):  # pragma: no cover - protocol completeness
        _ = lease


def test_sync_agent_execution_spec_and_run_record_are_structured(tmp_path: Path) -> None:
    async def scenario() -> tuple[AgentRuntime, FakeModelClient, object]:
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-sync"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "sync answer"}),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ]
            ]
        )
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(
                name="verification",
                description="verify",
                prompt="verify",
                model="base-model",
            )
        )
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=model_client,
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=SkillRegistry(),
                task_manager=TaskManager(),
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=SkillRegistry(),
            task_manager=TaskManager(),
        )
        result = await runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="run checks",
                session_id="session-sync",
                cwd=tmp_path,
                query_source="agent_tool",
                parent_run_id="parent-run-1",
                parent_turn_id="parent-turn-1",
                requested_model_route="reviewer-route",
                requested_model="override-model",
            )
        )
        record = await runtime.run_store.get(result.run_id)
        return runtime, model_client, (result, record)

    _, model_client, payload = asyncio.run(scenario())
    result, record = payload

    assert result.execution_spec is not None
    assert result.run_id == result.execution_spec.run_id
    assert result.parent_run_id == "parent-run-1"
    assert result.turn_id == result.execution_spec.turn_id
    assert result.query_source == "agent_tool"
    assert result.execution_spec.metadata.get("run_id") is None
    assert result.execution_spec.requested_model_route == "reviewer-route"
    assert model_client.requests[0].query_source == "agent_tool"
    assert model_client.requests[0].model == "override-model"
    assert model_client.requests[0].metadata["run_id"] == result.run_id
    assert model_client.requests[0].metadata["parent_run_id"] == "parent-run-1"
    assert model_client.requests[0].metadata["parent_turn_id"] == "parent-turn-1"
    assert model_client.requests[0].metadata["requested_model_route"] == "reviewer-route"
    assert model_client.requests[0].metadata["requested_model"] == "override-model"
    assert record is not None
    assert record.status == AgentRunStatus.COMPLETED
    assert record.run_id == result.run_id
    assert record.parent_run_id == "parent-run-1"
    assert record.parent_turn_id == "parent-turn-1"
    assert record.query_source == "agent_tool"
    assert record.requested_model_route == "reviewer-route"
    assert record.requested_model == "override-model"
    assert record.request_metadata["run_id"] == result.run_id
    assert record.request_metadata["spawn_mode"] == "sync"
    assert record.terminal_metadata["request_id"] == "req-sync"
    assert record.messages[-1].text == "sync answer"


def test_background_agent_writes_running_and_terminal_run_records(tmp_path: Path) -> None:
    async def scenario() -> tuple[AgentRuntime, object]:
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-bg"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "background answer"}),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ]
            ]
        )
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(name="verification", description="verify", prompt="verify")
        )
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=model_client,
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=SkillRegistry(),
                task_manager=TaskManager(),
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=SkillRegistry(),
            task_manager=TaskManager(),
        )
        initial = await runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="background run",
                session_id="session-background",
                cwd=tmp_path,
                background=True,
            )
        )
        running_record = await runtime.run_store.get(initial.run_id)
        completed = await runtime.wait_for_background(initial.task_id)
        terminal_record = await runtime.run_store.get(initial.run_id)
        task = runtime.runtime_services.task_manager.get(initial.task_id)
        return runtime, (initial, running_record, completed, terminal_record, task)

    _, payload = asyncio.run(scenario())
    initial, running_record, completed, terminal_record, task = payload

    assert initial.status == "running"
    assert initial.query_source == "background_agent"
    assert running_record is not None
    assert running_record.status == AgentRunStatus.RUNNING
    assert running_record.request_metadata["spawn_mode"] == "background"
    assert completed.status == "completed"
    assert completed.notification is not None
    assert completed.notification.role == MessageRole.NOTIFICATION
    assert completed.notification.text == "Background agent 'verification' completed"
    assert terminal_record is not None
    assert terminal_record.status == AgentRunStatus.COMPLETED
    assert terminal_record.run_id == initial.run_id
    assert terminal_record.turn_id == initial.turn_id
    assert terminal_record.messages[-1].text == "background answer"
    assert task is not None
    assert task.status == TaskStatus.COMPLETED
    assert task.metadata["agent_status"] == "completed"


def test_denied_agent_still_produces_minimal_run_record(tmp_path: Path) -> None:
    async def scenario():
        model_client = FakeModelClient([])
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(name="verification", description="verify", prompt="verify")
        )
        services = RuntimeServices(permissions=DenyingPermissionService())
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=model_client,
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=SkillRegistry(),
                task_manager=TaskManager(),
                runtime_services=services,
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=SkillRegistry(),
            task_manager=TaskManager(),
            runtime_services=services,
        )
        result = await runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="blocked run",
                session_id="session-denied",
                cwd=tmp_path,
                query_source="agent_tool",
                parent_turn_id="parent-turn-2",
            )
        )
        record = await runtime.run_store.get(result.run_id)
        return model_client, result, record

    model_client, result, record = asyncio.run(scenario())

    assert result.status == "denied"
    assert result.run_id is not None
    assert model_client.requests == []
    assert record is not None
    assert record.status == AgentRunStatus.DENIED
    assert record.parent_turn_id == "parent-turn-2"
    assert record.query_source == "agent_tool"
    assert record.request_metadata["run_id"] == result.run_id
    assert record.terminal_metadata["permission_denied"] is True
    assert record.messages[0].metadata["permission_denied"] is True


def test_explicit_spawn_mode_sync_overrides_background_agent_default(tmp_path: Path) -> None:
    async def scenario():
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-sync-override"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "sync override"}),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ]
            ]
        )
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(
                name="verification",
                description="verify",
                prompt="verify",
                background=True,
            )
        )
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=model_client,
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=SkillRegistry(),
                task_manager=TaskManager(),
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=SkillRegistry(),
            task_manager=TaskManager(),
        )
        result = await runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="run checks",
                session_id="session-sync-override",
                cwd=tmp_path,
                spawn_mode=SpawnMode.SYNC,
            )
        )
        return runtime, model_client, result

    runtime, model_client, result = asyncio.run(scenario())

    assert result.status == "completed"
    assert result.background is False
    assert result.task_id is None
    assert result.execution_spec is not None
    assert result.execution_spec.spawn_mode == SpawnMode.SYNC
    assert result.execution_spec.background is False
    assert result.query_source == "agent_invocation"
    assert model_client.requests[0].query_source == "agent_invocation"
    assert runtime.runtime_services.task_manager.list() == ()


def test_background_denied_agent_marks_task_failed_and_emits_denied_notification(tmp_path: Path) -> None:
    async def scenario():
        model_client = FakeModelClient([])
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(name="verification", description="verify", prompt="verify")
        )
        services = RuntimeServices(permissions=DenyingPermissionService())
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=model_client,
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=SkillRegistry(),
                task_manager=TaskManager(),
                runtime_services=services,
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=SkillRegistry(),
            task_manager=TaskManager(),
            runtime_services=services,
        )
        initial = await runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="blocked run",
                session_id="session-background-denied",
                cwd=tmp_path,
                background=True,
            )
        )
        completed = await runtime.wait_for_background(initial.task_id)
        record = await runtime.run_store.get(initial.run_id)
        task = runtime.runtime_services.task_manager.get(initial.task_id)
        return runtime, initial, completed, record, task

    runtime, initial, completed, record, task = asyncio.run(scenario())

    assert initial.status == "running"
    assert completed.status == "denied"
    assert completed.notification is not None
    assert completed.notification.text == "Background agent 'verification' was denied: blocked by policy"
    assert record is not None
    assert record.status == AgentRunStatus.DENIED
    assert task is not None
    assert task.status == TaskStatus.FAILED
    assert task.error == "blocked by policy"
    assert task.metadata["agent_status"] == "denied"
    assert runtime.notifications[-1].text == completed.notification.text


def test_background_failure_marks_task_failed_and_emits_failure_notification(tmp_path: Path) -> None:
    async def scenario():
        model_client = FakeModelClient([])
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(name="verification", description="verify", prompt="verify")
        )
        services = RuntimeServices(isolation=FailingIsolationService())
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=model_client,
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=SkillRegistry(),
                task_manager=TaskManager(),
                runtime_services=services,
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=SkillRegistry(),
            task_manager=TaskManager(),
            runtime_services=services,
        )
        initial = await runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="failing run",
                session_id="session-background-failed",
                cwd=tmp_path,
                background=True,
            )
        )
        error = None
        try:
            await runtime.wait_for_background(initial.task_id)
        except RuntimeError as exc:
            error = str(exc)
        task = runtime.runtime_services.task_manager.get(initial.task_id)
        record = await runtime.run_store.get(initial.run_id)
        return runtime, initial, error, task, record

    runtime, initial, error, task, record = asyncio.run(scenario())

    assert initial.status == "running"
    assert error == "isolation prepare failed"
    assert task is not None
    assert task.status == TaskStatus.FAILED
    assert task.error == "isolation prepare failed"
    assert task.metadata["agent_status"] == "failed"
    assert record is not None
    assert record.status == AgentRunStatus.FAILED
    assert record.terminal_metadata["error"] == "isolation prepare failed"
    assert runtime.notifications[-1].text == "Background agent 'verification' failed: isolation prepare failed"
