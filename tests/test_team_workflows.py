import asyncio
from datetime import timedelta
from pathlib import Path

from runtime import (
    AgentDefinition,
    BuiltinPackConfig,
    PermissionBehavior,
    PermissionOutcome,
    RuntimeConfig,
    SessionStatus,
    TeamControlError,
    TeamWorkflowActorKind,
    TeamWorkflowError,
    TeammateOrchestrationConfig,
    assemble_runtime,
    build_workflow_request_protocol,
    build_workflow_response_protocol,
    parse_workflow_request_protocol,
    parse_workflow_response_protocol,
)
from runtime.tool_runtime import ToolCall, ToolContext, ToolScheduler
from runtime.turn_engine import ModelStreamEvent, ModelStreamEventType


class FakeModelClient:
    def __init__(self, event_batches: list[list[ModelStreamEvent]]) -> None:
        self._event_batches = [list(batch) for batch in event_batches]

    async def complete(self, request):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request):
        if not self._event_batches:
            raise AssertionError("No fake model batch available")
        batch = self._event_batches.pop(0)
        for event in batch:
            yield event


class ControlledPermissionHost:
    def __init__(self) -> None:
        self.name = "controlled"
        self.requests = []
        self.notifications = []
        self.team_events = []

    async def startup(self) -> None:
        return None

    async def ready(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def request_permission(self, request):
        self.requests.append(request)
        return PermissionOutcome(PermissionBehavior.ALLOW, message="approved", source="host")

    async def request_elicitation(self, request):  # pragma: no cover - protocol completeness
        _ = request
        raise RuntimeError("elicitation not used in this test")

    def current_notifications(self):
        return tuple(self.notifications)

    async def emit_notification(self, message) -> None:
        self.notifications.append(message)

    async def emit_turn_event(self, session_id: str, event) -> None:
        _ = session_id, event
        return None

    async def emit_team_event(self, event) -> None:
        self.team_events.append(event)


def _worker_runtime(tmp_path: Path, *, model_batches: list[list[ModelStreamEvent]]):
    return assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient(model_batches),
            builtins=BuiltinPackConfig(
                extra_agents=[
                    AgentDefinition(
                        name="worker",
                        description="persistent teammate worker",
                        prompt="work mailbox",
                        tools=("*",),
                    )
                ]
            ),
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )


def _tool_context(runtime, *, session_id: str, cwd: Path, metadata: dict[str, object] | None = None):
    return ToolContext(
        session_id=session_id,
        turn_id="turn-1",
        agent_name="main-router",
        cwd=cwd,
        tool_registry=runtime.kernel.tool_registry,
        agent_registry=runtime.kernel.agent_registry,
        skill_registry=runtime.kernel.skill_registry,
        tool_pool=tuple(runtime.kernel.tool_registry.definitions()),
        skill_pool=tuple(runtime.kernel.skill_registry.definitions()),
        task_manager=runtime.task_manager,
        permission_handler=runtime.services.permission_handler,
        ask_user_handler=runtime.services.ask_user_handler,
        agent_runner=runtime.services.agent_runner,
        skill_runner=runtime.services.skill_runner,
        runtime_services=runtime.services,
        metadata=metadata or {},
    )


async def _wait_for(predicate, *, attempts: int = 500, delay: float = 0.01):
    for _ in range(attempts):
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return result
        await asyncio.sleep(delay)
    raise AssertionError("condition was not satisfied before timeout")


def test_permission_workflow_blocks_host_until_approved(tmp_path: Path) -> None:
    runtime = _worker_runtime(
        tmp_path,
        model_batches=[
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "bash",
                        "tool_input": {"command": "printf teammate"},
                        "call_id": "call-bash-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ],
    )
    host = ControlledPermissionHost()
    runtime.bind_host(host)
    plane = runtime.team_control_plane
    bus = runtime.team_message_bus
    workflows = runtime.team_workflows
    assert plane is not None
    assert bus is not None
    assert workflows is not None

    async def scenario():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="worker",
            execution_defaults={"cwd": str(tmp_path)},
        )
        await bus.send_public_message(
            session_id="leader-session",
            extensions={},
            to="alpha",
            message="run the privileged step",
        )
        workflow = None
        for _ in range(500):
            pending = workflows.list_workflows(team_id=team.team_id, pending_only=True)
            if pending:
                workflow = pending[0]
                break
            await asyncio.sleep(0.01)
        assert workflow is not None
        assert host.requests == []
        await workflows.respond_host(workflow_id=workflow.workflow_id, action="approve")
        for _ in range(500):
            if host.requests:
                break
            await asyncio.sleep(0.01)
        assert host.requests
        await plane.runner_manager.wait_for_idle(team_id=team.team_id, member_id=member.member_id)
        return workflows.get(workflow.workflow_id)

    record = asyncio.run(scenario())

    assert record is not None
    assert record.terminal is True
    assert record.status.value == "completed"


