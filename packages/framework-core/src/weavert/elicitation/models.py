from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ElicitationRequest:
    session_id: str
    turn_id: str | None
    prompt: str
    kind: str = "text"
    options: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ElicitationResponse:
    response: Any
    source: str = "host"
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["ElicitationRequest", "ElicitationResponse"]
