import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime import (
    AgentDefinition,
    BuiltinPackConfig,
    MessageRole,
    PermissionBehavior,
    RuntimeConfig,
    TeammateLifecycleState,
    TeammateOrchestrationConfig,
    assemble_runtime,
)
from runtime.jobs import JobNotStoppableError, JobScopeFilter, JobStatus
from runtime.permissions import PermissionOutcome, PermissionRequest
from runtime.tasking import TaskStatus
from runtime.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType


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


class ControlledPermissionHost:
    def __init__(self) -> None:
        self.requests: list[PermissionRequest] = []
        self.notifications = []
        self.allow_event = asyncio.Event()
        self.name = "controlled"

    async def startup(self) -> None:
        return None

    async def ready(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def request_permission(self, request: PermissionRequest) -> PermissionOutcome:
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


class GatedModelClient(FakeModelClient):
    def __init__(self, event_batches: list[list[ModelStreamEvent]]) -> None:
        super().__init__(event_batches)
        self.first_batch_started = asyncio.Event()
        self.release_first_batch = asyncio.Event()
        self._stream_count = 0

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        batch = self._event_batches.pop(0)
        stream_index = self._stream_count
        self._stream_count += 1
        for index, event in enumerate(batch):
            if stream_index == 0 and index == 1:
                self.first_batch_started.set()
                await self.release_first_batch.wait()
            yield event


def test_runtime_feature_gate_exposes_persistent_teammate_orchestration(tmp_path: Path) -> None:
    disabled = assemble_runtime(RuntimeConfig(working_directory=tmp_path))
    enabled = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True),
        )
    )

    assert disabled.teammates is None
    assert enabled.teammates is not None
    assert enabled.teammates.mailbox.root == (tmp_path / ".runtime" / "teammates").resolve()


def test_mailbox_publish_is_atomic_and_claims_are_exclusive(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True),
        )
    )
    teammates = runtime.teammates
    assert teammates is not None
    teammates.register_teammate(
        team_id="team-alpha",
        teammate_id="tm-research",
        agent_name="main-router",
        session_id="session-alpha",
        working_directory=tmp_path,
    )

    async def publish_two():
        return await asyncio.gather(
            asyncio.to_thread(
                teammates.publish_work_item,
                team_id="team-alpha",
                teammate_id="tm-research",
                prompt="first",
            ),
            asyncio.to_thread(
                teammates.publish_work_item,
                team_id="team-alpha",
                teammate_id="tm-research",
                prompt="second",
            ),
        )

    first, second = asyncio.run(publish_two())
    inbox = teammates.mailbox.ensure_paths("team-alpha", "tm-research").inbox

    assert sorted(path.name for path in inbox.glob("*.json")) == sorted(
        [f"{first.message_id}.json", f"{second.message_id}.json"]
    )
    assert list(inbox.glob(".tmp-*")) == []

    single_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            teammate_orchestration=TeammateOrchestrationConfig(
                enabled=True,
                mailbox_root=tmp_path / "single-mailbox",
            ),
        )
    )
    single_teammates = single_runtime.teammates
    assert single_teammates is not None
    single_teammates.register_teammate(
        team_id="team-alpha",
        teammate_id="tm-claim",
        agent_name="main-router",
        session_id="session-claim",
        working_directory=tmp_path,
    )
    single_message = single_teammates.publish_work_item(
        team_id="team-alpha",
        teammate_id="tm-claim",
        prompt="claim once",
    )

    async def claim_twice():
        return await asyncio.gather(
            asyncio.to_thread(
                single_teammates.mailbox.claim_next,
                "team-alpha",
                "tm-claim",
                claimer_identity="worker-a",
            ),
            asyncio.to_thread(
                single_teammates.mailbox.claim_next,
                "team-alpha",
                "tm-claim",
                claimer_identity="worker-b",
            ),
        )

    left, right = asyncio.run(claim_twice())
    successful = [claim for claim in (left, right) if claim is not None]

    assert len(successful) == 1
    assert successful[0].message_id == single_message.message_id
    assert single_teammates.mailbox.claim_next(
        "team-alpha",
        "tm-claim",
        claimer_identity="worker-c",
    ) is None


