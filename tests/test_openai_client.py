import asyncio
import json
from pathlib import Path

from weavert.builtins.tools import builtin_tools
from weavert.contracts import (
    MessageRole,
    RedactedThinkingBlock,
    RuntimeMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    TurnContext,
)
from weavert.definitions import ToolDefinition, ToolTraits
from weavert.devtools.builtins import devtools_builtin_tools
from weavert.devtools.tool_impls import _GLOB_TOOL_MAX_MATCHES
from weavert.openai_client import (
    BundledOpenAIModelClient,
    OPENAI_ROUTE_NAME,
    _build_responses_request_payload,
    _tool_definition_to_function_tool,
)
from weavert.runtime_kernel import BuiltinPackConfig, RuntimeConfig, assemble_runtime
from weavert.team.builtins import team_builtin_tools
from weavert.turn_engine import ModelRequest


def _turn_context() -> TurnContext:
    return TurnContext(
        session_id="session",
        turn_id="turn",
        agent_name="main-router",
        cwd="/tmp/project",
        messages=(),
    )


def _make_request(
    *,
    messages: tuple[RuntimeMessage, ...],
    tools: tuple[ToolDefinition, ...] = (),
    metadata: dict[str, object] | None = None,
) -> ModelRequest:
    return ModelRequest(
        system_prompt="System prompt",
        turn_context=_turn_context(),
        messages=messages,
        tools=tools,
        model="gpt-test",
        max_output_tokens=256,
        metadata={} if metadata is None else dict(metadata),
    )


def _nested_roundtrip_tool() -> ToolDefinition:
    return ToolDefinition(
        name="sync_jobs",
        description="Sync nested job state.",
        input_schema={
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string"},
                        "note": {"type": "string"},
                        "metadata": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["mode"],
                    "additionalProperties": False,
                },
                "jobs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "cwd": {"type": "string"},
                            "env": {
                                "type": "object",
                                "additionalProperties": True,
                            },
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["config", "jobs"],
            "additionalProperties": False,
        },
    )


def test_build_responses_request_folds_post_tool_system_guidance_into_instructions() -> None:
    payload = _build_responses_request_payload(
        _make_request(
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
                RuntimeMessage(
                    message_id="system-1",
                    role=MessageRole.SYSTEM,
                    content=(TextBlock(text="Summarize the results briefly."),),
                ),
            ),
        ),
        model_name="gpt-test",
    )

    assert payload["instructions"] == "System prompt\n\nSummarize the results briefly."
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


def test_build_responses_request_leaves_non_post_tool_system_messages_in_input() -> None:
    payload = _build_responses_request_payload(
        _make_request(
            messages=(
                RuntimeMessage(
                    message_id="user-1",
                    role=MessageRole.USER,
                    content=(TextBlock(text="Find the release notes."),),
                ),
                RuntimeMessage(
                    message_id="system-1",
                    role=MessageRole.SYSTEM,
                    content=(TextBlock(text="Prefer concise file summaries."),),
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
        ),
        model_name="gpt-test",
    )

    assert payload["instructions"] == "System prompt"
    assert payload["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Find the release notes."}],
        },
        {
            "type": "message",
            "role": "system",
            "content": [{"type": "input_text", "text": "Prefer concise file summaries."}],
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


def test_build_responses_request_folds_post_tool_system_guidance_across_thinking_only_gap() -> None:
    payload = _build_responses_request_payload(
        _make_request(
            messages=(
                RuntimeMessage(
                    message_id="assistant-1",
                    role=MessageRole.ASSISTANT,
                    content=(
                        ToolUseBlock(tool_use_id="call_prev", name="lookup", input={"path": "CHANGELOG.md"}),
                    ),
                ),
                RuntimeMessage(
                    message_id="user-1",
                    role=MessageRole.USER,
                    content=(
                        ToolResultBlock(
                            tool_use_id="call_prev",
                            content={"path": "CHANGELOG.md", "found": True},
                        ),
                    ),
                ),
                RuntimeMessage(
                    message_id="assistant-2",
                    role=MessageRole.ASSISTANT,
                    content=(ThinkingBlock(thinking="hidden reasoning"),),
                ),
                RuntimeMessage(
                    message_id="system-1",
                    role=MessageRole.SYSTEM,
                    content=(TextBlock(text="Summarize the results briefly."),),
                ),
            ),
        ),
        model_name="gpt-test",
    )

    assert payload["instructions"] == "System prompt\n\nSummarize the results briefly."
    assert payload["input"] == [
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


def test_build_responses_request_does_not_fold_system_guidance_after_visible_assistant_output() -> None:
    payload = _build_responses_request_payload(
        _make_request(
            messages=(
                RuntimeMessage(
                    message_id="assistant-1",
                    role=MessageRole.ASSISTANT,
                    content=(
                        ToolUseBlock(tool_use_id="call_prev", name="lookup", input={"path": "CHANGELOG.md"}),
                    ),
                ),
                RuntimeMessage(
                    message_id="user-1",
                    role=MessageRole.USER,
                    content=(
                        ToolResultBlock(
                            tool_use_id="call_prev",
                            content={"path": "CHANGELOG.md", "found": True},
                        ),
                    ),
                ),
                RuntimeMessage(
                    message_id="assistant-2",
                    role=MessageRole.ASSISTANT,
                    content=(TextBlock(text="I found the file."),),
                ),
                RuntimeMessage(
                    message_id="system-1",
                    role=MessageRole.SYSTEM,
                    content=(TextBlock(text="Summarize the results briefly."),),
                ),
            ),
        ),
        model_name="gpt-test",
    )

    assert payload["instructions"] == "System prompt"
    assert payload["input"] == [
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
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "I found the file."}],
            "status": "completed",
        },
        {
            "type": "message",
            "role": "system",
            "content": [{"type": "input_text", "text": "Summarize the results briefly."}],
        },
    ]


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
        metadata={"provider_request_policy": {"parallel_tool_calls": True}},
    )

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
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
    assert payload["parallel_tool_calls"] is True
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


