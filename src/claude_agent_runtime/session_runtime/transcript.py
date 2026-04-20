from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from ..contracts import (
    MessageAttachment,
    MessageRole,
    RuntimeMessage,
    ToolResultBlock,
    deserialize_content_blocks,
    serialize_content_blocks,
    utc_now,
)
from ..turn_engine.models import (
    ArtifactManifestEntry,
    TranscriptArtifact,
    TranscriptEntry,
    TranscriptSession,
    TranscriptStore,
)


class InMemoryTranscriptStore(TranscriptStore):
    def __init__(self) -> None:
        self._sessions: dict[str, list[TranscriptEntry]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._artifact_manifests: dict[str, dict[str, ArtifactManifestEntry]] = {}

    async def append(self, entry: TranscriptEntry) -> None:
        self._sessions.setdefault(entry.session_id, []).append(entry)

    async def load(self, session_id: str) -> TranscriptSession:
        return TranscriptSession(session_id=session_id, entries=tuple(self._sessions.get(session_id, [])))

    async def replace(self, session: TranscriptSession) -> None:
        self._sessions[session.session_id] = list(session.entries)

    async def load_session_metadata(self, session_id: str) -> Mapping[str, Any] | None:
        metadata = self._metadata.get(session_id)
        return dict(metadata) if metadata is not None else None

    async def save_session_metadata(
        self,
        session_id: str,
        metadata: Mapping[str, Any],
    ) -> None:
        self._metadata[session_id] = {str(key): value for key, value in metadata.items()}

    async def persist_artifact(
        self,
        session_id: str,
        *,
        turn_id: str | None,
        kind: str,
        payload: Any,
        metadata: Mapping[str, Any] | None = None,
        retention_class: str = "session_lifetime",
    ) -> ArtifactManifestEntry:
        payload_copy = _json_safe_copy(payload)
        digest = _artifact_digest(payload_copy)
        manifest = self._artifact_manifests.setdefault(session_id, {})
        artifact_ref = _artifact_ref(kind, digest)
        while artifact_ref in manifest:
            artifact_ref = _artifact_ref(kind, digest, suffix=uuid4().hex[:8])
        entry = ArtifactManifestEntry(
            artifact_ref=artifact_ref,
            producing_turn=turn_id,
            kind=kind,
            digest=digest,
            created_at=utc_now(),
            retention_class=retention_class,
            metadata={str(key): value for key, value in (metadata or {}).items()},
        )
        manifest[artifact_ref] = entry
        self._artifacts.setdefault(session_id, {})[artifact_ref] = payload_copy
        return entry

    async def load_artifact(
        self,
        session_id: str,
        artifact_ref: str,
    ) -> TranscriptArtifact | None:
        entry = self._artifact_manifests.get(session_id, {}).get(artifact_ref)
        if entry is None:
            return None
        payload = self._artifacts.get(session_id, {}).get(artifact_ref)
        if payload is None:
            return None
        return TranscriptArtifact(entry=entry, payload=_json_safe_copy(payload))

    async def list_artifacts(self, session_id: str) -> tuple[ArtifactManifestEntry, ...]:
        manifest = self._artifact_manifests.get(session_id, {})
        return tuple(manifest[key] for key in sorted(manifest))

    async def purge_unreferenced_artifacts(self, session_id: str) -> tuple[str, ...]:
        referenced = _referenced_artifact_refs(
            tuple(self._sessions.get(session_id, ())),
            self._metadata.get(session_id),
        )
        manifest = self._artifact_manifests.get(session_id, {})
        removed: list[str] = []
        for artifact_ref in list(manifest):
            if artifact_ref in referenced:
                continue
            removed.append(artifact_ref)
            manifest.pop(artifact_ref, None)
            self._artifacts.get(session_id, {}).pop(artifact_ref, None)
        return tuple(sorted(removed))


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

    async def load_session_metadata(self, session_id: str) -> Mapping[str, Any] | None:
        path = self._metadata_path(session_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, Mapping):
            return None
        return {str(key): value for key, value in payload.items()}

    async def save_session_metadata(
        self,
        session_id: str,
        metadata: Mapping[str, Any],
    ) -> None:
        self._metadata_path(session_id).write_text(
            json.dumps({str(key): value for key, value in metadata.items()}, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    async def persist_artifact(
        self,
        session_id: str,
        *,
        turn_id: str | None,
        kind: str,
        payload: Any,
        metadata: Mapping[str, Any] | None = None,
        retention_class: str = "session_lifetime",
    ) -> ArtifactManifestEntry:
        payload_copy = _json_safe_copy(payload)
        digest = _artifact_digest(payload_copy)
        artifact_ref = _artifact_ref(kind, digest)
        manifest = self._read_artifact_manifest(session_id)
        while artifact_ref in manifest:
            artifact_ref = _artifact_ref(kind, digest, suffix=uuid4().hex[:8])
        entry = ArtifactManifestEntry(
            artifact_ref=artifact_ref,
            producing_turn=turn_id,
            kind=kind,
            digest=digest,
            created_at=utc_now(),
            retention_class=retention_class,
            metadata={str(key): value for key, value in (metadata or {}).items()},
        )
        self._artifact_dir(session_id).mkdir(parents=True, exist_ok=True)
        self._artifact_payload_path(session_id, artifact_ref).write_text(
            json.dumps(payload_copy, indent=2, ensure_ascii=True, default=str) + "\n",
            encoding="utf-8",
        )
        manifest[artifact_ref] = entry
        self._write_artifact_manifest(session_id, manifest)
        return entry

    async def load_artifact(
        self,
        session_id: str,
        artifact_ref: str,
    ) -> TranscriptArtifact | None:
        entry = self._read_artifact_manifest(session_id).get(artifact_ref)
        if entry is None:
            return None
        path = self._artifact_payload_path(session_id, artifact_ref)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return TranscriptArtifact(entry=entry, payload=payload)

    async def list_artifacts(self, session_id: str) -> tuple[ArtifactManifestEntry, ...]:
        manifest = self._read_artifact_manifest(session_id)
        return tuple(manifest[key] for key in sorted(manifest))

    async def purge_unreferenced_artifacts(self, session_id: str) -> tuple[str, ...]:
        transcript = await self.load(session_id)
        metadata = await self.load_session_metadata(session_id)
        referenced = _referenced_artifact_refs(transcript.entries, metadata)
        manifest = self._read_artifact_manifest(session_id)
        removed: list[str] = []
        for artifact_ref in list(manifest):
            if artifact_ref in referenced:
                continue
            removed.append(artifact_ref)
            manifest.pop(artifact_ref, None)
            try:
                self._artifact_payload_path(session_id, artifact_ref).unlink()
            except FileNotFoundError:
                pass
        self._write_artifact_manifest(session_id, manifest)
        return tuple(sorted(removed))

    def _path(self, session_id: str) -> Path:
        return self._root / f"{session_id}.jsonl"

    def _metadata_path(self, session_id: str) -> Path:
        return self._root / f"{session_id}.meta.json"

    def _artifact_dir(self, session_id: str) -> Path:
        return self._root / f"{session_id}.artifacts"

    def _artifact_manifest_path(self, session_id: str) -> Path:
        return self._artifact_dir(session_id) / "manifest.json"

    def _artifact_payload_path(self, session_id: str, artifact_ref: str) -> Path:
        return self._artifact_dir(session_id) / f"{artifact_ref}.json"

    def _read_artifact_manifest(self, session_id: str) -> dict[str, ArtifactManifestEntry]:
        path = self._artifact_manifest_path(session_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, list):
            return {}
        manifest: dict[str, ArtifactManifestEntry] = {}
        for item in payload:
            entry = _deserialize_artifact_manifest_entry(item)
            if entry is not None:
                manifest[entry.artifact_ref] = entry
        return manifest

    def _write_artifact_manifest(
        self,
        session_id: str,
        manifest: Mapping[str, ArtifactManifestEntry],
    ) -> None:
        artifact_dir = self._artifact_dir(session_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        serialized = [
            _serialize_artifact_manifest_entry(entry)
            for entry in sorted(manifest.values(), key=lambda item: item.artifact_ref)
        ]
        self._artifact_manifest_path(session_id).write_text(
            json.dumps(serialized, indent=2, ensure_ascii=True, default=str) + "\n",
            encoding="utf-8",
        )


def _serialize_entry(entry: TranscriptEntry) -> dict[str, object]:
    return {
        "session_id": entry.session_id,
        "turn_id": entry.turn_id,
        "created_at": entry.created_at.isoformat(),
        "message": {
            "message_id": entry.message.message_id,
            "role": entry.message.role.value,
            "content": serialize_content_blocks(entry.message.content),
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
        content=deserialize_content_blocks(message_payload["content"]),
        created_at=datetime.fromisoformat(message_payload["created_at"]),
        attachments=attachments,
        metadata=message_payload.get("metadata", {}),
    )
    return TranscriptEntry(
        session_id=payload["session_id"],
        turn_id=payload.get("turn_id"),
        message=message,
        created_at=datetime.fromisoformat(payload["created_at"]),
    )


def _serialize_artifact_manifest_entry(entry: ArtifactManifestEntry) -> dict[str, object]:
    return {
        "artifact_ref": entry.artifact_ref,
        "producing_turn": entry.producing_turn,
        "kind": entry.kind,
        "digest": entry.digest,
        "created_at": entry.created_at.isoformat(),
        "retention_class": entry.retention_class,
        "metadata": dict(entry.metadata),
    }


def _deserialize_artifact_manifest_entry(payload: object) -> ArtifactManifestEntry | None:
    if not isinstance(payload, Mapping):
        return None
    artifact_ref = payload.get("artifact_ref")
    kind = payload.get("kind")
    digest = payload.get("digest")
    created_at = payload.get("created_at")
    if artifact_ref is None or kind is None or digest is None or created_at is None:
        return None
    try:
        parsed_created_at = datetime.fromisoformat(str(created_at))
    except ValueError:
        return None
    metadata = payload.get("metadata")
    return ArtifactManifestEntry(
        artifact_ref=str(artifact_ref),
        producing_turn=str(payload["producing_turn"]) if payload.get("producing_turn") is not None else None,
        kind=str(kind),
        digest=str(digest),
        created_at=parsed_created_at,
        retention_class=str(payload.get("retention_class") or "session_lifetime"),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _artifact_digest(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _artifact_ref(kind: str, digest: str, *, suffix: str | None = None) -> str:
    base = f"{kind}-{digest[:12]}"
    if suffix is not None:
        return f"{base}-{suffix}"
    return base


def _json_safe_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=True, default=str))


def _referenced_artifact_refs(
    entries: tuple[TranscriptEntry, ...] | list[TranscriptEntry],
    metadata: Mapping[str, Any] | None,
) -> set[str]:
    references: set[str] = set()
    for entry in entries:
        references.update(_collect_artifact_refs(entry.message.metadata))
        for block in entry.message.content:
            if isinstance(block, ToolResultBlock):
                references.update(_collect_artifact_refs(block.content))
    references.update(_collect_artifact_refs(metadata))
    return references


def _collect_artifact_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        artifact_ref = value.get("artifact_ref")
        if artifact_ref is not None:
            refs.add(str(artifact_ref))
        for item in value.values():
            refs.update(_collect_artifact_refs(item))
        return refs
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            refs.update(_collect_artifact_refs(item))
    return refs
