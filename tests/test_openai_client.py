import asyncio
from pathlib import Path

from weavert.contracts import (
    MessageRole,
    RuntimeMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    TurnContext,
)
from weavert.definitions import ToolDefinition, ToolTraits
from weavert.openai_client import BundledOpenAIModelClient, OPENAI_ROUTE_NAME
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime
from weavert.turn_engine import ModelRequest


def _turn_context() -> TurnContext:
    return TurnContext(
        session_id="session",
        turn_id="turn",
        agent_name="main-router",
        cwd="/tmp/project",
        messages=(),
    )


def _make_request(*, messages: tuple[RuntimeMessage, ...], tools: tuple[ToolDefinition, ...] = ()) -> ModelRequest:
    return ModelRequest(
        system_prompt="System prompt",
        turn_context=_turn_context(),
        messages=messages,
        tools=tools,
        model="gpt-test",
        max_output_tokens=256,
    )


def test_complete_serializes_responses_payload_with_tools_and_tool_results(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post_json(url: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        captured["url"] = url
        captured["payload"] = payload
        captured["api_key"] = api_key
        return {
            "id": "resp_complete",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 5},
        }

    tool = ToolDefinition(
        name="lookup",
        description="Lookup a file.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    )
    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Find the release notes."),),
            ),
            RuntimeMessage(
                message_id="assistant-1",
                role=MessageRole.ASSISTANT,
                content=(
                    TextBlock(text="I will inspect the file."),
                    ToolUseBlock(tool_use_id="call_prev", name="lookup", input={"path": "CHANGELOG.md"}),
                ),
            ),
            RuntimeMessage(
                message_id="user-2",
                role=MessageRole.USER,
                content=(
                    ToolResultBlock(
                        tool_use_id="call_prev",
                        content={"path": "CHANGELOG.md", "found": True},
                    ),
                ),
            ),
        ),
        tools=(tool,),
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json", fake_post_json)

    response = asyncio.run(BundledOpenAIModelClient().complete(request))

    assert response.message.text == "done"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["api_key"] == "test-key"

    payload = captured["payload"]
    assert payload["model"] == "gpt-test"
    assert payload["instructions"] == "System prompt"
    assert payload["max_output_tokens"] == 256
    assert payload["parallel_tool_calls"] is False
    assert payload["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Find the release notes."}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "I will inspect the file."}],
            "status": "completed",
        },
        {
            "type": "function_call",
            "call_id": "call_prev",
            "name": "lookup",
            "arguments": '{"path":"CHANGELOG.md"}',
            "status": "completed",
        },
        {
            "type": "function_call_output",
            "call_id": "call_prev",
            "output": '{"path":"CHANGELOG.md","found":true}',
        },
    ]
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Lookup a file.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "note": {"type": ["string", "null"]},
                },
                "required": ["path", "note"],
                "additionalProperties": False,
            },
        }
    ]



def test_complete_parses_function_calls_into_runtime_blocks(monkeypatch) -> None:
    def fake_post_json(_url: str, _payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        assert api_key == "test-key"
        return {
            "id": "resp_tool_use",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "I need to check."}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_lookup",
                    "name": "lookup",
                    "arguments": '{"path":"README.md"}',
                },
            ],
            "usage": {"input_tokens": 7, "output_tokens": 3},
        }

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Read the readme."),),
            ),
        )
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json", fake_post_json)

    response = asyncio.run(BundledOpenAIModelClient().complete(request))

    assert response.stop_reason == "tool_use"
    assert response.request_id == "resp_tool_use"
    assert response.message.content[0] == TextBlock(text="I need to check.")
    assert response.message.content[1] == ToolUseBlock(
        tool_use_id="call_lookup",
        name="lookup",
        input={"path": "README.md"},
    )
    assert response.terminal is not None
    assert response.terminal.metadata["provider_response_id"] == "resp_tool_use"
    assert response.terminal.metadata["response_status"] == "completed"



