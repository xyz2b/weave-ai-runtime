import asyncio
from pathlib import Path

import pytest

from weavert.builtins.tool_impls import ask_user_tool
from weavert.contracts import MessageRole, RuntimeMessage, ToolResultBlock
from weavert.definitions import (
    AgentDefinition,
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    ToolDefinition,
    ToolTraits,
)
from weavert.elicitation import ElicitationRequest
from weavert.hooks import HookBus, RuntimeHookPhase
from weavert.hosts import SdkHostRuntime
from weavert.permissions import PermissionContext
from weavert.registries import ToolRegistry
from weavert.runtime_kernel import RuntimeConfig, assemble_runtime
from weavert.runtime_services import RuntimeServices
from weavert.session_runtime import FileTranscriptStore, InboundEvent, InboundEventType, SessionController
from weavert.tool_runtime import ToolCall, ToolContext, ToolScheduler
from weavert.turn_engine import ModelRequest, ModelStreamEvent, ModelStreamEventType, TurnEngine


class BatchedModelClient:
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


class InterruptibleModelClient:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.started = asyncio.Event()

    async def complete(self, request: ModelRequest):  # pragma: no cover - protocol completeness
        raise NotImplementedError

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        yield ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-interrupt"})
        self.started.set()
        yield ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "partial"})
        while request.abort_signal is not None and not request.abort_signal.aborted:
            await asyncio.sleep(0.01)


def test_hook_bus_updates_tool_input_and_scopes_ownership(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="echo",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            traits=ToolTraits(read_only=True, concurrency_safe=True),
            execute=lambda tool_input, _: {"echo": tool_input["value"]},
        )
    )
    services = RuntimeServices()
    services.hook_bus.register(
        session_id="session-a",
        owner="skill:rewrite",
        phase=RuntimeHookPhase.PRE_TOOL_USE,
        matcher="echo",
        handler=lambda _payload: {"updated_input": {"value": "rewritten"}},
    )
    scheduler = ToolScheduler(registry)
    context = ToolContext(
        session_id="session-a",
        turn_id="turn-a",
        agent_name="main-router",
        cwd=tmp_path,
        tool_registry=registry,
        runtime_services=services,
        permission_context=PermissionContext(session_id="session-a"),
    )

    result = asyncio.run(
        scheduler.run(
            [ToolCall(call_id="1", tool_name="echo", tool_input={"value": "original"})],
            context,
        )
    )[0]
    other = asyncio.run(
        scheduler.run(
            [ToolCall(call_id="2", tool_name="echo", tool_input={"value": "untouched"})],
            ToolContext(
                session_id="session-b",
                turn_id="turn-b",
                agent_name="main-router",
                cwd=tmp_path,
                tool_registry=registry,
                runtime_services=services,
                permission_context=PermissionContext(session_id="session-b"),
            ),
        )
    )[0]

    assert result.output == {"echo": "rewritten"}
    assert other.output == {"echo": "untouched"}


def test_stop_hook_blocks_continuation_and_session_enters_waiting(tmp_path: Path) -> None:
    services = RuntimeServices()
    services.hook_bus.register(
        session_id="session-blocked",
        owner="host:blocker",
        phase=RuntimeHookPhase.STOP,
        handler=lambda _payload: {"continue_execution": False},
    )
    controller = SessionController(
        session_id="session-blocked",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
        turn_engine=TurnEngine(
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-block"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "blocked reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
            tool_registry=ToolRegistry(),
            runtime_services=services,
        ),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System",
        runtime_services=services,
    )
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "hello"))

    async def collect():
        return [event async for event in controller.stream_until_idle()]

    events = asyncio.run(collect())
    terminal = next(event for event in events if event.event_type.value == "terminal")

    assert terminal.terminal is not None
    assert terminal.terminal.stop_reason == "blocked"
    assert terminal.terminal.metadata["continuation_blocked"] is True
    assert controller.state.status.value == "waiting"


