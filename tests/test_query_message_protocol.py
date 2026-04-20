import asyncio
import json
from pathlib import Path

from runtime.contracts import MessageRole, RuntimeMessage, TextBlock, ToolResultBlock, ToolUseBlock
from runtime.session_runtime import FileTranscriptStore
from runtime.turn_engine import TranscriptEntry
from runtime.turn_engine.message_protocol import normalize_messages_for_api


def test_transcript_store_round_trips_structured_blocks(tmp_path: Path) -> None:
    store = FileTranscriptStore(tmp_path / "transcripts")
    entries = (
        TranscriptEntry(
            session_id="session",
            turn_id="turn-1",
            message=RuntimeMessage(
                message_id="assistant-tool-use",
                role=MessageRole.ASSISTANT,
                content=(
                    TextBlock(text="Working on it."),
                    ToolUseBlock(tool_use_id="call-1", name="echo", input={"value": "ping"}),
                ),
            ),
        ),
        TranscriptEntry(
            session_id="session",
            turn_id="turn-1",
            message=RuntimeMessage(
                message_id="user-tool-result",
                role=MessageRole.USER,
                content=(ToolResultBlock(tool_use_id="call-1", content={"echo": "ping"}),),
            ),
        ),
    )

    for entry in entries:
        asyncio.run(store.append(entry))

    loaded = asyncio.run(store.load("session"))

    assert len(loaded.entries) == 2
    assistant_blocks = loaded.entries[0].message.content
    assert isinstance(assistant_blocks[0], TextBlock)
    assert isinstance(assistant_blocks[1], ToolUseBlock)
    assert assistant_blocks[1].tool_use_id == "call-1"
    user_blocks = loaded.entries[1].message.content
    assert isinstance(user_blocks[0], ToolResultBlock)
    assert user_blocks[0].tool_use_id == "call-1"
    assert user_blocks[0].content == {"echo": "ping"}


def test_transcript_store_reads_legacy_flat_content_as_text_block(tmp_path: Path) -> None:
    store = FileTranscriptStore(tmp_path / "transcripts")
    path = tmp_path / "transcripts" / "legacy-session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "session_id": "legacy-session",
                "turn_id": "turn-1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "message": {
                    "message_id": "legacy-message",
                    "role": "user",
                    "content": "plain legacy content",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "attachments": [],
                    "metadata": {},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = asyncio.run(store.load("legacy-session"))

    assert loaded.entries[0].message.content == (TextBlock(text="plain legacy content"),)


def test_normalize_messages_for_api_merges_messages_and_repairs_pairing() -> None:
    normalized = normalize_messages_for_api(
        (
            RuntimeMessage(message_id="user-1", role=MessageRole.USER, content="hello "),
            RuntimeMessage(message_id="user-2", role=MessageRole.USER, content="world"),
            RuntimeMessage(message_id="host-only", role=MessageRole.TOOL, content="debug"),
            RuntimeMessage(
                message_id="assistant-1",
                role=MessageRole.ASSISTANT,
                content=(
                    TextBlock(text="draft"),
                    ToolUseBlock(tool_use_id="dangling-call", name=" echo ", input={"value": "ping"}),
                ),
            ),
            RuntimeMessage(
                message_id="user-3",
                role=MessageRole.USER,
                content=(
                    ToolResultBlock(tool_use_id="orphan-result", content={"bad": True}),
                    TextBlock(text="note"),
                ),
            ),
            RuntimeMessage(
                message_id="assistant-2",
                role=MessageRole.ASSISTANT,
                content=(ToolUseBlock(tool_use_id="call-2", name=" echo ", input={"value": "pong"}),),
            ),
            RuntimeMessage(
                message_id="user-4",
                role=MessageRole.USER,
                content=(ToolResultBlock(tool_use_id="call-2", content={"echo": "pong"}),),
            ),
        )
    )

    assert len(normalized) == 5
    assert normalized[0].role == MessageRole.USER
    assert normalized[0].text == "hello world"
    assert all(message.role != MessageRole.TOOL for message in normalized)
    assert normalized[1].role == MessageRole.ASSISTANT
    assert normalized[1].content == (TextBlock(text="draft"),)
    repaired_tool_use = next(
        block
        for message in normalized
        for block in message.content
        if isinstance(block, ToolUseBlock) and block.tool_use_id == "call-2"
    )
    assert repaired_tool_use.name == "echo"
    repaired_tool_result = next(
        block
        for message in normalized
        for block in message.content
        if isinstance(block, ToolResultBlock) and block.tool_use_id == "call-2"
    )
    assert repaired_tool_result.content == {"echo": "pong"}
    assert all(
        not any(
            isinstance(block, ToolUseBlock) and block.tool_use_id == "dangling-call"
            or isinstance(block, ToolResultBlock) and block.tool_use_id == "orphan-result"
            for block in message.content
        )
        for message in normalized
    )
