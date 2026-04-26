import asyncio
from pathlib import Path

from runtime import (
    AgentDefinition,
    BuiltinPackConfig,
    PermissionBehavior,
    PermissionOutcome,
    RuntimeConfig,
    SessionStatus,
    SdkHostRuntime,
    TeamControlError,
    TeamMessageKind,
    TeammateOrchestrationConfig,
    assemble_runtime,
)
from runtime.tool_runtime import ToolCall, ToolCallStatus, ToolContext, ToolScheduler
from runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType


class FakeModelClient:
    def __init__(self, event_batches: list[list[ModelStreamEvent]]) -> None:
        self._event_batches = [list(batch) for batch in event_batches]
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
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
        self.allow_event = asyncio.Event()

    async def startup(self) -> None:
        return None

    async def ready(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def request_permission(self, request):
        self.requests.append(request)
        await self.allow_event.wait()
        return PermissionOutcome(PermissionBehavior.ALLOW, message="approved")

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


def _message_batch(request_id: str, text: str) -> list[ModelStreamEvent]:
    return [
        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": request_id}),
        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": text}),
        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
    ]


def _build_runtime(tmp_path: Path, *, model_batches: list[list[ModelStreamEvent]] | None = None):
    return assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient(model_batches or []),
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=5),
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


def test_team_control_plane_create_reuse_and_delete(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    plane = runtime.team_control_plane
    assert plane is not None

    async def scenario():
        team, created = await plane.create_team(
            session_id="leader-session",
            extensions={},
            name="delivery",
        )
        reused, created_again = await plane.create_team(
            session_id="leader-session",
            extensions={},
            name="ignored",
        )
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="analyst",
            agent_name="general-purpose",
            execution_defaults={"cwd": str(tmp_path)},
        )
        duplicate_error = None
        try:
            await plane.register_member(
                session_id="leader-session",
                extensions={},
                name="analyst",
                agent_name="general-purpose",
                execution_defaults={"cwd": str(tmp_path)},
            )
        except TeamControlError as exc:
            duplicate_error = exc
        teammate_extensions = {
            "team_id": team.team_id,
            "team_member_id": member.member_id,
            "team_role": "teammate",
            "leader_session_id": "leader-session",
        }
        nested_error = None
        try:
            await plane.create_team(
                session_id="leader-session",
                extensions=teammate_extensions,
                name="nested",
            )
        except TeamControlError as exc:
            nested_error = exc
        deleted = await plane.delete_team(
            session_id="leader-session",
            extensions={},
        )
        return team, created, reused, created_again, member, duplicate_error, nested_error, deleted

    team, created, reused, created_again, member, duplicate_error, nested_error, deleted = asyncio.run(scenario())

    assert created is True
    assert team.team_id == reused.team_id
    assert created_again is False
    assert member.name == "analyst"
    assert duplicate_error is not None
    assert duplicate_error.code == "duplicate_member_name"
    assert nested_error is not None
    assert nested_error.code == "authority_denied"
    assert deleted.status.value == "deleted"
    assert plane.active_team_for_leader_session("leader-session") is None
    stored_team = plane.store.load_team(team.team_id)
    assert stored_team is not None
    assert stored_team.status.value == "deleted"
    stored_member = plane.get_member(team.team_id, member.member_id)
    assert stored_member is not None
    assert stored_member.status.value == "removed"


