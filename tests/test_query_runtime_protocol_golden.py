import asyncio
from pathlib import Path

from claude_agent_runtime.contracts import MessageRole, RuntimeMessage, ToolResultBlock, ToolUseBlock
from claude_agent_runtime.registries import ToolRegistry
from claude_agent_runtime.session_runtime import (
    FileTranscriptStore,
    InboundEvent,
    InboundEventType,
    SessionController,
)
from claude_agent_runtime.turn_engine import ModelStreamEvent, ModelStreamEventType, TurnEngine, TurnStreamEventType
from claude_agent_runtime.turn_engine.message_protocol import normalize_messages_for_api

from .runtime_protocol_harness import (
    InterruptibleCaptureModelClient,
    RequestCaptureModelClient,
    append_transcript_messages,
    build_builtin_orchestration_runtime,
    build_echo_tool_registry,
    capture_runtime_events,
    make_main_router_agent,
    message_fixture,
    messages_fixture,
    request_fixture,
    request_messages_fixture,
    turn_event_fixture,
)


def test_request_golden_captures_tool_use_and_tool_result_continuation() -> None:
    model_client = RequestCaptureModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-tool-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "echo",
                        "tool_input": {"value": "ping"},
                        "call_id": "call-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-tool-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ]
    )
    engine = TurnEngine(model_client=model_client, tool_registry=build_echo_tool_registry())

    result = asyncio.run(
        engine.run_turn(
            session_id="session",
            turn_id="turn",
            agent=make_main_router_agent(tools=("*",)),
            cwd=".",
            messages=[
                RuntimeMessage(message_id="user-1", role=MessageRole.USER, content="Use echo"),
            ],
            base_system_prompt="System",
        )
    )

    assert result.completed is True
    assert request_messages_fixture(model_client.requests[1]) == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "Use echo"}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "tool_use_id": "call-1",
                    "name": "echo",
                    "input": {"value": "ping"},
                }
            ],
            "metadata": {
                "stop_reason": "tool_use",
                "request_id": "req-tool-1",
            },
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": {"echo": "ping"},
                    "is_error": False,
                }
            ],
            "metadata": {
                "tool_results": [
                    {
                        "tool_use_id": "call-1",
                        "tool_name": "echo",
                        "status": "success",
                    }
                ]
            },
        },
    ]


def test_request_golden_captures_ingress_prompt_private_split(tmp_path: Path) -> None:
    runtime, model_client = build_builtin_orchestration_runtime(
        tmp_path,
        event_batches=[
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-split"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ],
    )

    produced = asyncio.run(
        runtime.run_prompt(
            "Inspect runtime boundaries",
            session_id="session-split",
            metadata={
                "prompt_updates": {"topic": "ops"},
                "private_updates": {"host_hint": "keep-private"},
            },
        )
    )

    fixture = request_fixture(model_client.requests[0])

    assert fixture["query_source"] == "user_prompt"
    assert fixture["prompt_context"]["session_hints"] == {"topic": "ops"}
    assert fixture["private_context"]["host_hint"] == "keep-private"
    assert fixture["private_context"]["query_source"] == "user_prompt"
    assert "host_hint" not in model_client.requests[0].system_prompt
    assert produced[-1].text == "done"


def test_protocol_golden_drops_flattened_and_orphaned_tool_results() -> None:
    normalized = normalize_messages_for_api(
        (
            RuntimeMessage(
                message_id="assistant-dangling",
                role=MessageRole.ASSISTANT,
                content=(ToolUseBlock(tool_use_id="call-flat", name=" echo ", input={"value": "flat"}),),
            ),
            RuntimeMessage(
                message_id="user-flat",
                role=MessageRole.USER,
                content='{"echo": "flat"}',
            ),
            RuntimeMessage(
                message_id="user-orphan",
                role=MessageRole.USER,
                content=(ToolResultBlock(tool_use_id="orphan-result", content={"bad": True}),),
            ),
            RuntimeMessage(
                message_id="assistant-valid",
                role=MessageRole.ASSISTANT,
                content=(ToolUseBlock(tool_use_id="call-2", name=" echo ", input={"value": "pong"}),),
            ),
            RuntimeMessage(
                message_id="user-valid",
                role=MessageRole.USER,
                content=(ToolResultBlock(tool_use_id="call-2", content={"echo": "pong"}),),
            ),
        )
    )

    assert messages_fixture(normalized) == [
        {
            "role": "user",
            "content": [{"type": "text", "text": '{"echo": "flat"}'}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "tool_use_id": "call-2",
                    "name": "echo",
                    "input": {"value": "pong"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-2",
                    "content": {"echo": "pong"},
                    "is_error": False,
                }
            ],
        },
    ]


def test_interrupt_golden_discards_partial_tool_use_before_transcript_persistence(
    tmp_path: Path,
) -> None:
    model_client = InterruptibleCaptureModelClient(
        [
            ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-interrupt"}),
            ModelStreamEvent(
                ModelStreamEventType.CONTENT_BLOCK_START,
                {
                    "block_type": "tool_use",
                    "tool_name": "echo",
                    "tool_input": {"value": "partial"},
                    "call_id": "call-slow",
                },
            ),
        ]
    )
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    controller = SessionController(
        session_id="session-interrupt",
        agent=make_main_router_agent(),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry()),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System",
    )
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "Start tool"))

    async def scenario():
        events_task = asyncio.create_task(_collect_session_events(controller))
        while not model_client.requests:
            await asyncio.sleep(0)
        controller.interrupt("user_cancel")
        return await events_task

    events = asyncio.run(scenario())

    discard_event = next(event for event in events if event.event_type == TurnStreamEventType.MESSAGE_DISCARDED)
    assert discard_event.metadata["reason"] == "user_cancel"
    assert turn_event_fixture(discard_event)["discarded"] == [
        {
            "type": "tool_use",
            "tool_use_id": "call-slow",
            "name": "echo",
            "input": {"value": "partial"},
        }
    ]
    terminal_event = next(event for event in events if event.event_type == TurnStreamEventType.TERMINAL)
    assert turn_event_fixture(terminal_event)["terminal"] == {
        "stop_reason": "interrupted",
        "request_id": "req-interrupt",
        "abort_reason": "user_cancel",
    }

    loaded = asyncio.run(transcript_store.load("session-interrupt"))
    assert [message_fixture(entry.message) for entry in loaded.entries] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "Start tool"}],
        }
    ]


