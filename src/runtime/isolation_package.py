from __future__ import annotations

from dataclasses import dataclass

from .definitions import IsolationMode
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


__all__ = [
    "IsolationPackageComponents",
    "assemble_core_isolation_manager",
    "assemble_isolation_package",
]
