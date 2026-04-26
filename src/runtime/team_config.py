from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TeammateOrchestrationConfig:
    enabled: bool = False
    mailbox_root: Path | None = None
    claim_lease_ms: int = 30_000
    heartbeat_interval_ms: int = 5_000
    retry_max_attempts: int = 3
    retry_backoff_ms: int = 0


__all__ = ["TeammateOrchestrationConfig"]
