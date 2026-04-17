from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .models import MemoryDocument, MemoryEntry, ResolvedMemoryScope
from .schema import (
    AGENT_MANIFEST_KIND,
    CONSOLIDATION_MANIFEST_KIND,
    LONG_TERM_MANIFEST_KIND,
    SESSION_MANIFEST_KIND,
    build_manifest_envelope,
    build_memory_artifact_metadata,
    content_fingerprint,
    estimate_token_count,
    file_timestamp_iso,
    parse_memory_artifact,
    serialize_memory_artifact,
    summarize_content,
    utc_now_iso,
)


class MemoryProvider(Protocol):
    def prepare_context(self, context: ResolvedMemoryScope) -> None: ...

    def load_entrypoint(self, context: ResolvedMemoryScope) -> MemoryDocument | None: ...

    def load_long_term_manifest(self, context: ResolvedMemoryScope) -> Mapping[str, Any] | None: ...

    def list_documents(self, context: ResolvedMemoryScope) -> tuple[MemoryDocument, ...]: ...

    def materialize_documents(
        self,
        context: ResolvedMemoryScope,
        relative_paths: Sequence[str],
    ) -> tuple[MemoryDocument, ...]: ...

    def persist_entries(
        self,
        context: ResolvedMemoryScope,
        entries: Sequence[MemoryEntry],
    ) -> tuple[MemoryDocument, ...]: ...