def test_complete_serializes_responses_payload_without_route_policy_falls_back_to_disabled_parallel_tool_calls(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post_json(_url: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        captured["payload"] = payload
        assert api_key == "test-key"
        return {
            "id": "resp_complete_fallback",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                }
            ],
            "usage": {"input_tokens": 5, "output_tokens": 2},
        }

    tool = ToolDefinition(
        name="lookup",
        description="Lookup a file.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )
    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Find README.md"),),
            ),
        ),
        tools=(tool,),
    )

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json", fake_post_json)

    response = asyncio.run(BundledOpenAIModelClient().complete(request))

    assert response.message.text == "done"
    payload = captured["payload"]
    assert payload["parallel_tool_calls"] is False


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


def test_complete_restores_optional_builtin_devtool_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}
    glob_tool = next(tool for tool in devtools_builtin_tools() if tool.name == "glob")

    def fake_post_json(_url: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        assert api_key == "test-key"
        captured["payload"] = payload
        return {
            "id": "resp_glob",
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_glob",
                    "name": "glob",
                    "arguments": '{"pattern":"*.md","root":null}',
                }
            ],
            "usage": {"input_tokens": 6, "output_tokens": 2},
        }

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Find markdown files."),),
            ),
        ),
        tools=(glob_tool,),
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json", fake_post_json)

    response = asyncio.run(BundledOpenAIModelClient().complete(request))

    exported = captured["payload"]["tools"][0]["parameters"]
    assert exported["properties"]["root"]["type"] == ["string", "null"]
    assert "root" in exported["required"]
    assert response.message.content[0] == ToolUseBlock(
        tool_use_id="call_glob",
        name="glob",
        input={"pattern": "*.md"},
    )


def test_complete_restores_nested_and_array_tool_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}
    tool = _nested_roundtrip_tool()
    provider_arguments = {
        "config": {
            "mode": "safe",
            "note": None,
            "metadata": json.dumps({"owner": "ops"}),
        },
        "jobs": [
            {
                "name": "first",
                "cwd": None,
                "env": json.dumps({"region": "us"}),
            },
            {
                "name": "second",
                "cwd": "/tmp/work",
                "env": None,
            },
        ],
    }

    def fake_post_json(_url: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        assert api_key == "test-key"
        captured["payload"] = payload
        return {
            "id": "resp_nested",
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_nested",
                    "name": "sync_jobs",
                    "arguments": json.dumps(provider_arguments),
                }
            ],
            "usage": {"input_tokens": 9, "output_tokens": 4},
        }

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Sync the job state."),),
            ),
        ),
        tools=(tool,),
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json", fake_post_json)

    response = asyncio.run(BundledOpenAIModelClient().complete(request))

    exported = captured["payload"]["tools"][0]["parameters"]
    config_schema = exported["properties"]["config"]
    jobs_item_schema = exported["properties"]["jobs"]["items"]
    assert config_schema["properties"]["note"]["type"] == ["string", "null"]
    assert config_schema["properties"]["metadata"]["type"] == ["string", "null"]
    assert jobs_item_schema["properties"]["cwd"]["type"] == ["string", "null"]
    assert jobs_item_schema["properties"]["env"]["type"] == ["string", "null"]
    assert response.message.content[0] == ToolUseBlock(
        tool_use_id="call_nested",
        name="sync_jobs",
        input={
            "config": {
                "mode": "safe",
                "metadata": {"owner": "ops"},
            },
            "jobs": [
                {
                    "name": "first",
                    "env": {"region": "us"},
                },
                {
                    "name": "second",
                    "cwd": "/tmp/work",
                },
            ],
        },
    )