def test_recovery_requeues_stale_claims_and_enforces_retry_ceiling(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            teammate_orchestration=TeammateOrchestrationConfig(
                enabled=True,
                claim_lease_ms=25,
                retry_max_attempts=2,
            ),
        )
    )
    teammates = runtime.teammates
    assert teammates is not None
    teammates.register_teammate(
        team_id="team-alpha",
        teammate_id="tm-recovery",
        agent_name="main-router",
        session_id="session-recovery",
        working_directory=tmp_path,
        retry_max_attempts=2,
    )

    first_message = teammates.publish_work_item(
        team_id="team-alpha",
        teammate_id="tm-recovery",
        prompt="recover me",
    )
    first_claim = teammates.mailbox.claim_next(
        "team-alpha",
        "tm-recovery",
        claimer_identity="worker-a",
        now=datetime.now(timezone.utc),
    )
    assert first_claim is not None
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    teammates.mailbox.update_claim(
        replace(
            first_claim,
            claimed_at=stale_at,
            last_heartbeat_at=stale_at,
        )
    )
    teammates._write_snapshot(  # noqa: SLF001
        teammates.snapshot("team-alpha", "tm-recovery").activate(
            message_id=first_message.message_id,
            run_id="run-stale-1",
            claim_id=str(first_claim.claim_id),
        )
    )

    first_recovery = asyncio.run(
        teammates.recover(team_id="team-alpha", teammate_id="tm-recovery")
    )
    inbox_paths = teammates.mailbox.ensure_paths("team-alpha", "tm-recovery")
    requeued = teammates.mailbox.claim_next(
        "team-alpha",
        "tm-recovery",
        claimer_identity="worker-b",
        now=datetime.now(timezone.utc),
    )

    assert first_recovery[0].action == "retry"
    assert requeued is not None
    assert requeued.attempt == 2
    assert len(list(inbox_paths.retry.glob("*.json"))) == 1

    teammates.mailbox.update_claim(
        replace(
            requeued,
            claimed_at=stale_at,
            last_heartbeat_at=stale_at,
        )
    )
    teammates._write_snapshot(  # noqa: SLF001
        teammates.snapshot("team-alpha", "tm-recovery").activate(
            message_id=requeued.message_id,
            run_id="run-stale-2",
            claim_id=str(requeued.claim_id),
        )
    )

    second_recovery = asyncio.run(
        teammates.recover(team_id="team-alpha", teammate_id="tm-recovery")
    )

    assert second_recovery[0].action == "failed"
    assert list(inbox_paths.inbox.glob("*.json")) == []
    assert len(list(inbox_paths.failed.glob("*.json"))) == 1
    assert teammates.snapshot("team-alpha", "tm-recovery").state == TeammateLifecycleState.IDLE


def test_recovery_retries_lost_permission_waits_after_restart(tmp_path: Path) -> None:
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            teammate_orchestration=TeammateOrchestrationConfig(
                enabled=True,
                claim_lease_ms=25,
                retry_max_attempts=2,
            ),
        )
    )
    teammates = runtime.teammates
    assert teammates is not None
    teammates.register_teammate(
        team_id="team-alpha",
        teammate_id="tm-waiting",
        agent_name="worker",
        session_id="session-waiting",
        working_directory=tmp_path,
        retry_max_attempts=2,
    )

    message = teammates.publish_work_item(
        team_id="team-alpha",
        teammate_id="tm-waiting",
        prompt="resume me",
    )
    claim = teammates.mailbox.claim_next(
        "team-alpha",
        "tm-waiting",
        claimer_identity="worker-a",
        now=datetime.now(timezone.utc),
    )
    assert claim is not None
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    teammates.mailbox.update_claim(
        replace(
            claim,
            claimed_at=stale_at,
            last_heartbeat_at=stale_at,
        )
    )
    waiting_snapshot = teammates.snapshot("team-alpha", "tm-waiting").activate(
        message_id=message.message_id,
        run_id="run-waiting",
        claim_id=str(claim.claim_id),
    ).waiting_permission("perm-lost")
    teammates._write_snapshot(waiting_snapshot)  # noqa: SLF001

    restarted = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            teammate_orchestration=TeammateOrchestrationConfig(
                enabled=True,
                claim_lease_ms=25,
                retry_max_attempts=2,
            ),
        )
    )
    restarted_teammates = restarted.teammates
    assert restarted_teammates is not None

    recovery = asyncio.run(
        restarted_teammates.recover(team_id="team-alpha", teammate_id="tm-waiting")
    )
    inbox_paths = restarted_teammates.mailbox.ensure_paths("team-alpha", "tm-waiting")
    requeued = restarted_teammates.mailbox.claim_next(
        "team-alpha",
        "tm-waiting",
        claimer_identity="worker-b",
        now=datetime.now(timezone.utc),
    )

    assert recovery[0].action == "retry"
    assert recovery[0].reason == "lost_permission_wait"
    assert requeued is not None
    assert requeued.attempt == 2
    assert len(list(inbox_paths.retry.glob("*.json"))) == 1
    assert restarted_teammates.snapshot("team-alpha", "tm-waiting").state == TeammateLifecycleState.IDLE


