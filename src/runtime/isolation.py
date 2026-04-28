from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .definitions import IsolationMode
from .public_contract import ensure_canonical_workspace_root


@dataclass(frozen=True, slots=True)
class IsolationRequest:
    session_id: str
    agent_name: str
    mode: IsolationMode
    cwd: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IsolationLease:
    session_id: str
    agent_name: str
    mode: IsolationMode
    working_directory: Path
    adapter_name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    lifecycle: list[str] = field(default_factory=list)


class IsolationPreparationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        mode: IsolationMode,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.mode = mode
        self.metadata = dict(metadata or {})

    def to_metadata(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "mode": self.mode.value,
            "details": dict(self.metadata),
        }


class IsolationAdapter(Protocol):
    mode: IsolationMode

    async def prepare(self, request: IsolationRequest) -> IsolationLease: ...

    async def cleanup(self, lease: IsolationLease) -> None: ...

    def readiness_metadata(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class BaseIsolationAdapter:
    mode: IsolationMode = IsolationMode.NONE

    async def prepare(self, request: IsolationRequest) -> IsolationLease:
        lease = self._build_lease(request)
        lease.lifecycle.append("prepared")
        return lease

    async def cleanup(self, lease: IsolationLease) -> None:
        lease.lifecycle.append("released")

    def readiness_metadata(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "effective_mode": self.mode.value,
            "adapter": type(self).__name__,
        }

    def _build_lease(
        self,
        request: IsolationRequest,
        *,
        working_directory: Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IsolationLease:
        lease = IsolationLease(
            session_id=request.session_id,
            agent_name=request.agent_name,
            mode=self.mode,
            working_directory=working_directory or request.cwd,
            adapter_name=type(self).__name__,
            metadata={
                "requested_mode": request.mode.value,
                "effective_mode": self.mode.value,
                "cwd": str(request.cwd),
                **dict(request.metadata),
                **dict(metadata or {}),
            },
        )
        return lease


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


@dataclass(slots=True)
class IsolationManager:
    adapters: dict[IsolationMode, IsolationAdapter] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.adapters:
            self.adapters = {
                IsolationMode.NONE: BaseIsolationAdapter(),
                IsolationMode.WORKTREE: WorktreeIsolationAdapter(),
                IsolationMode.REMOTE: RemoteIsolationAdapter(),
            }
        else:
            self.adapters.setdefault(IsolationMode.NONE, BaseIsolationAdapter())

    async def prepare(
        self,
        *,
        session_id: str,
        agent_name: str,
        mode: IsolationMode,
        cwd: Path,
        metadata: dict[str, Any] | None = None,
    ) -> IsolationLease:
        adapter = self.adapters.get(mode)
        if adapter is None:
            if mode is IsolationMode.NONE:
                adapter = self.adapters[IsolationMode.NONE]
            else:
                raise IsolationPreparationError(
                    f"{mode.value} isolation is not available",
                    code="not_available",
                    mode=mode,
                    metadata={"available_modes": [item.value for item in self.adapters]},
                )
        lease = await _maybe_await(
            adapter.prepare(
                IsolationRequest(
                    session_id=session_id,
                    agent_name=agent_name,
                    mode=mode,
                    cwd=cwd,
                    metadata=dict(metadata or {}),
                )
            )
        )
        lease.metadata.setdefault("adapter", type(adapter).__name__)
        return lease

    async def cleanup(self, lease: IsolationLease | None) -> None:
        if lease is None:
            return
        adapter = self.adapters.get(lease.mode, self.adapters[IsolationMode.NONE])
        await _maybe_await(adapter.cleanup(lease))

    def describe_modes(self) -> dict[str, Any]:
        modes: dict[str, Any] = {}
        for mode in IsolationMode:
            adapter = self.adapters.get(mode)
            if adapter is None:
                modes[mode.value] = {
                    "status": "not_available",
                    "effective_mode": mode.value,
                }
                continue
            readiness = (
                adapter.readiness_metadata()
                if hasattr(adapter, "readiness_metadata")
                else {
                    "status": "ready" if mode is IsolationMode.NONE else "adapter_provided",
                    "effective_mode": mode.value,
                    "adapter": type(adapter).__name__,
                }
            )
            modes[mode.value] = dict(readiness)
        return modes


def serialize_isolation_lease(lease: IsolationLease | None) -> dict[str, Any] | None:
    if lease is None:
        return None
    return {
        "mode": lease.mode.value,
        "working_directory": str(lease.working_directory),
        "adapter": lease.adapter_name,
        "metadata": dict(lease.metadata),
        "lifecycle": list(lease.lifecycle),
    }


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


def _lease_identifier(request: IsolationRequest) -> str:
    parts = [
        request.session_id,
        request.agent_name,
        str(request.metadata.get("run_id") or request.metadata.get("turn_id") or request.mode.value),
    ]
    return "-".join(_slugify(part) for part in parts if str(part).strip())


def _slugify(value: object) -> str:
    text = "".join(ch if str(ch).isalnum() or ch in {"-", "_"} else "-" for ch in str(value))
    normalized = "-".join(part for part in text.split("-") if part)
    return normalized or "lease"


def _materialize_worktree(source: Path, target: Path) -> int:
    copied_entries = 0
    for entry in source.iterdir():
        if entry.name in {".git", ".runtime", ".weavert", "__pycache__"}:
            continue
        destination = target / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, destination)
        copied_entries += 1
    return copied_entries