def test_team_private_context_persists_across_resume(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    plane = runtime.team_control_plane
    assert plane is not None

    async def scenario():
        session = runtime.create_session(session_id="leader-session", agent_name="general-purpose")
        await session.start()
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        await session.run_until_idle()
        before_close = dict(session._session_scope.private_context.extensions)
        await session.close()

        resumed = runtime.create_session(session_id="leader-session", agent_name="general-purpose")
        await resumed.resume()
        return team, before_close, dict(resumed._session_scope.private_context.extensions)

    team, before_close, resumed_scope = asyncio.run(scenario())

    assert before_close["team_id"] == team.team_id
    assert before_close["team_role"] == "leader"
    assert resumed_scope["team_id"] == team.team_id
    assert resumed_scope["team_role"] == "leader"
    assert resumed_scope["leader_session_id"] == "leader-session"


def test_offline_leader_messages_replay_on_resume_and_ack_delivery(tmp_path: Path) -> None:
    runtime = _build_runtime(
        tmp_path,
        model_batches=[_message_batch("leader-replayed", "leader handled offline")],
    )
    plane = runtime.team_control_plane
    bus = runtime.team_message_bus
    assert plane is not None
    assert bus is not None

    async def scenario():
        session = runtime.create_session(session_id="leader-session", agent_name="general-purpose")
        await session.start()
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        await session.run_until_idle()
        await session.close()

        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="general-purpose",
            execution_defaults={"cwd": str(tmp_path)},
        )
        teammate_extensions = {
            "team_id": team.team_id,
            "team_member_id": member.member_id,
            "team_role": "teammate",
            "leader_session_id": "leader-session",
        }
        envelope = await bus.send_public_message(
            session_id="leader-session",
            extensions=teammate_extensions,
            to="leader",
            message="offline hello",
        )
        stored_before = bus.store.load(team.team_id, envelope.message_id)

        resumed = runtime.create_session(session_id="leader-session", agent_name="general-purpose")
        await resumed.resume()
        queued_after_resume = len(resumed.state.queued_commands)
        await resumed.run_until_idle()
        stored_after = bus.store.load(team.team_id, envelope.message_id)
        return queued_after_resume, tuple(message.text for message in resumed.messages), stored_before, stored_after

    queued_after_resume, texts, stored_before, stored_after = asyncio.run(scenario())

    assert queued_after_resume == 1
    assert stored_before is not None
    assert stored_before.deliveries[0].delivered_at is None
    assert "Message from alpha: offline hello" in texts
    assert stored_after is not None
    assert stored_after.deliveries[0].queued is False
    assert stored_after.deliveries[0].delivered_at is not None


def test_team_message_bus_routes_messages_and_emits_events(tmp_path: Path) -> None:
    runtime = _build_runtime(
        tmp_path,
        model_batches=[
            _message_batch("leader-waiting", "leader resumed"),
            _message_batch("alpha-run", "alpha done"),
            _message_batch("bravo-run", "bravo done"),
            _message_batch("bravo-direct", "bravo direct"),
        ],
    )
    host = SdkHostRuntime(name="sdk")
    runtime.bind_host(host)
    plane = runtime.team_control_plane
    bus = runtime.team_message_bus
    teammates = runtime.teammates
    assert plane is not None
    assert bus is not None
    assert teammates is not None

    async def scenario():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        alpha = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="general-purpose",
            execution_defaults={"cwd": str(tmp_path)},
        )
        bravo = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="bravo",
            agent_name="general-purpose",
            execution_defaults={"cwd": str(tmp_path)},
        )
        session = runtime.create_session(session_id="leader-session", agent_name="general-purpose")
        await session.start()
        session.state.status = SessionStatus.WAITING

        teammate_extensions = {
            "team_id": team.team_id,
            "team_member_id": alpha.member_id,
            "team_role": "teammate",
            "leader_session_id": "leader-session",
        }
        await bus.send_public_message(
            session_id="leader-session",
            extensions=teammate_extensions,
            to="leader",
            message="need review",
        )

        broadcast = await bus.send_public_message(
            session_id="leader-session",
            extensions={},
            to="*",
            message="fan out",
        )
        await plane.runner_manager.wait_for_idle(team_id=team.team_id, member_id=alpha.member_id)
        await plane.runner_manager.wait_for_idle(team_id=team.team_id, member_id=bravo.member_id)

        direct = await bus.send_public_message(
            session_id="leader-session",
            extensions={},
            to="bravo",
            message="direct note",
        )
        await plane.runner_manager.wait_for_idle(team_id=team.team_id, member_id=bravo.member_id)

        cross_team_error = None
        try:
            await bus.send_public_message(
                session_id="leader-session",
                extensions=teammate_extensions,
                to="other-team/bravo",
                message="not allowed",
            )
        except TeamControlError as exc:
            cross_team_error = exc

        control = await bus.send_control_message(
            team_id=team.team_id,
            sender_member_id=alpha.member_id,
            recipient_member_id=team.leader_member_id,
            control_type="shutdown_request",
            payload={"reason": "done"},
            correlation_id="corr-1",
        )
        await session.run_until_idle()
        return team, alpha, bravo, session, broadcast, direct, cross_team_error, control

    team, alpha, bravo, session, broadcast, direct, cross_team_error, control = asyncio.run(scenario())

    leader_inputs = [message for message in session.messages if message.metadata.get("source") == "team_message"]
    assert leader_inputs
    assert leader_inputs[0].text == "Message from alpha: need review"
    assert broadcast.kind is TeamMessageKind.BROADCAST
    assert len(broadcast.deliveries) == 2
    assert all(delivery.recipient_member_id != team.leader_member_id for delivery in broadcast.deliveries)
    assert len(direct.deliveries) == 1
    assert direct.deliveries[0].recipient_member_id == bravo.member_id
    assert cross_team_error is not None
    assert cross_team_error.code == "invalid_recipient"
    assert control.correlation_id == "corr-1"
    assert any("shutdown_request" in notification.text for notification in host.notifications)
    assert any(event.event_type == "team.message.routed" for event in host.team_events)

    routed_messages = bus.store.list_messages(team.team_id, recipient_member_id=bravo.member_id)
    assert {message.message_id for message in routed_messages} >= {broadcast.message_id, direct.message_id}
    assert (tmp_path / ".runtime" / "team_messages" / "teams" / team.team_id / "messages" / f"{broadcast.message_id}.json").exists()
    assert list(teammates.mailbox.ensure_paths(team.team_id, alpha.member_id).done.glob("*.json"))
    assert list(teammates.mailbox.ensure_paths(team.team_id, bravo.member_id).done.glob("*.json"))