def test_team_respond_resolves_pending_permission_workflow(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=None,
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )
    plane = runtime.team_control_plane
    workflows = runtime.team_workflows
    assert plane is not None
    assert workflows is not None

    async def setup():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="main-router",
            execution_defaults={"cwd": str(tmp_path)},
        )
        workflow = await workflows.create_permission_workflow(
            team=team,
            requester_member_id=member.member_id,
            requester_name=member.name,
            responder_member_id=team.leader_member_id,
            responder_name="leader",
            request_payload={"permission_name": "bash", "permission_message": "approve?"},
        )
        leader = plane.get_member(team.team_id, team.leader_member_id)
        assert leader is not None
        return team, leader, workflow

    team, leader, workflow = asyncio.run(setup())
    scheduler = ToolScheduler(runtime.kernel.tool_registry)
    result = asyncio.run(
        scheduler.run(
            [ToolCall("1", "team_respond", {"workflow_id": workflow.workflow_id, "action": "reject"})],
            _tool_context(
                runtime,
                session_id="leader-session",
                cwd=tmp_path,
                metadata=plane.team_private_context(team, leader),
            ),
        )
    )

    assert result[0].status.value == "success"
    assert result[0].output["status"] == "rejected"
    assert result[0].output["workflow_kind"] == "permission"


def test_workflow_protocol_round_trip_and_unauthorized_response_is_rejected(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=None,
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )
    plane = runtime.team_control_plane
    workflows = runtime.team_workflows
    assert plane is not None
    assert workflows is not None

    async def setup():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="main-router",
            execution_defaults={"cwd": str(tmp_path)},
        )
        workflow = await workflows.create_permission_workflow(
            team=team,
            requester_member_id=member.member_id,
            requester_name=member.name,
            responder_member_id=team.leader_member_id,
            responder_name="leader",
            request_payload={"permission_name": "bash", "permission_message": "approve?"},
        )
        return team, member, workflow

    team, member, workflow = asyncio.run(setup())

    request_protocol = build_workflow_request_protocol(workflow)
    parsed_request = parse_workflow_request_protocol(request_protocol.to_dict())
    assert parsed_request is not None
    assert parsed_request.workflow_id == workflow.workflow_id
    assert parsed_request.allowed_actions == ("approve", "reject")

    scheduler = ToolScheduler(runtime.kernel.tool_registry)
    unauthorized = asyncio.run(
        scheduler.run(
            [ToolCall("1", "team_respond", {"workflow_id": workflow.workflow_id, "action": "reject"})],
            _tool_context(
                runtime,
                session_id="leader-session",
                cwd=tmp_path,
                metadata=plane.team_private_context(team, member),
            ),
        )
    )

    assert unauthorized[0].status.value == "error"
    assert unauthorized[0].output["error"]["code"] == "authority_denied"

    updated = asyncio.run(
        workflows.respond_host(workflow_id=workflow.workflow_id, action="reject")
    )
    response_protocol = build_workflow_response_protocol(
        updated,
        action="reject",
        actor_kind=TeamWorkflowActorKind.HOST,
        actor_id="host",
        payload=updated.response_payload,
    )
    parsed_response = parse_workflow_response_protocol(response_protocol.to_dict())
    assert parsed_response is not None
    assert parsed_response.workflow_id == workflow.workflow_id
    assert parsed_response.status.value == "rejected"


def test_shutdown_workflow_completes_before_member_cleanup(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=None,
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )
    plane = runtime.team_control_plane
    workflows = runtime.team_workflows
    assert plane is not None
    assert workflows is not None

    async def scenario():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="main-router",
            execution_defaults={"cwd": str(tmp_path)},
        )
        removed = await plane.remove_member(
            session_id="leader-session",
            extensions={},
            member_id=member.member_id,
        )
        records = workflows.list_workflows(team_id=team.team_id, pending_only=False)
        shutdowns = [record for record in records if record.workflow_kind.value == "shutdown"]
        return removed, shutdowns

    removed, shutdowns = asyncio.run(scenario())

    assert removed.status.value == "removed"
    assert shutdowns
    assert shutdowns[-1].terminal is True
    assert shutdowns[-1].status.value == "completed"