def test_resume_golden_repairs_transcript_pairing_before_next_request(tmp_path: Path) -> None:
    transcript_store = FileTranscriptStore(tmp_path / "transcripts")
    append_transcript_messages(
        transcript_store,
        session_id="session-resume",
        messages=[
            RuntimeMessage(message_id="user-history", role=MessageRole.USER, content="Earlier prompt"),
            RuntimeMessage(
                message_id="assistant-dangling",
                role=MessageRole.ASSISTANT,
                content=(ToolUseBlock(tool_use_id="dangling-call", name=" echo ", input={"value": "bad"}),),
            ),
            RuntimeMessage(
                message_id="user-orphan",
                role=MessageRole.USER,
                content=(ToolResultBlock(tool_use_id="orphan-result", content={"bad": True}),),
            ),
            RuntimeMessage(
                message_id="assistant-valid",
                role=MessageRole.ASSISTANT,
                content=(ToolUseBlock(tool_use_id="call-2", name=" echo ", input={"value": "pong"}),),
            ),
            RuntimeMessage(
                message_id="user-valid",
                role=MessageRole.USER,
                content=(ToolResultBlock(tool_use_id="call-2", content={"echo": "pong"}),),
            ),
        ],
    )
    model_client = RequestCaptureModelClient(
        [
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-resume-1"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "recovered answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ]
        ]
    )
    controller = SessionController(
        session_id="session-resume",
        agent=make_main_router_agent(),
        turn_engine=TurnEngine(model_client=model_client, tool_registry=ToolRegistry()),
        transcript_store=transcript_store,
        cwd=str(tmp_path),
        system_prompt="System",
    )

    asyncio.run(controller.resume())
    controller.enqueue_event(InboundEvent(InboundEventType.USER_PROMPT, "Continue after repair"))
    produced = asyncio.run(controller.run_until_idle())

    assert produced[-1].text == "recovered answer"
    assert request_messages_fixture(model_client.requests[0]) == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "Earlier prompt"}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "tool_use_id": "call-2",
                    "name": "echo",
                    "input": {"value": "pong"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-2",
                    "content": {"echo": "pong"},
                    "is_error": False,
                },
                {"type": "text", "text": "Continue after repair"},
            ],
        },
    ]


def test_assembled_runtime_golden_covers_model_generated_agent_and_skill_tools(
    tmp_path: Path,
) -> None:
    runtime, model_client = build_builtin_orchestration_runtime(
        tmp_path,
        event_batches=[
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agent-main-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "agent",
                        "tool_input": {"agent": "verification", "prompt": "run checks"},
                        "call_id": "call-agent-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agent-sub"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "subagent answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-agent-main-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "agent delegation done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-skill-main-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "skill",
                        "tool_input": {"skill": "fork-skill", "arguments": ["ARG"]},
                        "call_id": "call-skill-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-skill-sub"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "forked answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-skill-main-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "skill delegation done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ],
    )

    agent_messages = asyncio.run(runtime.run_prompt("Run agent tool", session_id="session-agent"))
    skill_messages = asyncio.run(runtime.run_prompt("Run skill tool", session_id="session-skill"))

    agent_followup_request = request_messages_fixture(model_client.requests[2])
    agent_result_block = agent_followup_request[2]["content"][0]
    assert agent_followup_request[1]["content"] == [
        {
            "type": "tool_use",
            "tool_use_id": "call-agent-1",
            "name": "agent",
            "input": {"agent": "verification", "prompt": "run checks"},
        }
    ]
    assert agent_result_block["tool_use_id"] == "call-agent-1"
    assert agent_result_block["content"]["agent"] == "verification"
    assert agent_result_block["content"]["status"] == "completed"
    assert agent_result_block["content"]["messages"][-1]["content"][0]["text"] == "subagent answer"

    skill_followup_request = request_messages_fixture(model_client.requests[5])
    skill_result_block = skill_followup_request[2]["content"][0]
    assert skill_followup_request[1]["content"] == [
        {
            "type": "tool_use",
            "tool_use_id": "call-skill-1",
            "name": "skill",
            "input": {"skill": "fork-skill", "arguments": ["ARG"]},
        }
    ]
    assert skill_result_block["tool_use_id"] == "call-skill-1"
    assert skill_result_block["content"]["skill"] == "fork-skill"
    assert skill_result_block["content"]["mode"] == "fork"
    assert (
        skill_result_block["content"]["agent_result"]["messages"][-1]["content"][0]["text"]
        == "forked answer"
    )
    assert agent_messages[-1].text == "agent delegation done"
    assert skill_messages[-1].text == "skill delegation done"


