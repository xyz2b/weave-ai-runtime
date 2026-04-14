from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