def test_permission_workflow_rejection_skips_host_permission_call(tmp_path: Path) -> None:
    runtime = _worker_runtime(
        tmp_path,
        model_batches=[
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "bash",
                        "tool_input": {"command": "printf teammate"},
                        "call_id": "call-bash-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ],
    )
    host = ControlledPermissionHost()
    runtime.bind_host(host)
    plane = runtime.team_control_plane
    bus = runtime.team_message_bus
    workflows = runtime.team_workflows
    assert plane is not None
    assert bus is not None
    assert workflows is not None

    async def scenario():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="worker",
            execution_defaults={"cwd": str(tmp_path)},
        )
        await bus.send_public_message(
            session_id="leader-session",
            extensions={},
            to="alpha",
            message="run the privileged step",
        )
        pending = await _wait_for(
            lambda: workflows.list_workflows(team_id=team.team_id, pending_only=True)
        )
        await workflows.respond_host(workflow_id=pending[0].workflow_id, action="reject")
        await plane.runner_manager.wait_for_idle(team_id=team.team_id, member_id=member.member_id)
        return workflows.get(pending[0].workflow_id)

    record = asyncio.run(scenario())

    assert record is not None
    assert record.status.value == "rejected"
    assert host.requests == []
    assert any(event.event_type == "team.workflow.rejected" for event in host.team_events)


def test_permission_workflow_timeout_denies_without_host_permission_call(tmp_path: Path) -> None:
    runtime = _worker_runtime(
        tmp_path,
        model_batches=[
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "bash",
                        "tool_input": {"command": "printf teammate"},
                        "call_id": "call-bash-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ]
        ],
    )
    host = ControlledPermissionHost()
    runtime.bind_host(host)
    plane = runtime.team_control_plane
    bus = runtime.team_message_bus
    workflows = runtime.team_workflows
    assert plane is not None
    assert bus is not None
    assert workflows is not None
    workflows._permission_timeout = timedelta(milliseconds=20)  # noqa: SLF001

    async def scenario():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="worker",
            execution_defaults={"cwd": str(tmp_path)},
        )
        await bus.send_public_message(
            session_id="leader-session",
            extensions={},
            to="alpha",
            message="run the privileged step",
        )
        await _wait_for(
            lambda: any(
                record.status.value == "timed_out"
                for record in workflows.list_workflows(team_id=team.team_id, pending_only=False)
                if record.workflow_kind.value == "permission"
            )
        )
        await plane.runner_manager.wait_for_idle(team_id=team.team_id, member_id=member.member_id)
        terminal = [
            record
            for record in workflows.list_workflows(team_id=team.team_id, pending_only=False)
            if record.workflow_kind.value == "permission"
        ]
        return terminal[-1]

    record = asyncio.run(scenario())

    assert record.status.value == "timed_out"
    assert host.requests == []
    assert any(event.event_type == "team.workflow.timed_out" for event in host.team_events)


def test_permission_wait_recovery_preserves_waiting_state_across_restart(tmp_path: Path) -> None:
    runtime = _worker_runtime(
        tmp_path,
        model_batches=[
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "bash",
                        "tool_input": {"command": "printf teammate"},
                        "call_id": "call-bash-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ]
        ],
    )
    host = ControlledPermissionHost()
    runtime.bind_host(host)
    plane = runtime.team_control_plane
    bus = runtime.team_message_bus
    workflows = runtime.team_workflows
    teammates = runtime.teammates
    assert plane is not None
    assert bus is not None
    assert workflows is not None
    assert teammates is not None

    async def stage_one():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="worker",
            execution_defaults={"cwd": str(tmp_path)},
        )
        await bus.send_public_message(
            session_id="leader-session",
            extensions={},
            to="alpha",
            message="run the privileged step",
        )
        await _wait_for(lambda: workflows.list_workflows(team_id=team.team_id, pending_only=True))
        snapshot = teammates.snapshot(team.team_id, member.member_id)
        assert snapshot is not None
        assert snapshot.state.value == "waiting_permission"
        return team.team_id, member.member_id

    team_id, member_id = asyncio.run(stage_one())

    restarted = _worker_runtime(tmp_path, model_batches=[])
    assert restarted.teammates is not None
    assert restarted.team_workflows is not None

    async def stage_two():
        recovered = await restarted.teammates.recover(team_id=team_id, teammate_id=member_id)
        snapshot = restarted.teammates.snapshot(team_id, member_id)
        pending = restarted.team_workflows.list_workflows(team_id=team_id, pending_only=True)
        return recovered, snapshot, pending

    recovered, snapshot, pending = asyncio.run(stage_two())

    assert recovered
    assert recovered[0].action == "kept_waiting_permission"
    assert snapshot is not None
    assert snapshot.state.value == "waiting_permission"
    assert pending
    assert pending[0].workflow_kind.value == "permission"


