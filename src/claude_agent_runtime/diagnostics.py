from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: DiagnosticSeverity
    code: str
    message: str
    definition_type: str | None = None
    source: str | None = None
    location: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

