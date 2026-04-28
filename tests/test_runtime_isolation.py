import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from weavert.definitions import IsolationMode
from weavert.isolation import (
    BaseIsolationAdapter,
    IsolationLease,
    IsolationManager,
    IsolationPreparationError,
    WorktreeIsolationAdapter,
)


@dataclass(slots=True)
class AdapterBackedRemoteAdapter(BaseIsolationAdapter):
    mode: IsolationMode = IsolationMode.REMOTE
    endpoint: str = "ssh://runtime-remote"

    async def prepare(self, request) -> IsolationLease:
        lease = self._build_lease(
            request,
            metadata={
                "contract": "remote",
                "adapter_endpoint": self.endpoint,
                "lease_kind": "remote_workspace",
                "cleanup_owner": "adapter",
            },
        )
        lease.lifecycle.extend(("prepared", "delegated"))
        return lease

    async def cleanup(self, lease: IsolationLease) -> None:
        lease.lifecycle.extend(("adapter_cleaned", "released"))

    def readiness_metadata(self) -> dict[str, str]:
        return {
            "status": "ready",
            "effective_mode": self.mode.value,
            "adapter": type(self).__name__,
            "adapter_endpoint": self.endpoint,
            "lease_kind": "remote_workspace",
        }


def test_worktree_isolation_adapter_materializes_and_cleans_local_lease(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "keep.txt").write_text("hello", encoding="utf-8")
    (source / "nested").mkdir()
    (source / "nested" / "note.txt").write_text("nested", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "ignored.txt").write_text("ignored", encoding="utf-8")
    (source / ".weavert").mkdir()
    (source / ".weavert" / "ignored.txt").write_text("ignored", encoding="utf-8")

    manager = IsolationManager(
        adapters={
            IsolationMode.NONE: BaseIsolationAdapter(),
            IsolationMode.WORKTREE: WorktreeIsolationAdapter(),
        }
    )
    lease = asyncio.run(
        manager.prepare(
            mode=IsolationMode.WORKTREE,
            session_id="session",
            agent_name="delegate",
            cwd=source,
            metadata={"run_id": "run-1"},
        )
    )

    assert lease.metadata["prepared"] is True
    assert lease.metadata["lease_kind"] == "filesystem_local_copy"
    assert lease.metadata["cleanup_owner"] == "runtime"
    assert (lease.working_directory / "keep.txt").read_text(encoding="utf-8") == "hello"
    assert (lease.working_directory / "nested" / "note.txt").read_text(encoding="utf-8") == "nested"
    assert not (lease.working_directory / ".git").exists()
    assert not (lease.working_directory / ".weavert").exists()

    asyncio.run(manager.cleanup(lease))

    assert lease.lifecycle[-2:] == ["cleaned", "released"]
    assert not lease.working_directory.exists()


def test_missing_remote_adapter_reports_not_available_before_preparation(tmp_path: Path) -> None:
    manager = IsolationManager(adapters={IsolationMode.NONE: BaseIsolationAdapter()})

    with pytest.raises(IsolationPreparationError) as excinfo:
        asyncio.run(
            manager.prepare(
                mode=IsolationMode.REMOTE,
                session_id="session",
                agent_name="delegate",
                cwd=tmp_path,
            )
        )

    assert excinfo.value.code == "not_available"
    assert excinfo.value.to_metadata() == {
        "code": "not_available",
        "mode": "remote",
        "details": {"available_modes": ["none"]},
    }
    assert manager.describe_modes()["remote"] == {
        "status": "not_available",
        "effective_mode": "remote",
    }


def test_remote_adapter_backends_publish_effective_metadata_and_cleanup(tmp_path: Path) -> None:
    manager = IsolationManager(
        adapters={
            IsolationMode.NONE: BaseIsolationAdapter(),
            IsolationMode.REMOTE: AdapterBackedRemoteAdapter(),
        }
    )
    lease = asyncio.run(
        manager.prepare(
            mode=IsolationMode.REMOTE,
            session_id="session",
            agent_name="delegate",
            cwd=tmp_path,
            metadata={"run_id": "run-remote"},
        )
    )

    assert lease.mode is IsolationMode.REMOTE
    assert lease.metadata["requested_mode"] == "remote"
    assert lease.metadata["effective_mode"] == "remote"
    assert lease.metadata["adapter_endpoint"] == "ssh://runtime-remote"
    assert lease.metadata["lease_kind"] == "remote_workspace"
    assert lease.metadata["cleanup_owner"] == "adapter"
    assert manager.describe_modes()["remote"] == {
        "status": "ready",
        "effective_mode": "remote",
        "adapter": "AdapterBackedRemoteAdapter",
        "adapter_endpoint": "ssh://runtime-remote",
        "lease_kind": "remote_workspace",
    }

    asyncio.run(manager.cleanup(lease))

    assert lease.lifecycle[-2:] == ["adapter_cleaned", "released"]