def test_complete_omits_hidden_thinking_from_request_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post_json(_url: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        assert api_key == "test-key"
        captured["payload"] = payload
        return {
            "id": "resp_no_thinking",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ],
            "usage": {"input_tokens": 4, "output_tokens": 1},
        }

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="assistant-1",
                role=MessageRole.ASSISTANT,
                content=(
                    TextBlock(text="Visible text."),
                    ThinkingBlock(thinking="hidden reasoning"),
                    RedactedThinkingBlock(data="sealed"),
                ),
            ),
        )
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json", fake_post_json)

    response = asyncio.run(BundledOpenAIModelClient().complete(request))

    assert response.message.text == "ok"
    assert captured["payload"]["input"] == [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Visible text."}],
            "status": "completed",
        }
    ]


def test_complete_maps_open_object_arguments_through_json_string_surrogates(monkeypatch) -> None:
    captured: dict[str, object] = {}

    surrogate_tool = ToolDefinition(
        name="dynamic_map",
        description="Uses dynamic keys.",
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
        tools=(surrogate_tool,),
    )

    def fake_post_json(_url: str, payload: dict[str, object], *, api_key: str) -> dict[str, object]:
        captured["payload"] = payload
        captured["api_key"] = api_key
        return {
            "id": "resp_dynamic_map",
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_dynamic_map",
                    "name": "dynamic_map",
                    "arguments": '{"labels":"{\\"priority\\":\\"high\\"}"}',
                }
            ],
            "usage": {"input_tokens": 4, "output_tokens": 2},
        }

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json", fake_post_json)

    response = asyncio.run(BundledOpenAIModelClient().complete(request))

    assert captured["api_key"] == "test-key"
    assert captured["payload"]["tools"][0]["parameters"]["properties"]["labels"] == {
        "type": "string",
        "description": "Pass a JSON object encoded as a string.",
    }
    assert response.stop_reason == "tool_use"
    assert response.message.content == (
        ToolUseBlock(
            tool_use_id="call_dynamic_map",
            name="dynamic_map",
            input={"labels": {"priority": "high"}},
        ),
    )


def test_bundled_tools_export_open_object_fields_as_json_string_surrogates() -> None:
    task_create = next(tool for tool in builtin_tools() if tool.name == "task_create")
    task_update = next(tool for tool in builtin_tools() if tool.name == "task_update")
    team_respond = next(tool for tool in team_builtin_tools() if tool.name == "team_respond")

    task_create_schema = _tool_definition_to_function_tool(task_create).function_tool["parameters"]
    task_update_schema = _tool_definition_to_function_tool(task_update).function_tool["parameters"]
    team_respond_schema = _tool_definition_to_function_tool(team_respond).function_tool["parameters"]

    assert task_create_schema["properties"]["metadata"]["type"] == ["string", "null"]
    assert task_update_schema["properties"]["metadata"]["type"] == ["string", "null"]
    assert team_respond_schema["properties"]["payload"]["type"] == ["string", "null"]



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