def test_process_next_work_item_recovers_each_teammate_independently(tmp_path: Path) -> None:
    setup_runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            teammate_orchestration=TeammateOrchestrationConfig(
                enabled=True,
                claim_lease_ms=25,
                retry_max_attempts=2,
            ),
        )
    )
    setup_teammates = setup_runtime.teammates
    assert setup_teammates is not None
    for teammate_id in ("tm-a", "tm-b"):
        setup_teammates.register_teammate(
            team_id="team-alpha",
            teammate_id=teammate_id,
            agent_name="worker",
            session_id=f"session-{teammate_id}",
            working_directory=tmp_path,
            retry_max_attempts=2,
        )

    message = setup_teammates.publish_work_item(
        team_id="team-alpha",
        teammate_id="tm-b",
        prompt="recover me before work",
    )
    claim = setup_teammates.mailbox.claim_next(
        "team-alpha",
        "tm-b",
        claimer_identity="worker-a",
        now=datetime.now(timezone.utc),
    )
    assert claim is not None
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    setup_teammates.mailbox.update_claim(
        replace(
            claim,
            claimed_at=stale_at,
            last_heartbeat_at=stale_at,
        )
    )
    setup_teammates._write_snapshot(  # noqa: SLF001
        setup_teammates.snapshot("team-alpha", "tm-b").activate(
            message_id=message.message_id,
            run_id="run-stale",
            claim_id=str(claim.claim_id),
        )
    )

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=FakeModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-recovered"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
            builtins=BuiltinPackConfig(
                extra_agents=[
                    AgentDefinition(
                        name="worker",
                        description="persistent teammate worker",
                        prompt="work mailbox",
                        tools=(),
                    )
                ]
            ),
            teammate_orchestration=TeammateOrchestrationConfig(
                enabled=True,
                claim_lease_ms=25,
                retry_max_attempts=2,
            ),
        )
    )
    teammates = runtime.teammates
    assert teammates is not None

    async def scenario():
        first_result = await teammates.process_next_work_item(team_id="team-alpha", teammate_id="tm-a")
        second_result = await teammates.process_next_work_item(team_id="team-alpha", teammate_id="tm-b")
        return first_result, second_result

    first_result, second_result = asyncio.run(scenario())
    paths = teammates.mailbox.ensure_paths("team-alpha", "tm-b")

    assert first_result is None
    assert second_result is not None
    assert second_result.status == "completed"
    assert len(list(paths.retry.glob("*.json"))) == 1
    assert len(list(paths.done.glob("*.json"))) == 1
    assert teammates.snapshot("team-alpha", "tm-b").state == TeammateLifecycleState.IDLE