def test_headless_host_can_consume_runtime_turn_event_stream_without_reimplementing_orchestration(
    tmp_path: Path,
) -> None:
    runtime, _ = build_builtin_orchestration_runtime(
        tmp_path,
        event_batches=[
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-host-main-1"}),
                ModelStreamEvent(
                    ModelStreamEventType.TOOL_CALL,
                    {
                        "tool_name": "agent",
                        "tool_input": {"agent": "verification", "prompt": "run checks"},
                        "call_id": "call-agent-1",
                    },
                ),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "tool_use"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-host-sub"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "subagent answer"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
            [
                ModelStreamEvent(ModelStreamEventType.MESSAGE_START, {"request_id": "req-host-main-2"}),
                ModelStreamEvent(ModelStreamEventType.CONTENT_DELTA, {"text": "agent delegation done"}),
                ModelStreamEvent(ModelStreamEventType.MESSAGE_STOP, {"stop_reason": "end_turn"}),
            ],
        ],
    )

    events = capture_runtime_events(runtime, "Run agent tool", session_id="session-host")
    host_view: list[dict[str, object]] = []
    for event in events:
        if event.event_type == TurnStreamEventType.MESSAGE and event.message is not None:
            host_view.append(message_fixture(event.message))
        elif event.event_type == TurnStreamEventType.ATTEMPT_FINISHED and event.attempt is not None:
            host_view.append(
                {
                    "attempt_stop_reason": event.attempt.stop_reason,
                    "request_id": event.attempt.request_id,
                    "produced_tool_calls": event.attempt.produced_tool_calls,
                }
            )
        elif event.event_type == TurnStreamEventType.TERMINAL and event.terminal is not None:
            host_view.append(
                {
                    "stop_reason": event.terminal.stop_reason,
                    "request_id": event.terminal.request_id,
                }
            )

    assert host_view[0] == {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "tool_use_id": "call-agent-1",
                "name": "agent",
                "input": {"agent": "verification", "prompt": "run checks"},
            }
        ],
        "metadata": {
            "stop_reason": "tool_use",
            "request_id": "req-host-main-1",
        },
    }
    assert host_view[1] == {
        "attempt_stop_reason": "tool_use",
        "request_id": "req-host-main-1",
        "produced_tool_calls": True,
    }
    assert host_view[2]["role"] == "user"
    assert host_view[2]["metadata"] == {
        "tool_results": [
            {
                "tool_use_id": "call-agent-1",
                "tool_name": "agent",
                "status": "success",
            }
        ]
    }
    tool_result = host_view[2]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "call-agent-1"
    assert tool_result["is_error"] is False
    assert tool_result["content"]["agent"] == "verification"
    assert tool_result["content"]["status"] == "completed"
    assert tool_result["content"]["background"] is False
    assert tool_result["content"]["run_id"]
    assert tool_result["content"]["turn_id"]
    assert tool_result["content"]["messages"] == [
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "subagent answer"}],
            "metadata": {
                "stop_reason": "end_turn",
                "request_id": "req-host-sub",
            },
        }
    ]
    assert tool_result["content"]["isolation_mode"] == "worktree"
    assert tool_result["content"]["terminal_metadata"] == {
        "stop_reason": "end_turn",
        "request_id": "req-host-sub",
    }
    assert host_view[3] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "agent delegation done"}],
        "metadata": {
            "stop_reason": "end_turn",
            "request_id": "req-host-main-2",
        },
    }
    assert host_view[4] == {
        "attempt_stop_reason": "end_turn",
        "request_id": "req-host-main-2",
        "produced_tool_calls": False,
    }
    assert host_view[5] == {
        "stop_reason": "end_turn",
        "request_id": "req-host-main-2",
    }
    assert all(
        not (
            isinstance(item, dict)
            and item.get("request_id") == "req-host-sub"
            or isinstance(item, dict)
            and item.get("metadata", {}).get("request_id") == "req-host-sub"
        )
        for item in host_view
    )


async def _collect_session_events(controller: SessionController):
    return [event async for event in controller.stream_until_idle()]