class FileMemoryProvider:
    def prepare_context(self, context: ResolvedMemoryScope) -> None:
        self._ensure_layout(context)
        self._refresh_manifests(context)

    def load_entrypoint(self, context: ResolvedMemoryScope) -> MemoryDocument | None:
        if not context.entrypoint_path.exists() or not context.entrypoint_path.is_file():
            return None
        content = context.entrypoint_path.read_text(encoding="utf-8")
        return MemoryDocument(
            scope=context.scope,
            path=context.entrypoint_path,
            title="MEMORY.md",
            content=content,
            kind="entrypoint",
        )

    def load_long_term_manifest(self, context: ResolvedMemoryScope) -> Mapping[str, Any] | None:
        self._refresh_manifests(context)
        return _read_json_document(context.long_term_manifest_path)

    def list_documents(self, context: ResolvedMemoryScope) -> tuple[MemoryDocument, ...]:
        documents, _ = self._refresh_manifests(context)
        return documents

    def materialize_documents(
        self,
        context: ResolvedMemoryScope,
        relative_paths: Sequence[str],
    ) -> tuple[MemoryDocument, ...]:
        documents: list[MemoryDocument] = []
        for relative_path in relative_paths:
            path = context.memory_root / relative_path
            document = self._read_memory_document(context, path)
            if document is None:
                continue
            documents.append(document)
        return tuple(documents)

    def persist_entries(
        self,
        context: ResolvedMemoryScope,
        entries: Sequence[MemoryEntry],
    ) -> tuple[MemoryDocument, ...]:
        if not entries:
            return ()

        self._ensure_layout(context)
        existing_documents, _ = self._scan_long_term_documents(context)
        known = _existing_fingerprints(existing_documents)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        persisted: list[MemoryDocument] = []
        for index, entry in enumerate(entries, start=1):
            normalized = _normalize_content(entry.content)
            if not normalized:
                continue
            fingerprint = content_fingerprint(normalized)
            if fingerprint in known:
                continue

            metadata = build_memory_artifact_metadata(entry, context=context)
            slug = _slugify(entry.title) or f"memory-{index}"
            target_dir = _directory_for_metadata(context, metadata)
            target_dir.mkdir(parents=True, exist_ok=True)
            path = target_dir / f"{timestamp}-{slug}-{fingerprint}.md"
            title = entry.title.strip() or "Memory note"
            path.write_text(
                serialize_memory_artifact(title, normalized, metadata),
                encoding="utf-8",
            )
            known[fingerprint] = path
            persisted.append(
                MemoryDocument(
                    scope=context.scope,
                    path=path,
                    title=title,
                    content=normalized,
                    kind=str(metadata.get("memory_kind") or "document"),
                    metadata=metadata,
                )
            )
        self._refresh_manifests(context)
        return tuple(persisted)

    def _ensure_layout(self, context: ResolvedMemoryScope) -> None:
        directories = (
            context.memory_root,
            context.manifests_dir,
            context.documents_dir,
            context.shared_documents_dir,
            context.preferences_documents_dir,
            context.conventions_documents_dir,
            context.topics_documents_dir,
            context.agents_dir,
            context.sessions_dir,
            context.consolidations_dir,
            context.consolidation_checkpoints_dir,
            context.consolidation_logs_dir,
            context.consolidation_staging_dir,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

        self._ensure_manifest_file(
            context.long_term_manifest_path,
            build_manifest_envelope(
                manifest_kind=LONG_TERM_MANIFEST_KIND,
                boundary_scope=context.scope,
                payload_key="entries",
                payload=(),
            ),
        )
        self._ensure_manifest_file(
            context.agent_manifest_path,
            build_manifest_envelope(
                manifest_kind=AGENT_MANIFEST_KIND,
                boundary_scope=context.scope,
                payload_key="namespaces",
                payload=(),
            ),
        )
        self._ensure_manifest_file(
            context.session_manifest_path,
            build_manifest_envelope(
                manifest_kind=SESSION_MANIFEST_KIND,
                boundary_scope=context.scope,
                payload_key="sessions",
                payload=(),
            ),
        )
        self._ensure_manifest_file(
            context.consolidation_manifest_path,
            build_manifest_envelope(
                manifest_kind=CONSOLIDATION_MANIFEST_KIND,
                boundary_scope=context.scope,
                payload_key="runs",
                payload=(),
            ),
        )

    def _ensure_manifest_file(self, path: Path, payload: Mapping[str, Any]) -> None:
        if path.exists():
            return
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _refresh_manifests(self, context: ResolvedMemoryScope) -> tuple[tuple[MemoryDocument, ...], int]:
        self._ensure_layout(context)
        documents, invalid_count = self._scan_long_term_documents(context)
        long_term_manifest = build_manifest_envelope(
            manifest_kind=LONG_TERM_MANIFEST_KIND,
            boundary_scope=context.scope,
            payload_key="entries",
            payload=[self._long_term_manifest_entry(context, document) for document in documents],
            stats={
                "invalid_entry_count": invalid_count,
                "stale_entry_count": sum(_is_stale(document.metadata.get("stale_after")) for document in documents),
            },
        )
        context.long_term_manifest_path.write_text(
            json.dumps(long_term_manifest, indent=2) + "\n",
            encoding="utf-8",
        )

        agent_manifest = build_manifest_envelope(
            manifest_kind=AGENT_MANIFEST_KIND,
            boundary_scope=context.scope,
            payload_key="namespaces",
            payload=self._agent_namespaces(context),
        )
        context.agent_manifest_path.write_text(json.dumps(agent_manifest, indent=2) + "\n", encoding="utf-8")
        return documents, invalid_count

    def _scan_long_term_documents(self, context: ResolvedMemoryScope) -> tuple[tuple[MemoryDocument, ...], int]:
        if not context.documents_dir.exists():
            return (), 0

        documents: list[MemoryDocument] = []
        invalid_count = 0
        for path in sorted(context.documents_dir.rglob("*.md")):
            if not path.is_file():
                continue
            document = self._read_memory_document(context, path)
            if document is None:
                invalid_count += 1
                continue
            documents.append(document)
        return tuple(documents), invalid_count

    def _read_memory_document(
        self,
        context: ResolvedMemoryScope,
        path: Path,
    ) -> MemoryDocument | None:
        if not path.exists() or not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8")
        fallback_created_at = file_timestamp_iso(path)
        parsed = parse_memory_artifact(
            raw,
            default_title=path.stem.replace("-", " ").strip() or "Memory note",
            context=context,
            fallback_created_at=fallback_created_at,
        )
        if not parsed.valid:
            return None
        return MemoryDocument(
            scope=context.scope,
            path=path,
            title=parsed.title,
            content=parsed.content,
            kind=str(parsed.metadata.get("memory_kind") or "document"),
            metadata=parsed.metadata,
        )

    def _long_term_manifest_entry(
        self,
        context: ResolvedMemoryScope,
        document: MemoryDocument,
    ) -> dict[str, Any]:
        metadata = dict(document.metadata)
        relative_path = document.path.relative_to(context.memory_root).as_posix()
        summary = str(metadata.get("summary") or summarize_content(document.content))
        token_estimate = int(metadata.get("token_estimate") or estimate_token_count(document.content))
        doc_id_seed = f"{relative_path}:{document.title}:{document.content}"
        entry = {
            "doc_id": metadata.get("doc_id") or content_fingerprint(doc_id_seed),
            "path": relative_path,
            "title": document.title,
            "memory_kind": metadata.get("memory_kind", "note"),
            "namespace": metadata.get("namespace", "shared"),
            "scope": metadata.get("scope", context.scope.value),
            "agent_namespace": metadata.get("agent_namespace"),
            "tags": list(metadata.get("tags", ())),
            "summary": summary,
            "token_estimate": token_estimate,
            "source_pathway": metadata.get("source_pathway", "legacy"),
            "source_message_ids": list(metadata.get("source_message_ids", ())),
            "created_at": metadata.get("created_at", file_timestamp_iso(document.path)),
            "last_confirmed_at": metadata.get("last_confirmed_at", file_timestamp_iso(document.path)),
            "retention": metadata.get("retention", "durable_until_superseded"),
            "conflict_key": metadata.get("conflict_key"),
            "contested": bool(metadata.get("contested", False)),
        }
        if "stale_after" in metadata:
            entry["stale_after"] = metadata["stale_after"]
        if "confidence" in metadata:
            entry["confidence"] = metadata["confidence"]
        return entry

    def _agent_namespaces(self, context: ResolvedMemoryScope) -> list[dict[str, Any]]:
        if not context.agents_dir.exists():
            return []
        namespaces: list[dict[str, Any]] = []
        for path in sorted(context.agents_dir.iterdir()):
            if not path.is_dir():
                continue
            namespace_documents = [
                document_path
                for document_path in sorted((path / "documents").rglob("*.md"))
                if document_path.is_file()
            ] if (path / "documents").exists() else []
            manifest_payload = _read_json_document(path / "namespace-manifest.json") or {}
            raw_entries = manifest_payload.get("entries", ()) if isinstance(manifest_payload, dict) else ()
            conflict_keys = [
                str(entry.get("conflict_key")).strip()
                for entry in raw_entries
                if isinstance(entry, dict) and str(entry.get("conflict_key", "")).strip()
            ]
            latest_update = _latest_path_timestamp(namespace_documents + [path / "namespace-manifest.json"])
            namespaces.append(
                {
                    "agent_name": path.name,
                    "path": path.relative_to(context.memory_root).as_posix() + "/",
                    "entry_count": len(namespace_documents),
                    "last_updated_at": latest_update or utc_now_iso(),
                    "conflict_keys": conflict_keys,
                }
            )
        return namespaces


def _existing_fingerprints(documents: Sequence[MemoryDocument]) -> dict[str, Path]:
    fingerprints: dict[str, Path] = {}
    for document in documents:
        normalized = _normalize_content(document.content)
        if not normalized:
            continue
        fingerprint = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        fingerprints[fingerprint] = document.path
    return fingerprints


def _normalize_content(content: str) -> str:
    return " ".join(content.strip().split())


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48]


def _directory_for_metadata(context: ResolvedMemoryScope, metadata: Mapping[str, Any]) -> Path:
    memory_kind = str(metadata.get("memory_kind") or "").strip()
    if memory_kind == "preference":
        return context.preferences_documents_dir
    if memory_kind in {"project_convention", "convention"}:
        return context.conventions_documents_dir
    if memory_kind == "topic":
        return context.topics_documents_dir
    return context.shared_documents_dir


def _read_json_document(path: Path) -> Mapping[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _latest_path_timestamp(paths: Sequence[Path]) -> str | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    latest = max(existing, key=lambda candidate: candidate.stat().st_mtime)
    return file_timestamp_iso(latest)


def _is_stale(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        stale_after = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return stale_after <= datetime.now(timezone.utc)