def test_team_builtin_tools_return_structured_results_and_enforce_authority(tmp_path: Path) -> None:
    runtime = _build_runtime(
        tmp_path,
        model_batches=[
            _message_batch("beta-direct", "beta direct"),
            _message_batch("alpha-broadcast", "alpha broadcast"),
            _message_batch("beta-broadcast", "beta broadcast"),
        ],
    )
    scheduler = ToolScheduler(runtime.kernel.tool_registry)
    leader_context = _tool_context(runtime, session_id="leader-session", cwd=tmp_path)

    primary = asyncio.run(
        scheduler.run(
            [
                ToolCall("1", "team_send", {"to": "leader", "message": "missing"}),
                ToolCall("2", "team_create", {"name": "delivery"}),
                ToolCall("3", "team_create", {"name": "delivery"}),
                ToolCall("4", "team_spawn", {"name": "alpha", "agent": "general-purpose"}),
                ToolCall("5", "team_spawn", {"name": "beta", "agent": "general-purpose"}),
                ToolCall("6", "team_send", {"to": "beta", "message": "direct"}),
                ToolCall("7", "team_send", {"to": "*", "message": "broadcast"}),
            ],
            leader_context,
        )
    )

    team_id = primary[1].output["team_id"]
    alpha_id = primary[3].output["member_id"]
    beta_id = primary[4].output["member_id"]
    assert runtime.team_control_plane is not None
    asyncio.run(runtime.team_control_plane.runner_manager.wait_for_idle(team_id=team_id, member_id=alpha_id))
    asyncio.run(runtime.team_control_plane.runner_manager.wait_for_idle(team_id=team_id, member_id=beta_id))

    teammate_context = _tool_context(
        runtime,
        session_id="leader-session",
        cwd=tmp_path,
        metadata={
            "team_id": team_id,
            "team_member_id": alpha_id,
            "team_role": "teammate",
            "leader_session_id": "leader-session",
        },
    )
    teammate_delete = asyncio.run(
        scheduler.run([ToolCall("8", "team_delete", {})], teammate_context)
    )

    assert primary[0].status == ToolCallStatus.ERROR
    assert primary[0].output["error"]["code"] == "invalid_team_state"
    assert primary[1].status == ToolCallStatus.SUCCESS
    assert primary[1].output["created"] is True
    assert primary[2].status == ToolCallStatus.SUCCESS
    assert primary[2].output["created"] is False
    assert primary[2].output["team_id"] == team_id
    assert primary[3].output["status"] == "active"
    assert primary[4].output["status"] == "active"
    assert primary[5].output["delivery_count"] == 1
    assert primary[6].output["delivery_count"] == 2
    assert primary[6].output["queued"] is True
    assert teammate_delete[0].status == ToolCallStatus.ERROR
    assert teammate_delete[0].output["error"]["code"] == "authority_denied"