def test_stream_preserves_single_tool_use_when_completed_output_is_empty(monkeypatch) -> None:
    def fake_post_json_stream(_url: str, _payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        return iter(
            [
                {"type": "response.created", "response": {"id": "resp_stream_empty_completed"}},
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "type": "function_call",
                        "id": "fc_empty_completed",
                        "call_id": "call_empty_completed",
                        "name": "lookup",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_empty_completed",
                    "output_index": 0,
                    "arguments": '{"path":"README.md"}',
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_stream_empty_completed",
                        "status": "completed",
                        "output": [],
                        "usage": {"input_tokens": 8, "output_tokens": 2},
                    },
                },
            ]
        )

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Find the readme."),),
            ),
        )
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    async def collect_events():
        return [event async for event in BundledOpenAIModelClient().stream(request)]

    events = asyncio.run(collect_events())

    assert [event.event_type.value for event in events] == [
        "message_start",
        "content_block_start",
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
    assert (
        events[-1].terminal.metadata["stream_completed_output_fallback"]
        == "finalized_stream_tool_blocks"
    )


def test_stream_restores_nested_and_array_tool_fields(monkeypatch) -> None:
    tool = _nested_roundtrip_tool()
    provider_arguments = json.dumps(
        {
            "config": {
                "mode": "safe",
                "note": None,
                "metadata": json.dumps({"owner": "ops"}),
            },
            "jobs": [
                {
                    "name": "first",
                    "cwd": None,
                    "env": json.dumps({"region": "us"}),
                },
                {
                    "name": "second",
                    "cwd": "/tmp/work",
                    "env": None,
                },
            ],
        }
    )

    def fake_post_json_stream(_url: str, _payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        return iter(
            [
                {"type": "response.created", "response": {"id": "resp_nested_stream"}},
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "type": "function_call",
                        "id": "fc_nested",
                        "call_id": "call_nested",
                        "name": "sync_jobs",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_nested",
                    "output_index": 0,
                    "arguments": provider_arguments,
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_nested_stream",
                        "status": "completed",
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "call_nested",
                                "name": "sync_jobs",
                                "arguments": provider_arguments,
                            }
                        ],
                        "usage": {"input_tokens": 7, "output_tokens": 3},
                    },
                },
            ]
        )

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Stream the nested tool call."),),
            ),
        ),
        tools=(tool,),
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    async def collect_events():
        return [event async for event in BundledOpenAIModelClient().stream(request)]

    events = asyncio.run(collect_events())

    finalized_delta = next(
        event
        for event in events
        if event.event_type.value == "content_block_delta" and "input" in event.payload
    )
    assert finalized_delta.payload["input"] == {
        "config": {
            "mode": "safe",
            "metadata": {"owner": "ops"},
        },
        "jobs": [
            {
                "name": "first",
                "env": {"region": "us"},
            },
            {
                "name": "second",
                "cwd": "/tmp/work",
            },
        ],
    }
    assert events[-1].terminal is not None
    assert events[-1].terminal.stop_reason == "tool_use"


def test_stream_replays_completed_only_blocks_when_no_prior_deltas(monkeypatch) -> None:
    def fake_post_json_stream(_url: str, _payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        return iter(
            [
                {"type": "response.created", "response": {"id": "resp_completed_only"}},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_completed_only",
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": "Need fallback"}],
                            },
                            {
                                "type": "function_call",
                                "call_id": "call_fallback",
                                "name": "lookup",
                                "arguments": '{"path":"README.md"}',
                            },
                        ],
                        "usage": {"input_tokens": 5, "output_tokens": 4},
                    },
                },
            ]
        )

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Fallback please."),),
            ),
        )
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    async def collect_events():
        return [event async for event in BundledOpenAIModelClient().stream(request)]

    events = asyncio.run(collect_events())

    assert [event.event_type.value for event in events] == [
        "message_start",
        "content_delta",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_stop",
    ]
    assert events[1].payload["text"] == "Need fallback"
    assert events[-1].terminal is not None
    assert events[-1].terminal.stop_reason == "tool_use"


def test_stream_completed_only_restores_builtin_optional_devtool_fields(monkeypatch) -> None:
    bash_tool = next(tool for tool in devtools_builtin_tools() if tool.name == "bash")

    def fake_post_json_stream(_url: str, _payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        return iter(
            [
                {"type": "response.created", "response": {"id": "resp_bash_fallback"}},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_bash_fallback",
                        "status": "completed",
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "call_bash",
                                "name": "bash",
                                "arguments": (
                                    '{"command":"printf hi","cwd":null,"shell":null,"timeout_ms":null}'
                                ),
                            }
                        ],
                        "usage": {"input_tokens": 5, "output_tokens": 3},
                    },
                },
            ]
        )

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Replay the builtin bash call."),),
            ),
        ),
        tools=(bash_tool,),
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    async def collect_events():
        return [event async for event in BundledOpenAIModelClient().stream(request)]

    events = asyncio.run(collect_events())

    finalized_delta = next(
        event
        for event in events
        if event.event_type.value == "content_block_delta" and "input" in event.payload
    )
    assert finalized_delta.payload["input"] == {"command": "printf hi"}
    assert events[-1].terminal is not None
    assert events[-1].terminal.stop_reason == "tool_use"


