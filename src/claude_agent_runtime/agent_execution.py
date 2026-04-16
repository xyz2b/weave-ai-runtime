from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from .contracts import RuntimeMessage
from .execution_policy import ExecutionPolicyState


class SpawnMode(StrEnum):
    SYNC = "sync"
    BACKGROUND = "background"
    FORK = "fork"
    TEAMMATE = "teammate"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    MAX_TURNS = "max_turns"
    FAILED = "failed"
    DENIED = "denied"

    @property
    def terminal(self) -> bool:
        return self is not AgentRunStatus.RUNNING


@dataclass(frozen=True, slots=True)
class AgentRunLinkage:
    run_id: str
    session_id: str
    parent_run_id: str | None = None
    parent_turn_id: str | None = None
    turn_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgentExecutionSpec:
    run_id: str
    parent_run_id: str | None
    session_id: str
    parent_turn_id: str | None
    turn_id: str
    agent_name: str
    spawn_mode: SpawnMode
    query_source: str | None
    prompt_messages: tuple[RuntimeMessage, ...]
    cwd: Path
    base_system_prompt: str = ""
    parent_policy_state: ExecutionPolicyState | None = None
    requested_model_route: str | None = None
    requested_model: str | None = None
    background: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def linkage(self) -> AgentRunLinkage:
        return AgentRunLinkage(
            run_id=self.run_id,
            session_id=self.session_id,
            parent_run_id=self.parent_run_id,
            parent_turn_id=self.parent_turn_id,
            turn_id=self.turn_id,
        )


@dataclass(frozen=True, slots=True)
class AgentRunRecord:
    run_id: str
    parent_run_id: str | None
    session_id: str
    parent_turn_id: str | None
    turn_id: str | None
    agent_name: str
    spawn_mode: SpawnMode
    status: AgentRunStatus
    query_source: str | None = None
    requested_model_route: str | None = None
    requested_model: str | None = None
    resolved_model_route: str | None = None
    request_metadata: dict[str, Any] = field(default_factory=dict)
    terminal_metadata: dict[str, Any] = field(default_factory=dict)
    messages: tuple[RuntimeMessage, ...] = ()

    @property
    def linkage(self) -> AgentRunLinkage:
        return AgentRunLinkage(
            run_id=self.run_id,
            session_id=self.session_id,
            parent_run_id=self.parent_run_id,
            parent_turn_id=self.parent_turn_id,
            turn_id=self.turn_id,
        )

    @property
    def terminal(self) -> bool:
        return self.status.terminal


class ChildRunStore(Protocol):
    async def upsert(self, record: AgentRunRecord) -> None: ...

    async def get(self, run_id: str) -> AgentRunRecord | None: ...

    async def list_by_session(self, session_id: str) -> tuple[AgentRunRecord, ...]: ...


@dataclass(slots=True)
class InMemoryChildRunStore:
    _records: dict[str, AgentRunRecord] = field(default_factory=dict)
    _session_index: dict[str, list[str]] = field(default_factory=dict)

    async def upsert(self, record: AgentRunRecord) -> None:
        self._records[record.run_id] = record
        session_records = self._session_index.setdefault(record.session_id, [])
        if record.run_id not in session_records:
            session_records.append(record.run_id)

    async def get(self, run_id: str) -> AgentRunRecord | None:
        return self._records.get(run_id)

    async def list_by_session(self, session_id: str) -> tuple[AgentRunRecord, ...]:
        run_ids = self._session_index.get(session_id, [])
        return tuple(self._records[run_id] for run_id in run_ids if run_id in self._records)


__all__ = [
    "AgentExecutionSpec",
    "AgentRunLinkage",
    "AgentRunRecord",
    "AgentRunStatus",
    "ChildRunStore",
    "InMemoryChildRunStore",
    "SpawnMode",
]