def test_stop_hook_does_not_rewrite_model_error_to_waiting(tmp_path: Path) -> None:
    services = RuntimeServices()
    services.hook_bus.register(
        session_id="session-error",
        owner="host:blocker",
        phase=RuntimeHookPhase.STOP,
        handler=lambda _payload: {"continue_execution": False},
    )
    controller = SessionController(
        session_id="session-error",
        agent=AgentDefinition(name="main-router", description="router", prompt="route"),
        turn_engine=TurnEngine(
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-error"}),
                        ModelStreamEvent(ModelStreamEventType.ERROR, {"error": "model exploded"}),
                    ]
                ]
            ),
            tool_registry=ToolRegistry(),
            runtime_services=services,
        ),
        transcript_store=FileTranscriptStore(tmp_path / "transcripts"),
        cwd=str(tmp_path),
        system_prompt="System",
        runtime_services=services,
    )
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "hello"))

    async def collect():
        return [event async for event in controller.stream_until_idle()]

    events = asyncio.run(collect())
    terminal = next(event for event in events if event.event_type.value == "terminal")

    assert terminal.terminal is not None
    assert terminal.terminal.stop_reason == "error"
    assert terminal.terminal.metadata.get("continuation_blocked") is None
    assert controller.state.status.value == "ready"


def test_permission_modes_and_elicitation_flow_use_shared_control_plane(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="restricted",
            description="restricted",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            check_permissions=lambda _tool_input, _context: PermissionDecision(
                PermissionBehavior.ASK,
                "approval required",
            ),
            execute=lambda tool_input, _: {"value": tool_input["value"]},
        )
    )
    scheduler = ToolScheduler(registry)
    bypass_services = RuntimeServices()
    bypass_result = asyncio.run(
        scheduler.run(
            [ToolCall(call_id="1", tool_name="restricted", tool_input={"value": "ok"})],
            ToolContext(
                session_id="bypass",
                turn_id="turn-bypass",
                agent_name="main-router",
                cwd=tmp_path,
                tool_registry=registry,
                runtime_services=bypass_services,
                permission_context=PermissionContext(
                    session_id="bypass",
                    mode=PermissionMode.BYPASS_PERMISSIONS,
                ),
            ),
        )
    )[0]
    dont_ask_result = asyncio.run(
        scheduler.run(
            [ToolCall(call_id="2", tool_name="restricted", tool_input={"value": "no"})],
            ToolContext(
                session_id="dont-ask",
                turn_id="turn-dont-ask",
                agent_name="main-router",
                cwd=tmp_path,
                tool_registry=registry,
                runtime_services=RuntimeServices(),
                permission_context=PermissionContext(
                    session_id="dont-ask",
                    mode=PermissionMode.DONT_ASK,
                ),
            ),
        )
    )[0]

    hook_services = RuntimeServices()
    hook_services.hook_bus.register(
        session_id="hook-elicit",
        owner="hook:auto-answer",
        phase=RuntimeHookPhase.ELICITATION,
        handler=lambda _payload: {"elicitation_result": {"response": "hooked"}},
    )
    hook_response = asyncio.run(
        ask_user_tool(
            {"question": "continue?"},
            ToolContext(
                session_id="hook-elicit",
                turn_id="turn-hook-elicit",
                agent_name="main-router",
                cwd=tmp_path,
                runtime_services=hook_services,
            ),
        )
    )

    host = SdkHostRuntime(name="sdk", ask_user_handler=lambda question, options=None: "hosted")
    host_services = RuntimeServices()
    host_services.bind_host(host)
    host_response = asyncio.run(
        ask_user_tool(
            {"question": "continue?", "options": ["yes", "no"]},
            ToolContext(
                session_id="host-elicit",
                turn_id="turn-host-elicit",
                agent_name="main-router",
                cwd=tmp_path,
                runtime_services=host_services,
            ),
        )
    )

    assert bypass_result.output == {"value": "ok"}
    assert dont_ask_result.error == "approval required"
    assert hook_response["response"] == {"response": "hooked"}
    assert host_response["response"] == "hosted"


def test_bound_host_runtime_emits_lifecycle_and_turn_events(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-host"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "host reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
        )
    )
    bound = runtime.bind_host(host)

    produced = asyncio.run(bound.run_prompt("hello host", session_id="host-session"))
    asyncio.run(bound.shutdown())

    assert produced[-1].text == "host reply"
    assert host.lifecycle == ["startup", "ready", "shutdown"]
    assert any(event.event_type.value == "terminal" for _, event in host.turn_events)


