import pytest

from runtime.contracts import MessageRole, RuntimeMessage
from runtime.runtime_services import RuntimeServices
from runtime.session_runtime import (
    InboundEvent,
    InboundEventType,
    SessionIngressProcessor,
)
from runtime.session_runtime.models import (
    IngressAdmission,
    IngressAdmissionKind,
    IngressReplayOutput,
    SessionIngressResult,
    SessionIngressSnapshot,
    SessionState,
    SessionStatus,
)

from .runtime_protocol_harness import ingress_result_fixture


def test_session_ingress_protocol_distinguishes_turn_local_only_and_reject(tmp_path) -> None:
    processor = SessionIngressProcessor()
    state = SessionState(
        session_id="session-ingress",
        current_agent="main-router",
        status=SessionStatus.READY,
    )
    state.metadata["ingress_private_defaults"] = {"session_scope": "interactive"}
    snapshot = SessionIngressSnapshot.from_state(state, cwd=str(tmp_path))
    services = RuntimeServices(
        metadata={
            "ingress_prompt_defaults": {"session_hint": "active"},
            "ingress_private_defaults": {"host_scope": "bound"},
        }
    )

    admitted = processor.process(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "Summarize the deployment failure",
            metadata={
                "completion_receipts": [
                    {
                        "receipt_id": "receipt-1",
                        "kind": "runtime.test.receipt",
                        "payload": {"ack": "host"},
                    }
                ],
                "prompt_updates": {"topic": "incident"},
                "private_updates": {"request_id": "req-1"},
            },
        ),
        session_snapshot=snapshot,
        runtime_services=services,
    )
    local_only = processor.process(
        InboundEvent(
            InboundEventType.HOST_EVENT,
            "Refresh complete",
            metadata={"private_updates": {"refresh": True}},
        ),
        session_snapshot=snapshot,
        runtime_services=services,
    )
    rejected = processor.process(
        InboundEvent(
            InboundEventType.USER_PROMPT,
            "rm -rf /",
            metadata={
                "admission_kind": "reject",
                "ingress_reason": "policy_blocked",
                "replay_text": "Blocked by policy",
                "private_updates": {"policy": "manual_review"},
            },
        ),
        session_snapshot=snapshot,
        runtime_services=services,
    )

    assert ingress_result_fixture(admitted) == {
        "admission": {"kind": "admit_turn", "reason": "admit_turn"},
        "normalized_messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Summarize the deployment failure"}],
            }
        ],
        "replay_outputs": [],
        "completion_receipts": [
            {
                "receipt_id": "receipt-1",
                "kind": "runtime.test.receipt",
                "payload": {"ack": "host"},
            }
        ],
        "prompt_updates": {"session_hint": "active", "topic": "incident"},
        "private_updates": {
            "host_scope": "bound",
            "request_id": "req-1",
            "session_scope": "interactive",
        },
    }
    assert ingress_result_fixture(local_only) == {
        "admission": {"kind": "local_only", "reason": "local_only"},
        "normalized_messages": [],
        "replay_outputs": [
            {
                "role": "notification",
                "content": [{"type": "text", "text": "Refresh complete"}],
                "visibility": "host",
                "source": "host_event",
            }
        ],
        "private_updates": {
            "host_scope": "bound",
            "refresh": True,
            "session_scope": "interactive",
        },
    }
    assert ingress_result_fixture(rejected) == {
        "admission": {"kind": "reject", "reason": "policy_blocked"},
        "normalized_messages": [],
        "replay_outputs": [
            {
                "role": "notification",
                "content": [{"type": "text", "text": "Blocked by policy"}],
                "visibility": "host",
                "source": "user_prompt",
            }
        ],
        "private_updates": {
            "host_scope": "bound",
            "policy": "manual_review",
            "session_scope": "interactive",
        },
    }
    assert [_consume_ingress_result(result) for result in (admitted, local_only, rejected)] == [
        ("turn", ("Summarize the deployment failure",)),
        ("local_only", ("Refresh complete",)),
        ("reject", ("Blocked by policy",)),
    ]


def test_session_ingress_processor_defaults_task_notifications_to_transcript_only(tmp_path) -> None:
    processor = SessionIngressProcessor()
    snapshot = SessionIngressSnapshot(
        session_id="session-notify",
        current_agent="main-router",
        cwd=str(tmp_path),
        status=SessionStatus.READY,
    )

    result = processor.process(
        InboundEvent(InboundEventType.TASK_NOTIFICATION, "Background job finished"),
        session_snapshot=snapshot,
        runtime_services=RuntimeServices(),
    )

    assert result.admission.kind == IngressAdmissionKind.TRANSCRIPT_ONLY
    assert [message.role for message in result.normalized_messages] == [MessageRole.NOTIFICATION]
    assert [message.text for message in result.normalized_messages] == ["Background job finished"]
    assert result.replay_outputs == ()
    assert result.prompt_updates == {}


