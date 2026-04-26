from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .manager import CompactionManager, OrderedCompactionStrategy
from .models import CompactionPolicy


@dataclass(frozen=True, slots=True)
class CompactionPackageComponents:
    manager: CompactionManager


def assemble_compaction_package(
    *,
    strategies: Sequence[OrderedCompactionStrategy] | None = None,
    default_policy: CompactionPolicy | None = None,
    manager: CompactionManager | None = None,
) -> CompactionPackageComponents:
    resolved_manager = manager or CompactionManager(
        strategies=strategies,
        default_policy=default_policy,
    )
    return CompactionPackageComponents(manager=resolved_manager)


__all__ = [
    "CompactionPackageComponents",
    "assemble_compaction_package",
]