def test_stream_ignores_empty_output_fallback_when_completed_output_has_items(monkeypatch) -> None:
    def fake_post_json_stream(_url: str, _payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        return iter(
            [
                {"type": "response.created", "response": {"id": "resp_populated_completed"}},
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "type": "function_call",
                        "id": "fc_populated_completed",
                        "call_id": "call_populated_completed",
                        "name": "lookup",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_populated_completed",
                    "output_index": 0,
                    "arguments": '{"path":"README.md"}',
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_populated_completed",
                        "status": "completed",
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "call_populated_completed",
                                "name": "lookup",
                                "arguments": '{"path":"README.md"}',
                            }
                        ],
                        "usage": {"input_tokens": 8, "output_tokens": 2},
                    },
                },
            ]
        )

    request = _make_request(
        messages=(
            RuntimeMessage(
                message_id="user-1",
                role=MessageRole.USER,
                content=(TextBlock(text="Find the readme."),),
            ),
        )
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    async def collect_events():
        return [event async for event in BundledOpenAIModelClient().stream(request)]

    events = asyncio.run(collect_events())

    assert events[-1].terminal is not None
    assert events[-1].terminal.stop_reason == "tool_use"
    assert "stream_completed_output_fallback" not in events[-1].terminal.metadata


def test_runtime_default_openai_route_preserves_ordered_multi_tool_continuations(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_payloads: list[dict[str, object]] = []
    scripted_batches = [
        [
            {"type": "response.created", "response": {"id": "resp-1"}},
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_slow_lookup",
                    "call_id": "call_slow_lookup",
                    "name": "slow_lookup",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_slow_lookup",
                "output_index": 0,
                "arguments": '{"path":"README.md"}',
            },
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": "fc_fast_lookup",
                    "call_id": "call_fast_lookup",
                    "name": "fast_lookup",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_fast_lookup",
                "output_index": 1,
                "arguments": '{"path":"CONTRIBUTING.md"}',
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-1",
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_slow_lookup",
                            "name": "slow_lookup",
                            "arguments": '{"path":"README.md"}',
                        },
                        {
                            "type": "function_call",
                            "call_id": "call_fast_lookup",
                            "name": "fast_lookup",
                            "arguments": '{"path":"CONTRIBUTING.md"}',
                        },
                    ],
                    "usage": {"input_tokens": 18, "output_tokens": 6},
                },
            },
        ],
        [
            {"type": "response.created", "response": {"id": "resp-2"}},
            {"type": "response.output_text.delta", "delta": "Tools said hello"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-2",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Tools said hello"}],
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 4},
                },
            },
        ],
    ]

    def fake_post_json_stream(_url: str, payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        captured_payloads.append(payload)
        return iter(scripted_batches.pop(0))

    async def slow_lookup(tool_input, _context):
        await asyncio.sleep(0.02)
        return {"path": tool_input["path"], "content": "slow hello"}

    async def fast_lookup(tool_input, _context):
        await asyncio.sleep(0)
        return {"path": tool_input["path"], "content": "fast hello"}

    slow_tool = ToolDefinition(
        name="slow_lookup",
        description="Lookup a file slowly.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        traits=ToolTraits(read_only=True, concurrency_safe=True),
        execute=slow_lookup,
    )
    fast_tool = ToolDefinition(
        name="fast_lookup",
        description="Lookup a file quickly.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        traits=ToolTraits(read_only=True, concurrency_safe=True),
        execute=fast_lookup,
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            builtins=BuiltinPackConfig(extra_tools=[slow_tool, fast_tool]),
        )
    )
    produced = asyncio.run(runtime.run_prompt("Read the readme", session_id="openai-tool"))

    assert runtime.kernel.config.default_model_route == OPENAI_ROUTE_NAME
    route_metadata = runtime.kernel.config.model_routes[OPENAI_ROUTE_NAME].metadata
    assert route_metadata["provider_request_policy"] == {"parallel_tool_calls": True}
    assert "parallel_tool_calls" not in route_metadata
    assert produced[-1].text == "Tools said hello"
    assert captured_payloads[0]["parallel_tool_calls"] is True
    tool_names = {tool["name"] for tool in captured_payloads[0]["tools"]}
    assert {"slow_lookup", "fast_lookup"}.issubset(tool_names)
    continuation_items = [
        (item.get("type"), item.get("call_id"))
        for item in captured_payloads[1]["input"]
        if item.get("call_id") in {"call_slow_lookup", "call_fast_lookup"}
    ]
    assert continuation_items == [
        ("function_call", "call_slow_lookup"),
        ("function_call", "call_fast_lookup"),
        ("function_call_output", "call_slow_lookup"),
        ("function_call_output", "call_fast_lookup"),
    ]


