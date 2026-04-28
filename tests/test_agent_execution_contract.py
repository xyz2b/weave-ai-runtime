import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from weavert.agent_execution import AgentRunRecord, AgentRunStatus, SpawnMode
from weavert.child_result_projection import summarize_child_run_record
from weavert.agent_execution_service import _agent_run_status_from_turn_result
from weavert.agent_runtime import AgentInvocation, AgentRuntime
from weavert.context_window import ModelContextWindowProfile, RouteContextWindowPolicy, TokenEstimationHint
from weavert.contracts import MessageRole, RuntimeMessage
from weavert.definitions import (
    AgentDefinition,
    IsolationMode,
    PermissionBehavior,
    PermissionDecision,
    ToolDefinition,
    ToolTraits,
)
from weavert.execution_policy import ChildResultProjectionMode, resolve_delegation_policy
from weavert.hooks import RuntimeHookPhase
from weavert.registries import AgentRegistry, SkillRegistry, ToolRegistry
from weavert.runtime_kernel import ModelProviderBinding, ModelRouteBinding
from weavert.runtime_services import RuntimeServices
from weavert.tasking import TaskManager, TaskStatus
from weavert.turn_engine import (
    ModelInvocationMode,
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    NormalizedModelCapabilities,
    TurnEngine,
)


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


def test_delegation_policy_parsing_defaults_and_overrides() -> None:
    default_policy = resolve_delegation_policy({})
    assert default_policy.max_depth == 1
    assert default_policy.child_result_projection == ChildResultProjectionMode.SUMMARY
    assert default_policy.summary_max_chars == 2000

    overridden = resolve_delegation_policy(
        {
            "delegation": {
                "max_depth": "3",
                "child_result_projection": "detailed",
                "summary_max_chars": "120",
            }
        }
    )
    assert overridden.max_depth == 3
    assert overridden.child_result_projection == ChildResultProjectionMode.DETAILED
    assert overridden.summary_max_chars == 120


def test_failed_child_summary_uses_runtime_fallback_even_with_assistant_output() -> None:
    record = AgentRunRecord(
        run_id="child-run-failed",
        parent_run_id="parent-run",
        session_id="session-failed-summary",
        parent_turn_id="parent-turn",
        turn_id="child-turn",
        agent_name="verification",
        spawn_mode=SpawnMode.SYNC,
        status=AgentRunStatus.FAILED,
        terminal_metadata={"error": "approval required"},
        messages=(
            RuntimeMessage(
                message_id="assistant-before-failure",
                role=MessageRole.ASSISTANT,
                content="partial success before failure",
            ),
        ),
    )

    assert summarize_child_run_record(record) == (
        "Child run 'verification' ended with status 'failed': approval required"
    )


def test_child_delegation_depth_is_threaded_into_spec_request_and_record(tmp_path: Path) -> None:
    async def scenario():
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-delegation-depth"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "depth ok"}),
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
            )
        )
        services = RuntimeServices(metadata={"delegation": {"max_depth": 3}})
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
                prompt="run checks",
                session_id="session-child-depth",
                cwd=tmp_path,
                query_source="agent_tool",
                parent_run_id="parent-run-depth",
                parent_turn_id="parent-turn-depth",
                metadata={"delegation_depth": 1},
            )
        )
        record = await runtime.run_store.get(result.run_id)
        return model_client, result, record

    model_client, result, record = asyncio.run(scenario())

    assert result.execution_spec is not None
    assert result.execution_spec.delegation_depth == 2
    assert model_client.requests[0].metadata["delegation_depth"] == 2
    assert record is not None
    assert record.delegation_depth == 2
    assert record.request_metadata["delegation_depth"] == 2


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
            model_routes={
                "reviewer-route": ModelRouteBinding(
                    client=model_client,
                    default_model="base-model",
                    provider_name="provider-reviewer",
                    capabilities=NormalizedModelCapabilities(),
                )
            },
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


def test_agent_default_model_does_not_overwrite_requested_model_metadata(tmp_path: Path) -> None:
    async def scenario():
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-default-model"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "default model answer"}),
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
                model="agent-default-model",
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
                session_id="session-default-model",
                cwd=tmp_path,
            )
        )
        record = await runtime.run_store.get(result.run_id)
        return model_client, result, record

    model_client, result, record = asyncio.run(scenario())

    assert result.execution_spec is not None
    assert result.execution_spec.requested_model is None
    assert model_client.requests[0].model == "agent-default-model"
    assert model_client.requests[0].metadata["requested_model"] is None
    assert record is not None
    assert record.requested_model is None
    assert record.request_metadata["requested_model"] is None