def test_leader_workflow_ingress_is_actionable_and_prioritized(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "leader-1"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "handled"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )
    plane = runtime.team_control_plane
    workflows = runtime.team_workflows
    assert plane is not None
    assert workflows is not None

    async def scenario():
        session = runtime.create_session(session_id="leader-session", agent_name="main-router")
        await session.start()
        session.state.status = SessionStatus.READY
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="main-router",
            execution_defaults={"cwd": str(tmp_path)},
        )
        await workflows.create_permission_workflow(
            team=team,
            requester_member_id=member.member_id,
            requester_name=member.name,
            responder_member_id=team.leader_member_id,
            responder_name="leader",
            request_payload={"permission_name": "bash", "permission_message": "approve?"},
        )
        assert session.state.queued_commands
        metadata = session.state.queued_commands[0].payload["metadata"]
        return session, metadata

    session, metadata = asyncio.run(scenario())

    assert metadata["source"] == "team_workflow_request"
    assert metadata["admission_kind"] == "admit_turn"
    assert metadata["workflow_kind"] == "permission"
    assert int(metadata["ingress_priority"]) >= 80
    assert metadata["visibility"] == "transcript"
    assert "team control message" not in session.state.queued_commands[0].payload["content"].lower()
    assert metadata["workflow_id"] in session.state.queued_commands[0].payload["content"]


def test_shutdown_workflow_is_prioritized_and_preserves_private_envelope(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "leader-1"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "handled shutdown"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "leader-2"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "handled chatter"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                ]
            ),
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )
    plane = runtime.team_control_plane
    bus = runtime.team_message_bus
    workflows = runtime.team_workflows
    assert plane is not None
    assert bus is not None
    assert workflows is not None

    async def scenario():
        session = runtime.create_session(session_id="leader-session", agent_name="main-router")
        await session.start()
        session.state.status = SessionStatus.READY
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="main-router",
            execution_defaults={"cwd": str(tmp_path)},
        )
        teammate_extensions = {
            "team_id": team.team_id,
            "team_member_id": member.member_id,
            "team_role": "teammate",
            "leader_session_id": "leader-session",
        }
        await bus.send_public_message(
            session_id="leader-session",
            extensions=teammate_extensions,
            to="leader",
            message="ordinary chatter",
        )
        await workflows.create_shutdown_workflow(
            team=team,
            requester_member_id=team.leader_member_id,
            requester_name="leader",
            responder_member_id=member.member_id,
            responder_name=member.name,
            request_payload={
                "reason": "cleanup",
                "member_id": member.member_id,
                "member_name": member.name,
            },
        )
        queued = list(session.state.queued_commands)
        await session.run_until_idle()
        workflow_messages = [
            message for message in session.messages if message.metadata.get("source") == "team_workflow_request"
        ]
        return queued, session.state.metadata, workflow_messages

    queued, metadata, workflow_messages = asyncio.run(scenario())

    assert len(queued) >= 2
    assert queued[0].payload["metadata"]["source"] == "team_workflow_request"
    assert queued[0].payload["metadata"]["workflow_kind"] == "shutdown"
    assert queued[0].payload["metadata"]["workflow_id"] in queued[0].payload["content"]
    assert workflow_messages
    assert workflow_messages[0].metadata["source"] == "team_workflow_request"
    assert metadata["team_last_control_message"]["control_type"] == "shutdown_request"
    assert metadata["team_last_control_message"]["payload"]["workflow_kind"] == "shutdown"
    assert metadata["team_last_control_message"]["payload"]["protocol_kind"] == "request"


