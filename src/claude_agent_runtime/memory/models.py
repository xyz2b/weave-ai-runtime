from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..definitions import MemoryScope


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryDocument:
    scope: MemoryScope
    path: Path
    title: str
    content: str
    kind: str = "document"
    metadata: dict[str, Any] = field(default_factory=dict)
    validation_errors: tuple[str, ...] = ()

    def render(self) -> str:
        header = f"[{self.scope.value}:{self.kind}] {self.title}".strip()
        body = self.content.strip()
        return header if not body else f"{header}\n{body}"


@dataclass(frozen=True, slots=True)
class ResolvedMemoryScope:
    session_id: str
    scope: MemoryScope
    boundary_root: Path
    memory_root: Path
    entrypoint_path: Path
    documents_dir: Path
    shared_documents_dir: Path
    preferences_documents_dir: Path
    conventions_documents_dir: Path
    topics_documents_dir: Path
    manifests_dir: Path
    long_term_manifest_path: Path
    agent_manifest_path: Path
    session_manifest_path: Path
    consolidation_manifest_path: Path
    agents_dir: Path
    sessions_dir: Path
    consolidations_dir: Path
    consolidation_checkpoints_dir: Path
    consolidation_logs_dir: Path
    consolidation_staging_dir: Path

    def agent_namespace_root(self, agent_name: str) -> Path:
        return self.agents_dir / normalize_memory_segment(agent_name, default="agent")

    def agent_namespace_documents_dir(self, agent_name: str) -> Path:
        return self.agent_namespace_root(agent_name) / "documents"

    def agent_namespace_manifest_path(self, agent_name: str) -> Path:
        return self.agent_namespace_root(agent_name) / "namespace-manifest.json"

    def session_root(self, session_id: str | None = None) -> Path:
        target = session_id or self.session_id
        return self.sessions_dir / normalize_memory_segment(target, default="session")

    def session_summary_path(self, session_id: str | None = None) -> Path:
        return self.session_root(session_id) / "session-summary.md"

    def session_open_threads_path(self, session_id: str | None = None) -> Path:
        return self.session_root(session_id) / "open-threads.md"

    def session_metadata_path(self, session_id: str | None = None) -> Path:
        return self.session_root(session_id) / "metadata.json"


_MEMORY_SEGMENT_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def normalize_memory_segment(value: str, *, default: str) -> str:
    normalized = _MEMORY_SEGMENT_PATTERN.sub("-", value.strip()).strip(".-").lower()
    return normalized or default
