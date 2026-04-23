from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .agent_execution import AgentRunRecord
from .runtime_services import LiveSessionRegistry
from .session_runtime import InboundEvent, InboundEventType, SessionStatus


@dataclass(slots=True)
class ChildRunContinuationBridge:
    session_registry: LiveSessionRegistry
    runtime_metadata: Mapping[str, Any] | None = None
    _delivered_terminal_states: set[tuple[str, str]] = field(default_factory=set, init=False)

    async def deliver(self, record: AgentRunRecord) -> bool:
        if not record.terminal:
            return False
        if record.parent_run_id is None and record.parent_turn_id is None:
            return False
        delivery_key = (record.run_id, record.status.value)
        if delivery_key in self._delivered_terminal_states:
            return False
        session = self.session_registry.get(record.session_id)
        if session is None:
            return False
        if session.state.status in {SessionStatus.INTERRUPTED, SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.STOPPED}:
            return False
        if (
            record.parent_turn_id is not None
            and session.state.active_turn_id is not None
            and session.state.active_turn_id == record.parent_turn_id
        ):
            return False

        drain = False
        if session.state.status == SessionStatus.WAITING:
            drain = _policy_flag(
                self.runtime_metadata,
                "auto_resume_waiting",
                default=True,
            )
        elif session.state.status == SessionStatus.READY:
            drain = _policy_flag(
                self.runtime_metadata,
                "auto_resume_ready",
                default=False,
            )

        event = InboundEvent(
            InboundEventType.TASK_NOTIFICATION,
            _continuation_content(record),
            metadata=_continuation_metadata(record),
        )
        await session.submit_runtime_event(event, drain=drain)
        self._delivered_terminal_states.add(delivery_key)
        return True


def _continuation_content(record: AgentRunRecord) -> str:
    return (
        f"Child run '{record.agent_name}' reached terminal status '{record.status.value}' "
        f"(run_id={record.run_id})."
    )


def _continuation_metadata(record: AgentRunRecord) -> dict[str, Any]:
    return {
        "admission_kind": "admit_turn",
        "ingress_reason": "child_run_completion",
        "source": "child_run_continuation",
        "visibility": "transcript",
        "private_updates": {
            "child_run_continuation": {
                "run_id": record.run_id,
                "parent_run_id": record.parent_run_id,
                "parent_turn_id": record.parent_turn_id,
                "turn_id": record.turn_id,
                "agent_name": record.agent_name,
                "status": record.status.value,
                "query_source": record.query_source,
                "spawn_mode": record.spawn_mode.value,
            }
        },
    }


def _policy_flag(metadata: Mapping[str, Any] | None, key: str, *, default: bool) -> bool:
    if not isinstance(metadata, Mapping):
        return default
    raw_policy = metadata.get("child_run_continuation")
    if not isinstance(raw_policy, Mapping):
        return default
    value = raw_policy.get(key)
    if isinstance(value, bool):
        return value
    return default


__all__ = ["ChildRunContinuationBridge"]
