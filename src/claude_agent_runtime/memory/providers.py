from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .models import MemoryDocument, MemoryEntry, ResolvedMemoryScope, normalize_memory_segment
from .schema import (
    AGENT_MANIFEST_KIND,
    AGENT_NAMESPACE_MANIFEST_KIND,
    CONSOLIDATION_MANIFEST_KIND,
    DEFAULT_NAMESPACE,
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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shared_documents: tuple[MemoryDocument, ...] | None = None
        namespace_documents: dict[str, tuple[MemoryDocument, ...]] = {}
        known_by_target: dict[tuple[str, str | None], dict[str, Path]] = {}
        touched_agent_namespaces: set[str] = set()

        persisted: list[MemoryDocument] = []
        for index, entry in enumerate(entries, start=1):
            normalized = _normalize_content(entry.content)
            if not normalized:
                continue

            metadata = build_memory_artifact_metadata(entry, context=context)
            metadata, target_key, target_dir = _persistence_target_for_metadata(context, metadata)
            known = known_by_target.get(target_key)
            if known is None:
                if target_key[0] == "shared":
                    if shared_documents is None:
                        shared_documents, _ = self._scan_long_term_documents(context)
                    known = _existing_fingerprints(shared_documents)
                else:
                    agent_name = str(target_key[1])
                    if agent_name not in namespace_documents:
                        namespace_documents[agent_name], _ = self._scan_agent_namespace_documents(context, agent_name)
                    known = _existing_fingerprints(namespace_documents[agent_name])
                known_by_target[target_key] = known

            fingerprint = content_fingerprint(normalized)
            if fingerprint in known:
                continue

            slug = _slugify(entry.title) or f"memory-{index}"
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
            if target_key[0] == "agent":
                touched_agent_namespaces.add(str(target_key[1]))

        for agent_name in sorted(touched_agent_namespaces):
            self._refresh_agent_namespace_manifest(context, agent_name)
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

    def _refresh_agent_namespace_manifest(
        self,
        context: ResolvedMemoryScope,
        agent_name: str,
    ) -> None:
        normalized_agent = normalize_memory_segment(agent_name, default="agent")
        documents, invalid_count = self._scan_agent_namespace_documents(context, normalized_agent)
        manifest = build_manifest_envelope(
            manifest_kind=AGENT_NAMESPACE_MANIFEST_KIND,
            boundary_scope=context.scope,
            payload_key="entries",
            payload=[self._agent_namespace_manifest_entry(context, normalized_agent, document) for document in documents],
            stats={
                "invalid_entry_count": invalid_count,
                "stale_entry_count": sum(_is_stale(document.metadata.get("stale_after")) for document in documents),
            },
        )
        manifest["agent_name"] = normalized_agent
        manifest["namespace"] = f"agent:{normalized_agent}"
        manifest_path = context.agent_namespace_manifest_path(normalized_agent)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

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
        aligned_metadata, alignment_errors = _align_artifact_metadata_to_path(
            context=context,
            path=path,
            metadata=parsed.metadata,
        )
        if not parsed.valid or alignment_errors:
            return None
        return MemoryDocument(
            scope=context.scope,
            path=path,
            title=parsed.title,
            content=parsed.content,
            kind=str(aligned_metadata.get("memory_kind") or "document"),
            metadata=aligned_metadata,
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
            "embedding_ref": metadata.get("embedding_ref"),
            "contested": bool(metadata.get("contested", False)),
        }
        if "stale_after" in metadata:
            entry["stale_after"] = metadata["stale_after"]
        if "confidence" in metadata:
            entry["confidence"] = metadata["confidence"]
        return entry

    def _agent_namespace_manifest_entry(
        self,
        context: ResolvedMemoryScope,
        agent_name: str,
        document: MemoryDocument,
    ) -> dict[str, Any]:
        entry = self._long_term_manifest_entry(context, document)
        entry["namespace"] = f"agent:{agent_name}"
        entry["agent_namespace"] = agent_name
        return entry

    def _agent_namespaces(self, context: ResolvedMemoryScope) -> list[dict[str, Any]]:
        if not context.agents_dir.exists():
            return []
        namespaces: list[dict[str, Any]] = []
        for path in sorted(context.agents_dir.iterdir()):
            if not path.is_dir():
                continue
            agent_name = path.name
            namespace_documents, _ = self._scan_agent_namespace_documents(context, agent_name)
            manifest_path = context.agent_namespace_manifest_path(agent_name)
            manifest_payload = _read_json_document(manifest_path) or {}
            raw_entries = manifest_payload.get("entries", ()) if isinstance(manifest_payload, dict) else ()
            conflict_keys = [
                entry.get("conflict_key").strip()
                for entry in raw_entries
                if isinstance(entry, dict)
                and isinstance(entry.get("conflict_key"), str)
                and entry.get("conflict_key", "").strip()
            ]
            if not conflict_keys:
                conflict_keys = [
                    document.metadata["conflict_key"]
                    for document in namespace_documents
                    if isinstance(document.metadata.get("conflict_key"), str)
                    and document.metadata["conflict_key"].strip()
                ]
            latest_update = _latest_path_timestamp(
                [document.path for document in namespace_documents] + [manifest_path]
            )
            namespaces.append(
                {
                    "agent_name": agent_name,
                    "path": path.relative_to(context.memory_root).as_posix() + "/",
                    "entry_count": len(namespace_documents),
                    "last_updated_at": latest_update or utc_now_iso(),
                    "conflict_keys": conflict_keys,
                }
            )
        return namespaces

    def _scan_agent_namespace_documents(
        self,
        context: ResolvedMemoryScope,
        agent_name: str,
    ) -> tuple[tuple[MemoryDocument, ...], int]:
        namespace_dir = context.agent_namespace_documents_dir(agent_name)
        if not namespace_dir.exists():
            return (), 0

        documents: list[MemoryDocument] = []
        invalid_count = 0
        for path in sorted(namespace_dir.rglob("*.md")):
            if not path.is_file():
                continue
            document = self._read_memory_document(context, path)
            if document is None:
                invalid_count += 1
                continue
            documents.append(document)
        return tuple(documents), invalid_count


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
    namespace = str(metadata.get("namespace") or DEFAULT_NAMESPACE).strip()
    if namespace.startswith("agent:"):
        normalized_agent = normalize_memory_segment(
            str(metadata.get("agent_namespace") or namespace.partition(":")[2]),
            default="agent",
        )
        documents_dir = context.agent_namespace_documents_dir(normalized_agent)
        memory_kind = str(metadata.get("memory_kind") or "").strip()
        if memory_kind in {"agent_workflow", "heuristic"}:
            return documents_dir / "heuristics"
        if memory_kind in {"workflow", "agent_workflow_step"}:
            return documents_dir / "workflows"
        return documents_dir / "durable-notes"

    memory_kind = str(metadata.get("memory_kind") or "").strip()
    if memory_kind == "preference":
        return context.preferences_documents_dir
    if memory_kind in {"project_convention", "convention", "workflow_command"}:
        return context.conventions_documents_dir
    if memory_kind in {"topic", "topic_memory"}:
        return context.topics_documents_dir
    return context.shared_documents_dir


def _persistence_target_for_metadata(
    context: ResolvedMemoryScope,
    metadata: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, str | None], Path]:
    normalized = dict(metadata)
    namespace = str(normalized.get("namespace") or DEFAULT_NAMESPACE).strip() or DEFAULT_NAMESPACE
    if namespace == DEFAULT_NAMESPACE:
        if normalized.get("agent_namespace") not in {None, ""}:
            raise ValueError("Shared durable memory entries cannot declare an agent namespace")
        normalized["namespace"] = DEFAULT_NAMESPACE
        normalized["agent_namespace"] = None
        return normalized, ("shared", None), _directory_for_metadata(context, normalized)

    if namespace.startswith("agent:"):
        requested_agent = namespace.partition(":")[2].strip()
        declared_agent = normalized.get("agent_namespace")
        if (
            isinstance(declared_agent, str)
            and declared_agent.strip()
            and requested_agent
            and declared_agent.strip() != requested_agent
        ):
            raise ValueError("Agent durable memory namespace metadata does not match the target namespace")
        agent_name = normalize_memory_segment(str(declared_agent or requested_agent), default="agent")
        normalized["namespace"] = f"agent:{agent_name}"
        normalized["agent_namespace"] = agent_name
        return normalized, ("agent", agent_name), _directory_for_metadata(context, normalized)

    raise ValueError(f"Unsupported durable memory namespace: {namespace}")


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