def test_route_owned_context_window_snapshot_is_threaded_with_precedence_and_narrowing(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[FakeModelClient, object]:
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-context-window"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "context aware answer"}),
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
            model_routes={
                "reviewer-route": ModelRouteBinding(
                    client=model_client,
                    default_model="gpt-4.1-mini",
                    provider_name="provider-reviewer",
                    capabilities=NormalizedModelCapabilities(),
                    context_window_profiles=(
                        ModelContextWindowProfile(
                            provider_name="provider-reviewer",
                            model_selector=None,
                            max_input_tokens=50,
                            reserved_output_tokens=8,
                            token_estimation_hint=TokenEstimationHint(chars_per_token=1.0),
                            source="integration",
                            confidence="medium",
                        ),
                        ModelContextWindowProfile(
                            provider_name="provider-reviewer",
                            model_selector="gpt-4.1-*",
                            max_input_tokens=80,
                            reserved_output_tokens=10,
                            token_estimation_hint=TokenEstimationHint(chars_per_token=1.0),
                            source="integration",
                            confidence="medium",
                        ),
                        ModelContextWindowProfile(
                            provider_name="provider-reviewer",
                            model_selector="gpt-4.1-mini",
                            max_input_tokens=120,
                            reserved_output_tokens=12,
                            token_estimation_hint=TokenEstimationHint(chars_per_token=1.0),
                            source="integration",
                            confidence="high",
                        ),
                    ),
                    context_window_policy=RouteContextWindowPolicy(
                        narrow_to_max_input_tokens=90,
                        reserved_output_tokens_override=16,
                        trigger_buffer_tokens=8,
                        policy_tag="reviewer-policy",
                    ),
                )
            },
        )
        result = await runtime.invoke(
            AgentInvocation(
                agent_name="verification",
                prompt="abcdefghij",
                session_id="session-context-window",
                cwd=tmp_path,
                requested_model_route="reviewer-route",
            )
        )
        return model_client, result

    model_client, result = asyncio.run(scenario())

    request = model_client.requests[0]
    assert request.context_window is not None
    assert request.context_window.max_input_tokens == 90
    assert request.context_window.reserved_output_tokens == 16
    assert request.context_window.source == "route_override"
    assert request.context_window.fallback_mode == "proactive_and_reactive"
    assert request.metadata["context_window"]["max_input_tokens"] == 90
    assert request.metadata["context_window_policy_tag"] == "reviewer-policy"
    assert request.metadata["control_plane"]["context_window_policy_tag"] == "reviewer-policy"
    assert result.execution_spec is not None
    assert result.execution_spec.metadata["provider_context_window_profiles"][2]["model_selector"] == "gpt-4.1-mini"


def test_model_route_binding_rejects_duplicate_exact_context_window_profiles() -> None:
    with pytest.raises(ValueError, match="duplicate_exact_profile"):
        ModelRouteBinding(
            client=FakeModelClient([]),
            provider_name="provider-reviewer",
            context_window_profiles=(
                ModelContextWindowProfile(
                    provider_name="provider-reviewer",
                    model_selector="gpt-4.1-mini",
                    max_input_tokens=120,
                ),
                ModelContextWindowProfile(
                    provider_name="provider-reviewer",
                    model_selector="gpt-4.1-mini",
                    max_input_tokens=240,
                ),
            ),
        )


def test_model_provider_binding_rejects_overlapping_pattern_context_window_profiles() -> None:
    with pytest.raises(ValueError, match="ambiguous_pattern_profile"):
        ModelProviderBinding(
            client=FakeModelClient([]),
            provider_name="provider-reviewer",
            context_window_profiles=(
                ModelContextWindowProfile(
                    provider_name="provider-reviewer",
                    model_selector="gpt-*",
                    max_input_tokens=120,
                ),
                ModelContextWindowProfile(
                    provider_name="provider-reviewer",
                    model_selector="gpt-4.*",
                    max_input_tokens=240,
                ),
            ),
        )


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


def test_remote_isolation_without_backend_fails_before_model_execution(tmp_path: Path) -> None:
    async def scenario():
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-remote-missing"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "should not run"}),
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
                isolation=IsolationMode.REMOTE,
            )
        )
        services = RuntimeServices()
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
        error = None
        try:
            await runtime.invoke(
                AgentInvocation(
                    agent_name="verification",
                    prompt="remote run",
                    session_id="session-remote-missing",
                    cwd=tmp_path,
                )
            )
        except RuntimeError as exc:
            error = str(exc)
        records = await runtime.run_store.list_by_session("session-remote-missing")
        return model_client, error, records

    model_client, error, records = asyncio.run(scenario())

    assert error == "remote isolation is not configured"
    assert model_client.requests == []
    assert len(records) == 1
    assert records[0].terminal_metadata["isolation"] == {
        "code": "not_configured",
        "mode": "remote",
        "details": {
            "contract": "remote",
            "requested_mode": "remote",
            "effective_mode": "remote",
            "cwd": str(tmp_path),
            "adapter": "RemoteIsolationAdapter",
        },
    }


