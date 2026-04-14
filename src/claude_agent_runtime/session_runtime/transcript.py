from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..contracts import MessageAttachment, MessageRole, RuntimeMessage
from ..turn_engine.models import TranscriptEntry, TranscriptSession, TranscriptStore


class InMemoryTranscriptStore(TranscriptStore):
    def __init__(self) -> None:
        self._sessions: dict[str, list[TranscriptEntry]] = {}

    async def append(self, entry: TranscriptEntry) -> None:
        self._sessions.setdefault(entry.session_id, []).append(entry)

    async def load(self, session_id: str) -> TranscriptSession:
        return TranscriptSession(session_id=session_id, entries=tuple(self._sessions.get(session_id, [])))

    async def replace(self, session: TranscriptSession) -> None:
        self._sessions[session.session_id] = list(session.entries)


class FileTranscriptStore(TranscriptStore):
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    async def append(self, entry: TranscriptEntry) -> None:
        with self._path(entry.session_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_serialize_entry(entry), ensure_ascii=True) + "\n")

    async def load(self, session_id: str) -> TranscriptSession:
        path = self._path(session_id)
        if not path.exists():
            return TranscriptSession(session_id=session_id, entries=())
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entries.append(_deserialize_entry(json.loads(line)))
        return TranscriptSession(session_id=session_id, entries=tuple(entries))

    async def replace(self, session: TranscriptSession) -> None:
        with self._path(session.session_id).open("w", encoding="utf-8") as handle:
            for entry in session.entries:
                handle.write(json.dumps(_serialize_entry(entry), ensure_ascii=True) + "\n")

    def _path(self, session_id: str) -> Path:
        return self._root / f"{session_id}.jsonl"


def _serialize_entry(entry: TranscriptEntry) -> dict[str, object]:
    return {
        "session_id": entry.session_id,
        "turn_id": entry.turn_id,
        "created_at": entry.created_at.isoformat(),
        "message": {
            "message_id": entry.message.message_id,
            "role": entry.message.role.value,
            "content": entry.message.content,
            "created_at": entry.message.created_at.isoformat(),
            "attachments": [asdict(attachment) for attachment in entry.message.attachments],
            "metadata": entry.message.metadata,
        },
    }


def _deserialize_entry(payload: dict[str, object]) -> TranscriptEntry:
    message_payload = payload["message"]
    attachments = tuple(
        MessageAttachment(**attachment) for attachment in message_payload.get("attachments", [])
    )
    message = RuntimeMessage(
        message_id=message_payload["message_id"],
        role=MessageRole(message_payload["role"]),
        content=message_payload["content"],
        attachments=attachments,
        metadata=message_payload.get("metadata", {}),
    )
    return TranscriptEntry(
        session_id=payload["session_id"],
        turn_id=payload.get("turn_id"),
        message=message,
    )

