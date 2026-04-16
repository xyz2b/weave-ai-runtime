from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .definitions import IsolationMode


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


class IsolationAdapter(Protocol):
    mode: IsolationMode

    async def prepare(self, request: IsolationRequest) -> IsolationLease: ...

    async def cleanup(self, lease: IsolationLease) -> None: ...


@dataclass(slots=True)
class BaseIsolationAdapter:
    mode: IsolationMode = IsolationMode.NONE

    async def prepare(self, request: IsolationRequest) -> IsolationLease:
        lease = IsolationLease(
            session_id=request.session_id,
            agent_name=request.agent_name,
            mode=self.mode,
            working_directory=request.cwd,
            adapter_name=type(self).__name__,
            metadata={
                "requested_mode": request.mode.value,
                "effective_mode": self.mode.value,
                "cwd": str(request.cwd),
                **dict(request.metadata),
            },
        )
        lease.lifecycle.append("prepared")
        return lease

    async def cleanup(self, lease: IsolationLease) -> None:
        lease.lifecycle.append("released")


@dataclass(slots=True)
class WorktreeIsolationAdapter(BaseIsolationAdapter):
    mode: IsolationMode = IsolationMode.WORKTREE

    async def prepare(self, request: IsolationRequest) -> IsolationLease:
        lease = await BaseIsolationAdapter.prepare(self, request)
        lease.metadata.setdefault("contract", "worktree")
        lease.metadata.setdefault("prepared", True)
        lease.metadata.setdefault("stub", True)
        return lease


@dataclass(slots=True)
class RemoteIsolationAdapter(BaseIsolationAdapter):
    mode: IsolationMode = IsolationMode.REMOTE

    async def prepare(self, request: IsolationRequest) -> IsolationLease:
        lease = await BaseIsolationAdapter.prepare(self, request)
        lease.metadata.setdefault("contract", "remote")
        lease.metadata.setdefault("prepared", True)
        lease.metadata.setdefault("stub", True)
        return lease


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
        adapter = self.adapters.get(mode, self.adapters[IsolationMode.NONE])
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
