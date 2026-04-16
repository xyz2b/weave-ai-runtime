from __future__ import annotations

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