def test_session_ingress_invalid_admission_kind_becomes_reject_with_private_diagnostics(tmp_path) -> None:
    processor = SessionIngressProcessor()
    snapshot = SessionIngressSnapshot(
        session_id="session-invalid-kind",
        current_agent="main-router",
        cwd=str(tmp_path),
        status=SessionStatus.READY,
    )

    result = processor.process(
        InboundEvent(
            InboundEventType.HOST_EVENT,
            "Blocked input",
            metadata={"admission_kind": "bogus", "replay_text": "Rejected by ingress"},
        ),
        session_snapshot=snapshot,
        runtime_services=RuntimeServices(),
    )

    assert result.admission.kind == IngressAdmissionKind.REJECT
    assert result.admission.reason == "invalid_admission_kind"
    assert result.private_updates["invalid_admission_kind"] == "bogus"
    assert [output.text for output in result.replay_outputs] == ["Rejected by ingress"]


def test_session_ingress_preserves_completion_receipt_order_and_identity(tmp_path) -> None:
    processor = SessionIngressProcessor()
    snapshot = SessionIngressSnapshot(
        session_id="session-receipts",
        current_agent="main-router",
        cwd=str(tmp_path),
        status=SessionStatus.READY,
    )

    result = processor.process(
        InboundEvent(
            InboundEventType.HOST_EVENT,
            "Queued receipt",
            metadata={
                "admission_kind": "local_only",
                "completion_receipts": [
                    {
                        "receipt_id": "receipt-1",
                        "kind": "runtime.test.first",
                        "payload": {"step": 1},
                    },
                    {
                        "receipt_id": "receipt-2",
                        "kind": "runtime.test.second",
                        "payload": {"step": 2},
                    },
                ],
            },
        ),
        session_snapshot=snapshot,
        runtime_services=RuntimeServices(),
    )

    assert [(receipt.receipt_id, receipt.kind) for receipt in result.completion_receipts] == [
        ("receipt-1", "runtime.test.first"),
        ("receipt-2", "runtime.test.second"),
    ]
    assert ingress_result_fixture(result)["completion_receipts"] == [
        {"receipt_id": "receipt-1", "kind": "runtime.test.first", "payload": {"step": 1}},
        {"receipt_id": "receipt-2", "kind": "runtime.test.second", "payload": {"step": 2}},
    ]


def test_session_ingress_result_rejects_invalid_field_combinations() -> None:
    message = RuntimeMessage(message_id="msg-1", role=MessageRole.USER, content="hello")
    replay_output = IngressReplayOutput(
        output_id="replay-1",
        role=MessageRole.NOTIFICATION,
        content="local output",
    )

    with pytest.raises(ValueError, match="reject ingress results cannot carry normalized messages"):
        SessionIngressResult(
            admission=IngressAdmission(IngressAdmissionKind.REJECT, "blocked"),
            normalized_messages=(message,),
        )
    with pytest.raises(ValueError, match="local_only ingress results cannot carry prompt updates"):
        SessionIngressResult(
            admission=IngressAdmission(IngressAdmissionKind.LOCAL_ONLY, "local"),
            prompt_updates={"leak": True},
        )
    with pytest.raises(ValueError, match="replay_only ingress results must include replay outputs"):
        SessionIngressResult(
            admission=IngressAdmission(IngressAdmissionKind.REPLAY_ONLY, "replay"),
        )

    valid_replay_only = SessionIngressResult.replay_only(replay_outputs=(replay_output,), reason="replay")
    assert valid_replay_only.admission.kind == IngressAdmissionKind.REPLAY_ONLY
    assert [output.text for output in valid_replay_only.replay_outputs] == ["local output"]


def _consume_ingress_result(result: SessionIngressResult) -> tuple[str, tuple[str, ...]]:
    if result.admits_turn:
        return ("turn", tuple(message.text for message in result.normalized_messages))
    if result.replay_outputs:
        return (result.admission.kind.value, tuple(output.text for output in result.replay_outputs))
    return (result.admission.kind.value, tuple(message.text for message in result.normalized_messages))