def test_runtime_default_openai_route_replays_single_tool_when_completed_output_is_empty(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_payloads: list[dict[str, object]] = []
    scripted_batches = [
        [
            {"type": "response.created", "response": {"id": "resp-empty-single-1"}},
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_empty_single",
                    "call_id": "call_empty_single",
                    "name": "lookup",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_empty_single",
                "output_index": 0,
                "arguments": '{"path":"README.md"}',
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-empty-single-1",
                    "status": "completed",
                    "output": [],
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                },
            },
        ],
        [
            {"type": "response.created", "response": {"id": "resp-empty-single-2"}},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-empty-single-2",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "Recovered from empty completed output"}
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 6, "output_tokens": 4},
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
    produced = asyncio.run(
        runtime.run_prompt("Read the readme", session_id="openai-tool-empty-completed-single")
    )

    assert produced[-1].text == "Recovered from empty completed output"
    continuation_items = [
        (item.get("type"), item.get("call_id"))
        for item in captured_payloads[1]["input"]
        if item.get("call_id") == "call_empty_single"
    ]
    assert continuation_items == [
        ("function_call", "call_empty_single"),
        ("function_call_output", "call_empty_single"),
    ]


def test_runtime_default_openai_route_replays_multi_tool_when_completed_output_is_empty(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_payloads: list[dict[str, object]] = []
    scripted_batches = [
        [
            {"type": "response.created", "response": {"id": "resp-empty-multi-1"}},
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_empty_slow_lookup",
                    "call_id": "call_empty_slow_lookup",
                    "name": "slow_lookup",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_empty_slow_lookup",
                "output_index": 0,
                "arguments": '{"path":"README.md"}',
            },
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": "fc_empty_fast_lookup",
                    "call_id": "call_empty_fast_lookup",
                    "name": "fast_lookup",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_empty_fast_lookup",
                "output_index": 1,
                "arguments": '{"path":"CONTRIBUTING.md"}',
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-empty-multi-1",
                    "status": "completed",
                    "output": [],
                    "usage": {"input_tokens": 18, "output_tokens": 4},
                },
            },
        ],
        [
            {"type": "response.created", "response": {"id": "resp-empty-multi-2"}},
            {
                "type": "response.output_text.delta",
                "delta": "Tools kept their order",
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-empty-multi-2",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "Tools kept their order"}
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 8, "output_tokens": 4},
                },
            },
        ],
    ]

    def fake_post_json_stream(_url: str, payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        captured_payloads.append(payload)
        return iter(scripted_batches.pop(0))

    async def slow_lookup(tool_input, _context):
        await asyncio.sleep(0.02)
        return {"path": tool_input["path"], "content": "slow hello"}

    async def fast_lookup(tool_input, _context):
        await asyncio.sleep(0)
        return {"path": tool_input["path"], "content": "fast hello"}

    slow_tool = ToolDefinition(
        name="slow_lookup",
        description="Lookup a file slowly.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        traits=ToolTraits(read_only=True, concurrency_safe=True),
        execute=slow_lookup,
    )
    fast_tool = ToolDefinition(
        name="fast_lookup",
        description="Lookup a file quickly.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        traits=ToolTraits(read_only=True, concurrency_safe=True),
        execute=fast_lookup,
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    runtime = assemble_runtime(
        RuntimeConfig(
            working_directory=tmp_path,
            builtins=BuiltinPackConfig(extra_tools=[slow_tool, fast_tool]),
        )
    )
    produced = asyncio.run(
        runtime.run_prompt("Read the readme", session_id="openai-tool-empty-completed-multi")
    )

    assert produced[-1].text == "Tools kept their order"
    continuation_items = [
        (item.get("type"), item.get("call_id"))
        for item in captured_payloads[1]["input"]
        if item.get("call_id") in {"call_empty_slow_lookup", "call_empty_fast_lookup"}
    ]
    assert continuation_items == [
        ("function_call", "call_empty_slow_lookup"),
        ("function_call", "call_empty_fast_lookup"),
        ("function_call_output", "call_empty_slow_lookup"),
        ("function_call_output", "call_empty_fast_lookup"),
    ]


def test_runtime_default_openai_route_restores_builtin_optional_devtool_fields_during_stream_deltas(
    monkeypatch,
    tmp_path: Path,
) -> None:
    scripted_batches = [
        [
            {"type": "response.created", "response": {"id": "resp-bash-1"}},
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_bash",
                    "call_id": "call_bash",
                    "name": "bash",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_bash",
                "output_index": 0,
                "delta": '{"command":"printf hi","cwd":null,"shell":null,"timeout_ms":null}',
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_bash",
                "output_index": 0,
                "arguments": '{"command":"printf hi","cwd":null,"shell":null,"timeout_ms":null}',
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-bash-1",
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_bash",
                            "name": "bash",
                            "arguments": '{"command":"printf hi","cwd":null,"shell":null,"timeout_ms":null}',
                        }
                    ],
                    "usage": {"input_tokens": 8, "output_tokens": 3},
                },
            },
        ],
        [
            {"type": "response.created", "response": {"id": "resp-bash-2"}},
            {"type": "response.output_text.delta", "delta": "hi"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-bash-2",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "hi"}],
                        }
                    ],
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
            },
        ],
    ]

    def fake_post_json_stream(_url: str, _payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
        return iter(scripted_batches.pop(0))

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    runtime = assemble_runtime(RuntimeConfig(working_directory=tmp_path))
    produced = asyncio.run(
        runtime.run_prompt("Run the builtin bash tool.", session_id="openai-bash-stream-delta")
    )

    assert produced[-1].text == "hi"


def test_runtime_default_openai_route_handles_completed_only_stream_blocks(monkeypatch, tmp_path: Path) -> None:
    scripted_batches = [
        [
            {"type": "response.created", "response": {"id": "resp-completed-tool"}},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-completed-tool",
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_lookup",
                            "name": "lookup",
                            "arguments": '{"path":"README.md"}',
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                },
            },
        ],
        [
            {"type": "response.created", "response": {"id": "resp-completed-text"}},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-completed-text",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "Recovered from completed-only stream"}
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 6, "output_tokens": 5},
                },
            },
        ],
    ]

    def fake_post_json_stream(_url: str, _payload: dict[str, object], *, api_key: str):
        assert api_key == "test-key"
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
    produced = asyncio.run(runtime.run_prompt("Read the readme", session_id="openai-tool-completed-only"))

    assert produced[-1].text == "Recovered from completed-only stream"


