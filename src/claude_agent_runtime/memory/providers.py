from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Sequence

from .models import MemoryDocument, MemoryEntry, ResolvedMemoryScope


class MemoryProvider(Protocol):
    def load_entrypoint(self, context: ResolvedMemoryScope) -> MemoryDocument | None: ...

    def list_documents(self, context: ResolvedMemoryScope) -> tuple[MemoryDocument, ...]: ...

    def persist_entries(
        self,
        context: ResolvedMemoryScope,
        entries: Sequence[MemoryEntry],
    ) -> tuple[MemoryDocument, ...]: ...


class FileMemoryProvider:
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

    def list_documents(self, context: ResolvedMemoryScope) -> tuple[MemoryDocument, ...]:
        if not context.documents_dir.exists():
            return ()

        documents: list[MemoryDocument] = []
        for path in sorted(context.documents_dir.rglob("*.md")):
            if not path.is_file():
                continue
            title, body = _read_markdown_document(path)
            documents.append(
                MemoryDocument(
                    scope=context.scope,
                    path=path,
                    title=title,
                    content=body,
                )
            )
        return tuple(documents)

    def persist_entries(
        self,
        context: ResolvedMemoryScope,
        entries: Sequence[MemoryEntry],
    ) -> tuple[MemoryDocument, ...]:
        if not entries:
            return ()

        context.documents_dir.mkdir(parents=True, exist_ok=True)
        known = _existing_fingerprints(context.documents_dir)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        persisted: list[MemoryDocument] = []
        for index, entry in enumerate(entries, start=1):
            normalized = _normalize_content(entry.content)
            if not normalized:
                continue
            fingerprint = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
            if fingerprint in known:
                continue

            slug = _slugify(entry.title) or f"memory-{index}"
            path = context.documents_dir / f"{timestamp}-{slug}-{fingerprint}.md"
            path.write_text(
                f"# {entry.title.strip() or 'Memory note'}\n\n{normalized}\n",
                encoding="utf-8",
            )
            known[fingerprint] = path
            persisted.append(
                MemoryDocument(
                    scope=context.scope,
                    path=path,
                    title=entry.title.strip() or "Memory note",
                    content=normalized,
                    kind="extracted",
                    metadata=dict(entry.metadata),
                )
            )
        return tuple(persisted)


def _existing_fingerprints(documents_dir: Path) -> dict[str, Path]:
    fingerprints: dict[str, Path] = {}
    for path in documents_dir.rglob("*.md"):
        if not path.is_file():
            continue
        _, body = _read_markdown_document(path)
        normalized = _normalize_content(body)
        if not normalized:
            continue
        fingerprint = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        fingerprints[fingerprint] = path
    return fingerprints


def _read_markdown_document(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    title = path.stem.replace("-", " ").strip() or "Memory note"
    body_lines = lines
    while body_lines and not body_lines[0].strip():
        body_lines = body_lines[1:]
    if body_lines and body_lines[0].startswith("# "):
        title = body_lines[0][2:].strip() or title
        body_lines = body_lines[1:]
        while body_lines and not body_lines[0].strip():
            body_lines = body_lines[1:]
    body = "\n".join(body_lines).strip()
    return title, body


def _normalize_content(content: str) -> str:
    return " ".join(content.strip().split())


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48]
