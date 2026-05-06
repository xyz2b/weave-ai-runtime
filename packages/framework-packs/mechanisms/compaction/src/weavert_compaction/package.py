from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from weavert.package_system.protocols import (
    CapabilityBinding,
    PackageAssemblyStage,
    PackageContext,
    PackageContribution,
    RuntimeCapabilityKey,
)
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


def assemble_runtime_compaction_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = assemble_compaction_package()
    return PackageContribution(
        capabilities=(
            CapabilityBinding(
                key=RuntimeCapabilityKey.COMPACTION_MANAGER.value,
                value=components.manager,
                owner=context.ownership("capability", component="manager"),
            ),
        ),
    )


__all__ = [
    "CompactionPackageComponents",
    "assemble_compaction_package",
    "assemble_runtime_compaction_package",
]