def test_session_close_does_not_shutdown_active_bound_host(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-session"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "session reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
        )
    )
    bound = runtime.bind_host(host)

    async def scenario() -> None:
        await bound.startup()
        await bound.ready()
        session = bound.create_session(session_id="bound-session")
        await session.start()
        session.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "hello"))
        await session.run_until_idle()
        await session.close()
        assert host.lifecycle == ["startup", "ready"]
        assert bound.metadata["closed_sessions"][-1]["owner"] == "bound"
        await bound.shutdown()

    asyncio.run(scenario())

    assert host.lifecycle == ["startup", "ready", "shutdown"]


def test_bound_host_runtime_shutdown_closes_managed_sessions_before_host_shutdown(tmp_path: Path) -> None:
    events: list[str] = []

    class RecordingHost(SdkHostRuntime):
        async def shutdown(self) -> None:
            events.append("host_shutdown")
            await super().shutdown()

    host = RecordingHost(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-managed"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "managed reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
        )
    )
    runtime.services.hook_bus.register(
        session_id="managed-session",
        owner="test",
        phase=RuntimeHookPhase.SESSION_END,
        handler=lambda _payload: events.append("session_end"),
    )
    bound = runtime.bind_host(host)

    async def scenario() -> None:
        await bound.startup()
        await bound.ready()
        session = bound.create_session(session_id="managed-session")
        await session.start()
        await bound.shutdown()

    asyncio.run(scenario())

    assert events == ["session_end", "host_shutdown"]
    assert host.lifecycle == ["startup", "ready", "shutdown"]
    assert bound.metadata["managed_shutdown_order"] == ["managed-session"]


def test_bound_host_runtime_supports_async_context_scope(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-context"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "context reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
        )
    )

    async def scenario():
        async with runtime.bind_host(host) as bound:
            session = bound.create_session(session_id="ctx-session")
            await session.start()
            return bound

    bound = asyncio.run(scenario())

    assert host.lifecycle == ["startup", "ready", "shutdown"]
    assert bound.metadata["closed_sessions"][-1]["session_id"] == "ctx-session"


def test_bound_host_runtime_reuses_host_across_multiple_sessions(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-first"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "first reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-second"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "second reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                ]
            ),
        )
    )

    async def scenario():
        async with runtime.bind_host(host) as bound:
            first = await bound.run_prompt("first", session_id="session-one")
            second = await bound.run_prompt("second", session_id="session-two")
            assert host.lifecycle == ["startup", "ready"]
            return first, second, bound

    first, second, bound = asyncio.run(scenario())

    assert first[-1].text == "first reply"
    assert second[-1].text == "second reply"
    assert host.lifecycle == ["startup", "ready", "shutdown"]
    assert [entry["session_id"] for entry in bound.metadata["closed_sessions"][-2:]] == [
        "session-one",
        "session-two",
    ]


def test_bound_host_runtime_run_prompt_report_closes_helper_owned_session(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-bound-report"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "bound report reply"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ]
                ]
            ),
        )
    )
    bound = runtime.bind_host(host)

    report = asyncio.run(
        bound.run_prompt_report(
            "hello host",
            session_id="bound-helper-report",
        )
    )
    asyncio.run(bound.shutdown())

    assert report.session_id == "bound-helper-report"
    assert report.session_owner == "helper"
    assert report.final_status == "completed"
    assert report.messages[-1].text == "bound report reply"
    assert host.lifecycle == ["startup", "ready", "shutdown"]
    assert bound.metadata["closed_sessions"][-1] == {
        "session_id": "bound-helper-report",
        "owner": "helper",
        "final_status": "completed",
    }


def test_bound_host_runtime_run_prompt_report_in_session_keeps_session_reusable(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-bound-caller-1"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "first bound report"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-bound-caller-2"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "second bound report"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                ]
            ),
        )
    )
    bound = runtime.bind_host(host)

    async def scenario():
        await bound.startup()
        await bound.ready()
        session = bound.create_session(session_id="bound-caller-report")
        first = await bound.run_prompt_report_in_session(session, "first turn")
        status_after_first = session.state.status.value
        second = await bound.run_prompt_report_in_session(session, "second turn")
        status_after_second = session.state.status.value
        closed_before_manual_close = list(bound.metadata.get("closed_sessions", []))
        await session.close()
        await bound.shutdown()
        return first, second, status_after_first, status_after_second, closed_before_manual_close

    (
        first,
        second,
        status_after_first,
        status_after_second,
        closed_before_manual_close,
    ) = asyncio.run(scenario())

    assert first.session_owner == "caller"
    assert first.final_status == "completed"
    assert first.messages[-1].text == "first bound report"
    assert second.messages[-1].text == "second bound report"
    assert status_after_first == "ready"
    assert status_after_second == "ready"
    assert closed_before_manual_close == []
    assert host.lifecycle == ["startup", "ready", "shutdown"]