def test_team_ingress_ready_running_defaults_and_no_sink_fallback(tmp_path: Path) -> None:
    runtime = _build_runtime(
        tmp_path,
        model_batches=[
            _message_batch("leader-ready", "processed ready"),
            _message_batch("leader-running", "processed running"),
        ],
    )
    plane = runtime.team_control_plane
    bus = runtime.team_message_bus
    assert plane is not None
    assert bus is not None

    async def scenario():
        team, _ = await plane.create_team(session_id="leader-session", extensions={}, name="ops")
        member = await plane.register_member(
            session_id="leader-session",
            extensions={},
            name="alpha",
            agent_name="general-purpose",
            execution_defaults={"cwd": str(tmp_path)},
        )
        session = runtime.create_session(session_id="leader-session", agent_name="general-purpose")
        await session.start()
        teammate_extensions = {
            "team_id": team.team_id,
            "team_member_id": member.member_id,
            "team_role": "teammate",
            "leader_session_id": "leader-session",
        }

        session.state.status = SessionStatus.READY
        await bus.send_public_message(
            session_id="leader-session",
            extensions=teammate_extensions,
            to="leader",
            message="queued for ready",
        )
        ready_queue_depth = len(session.state.queued_commands)
        ready_message_count = len(session.messages)
        await session.run_until_idle()

        session.state.status = SessionStatus.RUNNING
        await bus.send_public_message(
            session_id="leader-session",
            extensions=teammate_extensions,
            to="leader",
            message="queued for running",
        )
        running_queue_depth = len(session.state.queued_commands)
        running_message_count = len(session.messages)
        session.state.status = SessionStatus.READY
        await session.run_until_idle()

        await bus.send_control_message(
            team_id=team.team_id,
            sender_member_id=member.member_id,
            recipient_member_id=team.leader_member_id,
            control_type="permission_request",
            payload={"approval": "needed"},
            correlation_id="corr-ready",
        )
        await session.run_until_idle()
        return session, ready_queue_depth, ready_message_count, running_queue_depth, running_message_count

    session, ready_queue_depth, ready_message_count, running_queue_depth, running_message_count = asyncio.run(
        scenario()
    )

    assert ready_queue_depth == 1
    assert len(session.messages) > ready_message_count
    assert running_queue_depth == 1
    assert len(session.messages) > running_message_count
    assert not any(message.metadata.get("source") == "team_control_message" for message in session.messages)
    assert session.state.metadata["team_last_control_message"]["control_type"] == "permission_request"


def test_permission_bridge_routes_correlated_team_control_messages(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
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
        ]
    )
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
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
        await workflows.respond_host(workflow_id=workflow.workflow_id, action="approve")
        while not host.requests:
            await asyncio.sleep(0.01)
        host.allow_event.set()
        await plane.runner_manager.wait_for_idle(team_id=team.team_id, member_id=member.member_id)
        return team, member

    team, member = asyncio.run(scenario())

    control_messages = [
        envelope
        for envelope in bus.store.list_messages(team.team_id)
        if envelope.kind is TeamMessageKind.CONTROL
    ]

    assert [envelope.metadata["control_type"] for envelope in control_messages] == [
        "permission_request",
        "permission_response",
        "permission_response",
    ]
    assert [envelope.metadata.get("status") for envelope in control_messages] == [
        None,
        "waiting_host",
        "completed",
    ]
    assert {envelope.correlation_id for envelope in control_messages} == {control_messages[0].correlation_id}
    assert control_messages[0].sender.member_id == member.member_id
    assert all(envelope.sender.member_id == team.leader_member_id for envelope in control_messages[1:])
    assert any(event.event_type == "team.message.routed" for event in host.team_events)