def _align_artifact_metadata_to_path(
    *,
    context: ResolvedMemoryScope,
    path: Path,
    metadata: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    normalized = dict(metadata)
    errors: list[str] = []
    expected_scope = context.scope.value
    if normalized.get("scope") != expected_scope:
        errors.append("Artifact scope does not match its boundary path")

    try:
        path.relative_to(context.documents_dir)
    except ValueError:
        pass
    else:
        if normalized.get("namespace") != DEFAULT_NAMESPACE:
            errors.append("Long-term documents must use the shared namespace")
        if normalized.get("agent_namespace") is not None:
            errors.append("Long-term documents cannot declare an agent namespace")
        return normalized, tuple(errors)

    try:
        relative = path.relative_to(context.agents_dir)
    except ValueError:
        return normalized, tuple(errors)

    if len(relative.parts) < 2:
        errors.append("Agent namespace document path is incomplete")
        return normalized, tuple(errors)

    agent_namespace = relative.parts[0]
    expected_namespace = f"agent:{agent_namespace}"
    namespace = normalized.get("namespace")
    if namespace in {None, "", DEFAULT_NAMESPACE, expected_namespace}:
        normalized["namespace"] = expected_namespace
    else:
        errors.append("Artifact namespace does not match its agent namespace path")

    declared_agent_namespace = normalized.get("agent_namespace")
    if declared_agent_namespace in {None, "", agent_namespace}:
        normalized["agent_namespace"] = agent_namespace
    else:
        errors.append("Artifact agent namespace does not match its path")
    return normalized, tuple(errors)