def test_process_next_work_item_serializes_teammate_runs_and_marks_tasks_running(tmp_path: Path) -> None:
    model_client = GatedModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-serial-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "first"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-serial-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "second"}),
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
                        tools=(),
                    )
                ]
            ),
            teammate_orchestration=TeammateOrchestrationConfig(enabled=True, heartbeat_interval_ms=10),
        )
    )
    teammates = runtime.teammates
    assert teammates is not None
    teammates.register_teammate(
        team_id="team-alpha",
        teammate_id="tm-serial",
        agent_name="worker",
        session_id="session-serial",
        working_directory=tmp_path,
    )
    teammates.publish_work_item(
        team_id="team-alpha",
        teammate_id="tm-serial",
        prompt="first job",
    )
    teammates.publish_work_item(
        team_id="team-alpha",
        teammate_id="tm-serial",
        prompt="second job",
    )

    async def scenario():
        first_task = asyncio.create_task(
            teammates.process_next_work_item(team_id="team-alpha", teammate_id="tm-serial")
        )
        await model_client.first_batch_started.wait()
        second_task = asyncio.create_task(
            teammates.process_next_work_item(team_id="team-alpha", teammate_id="tm-serial")
        )
        await asyncio.sleep(0)

        snapshot = teammates.snapshot("team-alpha", "tm-serial")
        projection = teammates.projection("team-alpha", "tm-serial")
        claimed = teammates.mailbox.list_claimed("team-alpha", "tm-serial")
        inbox = teammates.mailbox.ensure_paths("team-alpha", "tm-serial").inbox
        tasks = runtime.task_manager.list()
        assert snapshot is not None
        assert projection is not None
        assert snapshot.state == TeammateLifecycleState.ACTIVE
        assert projection.lifecycle_state == TeammateLifecycleState.ACTIVE
        assert len(claimed) == 1
        assert len(list(inbox.glob("*.json"))) == 1
        assert len(tasks) == 1
        assert tasks[0].status == TaskStatus.RUNNING
        assert tasks[0].metadata["teammate_state"] == TeammateLifecycleState.ACTIVE.value
        assert projection.task_id == tasks[0].task_id

        model_client.release_first_batch.set()
        return await asyncio.gather(first_task, second_task)

    first_result, second_result = asyncio.run(scenario())

    assert first_result.status == "completed"
    assert second_result.status == "completed"
    assert [task.status for task in runtime.task_manager.list()] == [
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
    ]


def test_teammate_identity_permission_bridge_and_idle_projection_consistency(tmp_path: Path) -> None:
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
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done one"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-3"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "bash",
                        "tool_input": {"command": "printf teammate"},
                        "call_id": "call-bash-2",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-worker-4"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done two"}),
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
    teammates = runtime.teammates
    assert teammates is not None
    teammates.register_teammate(
        team_id="team-alpha",
        teammate_id="tm-worker",
        agent_name="worker",
        session_id="session-worker",
        working_directory=tmp_path,
    )
    teammates.publish_work_item(
        team_id="team-alpha",
        teammate_id="tm-worker",
        prompt="run the first privileged step",
    )

    async def scenario():
        first_task = asyncio.create_task(
            teammates.process_next_work_item(team_id="team-alpha", teammate_id="tm-worker")
        )
        while not host.requests:
            await asyncio.sleep(0)
        waiting_snapshot = teammates.snapshot("team-alpha", "tm-worker")
        waiting_projection = teammates.projection("team-alpha", "tm-worker")
        assert waiting_snapshot is not None
        assert waiting_projection is not None
        assert waiting_snapshot.state == TeammateLifecycleState.WAITING_PERMISSION
        assert waiting_snapshot.current_message_id is not None
        assert waiting_snapshot.current_claim_id is not None
        assert waiting_snapshot.waiting_permission_id is not None
        assert waiting_projection.lifecycle_state == TeammateLifecycleState.WAITING_PERMISSION
        assert waiting_projection.current_run_id == waiting_snapshot.current_run_id
        task = runtime.task_manager.get(waiting_projection.task_id)
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert task.metadata["teammate_state"] == TeammateLifecycleState.WAITING_PERMISSION.value
        assert host.requests[0].context is not None
        assert host.requests[0].context.metadata["teammate_id"] == "tm-worker"
        assert host.notifications[-1].role == MessageRole.NOTIFICATION
        assert host.notifications[-1].text == "Teammate 'tm-worker' is waiting for permission"
        first_run_id = waiting_snapshot.current_run_id
        first_permission_id = waiting_snapshot.waiting_permission_id
        host.allow_event.set()
        first_result = await first_task

        after_first = teammates.snapshot("team-alpha", "tm-worker")
        first_projection = teammates.projection("team-alpha", "tm-worker")
        first_task_record = runtime.task_manager.get(first_projection.task_id)
        assert first_result.status == "completed"
        assert after_first is not None
        assert after_first.state == TeammateLifecycleState.IDLE
        assert after_first.current_run_id is None
        assert after_first.waiting_permission_id is None
        assert first_projection is not None
        assert first_projection.lifecycle_state == TeammateLifecycleState.IDLE
        assert first_task_record is not None
        assert first_task_record.status == TaskStatus.COMPLETED
        assert first_task_record.metadata["mailbox_terminal_state"] == "done"

        teammates.publish_work_item(
            team_id="team-alpha",
            teammate_id="tm-worker",
            prompt="run the second privileged step",
        )
        second_result = await teammates.process_next_work_item(
            team_id="team-alpha",
            teammate_id="tm-worker",
        )
        after_second = teammates.snapshot("team-alpha", "tm-worker")
        second_projection = teammates.projection("team-alpha", "tm-worker")
        second_task_record = runtime.task_manager.get(second_projection.task_id)
        return (
            first_run_id,
            first_permission_id,
            first_result,
            second_result,
            after_second,
            second_projection,
            second_task_record,
        )

    (
        first_run_id,
        first_permission_id,
        first_result,
        second_result,
        after_second,
        second_projection,
        second_task_record,
    ) = asyncio.run(scenario())

    assert first_result.status == "completed"
    assert second_result.status == "completed"
    assert first_run_id != second_result.run_id
    assert first_permission_id is not None
    assert after_second is not None
    assert after_second.teammate_id == "tm-worker"
    assert after_second.state == TeammateLifecycleState.IDLE
    assert second_projection is not None
    assert second_projection.lifecycle_state == TeammateLifecycleState.IDLE
    assert second_task_record is not None
    assert second_task_record.status == TaskStatus.COMPLETED
    assert second_task_record.metadata["teammate_state"] == TeammateLifecycleState.IDLE.value
    assert [task.metadata["teammate_id"] for task in runtime.task_manager.list()] == [
        "tm-worker",
        "tm-worker",
    ]
    assert [message.text for message in host.notifications] == [
        "Teammate 'tm-worker' is waiting for permission",
        "Teammate 'tm-worker' completed mailbox item",
        "Teammate 'tm-worker' is waiting for permission",
        "Teammate 'tm-worker' completed mailbox item",
    ]