def test_complete_surfaces_tool_schema_errors_before_network(monkeypatch) -> None:
    def should_not_run(*_args, **_kwargs):  # pragma: no cover - defensive guard
        raise AssertionError("network should not run")

    bad_tool = ToolDefinition(
        name="dynamic_map",
        description="Uses unsupported dynamic keys.",
        input_schema={
            "type": "object",
            "properties": {
                "labels": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                }
            },
            "required": ["labels"],
            "additionalProperties": False,
        },
    )
    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Label this."),),
            ),
        ),
        tools=(bad_tool,),
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json", should_not_run)

    response = asyncio.run(BundledOpenAIModelClient().complete(request))

    assert response.terminal is not None
    assert response.terminal.metadata["failure_class"] == "tool_schema_error"
    assert response.terminal.metadata["tool_name"] == "dynamic_map"
    assert "additionalProperties" in response.terminal.metadata["error"]



def test_stream_maps_text_and_function_call_events(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_post_json_stream(_url: str, payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        captured.append(payload)
        return iter(
            [
                {"type": "response.created", "response": {"id": "resp_stream"}},
                {"type": "response.output_text.delta", "delta": "Need "},
                {"type": "response.output_text.delta", "delta": "data"},
                {
                    "type": "response.output_item.added",
                    "output_index": 1,
                    "item": {
                        "type": "function_call",
                        "id": "fc_1",
                        "call_id": "call_stream",
                        "name": "lookup",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "output_index": 1,
                    "delta": '{"path":"',
                },
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_1",
                    "output_index": 1,
                    "arguments": '{"path":"README.md"}',
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_stream",
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": "Need data"}],
                            },
                            {
                                "type": "function_call",
                                "call_id": "call_stream",
                                "name": "lookup",
                                "arguments": '{"path":"README.md"}',
                            },
                        ],
                        "usage": {"input_tokens": 8, "output_tokens": 4},
                    },
                },
            ]
        )

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Find data."),),
            ),
        )
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    async def collect_events():
        return [event async for event in BundledOpenAIModelClient().stream(request)]

    events = asyncio.run(collect_events())

    assert captured[0]["stream"] is True
    assert [event.event_type.value for event in events] == [
        "message_start",
        "content_delta",
        "content_delta",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_stop",
    ]
    finalized_delta = next(
        event
        for event in events
        if event.event_type.value == "content_block_delta" and "input" in event.payload
    )
    assert finalized_delta.payload["input"] == {"path": "README.md"}
    assert events[-1].terminal is not None
    assert events[-1].terminal.stop_reason == "tool_use"
    assert events[-1].terminal.metadata["provider_response_id"] == "resp_stream"



def test_runtime_default_openai_route_executes_tool_continuations(monkeypatch, tmp_path: Path) -> None:
    captured_payloads: list[dict[str, object]] = []
    scripted_batches = [
        [
            {"type": "response.created", "response": {"id": "resp-1"}},
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_lookup",
                    "call_id": "call_lookup",
                    "name": "lookup",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_lookup",
                "output_index": 0,
                "arguments": '{"path":"README.md"}',
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-1",
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_lookup",
                            "name": "lookup",
                            "arguments": '{"path":"README.md"}',
                        }
                    ],
                    "usage": {"input_tokens": 12, "output_tokens": 4},
                },
            },
        ],
        [
            {"type": "response.created", "response": {"id": "resp-2"}},
            {"type": "response.output_text.delta", "delta": "Tool said hello"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-2",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Tool said hello"}],
                        }
                    ],
                    "usage": {"input_tokens": 6, "output_tokens": 3},
                },
            },
        ],
    ]

    def fake_post_json_stream(_url: str, payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        captured_payloads.append(payload)
        return iter(scripted_batches.pop(0))

    tool = ToolDefinition(
        name="lookup",
        description="Lookup a file.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        traits=ToolTraits(read_only=True, concurrency_safe=True),
        execute=lambda tool_input, _context: {"path": tool_input["path"], "content": "hello"},
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            builtins=BuiltinPackConfig(extra_tools=[tool]),
        )
    )
    produced = asyncio.run(runtime.run_prompt("Read the readme", session_id="openai-tool"))

    assert runtime.kernel.config.default_model_route == OPENAI_ROUTE_NAME
    assert produced[-1].text == "Tool said hello"
    assert captured_payloads[0]["parallel_tool_calls"] is False
    assert any(tool["name"] == "lookup" for tool in captured_payloads[0]["tools"])
    continuation_items = captured_payloads[1]["input"]
    assert any(item.get("type") == "function_call" and item.get("call_id") == "call_lookup" for item in continuation_items)
    assert any(item.get("type") == "function_call_output" and item.get("call_id") == "call_lookup" for item in continuation_items)