def test_bound_host_runtime_run_prompt_report_cancellation_closes_helper_owned_session(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    model_client = InterruptibleModelClient()
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=model_client,
        )
    )
    bound = runtime.bind_host(host)

    async def scenario():
        task = asyncio.create_task(
            bound.run_prompt_report(
                "hello host",
                session_id="bound-helper-report-cancelled",
            )
        )
        await model_client.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert bound.metadata["closed_sessions"][-1] == {
            "session_id": "bound-helper-report-cancelled",
            "owner": "helper",
            "final_status": "interrupted",
        }
        session = bound.create_session(session_id="bound-helper-report-cancelled")
        await session.close()
        await bound.shutdown()

    asyncio.run(scenario())

    assert host.lifecycle == ["startup", "ready", "shutdown"]


def test_bound_host_runtime_rejects_duplicate_active_session_ids(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient([]),
        )
    )
    bound = runtime.bind_host(host)

    async def scenario():
        await bound.startup()
        await bound.ready()
        first = bound.create_session(session_id="dup-session")
        with pytest.raises(ValueError, match="dup-session"):
            bound.create_session(session_id="dup-session")
        await bound.shutdown()
        return first

    first = asyncio.run(scenario())

    assert first.state.status.value == "completed"
    assert host.lifecycle == ["startup", "ready", "shutdown"]
    assert [entry["session_id"] for entry in bound.metadata["closed_sessions"]] == ["dup-session"]


def test_bound_host_runtime_grouped_sessions_share_core_registry_and_shutdown_order(tmp_path: Path) -> None:
    events: list[str] = []

    class RecordingHost(SdkHostRuntime):
        async def shutdown(self) -> None:
            events.append("host_shutdown")
            await super().shutdown()

    host = RecordingHost(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient([]),
        )
    )
    for session_id in ("grouped-session", "compat-session"):
        runtime.services.hook_bus.register(
            session_id=session_id,
            owner=f"test:{session_id}",
            phase=RuntimeHookPhase.SESSION_END,
            handler=lambda _payload, session_id=session_id: events.append(f"{session_id}:session_end"),
        )
    bound = runtime.bind_host(host)

    async def scenario() -> None:
        await bound.startup()
        await bound.ready()
        grouped = bound.sessions.create_session(session_id="grouped-session")
        with pytest.raises(ValueError, match="grouped-session"):
            bound.create_session(session_id="grouped-session")
        compat = bound.create_session(session_id="compat-session")
        await grouped.start()
        await compat.start()
        await bound.shutdown()

    asyncio.run(scenario())

    assert events == [
        "grouped-session:session_end",
        "compat-session:session_end",
        "host_shutdown",
    ]
    assert bound.metadata["managed_shutdown_order"] == ["grouped-session", "compat-session"]
    assert bound.metadata["closed_sessions"][-2:] == [
        {
            "session_id": "grouped-session",
            "owner": "bound",
            "final_status": "completed",
        },
        {
            "session_id": "compat-session",
            "owner": "bound",
            "final_status": "completed",
        },
    ]
    assert host.lifecycle == ["startup", "ready", "shutdown"]