def test_runtime_default_openai_route_bounds_large_builtin_glob_results(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured_payloads: list[dict[str, object]] = []
    scripted_batches = [
        [
            {"type": "response.created", "response": {"id": "resp-glob-large-1"}},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-glob-large-1",
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_glob",
                            "name": "glob",
                            "arguments": '{"pattern":"**/*"}',
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                },
            },
        ],
        [
            {"type": "response.created", "response": {"id": "resp-glob-large-2"}},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-glob-large-2",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Repository summary"}],
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

    for index in range(_GLOB_TOOL_MAX_MATCHES + 7):
        (tmp_path / f"file-{index:03}.txt").write_text("payload", encoding="utf-8")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("weavert.openai_client._post_json_stream", fake_post_json_stream)

    runtime = assemble_runtime(RuntimeConfig(working_directory=tmp_path))
    produced = asyncio.run(
        runtime.run_prompt("Summarize this repository and use tools when needed.", session_id="openai-glob-large")
    )

    assert produced[-1].text == "Repository summary"
    continuation_items = captured_payloads[1]["input"]
    tool_result_item = next(
        item
        for item in continuation_items
        if item.get("type") == "function_call_output" and item.get("call_id") == "call_glob"
    )
    tool_result_output = json.loads(tool_result_item["output"])
    assert tool_result_output["truncated"] is True
    assert tool_result_output["total_matches"] > _GLOB_TOOL_MAX_MATCHES
    assert tool_result_output["returned_matches"] == _GLOB_TOOL_MAX_MATCHES
    assert len(tool_result_output["matches"]) == _GLOB_TOOL_MAX_MATCHES