def test_teammate_projection_stop_is_rejected_without_corrupting_terminal_projection(tmp_path: Path) -> None:
    model_client = FakeModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-stop-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "bash",
                        "tool_input": {"command": "printf teammate"},
                        "call_id": "call-stop-bash",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-stop-2"}),
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
    teammates = runtime.teammates
    assert teammates is not None
    teammates.register_teammate(
        team_id="team-alpha",
        teammate_id="tm-stop",
        agent_name="worker",
        session_id="session-stop",
        working_directory=tmp_path,
    )
    teammates.publish_work_item(
        team_id="team-alpha",
        teammate_id="tm-stop",
        prompt="run the privileged step",
    )

    async def scenario():
        work_item = asyncio.create_task(
            teammates.process_next_work_item(team_id="team-alpha", teammate_id="tm-stop")
        )
        while not host.requests:
            await asyncio.sleep(0)
        projection = teammates.projection("team-alpha", "tm-stop")
        assert projection is not None

        running = await runtime.job_service.get(
            projection.task_id,
            scope=JobScopeFilter(team_id="team-alpha"),
        )
        assert running is not None
        assert running.status is JobStatus.RUNNING

        try:
            await runtime.job_service.stop(
                projection.task_id,
                scope=JobScopeFilter(team_id="team-alpha"),
            )
        except JobNotStoppableError as exc:
            assert exc.code == "not_stoppable"
        else:  # pragma: no cover - regression guard
            raise AssertionError("teammate projection unexpectedly accepted stop")

        host.allow_event.set()
        result = await work_item
        final_projection = teammates.projection("team-alpha", "tm-stop")
        final_snapshot = teammates.snapshot("team-alpha", "tm-stop")
        final_record = await runtime.job_service.get(
            projection.task_id,
            scope=JobScopeFilter(team_id="team-alpha"),
        )
        return result, final_projection, final_snapshot, final_record

    result, final_projection, final_snapshot, final_record = asyncio.run(scenario())

    assert result.status == "completed"
    assert final_projection is not None
    assert final_projection.lifecycle_state == TeammateLifecycleState.IDLE
    assert final_snapshot is not None
    assert final_snapshot.state == TeammateLifecycleState.IDLE
    assert final_record is not None
    assert final_record.status is JobStatus.COMPLETED
    assert final_record.metadata["teammate_state"] == TeammateLifecycleState.IDLE.value