def test_host_bridge_lists_and_resolves_pending_workflows(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=None,
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )
    plane = runtime.team_control_plane
    workflows = runtime.team_workflows
    assert plane is not None
    assert workflows is not None
    host = ControlledPermissionHost()

    async def scenario():
        async with runtime.bind_host(host) as bound:
            team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
            member = await plane.register_member(
                session_id="leader-session",
                extensions={},
                name="alpha",
                agent_name="main-router",
                execution_defaults={"cwd": str(tmp_path)},
            )
            workflow = await workflows.create_permission_workflow(
                team=team,
                requester_member_id=member.member_id,
                requester_name=member.name,
                responder_member_id=team.leader_member_id,
                responder_name="leader",
                request_payload={"permission_name": "bash", "permission_message": "approve?"},
            )
            pending = await bound.list_team_workflows(session_id="leader-session", pending_only=True)
            updated = await bound.respond_team_workflow(workflow.workflow_id, action="reject")
            return pending, updated

    pending, updated = asyncio.run(scenario())

    assert pending
    assert pending[0]["workflow_kind"] == "permission"
    assert pending[0]["allowed_actions"] == ["approve", "reject"]
    assert updated["workflow_id"] == pending[0]["workflow_id"]
    assert updated["status"] == "rejected"


def test_host_and_model_share_invalid_action_validation(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=None,
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )
    plane = runtime.team_control_plane
    workflows = runtime.team_workflows
    assert plane is not None
    assert workflows is not None
    host = ControlledPermissionHost()

    async def setup():
        team, leader_created = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        _ = leader_created
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="main-router",
            execution_defaults={"cwd": str(tmp_path)},
        )
        workflow = await workflows.create_permission_workflow(
            team=team,
            requester_member_id=member.member_id,
            requester_name=member.name,
            responder_member_id=team.leader_member_id,
            responder_name="leader",
            request_payload={"permission_name": "bash", "permission_message": "approve?"},
        )
        leader = plane.get_member(team.team_id, team.leader_member_id)
        assert leader is not None
        return team, leader, workflow

    team, leader, workflow = asyncio.run(setup())

    async def host_error():
        async with runtime.bind_host(host) as bound:
            try:
                await bound.respond_team_workflow(workflow.workflow_id, action="complete")
            except TeamWorkflowError as exc:
                return exc
        raise AssertionError("host response unexpectedly succeeded")

    host_exc = asyncio.run(host_error())
    scheduler = ToolScheduler(runtime.kernel.tool_registry)
    model_result = asyncio.run(
        scheduler.run(
            [ToolCall("1", "team_respond", {"workflow_id": workflow.workflow_id, "action": "complete"})],
            _tool_context(
                runtime,
                session_id="leader-session",
                cwd=tmp_path,
                metadata=plane.team_private_context(team, leader),
            ),
        )
    )

    assert host_exc.code == "invalid_action"
    assert model_result[0].status.value == "error"
    assert model_result[0].output["error"]["code"] == host_exc.code


def test_raw_workflow_response_transport_is_rejected(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=None,
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )
    plane = runtime.team_control_plane
    bus = runtime.team_message_bus
    workflows = runtime.team_workflows
    assert plane is not None
    assert bus is not None
    assert workflows is not None

    async def scenario():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="main-router",
            execution_defaults={"cwd": str(tmp_path)},
        )
        workflow = await workflows.create_permission_workflow(
            team=team,
            requester_member_id=member.member_id,
            requester_name=member.name,
            responder_member_id=team.leader_member_id,
            responder_name="leader",
            request_payload={"permission_name": "bash", "permission_message": "approve?"},
        )
        payload = build_workflow_response_protocol(
            workflow,
            action="reject",
            actor_kind=TeamWorkflowActorKind.LEADER,
            actor_id=team.leader_member_id,
        ).to_dict()
        try:
            await bus.send_control_message(
                team_id=team.team_id,
                sender_member_id=team.leader_member_id,
                recipient_member_id=team.leader_member_id,
                control_type="permission_response",
                payload=payload,
                correlation_id=workflow.workflow_id,
            )
        except TeamControlError as exc:
            return exc
        raise AssertionError("raw workflow response transport unexpectedly succeeded")

    exc = asyncio.run(scenario())

    assert exc.code == "invalid_request"
