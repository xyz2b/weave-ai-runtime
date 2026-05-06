from __future__ import annotations

from dataclasses import dataclass

from weavert.definitions import IsolationMode
from weavert.runtime_package_protocols import (
    CapabilityBinding,
    PackageAssemblyStage,
    PackageContext,
    PackageContribution,
    RuntimeCapabilityKey,
)
from .isolation import (
    BaseIsolationAdapter,
    IsolationAdapter,
    IsolationManager,
    RemoteIsolationAdapter,
    WorktreeIsolationAdapter,
)


@dataclass(frozen=True, slots=True)
class IsolationPackageComponents:
    manager: IsolationManager


def assemble_core_isolation_manager() -> IsolationManager:
    return IsolationManager(adapters={IsolationMode.NONE: BaseIsolationAdapter()})


def assemble_isolation_package(
    *,
    adapters: dict[IsolationMode, IsolationAdapter] | None = None,
    manager: IsolationManager | None = None,
) -> IsolationPackageComponents:
    resolved_adapters = {
        IsolationMode.NONE: BaseIsolationAdapter(),
        IsolationMode.WORKTREE: WorktreeIsolationAdapter(),
        IsolationMode.REMOTE: RemoteIsolationAdapter(),
    }
    if adapters:
        resolved_adapters.update(adapters)
    resolved_manager = manager or IsolationManager(adapters=resolved_adapters)
    return IsolationPackageComponents(manager=resolved_manager)


def assemble_runtime_isolation_package(context: PackageContext) -> PackageContribution:
    if context.stage != PackageAssemblyStage.SERVICES:
        return PackageContribution()
    components = assemble_isolation_package()
    return PackageContribution(
        capabilities=(
            CapabilityBinding(
                key=RuntimeCapabilityKey.ISOLATION_MANAGER.value,
                value=components.manager,
                owner=context.ownership("capability", component="manager"),
            ),
        ),
    )


__all__ = [
    "IsolationPackageComponents",
    "assemble_core_isolation_manager",
    "assemble_isolation_package",
    "assemble_runtime_isolation_package",
]
