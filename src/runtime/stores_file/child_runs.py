from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from ..agent_execution import AgentRunRecord, AgentRunStatus, ChildRunStore, SpawnMode
from ..contracts import (
    MessageAttachment,
    MessageRole,
    RuntimeMessage,
    deserialize_content_blocks,
    serialize_content_blocks,
)


class FileChildRunStore(ChildRunStore):
    def __init__(self, root: Path) -> None:
        self._root = root
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    async def upsert(self, record: AgentRunRecord) -> None:
        self._run_path(record.run_id).write_text(
            json.dumps(_serialize_run_record(record), indent=2, ensure_ascii=True, default=str) + "\n",
            encoding="utf-8",
        )
        run_ids = self._read_session_index(record.session_id)
        if record.run_id not in run_ids:
            run_ids.append(record.run_id)
            self._write_session_index(record.session_id, run_ids)

    async def get(self, run_id: str) -> AgentRunRecord | None:
        path = self._run_path(run_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, Mapping):
            return None
        return _deserialize_run_record(payload)

    async def list_by_session(self, session_id: str) -> tuple[AgentRunRecord, ...]:
        records: list[AgentRunRecord] = []
        for run_id in self._read_session_index(session_id):
            record = await self.get(run_id)
            if record is not None:
                records.append(record)
        return tuple(records)

    @property
    def _runs_dir(self) -> Path:
        return self._root / "runs"

    @property
    def _sessions_dir(self) -> Path:
        return self._root / "sessions"

    def _run_path(self, run_id: str) -> Path:
        return self._runs_dir / f"{run_id}.json"

    def _session_index_path(self, session_id: str) -> Path:
        return self._sessions_dir / f"{session_id}.json"

    def _read_session_index(self, session_id: str) -> list[str]:
        path = self._session_index_path(session_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [str(item) for item in payload if str(item).strip()]

    def _write_session_index(self, session_id: str, run_ids: list[str]) -> None:
        self._session_index_path(session_id).write_text(
            json.dumps(run_ids, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )


def _serialize_run_record(record: AgentRunRecord) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "parent_run_id": record.parent_run_id,
        "session_id": record.session_id,
        "parent_turn_id": record.parent_turn_id,
        "turn_id": record.turn_id,
        "agent_name": record.agent_name,
        "spawn_mode": record.spawn_mode.value,
        "status": record.status.value,
        "query_source": record.query_source,
        "delegation_depth": record.delegation_depth,
        "requested_model_route": record.requested_model_route,
        "requested_model": record.requested_model,
        "requested_effort": record.requested_effort,
        "resolved_model_route": record.resolved_model_route,
        "provider_name": record.provider_name,
        "resolved_capabilities": record.resolved_capabilities,
        "invocation_mode": record.invocation_mode,
        "request_metadata": dict(record.request_metadata),
        "terminal_metadata": dict(record.terminal_metadata),
        "messages": [_serialize_message(message) for message in record.messages],
    }


def _deserialize_run_record(payload: Mapping[str, Any]) -> AgentRunRecord | None:
    run_id = str(payload.get("run_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    agent_name = str(payload.get("agent_name") or "").strip()
    spawn_mode = str(payload.get("spawn_mode") or "").strip()
    status = str(payload.get("status") or "").strip()
    if not run_id or not session_id or not agent_name or not spawn_mode or not status:
        return None
    messages = []
    for raw_message in payload.get("messages", ()) or ():
        if not isinstance(raw_message, Mapping):
            continue
        message = _deserialize_message(raw_message)
        if message is not None:
            messages.append(message)
    return AgentRunRecord(
        run_id=run_id,
        parent_run_id=_coerce_optional_string(payload.get("parent_run_id")),
        session_id=session_id,
        parent_turn_id=_coerce_optional_string(payload.get("parent_turn_id")),
        turn_id=_coerce_optional_string(payload.get("turn_id")),
        agent_name=agent_name,
        spawn_mode=SpawnMode(spawn_mode),
        status=AgentRunStatus(status),
        query_source=_coerce_optional_string(payload.get("query_source")),
        delegation_depth=int(payload.get("delegation_depth") or 0),
        requested_model_route=_coerce_optional_string(payload.get("requested_model_route")),
        requested_model=_coerce_optional_string(payload.get("requested_model")),
        requested_effort=payload.get("requested_effort"),
        resolved_model_route=_coerce_optional_string(payload.get("resolved_model_route")),
        provider_name=_coerce_optional_string(payload.get("provider_name")),
        resolved_capabilities=(
            dict(payload.get("resolved_capabilities"))
            if isinstance(payload.get("resolved_capabilities"), Mapping)
            else None
        ),
        invocation_mode=_coerce_optional_string(payload.get("invocation_mode")),
        request_metadata=_coerce_mapping(payload.get("request_metadata")),
        terminal_metadata=_coerce_mapping(payload.get("terminal_metadata")),
        messages=tuple(messages),
    )


def _serialize_message(message: RuntimeMessage) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "role": message.role.value,
        "content": serialize_content_blocks(message.content),
        "created_at": message.created_at.isoformat(),
        "attachments": [asdict(attachment) for attachment in message.attachments],
        "metadata": dict(message.metadata),
    }


def _deserialize_message(payload: Mapping[str, Any]) -> RuntimeMessage | None:
    message_id = str(payload.get("message_id") or "").strip()
    role = str(payload.get("role") or "").strip()
    created_at = payload.get("created_at")
    if not message_id or not role or not isinstance(created_at, str):
        return None
    attachments = tuple(
        MessageAttachment(**attachment)
        for attachment in payload.get("attachments", ())
        if isinstance(attachment, Mapping)
    )
    return RuntimeMessage(
        message_id=message_id,
        role=MessageRole(role),
        content=deserialize_content_blocks(payload.get("content")),
        created_at=datetime.fromisoformat(created_at),
        attachments=attachments,
        metadata=_coerce_mapping(payload.get("metadata")),
    )


def _coerce_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _coerce_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = ["FileChildRunStore"]
