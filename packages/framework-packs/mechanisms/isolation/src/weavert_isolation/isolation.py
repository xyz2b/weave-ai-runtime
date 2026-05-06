from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from weavert.extension_contracts.isolation import (
    BaseIsolationAdapter,
    IsolationAdapter,
    IsolationLease,
    IsolationManager,
    IsolationPreparationError,
    IsolationRequest,
    _lease_identifier,
)
from weavert.definitions import IsolationMode
from weavert.extension_contracts.public_contract import ensure_canonical_workspace_root


@dataclass(slots=True)
class WorktreeIsolationAdapter(BaseIsolationAdapter):
    mode: IsolationMode = IsolationMode.WORKTREE

    async def prepare(self, request: IsolationRequest) -> IsolationLease:
        lease_root = ensure_canonical_workspace_root(request.cwd) / "isolation" / "worktree"
        lease_id = _lease_identifier(request)
        prepared_target = lease_root / lease_id
        if prepared_target.exists():
            shutil.rmtree(prepared_target)
        prepared_target.mkdir(parents=True, exist_ok=True)
        copied_entries = _materialize_worktree(request.cwd, prepared_target)
        lease = self._build_lease(
            request,
            working_directory=prepared_target,
            metadata={
                "contract": "worktree",
                "prepared": True,
                "source_working_directory": str(request.cwd),
                "prepared_target": str(prepared_target),
                "lease_kind": "filesystem_local_copy",
                "cleanup_owner": "runtime",
                "cleanup_lifecycle": "child_run_exit",
                "copied_entries": copied_entries,
            },
        )
        lease.lifecycle.extend(("prepared", "materialized"))
        return lease

    async def cleanup(self, lease: IsolationLease) -> None:
        if lease.working_directory.exists():
            shutil.rmtree(lease.working_directory, ignore_errors=True)
        lease.lifecycle.extend(("cleaned", "released"))

    def readiness_metadata(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "effective_mode": self.mode.value,
            "adapter": type(self).__name__,
            "lease_kind": "filesystem_local_copy",
            "cleanup_owner": "runtime",
            "cleanup_lifecycle": "child_run_exit",
        }


@dataclass(slots=True)
class RemoteIsolationAdapter(BaseIsolationAdapter):
    mode: IsolationMode = IsolationMode.REMOTE

    async def prepare(self, request: IsolationRequest) -> IsolationLease:
        raise IsolationPreparationError(
            "remote isolation is not configured",
            code="not_configured",
            mode=self.mode,
            metadata={
                "contract": "remote",
                "requested_mode": request.mode.value,
                "effective_mode": self.mode.value,
                "cwd": str(request.cwd),
                "adapter": type(self).__name__,
            },
        )

    def readiness_metadata(self) -> dict[str, Any]:
        return {
            "status": "not_configured",
            "effective_mode": self.mode.value,
            "adapter": type(self).__name__,
        }


def _materialize_worktree(source: Path, target: Path) -> int:
    copied_entries = 0
    for entry in source.iterdir():
        if entry.name in {".git", ".weavert", "__pycache__"}:
            continue
        destination = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, destination)
        copied_entries += 1
    return copied_entries


__all__ = [
    "BaseIsolationAdapter",
    "IsolationAdapter",
    "IsolationLease",
    "IsolationManager",
    "IsolationPreparationError",
    "IsolationRequest",
    "RemoteIsolationAdapter",
    "WorktreeIsolationAdapter",
]