def test_background_max_turns_marks_task_stopped(tmp_path: Path) -> None:
    async def noop(_: dict[str, object], __) -> dict[str, bool]:
        return {"ok": True}

    async def scenario():
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-max-turns"}),
                    ModelStreamEvent(
                        ModelStreamEventType.TOOL_CALL,
                        {"tool_name": "noop", "tool_input": {}, "call_id": "call-noop"},
                    ),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
                ]
            ]
        )
        tool_registry = ToolRegistry()
        tool_registry.register(
            ToolDefinition(
                name="noop",
                description="noop",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                traits=ToolTraits(read_only=True, concurrency_safe=True),
                execute=noop,
            )
        )
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(
                name="reviewer",
                description="review",
                prompt="review",
                tools=("*",),
                max_turns=1,
            )
        )
        task_manager = TaskManager()
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=model_client,
                tool_registry=tool_registry,
                agent_registry=agent_registry,
                skill_registry=SkillRegistry(),
                task_manager=task_manager,
            ),
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            skill_registry=SkillRegistry(),
            task_manager=task_manager,
        )
        initial = await runtime.invoke(
            AgentInvocation(
                agent_name="reviewer",
                prompt="hit the max turn limit",
                session_id="session-background-max-turns",
                cwd=tmp_path,
                background=True,
            )
        )
        completed = await runtime.wait_for_background(initial.task_id)
        task = runtime.runtime_services.task_manager.get(initial.task_id)
        record = await runtime.run_store.get(initial.run_id)
        return initial, completed, task, record

    initial, completed, task, record = asyncio.run(scenario())

    assert initial.status == "running"
    assert completed.status == "max_turns"
    assert completed.notification is not None
    assert completed.notification.text == "Background agent 'reviewer' stopped after reaching the max turn limit"
    assert task is not None
    assert task.status == TaskStatus.STOPPED
    assert task.error is None
    assert task.metadata["agent_status"] == "max_turns"
    assert record is not None
    assert record.status == AgentRunStatus.MAX_TURNS


def test_child_run_status_projection_uses_terminal_reason() -> None:
    assert _agent_run_status_from_turn_result(SimpleNamespace(stop_reason="end_turn")) == AgentRunStatus.COMPLETED
    assert _agent_run_status_from_turn_result(SimpleNamespace(stop_reason="message_stop")) == AgentRunStatus.COMPLETED
    assert _agent_run_status_from_turn_result(SimpleNamespace(stop_reason="max_turns")) == AgentRunStatus.MAX_TURNS
    assert _agent_run_status_from_turn_result(SimpleNamespace(stop_reason="blocked")) == AgentRunStatus.FAILED
    assert _agent_run_status_from_turn_result(SimpleNamespace(stop_reason="error")) == AgentRunStatus.FAILED
    assert _agent_run_status_from_turn_result(SimpleNamespace(stop_reason="interrupted")) == AgentRunStatus.FAILED


def test_blocked_child_run_is_not_mislabeled_as_max_turns(tmp_path: Path) -> None:
    async def scenario():
        model_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-blocked-child"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "needs approval"}),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ]
            ]
        )
        services = RuntimeServices()
        services.hook_bus.register(
            session_id="session-blocked-child",
            owner="host:blocker",
            phase=RuntimeHookPhase.STOP,
            handler=lambda _payload: {"continue_execution": False},
        )
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(
                name="verification",
                description="verify",
                prompt="verify",
            )
        )
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
                prompt="run checks",
                session_id="session-blocked-child",
                cwd=tmp_path,
            )
        )
        record = await runtime.run_store.get(result.run_id)
        return result, record

    result, record = asyncio.run(scenario())

    assert result.status == AgentRunStatus.FAILED.value
    assert record is not None
    assert record.status == AgentRunStatus.FAILED
    assert record.terminal_metadata["stop_reason"] == "blocked"