def test_bound_host_runtime_grouped_prompt_and_session_surfaces_match_flat_helpers(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-grouped-helper"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "grouped helper"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-flat-helper"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "flat helper"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-grouped-caller"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "grouped caller"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-flat-caller"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "flat caller"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                ]
            ),
        )
    )
    bound = runtime.bind_host(host)

    async def scenario():
        grouped_helper = await bound.prompts.run_prompt_report(
            "grouped helper",
            session_id="grouped-helper-session",
        )
        flat_helper = await bound.run_prompt_report(
            "flat helper",
            session_id="flat-helper-session",
        )
        grouped_session = bound.sessions.create_session(session_id="grouped-caller-session")
        flat_session = bound.create_session(session_id="flat-caller-session")
        grouped_caller = await bound.sessions.run_prompt_report_in_session(
            grouped_session,
            "grouped caller",
        )
        flat_caller = await bound.run_prompt_report_in_session(
            flat_session,
            "flat caller",
        )
        statuses = {
            "grouped": grouped_session.state.status.value,
            "flat": flat_session.state.status.value,
        }
        closed_before_manual_close = list(bound.metadata.get("closed_sessions", []))
        await grouped_session.close()
        await flat_session.close()
        await bound.shutdown()
        return grouped_helper, flat_helper, grouped_caller, flat_caller, statuses, closed_before_manual_close

    (
        grouped_helper,
        flat_helper,
        grouped_caller,
        flat_caller,
        statuses,
        closed_before_manual_close,
    ) = asyncio.run(scenario())

    assert grouped_helper.session_owner == "helper"
    assert grouped_helper.final_status == "completed"
    assert grouped_helper.messages[-1].text == "grouped helper"
    assert flat_helper.session_owner == "helper"
    assert flat_helper.final_status == "completed"
    assert flat_helper.messages[-1].text == "flat helper"
    assert grouped_caller.session_owner == "caller"
    assert grouped_caller.final_status == "completed"
    assert grouped_caller.messages[-1].text == "grouped caller"
    assert flat_caller.session_owner == "caller"
    assert flat_caller.final_status == "completed"
    assert flat_caller.messages[-1].text == "flat caller"
    assert statuses == {"grouped": "ready", "flat": "ready"}
    assert closed_before_manual_close == [
        {
            "session_id": "grouped-helper-session",
            "owner": "helper",
            "final_status": "completed",
        },
        {
            "session_id": "flat-helper-session",
            "owner": "helper",
            "final_status": "completed",
        },
    ]
    assert host.lifecycle == ["startup", "ready", "shutdown"]


def test_bound_host_runtime_grouped_prompt_and_stream_surfaces_match_flat_helpers(tmp_path: Path) -> None:
    host = SdkHostRuntime(name="sdk")
    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            model_client=BatchedModelClient(
                [
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-grouped-run"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "grouped run"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-flat-run"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "flat run"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-grouped-stream"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "grouped stream"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                    [
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-flat-stream"}),
                        ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "flat stream"}),
                        ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
                    ],
                ]
            ),
        )
    )
    bound = runtime.bind_host(host)

    async def scenario():
        grouped_run = await bound.prompts.run_prompt(
            "grouped run",
            session_id="grouped-run-session",
        )
        flat_run = await bound.run_prompt(
            "flat run",
            session_id="flat-run-session",
        )
        grouped_stream = [
            event
            async for event in bound.prompts.stream_prompt(
                "grouped stream",
                session_id="grouped-stream-session",
            )
        ]
        flat_stream = [
            event
            async for event in bound.stream_prompt(
                "flat stream",
                session_id="flat-stream-session",
            )
        ]
        closed_sessions = list(bound.metadata.get("closed_sessions", []))
        await bound.shutdown()
        return grouped_run, flat_run, grouped_stream, flat_stream, closed_sessions

    grouped_run, flat_run, grouped_stream, flat_stream, closed_sessions = asyncio.run(scenario())

    assert grouped_run[-1].text == "grouped run"
    assert flat_run[-1].text == "flat run"
    assert [event.event_type.value for event in grouped_stream] == [event.event_type.value for event in flat_stream]
    assert any(event.event_type.value == "terminal" for event in grouped_stream)
    assert any(event.event_type.value == "terminal" for event in flat_stream)
    assert closed_sessions[-4:] == [
        {
            "session_id": "grouped-run-session",
            "owner": "helper",
            "final_status": "completed",
        },
        {
            "session_id": "flat-run-session",
            "owner": "helper",
            "final_status": "completed",
        },
        {
            "session_id": "grouped-stream-session",
            "owner": "helper",
            "final_status": "completed",
        },
        {
            "session_id": "flat-stream-session",
            "owner": "helper",
            "final_status": "completed",
        },
    ]
    assert [session_id for session_id, event in host.turn_events if event.event_type.value == "terminal"] == [
        "grouped-run-session",
        "flat-run-session",
        "grouped-stream-session",
        "flat-stream-session",
    ]
    assert host.lifecycle == ["startup", "ready", "shutdown"]