def test_route_resolution_uses_request_scoped_clients_and_persists_metadata(tmp_path: Path) -> None:
    async def scenario():
        route_a_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-route-a-1"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "route a"}),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ],
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-route-a-2"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "route a override"}),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ],
            ]
        )
        route_b_client = FakeModelClient(
            [
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-route-b-1"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "route b"}),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ],
                [
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-route-b-2"}),
                    ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "route b explicit"}),
                    ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                ],
            ]
        )
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(
                name="reviewer",
                description="review",
                prompt="review",
                model_route="route-a",
                model="route-a-default",
            )
        )
        agent_registry.register(
            AgentDefinition(
                name="analyst",
                description="analyze",
                prompt="analyze",
                model_route="route-b",
                model="route-b-default",
            )
        )
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=route_a_client,
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=SkillRegistry(),
                task_manager=TaskManager(),
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=SkillRegistry(),
            task_manager=TaskManager(),
            model_routes={
                "route-a": ModelRouteBinding(
                    client=route_a_client,
                    default_model="route-a-default",
                    provider_name="provider-a",
                    capabilities=NormalizedModelCapabilities(),
                ),
                "route-b": ModelRouteBinding(
                    client=route_b_client,
                    default_model="route-b-default",
                    provider_name="provider-b",
                    capabilities=NormalizedModelCapabilities(),
                ),
            },
            default_model_route="route-a",
        )
        first = await runtime.invoke(
            AgentInvocation(
                agent_name="reviewer",
                prompt="first",
                session_id="session-route",
                cwd=tmp_path,
            )
        )
        second = await runtime.invoke(
            AgentInvocation(
                agent_name="reviewer",
                prompt="second",
                session_id="session-route",
                cwd=tmp_path,
                requested_model="custom-route-a-model",
            )
        )
        third = await runtime.invoke(
            AgentInvocation(
                agent_name="analyst",
                prompt="third",
                session_id="session-route",
                cwd=tmp_path,
            )
        )
        fourth = await runtime.invoke(
            AgentInvocation(
                agent_name="reviewer",
                prompt="fourth",
                session_id="session-route",
                cwd=tmp_path,
                requested_model_route="route-b",
                requested_model="custom-route-b-model",
            )
        )
        record = await runtime.run_store.get(fourth.run_id)
        return route_a_client, route_b_client, (first, second, third, fourth, record)

    route_a_client, route_b_client, payload = asyncio.run(scenario())
    first, second, third, fourth, record = payload

    assert route_a_client.requests[0].resolved_model_route == "route-a"
    assert route_a_client.requests[0].provider_name == "provider-a"
    assert route_a_client.requests[0].model == "route-a-default"
    assert route_a_client.requests[1].resolved_model_route == "route-a"
    assert route_a_client.requests[1].model == "custom-route-a-model"
    assert route_b_client.requests[0].resolved_model_route == "route-b"
    assert route_b_client.requests[0].provider_name == "provider-b"
    assert route_b_client.requests[0].model == "route-b-default"
    assert route_b_client.requests[1].requested_model_route == "route-b"
    assert route_b_client.requests[1].resolved_model_route == "route-b"
    assert route_b_client.requests[1].model == "custom-route-b-model"
    assert route_b_client.requests[1].invocation_mode == ModelInvocationMode.STREAM
    assert first.execution_spec is not None
    assert first.execution_spec.resolved_model_route == "route-a"
    assert third.execution_spec is not None
    assert third.execution_spec.resolved_model_route == "route-b"
    assert fourth.execution_spec is not None
    assert fourth.execution_spec.resolved_model_route == "route-b"
    assert record is not None
    assert record.resolved_model_route == "route-b"
    assert record.provider_name == "provider-b"
    assert record.invocation_mode == ModelInvocationMode.STREAM.value


def test_unknown_route_override_fails_before_model_request(tmp_path: Path) -> None:
    async def scenario():
        default_client = FakeModelClient([])
        route_a_client = FakeModelClient([])
        agent_registry = AgentRegistry()
        agent_registry.register(
            AgentDefinition(
                name="reviewer",
                description="review",
                prompt="review",
            )
        )
        runtime = AgentRuntime(
            turn_engine=TurnEngine(
                model_client=default_client,
                tool_registry=ToolRegistry(),
                agent_registry=agent_registry,
                skill_registry=SkillRegistry(),
                task_manager=TaskManager(),
            ),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            skill_registry=SkillRegistry(),
            task_manager=TaskManager(),
            model_routes={
                "route-a": ModelRouteBinding(
                    client=route_a_client,
                    default_model="route-a-default",
                    provider_name="provider-a",
                    capabilities=NormalizedModelCapabilities(),
                )
            },
            default_model_route="route-a",
        )
        error = None
        try:
            await runtime.invoke(
                AgentInvocation(
                    agent_name="reviewer",
                    prompt="review this",
                    session_id="session-invalid-route",
                    cwd=tmp_path,
                    requested_model_route="missing-route",
                )
            )
        except ValueError as exc:
            error = str(exc)
        return default_client, route_a_client, error

    default_client, route_a_client, error = asyncio.run(scenario())

    assert error == "Unknown model route: missing-route"
    assert default_client.requests == []
    assert route_a_client.requests == []
