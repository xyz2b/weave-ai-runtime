from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4

from .contracts import RuntimePrivateContext, coerce_runtime_private_context

WORKFLOW_EXTENSION_EVENT_NAMESPACE = "weavert.workflow"
WORKFLOW_EXTENSION_EVENT_SCHEMA_VERSION = "1.0"
_SUCCESS_WORKFLOW_STOP_REASONS = {"completed", "end_turn", "message_stop"}


class WorkflowRunKind(StrEnum):
    ROOT = "root"
    CHILD = "child"


class WorkflowLifecycleStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    MAX_TURNS = "max_turns"
    DENIED = "denied"
    STOPPED = "stopped"


class WorkflowOutcome(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class WorkflowDiagnosticSeverity(StrEnum):
    INFO = "info"
    ADVISORY = "advisory"
    BLOCKING = "blocking"


class WorkflowObservationSurface(StrEnum):
    TURN_STREAM = "turn_stream"
    CHILD_RUN = "child_run"
    WORKFLOW_RUN_REPORT = "workflow_run_report"
    RESULT_PROJECTION = "result_projection"
    HOST_BRIDGE = "host_bridge"


@dataclass(frozen=True, slots=True)
class WorkflowRunIdentity:
    run_id: str
    session_id: str
    turn_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
        }


@dataclass(frozen=True, slots=True)
class WorkflowRunLinkage:
    parent_run_id: str | None = None
    parent_turn_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_run_id": self.parent_run_id,
            "parent_turn_id": self.parent_turn_id,
        }


@dataclass(frozen=True, slots=True)
class WorkflowDiagnostic:
    code: str
    severity: WorkflowDiagnosticSeverity
    message: str
    outcome: WorkflowOutcome | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "outcome": self.outcome.value if self.outcome is not None else None,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class WorkflowRunObservability:
    run_kind: WorkflowRunKind
    identity: WorkflowRunIdentity
    lifecycle_status: WorkflowLifecycleStatus
    outcome: WorkflowOutcome
    linkage: WorkflowRunLinkage = field(default_factory=WorkflowRunLinkage)
    diagnostics: tuple[WorkflowDiagnostic, ...] = ()
    query_source: str | None = None
    requested_model_route: str | None = None
    resolved_model_route: str | None = None
    provider_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def run_id(self) -> str:
        return self.identity.run_id

    @property
    def session_id(self) -> str:
        return self.identity.session_id

    @property
    def turn_id(self) -> str | None:
        return self.identity.turn_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_kind": self.run_kind.value,
            "identity": self.identity.to_dict(),
            "lifecycle_status": self.lifecycle_status.value,
            "outcome": self.outcome.value,
            "linkage": self.linkage.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "query_source": self.query_source,
            "requested_model_route": self.requested_model_route,
            "resolved_model_route": self.resolved_model_route,
            "provider_name": self.provider_name,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class WorkflowObservationEvent:
    session_id: str
    surface: WorkflowObservationSurface
    source_event_type: str
    workflow: WorkflowRunObservability
    turn_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "surface": self.surface.value,
            "source_event_type": self.source_event_type,
            "turn_id": self.turn_id,
            "workflow": self.workflow.to_dict(),
            "metadata": dict(self.metadata),
        }


def serialize_workflow_run_observability(
    observability: WorkflowRunObservability | None,
) -> dict[str, Any] | None:
    if observability is None:
        return None
    return observability.to_dict()


def workflow_run_observability_from_mapping(
    payload: Mapping[str, Any] | None,
) -> WorkflowRunObservability | None:
    if not isinstance(payload, Mapping):
        return None
    identity_payload = _coerce_mapping(payload.get("identity"))
    run_id = _coerce_optional_string(identity_payload.get("run_id"))
    session_id = _coerce_optional_string(identity_payload.get("session_id"))
    if run_id is None or session_id is None:
        return None
    linkage_payload = _coerce_mapping(payload.get("linkage"))
    diagnostics: list[WorkflowDiagnostic] = []
    for entry in payload.get("diagnostics", ()):
        if not isinstance(entry, Mapping):
            continue
        code = _coerce_optional_string(entry.get("code"))
        severity = _coerce_workflow_diagnostic_severity(entry.get("severity"))
        message = _coerce_optional_string(entry.get("message"))
        if code is None or severity is None or message is None:
            continue
        diagnostics.append(
            WorkflowDiagnostic(
                code=code,
                severity=severity,
                message=message,
                outcome=_coerce_workflow_outcome(entry.get("outcome")),
                details=_coerce_mapping(entry.get("details")),
            )
        )
    run_kind = _coerce_workflow_run_kind(payload.get("run_kind"))
    lifecycle_status = _coerce_workflow_lifecycle_status(payload.get("lifecycle_status"))
    outcome = _coerce_workflow_outcome(payload.get("outcome"))
    if run_kind is None or lifecycle_status is None or outcome is None:
        return None
    return WorkflowRunObservability(
        run_kind=run_kind,
        identity=WorkflowRunIdentity(
            run_id=run_id,
            session_id=session_id,
            turn_id=_coerce_optional_string(identity_payload.get("turn_id")),
        ),
        lifecycle_status=lifecycle_status,
        outcome=outcome,
        linkage=WorkflowRunLinkage(
            parent_run_id=_coerce_optional_string(linkage_payload.get("parent_run_id")),
            parent_turn_id=_coerce_optional_string(linkage_payload.get("parent_turn_id")),
        ),
        diagnostics=tuple(diagnostics),
        query_source=_coerce_optional_string(payload.get("query_source")),
        requested_model_route=_coerce_optional_string(payload.get("requested_model_route")),
        resolved_model_route=_coerce_optional_string(payload.get("resolved_model_route")),
        provider_name=_coerce_optional_string(payload.get("provider_name")),
        metadata=_coerce_mapping(payload.get("metadata")),
    )


def resolve_workflow_run_observability(source: Any) -> WorkflowRunObservability | None:
    if isinstance(source, WorkflowRunObservability):
        return source
    if isinstance(source, Mapping):
        nested = source.get("workflow_observability")
        if isinstance(nested, Mapping):
            resolved = workflow_run_observability_from_mapping(nested)
            if resolved is not None:
                return resolved
        return _workflow_observability_from_projection_mapping(source)
    explicit = getattr(source, "workflow_observability", None)
    if isinstance(explicit, WorkflowRunObservability):
        return explicit
    if isinstance(explicit, Mapping):
        resolved = workflow_run_observability_from_mapping(explicit)
        if resolved is not None:
            return resolved
    if _looks_like_child_run_record(source):
        return workflow_run_observability_from_child_run(source)
    if _looks_like_agent_run_result(source):
        return workflow_run_observability_from_agent_result(source)
    if _looks_like_report(source):
        return workflow_run_observability_from_report(source)
    return None


def workflow_run_observability_from_child_run(record: Any) -> WorkflowRunObservability:
    status_value = _coerce_optional_string(getattr(record, "status", None)) or str(getattr(record, "status", "running"))
    status = _coerce_workflow_lifecycle_status(status_value) or WorkflowLifecycleStatus.RUNNING
    metadata = _coerce_mapping(getattr(record, "terminal_metadata", None))
    diagnostics = _diagnostics_for_child_status(status=status, metadata=metadata)
    return WorkflowRunObservability(
        run_kind=WorkflowRunKind.CHILD,
        identity=WorkflowRunIdentity(
            run_id=str(getattr(record, "run_id", "")),
            session_id=str(getattr(record, "session_id", "")),
            turn_id=_coerce_optional_string(getattr(record, "turn_id", None)),
        ),
        lifecycle_status=status,
        outcome=_outcome_for_child_status(status),
        linkage=WorkflowRunLinkage(
            parent_run_id=_coerce_optional_string(getattr(record, "parent_run_id", None)),
            parent_turn_id=_coerce_optional_string(getattr(record, "parent_turn_id", None)),
        ),
        diagnostics=tuple(diagnostics),
        query_source=_coerce_optional_string(getattr(record, "query_source", None)),
        requested_model_route=_coerce_optional_string(getattr(record, "requested_model_route", None)),
        resolved_model_route=_coerce_optional_string(getattr(record, "resolved_model_route", None)),
        provider_name=_coerce_optional_string(getattr(record, "provider_name", None)),
        metadata=metadata,
    )


def workflow_run_observability_from_agent_result(result: Any) -> WorkflowRunObservability | None:
    run_record = getattr(result, "run_record", None)
    if run_record is not None and _looks_like_child_run_record(run_record):
        return workflow_run_observability_from_child_run(run_record)
    run_id = _coerce_optional_string(getattr(result, "run_id", None))
    session_id = _coerce_optional_string(getattr(getattr(result, "execution_spec", None), "session_id", None))
    if run_id is None or session_id is None:
        return None
    status_value = _coerce_optional_string(getattr(result, "status", None)) or "running"
    status = _coerce_workflow_lifecycle_status(status_value) or WorkflowLifecycleStatus.RUNNING
    metadata = _coerce_mapping(getattr(result, "terminal_metadata", None))
    if not metadata:
        notification = getattr(result, "notification", None)
        metadata = _coerce_mapping(getattr(notification, "metadata", None))
    return WorkflowRunObservability(
        run_kind=WorkflowRunKind.CHILD,
        identity=WorkflowRunIdentity(
            run_id=run_id,
            session_id=session_id,
            turn_id=_coerce_optional_string(getattr(result, "turn_id", None)),
        ),
        lifecycle_status=status,
        outcome=_outcome_for_child_status(status),
        linkage=WorkflowRunLinkage(
            parent_run_id=_coerce_optional_string(getattr(result, "parent_run_id", None)),
            parent_turn_id=_coerce_optional_string(
                getattr(getattr(result, "execution_spec", None), "parent_turn_id", None)
            ),
        ),
        diagnostics=tuple(_diagnostics_for_child_status(status=status, metadata=metadata)),
        query_source=_coerce_optional_string(getattr(result, "query_source", None)),
        requested_model_route=_coerce_optional_string(
            getattr(getattr(result, "execution_spec", None), "requested_model_route", None)
        ),
        resolved_model_route=_coerce_optional_string(
            getattr(getattr(result, "execution_spec", None), "resolved_model_route", None)
        ),
        provider_name=_coerce_optional_string(getattr(getattr(result, "execution_spec", None), "provider_name", None)),
        metadata=metadata,
    )


def workflow_run_observability_from_report(report: Any) -> WorkflowRunObservability | None:
    session_id = _coerce_optional_string(getattr(report, "session_id", None))
    if session_id is None:
        return None
    turn_id = _coerce_optional_string(getattr(report, "turn_id", None))
    run_id = _coerce_optional_string(getattr(report, "run_id", None)) or turn_id or session_id
    terminal = getattr(report, "terminal", None)
    if terminal is not None:
        private_context = RuntimePrivateContext(
            requested_model_route=_coerce_optional_string(getattr(report, "requested_model_route", None)),
            resolved_model_route=_coerce_optional_string(getattr(report, "resolved_model_route", None)),
            provider_name=_coerce_optional_string(getattr(report, "provider_name", None)),
        )
        return _root_workflow_observability_from_terminal(
            session_id=session_id,
            turn_id=turn_id or run_id,
            terminal=terminal,
            private_context=private_context,
            runtime_context={"query_source": getattr(report, "query_source", None)},
        )
    status = _status_from_final_status(_coerce_optional_string(getattr(report, "final_status", None)))
    if status is None:
        return None
    diagnostics = _diagnostics_for_report_status(status=status)
    return WorkflowRunObservability(
        run_kind=WorkflowRunKind.ROOT,
        identity=WorkflowRunIdentity(run_id=run_id, session_id=session_id, turn_id=turn_id),
        lifecycle_status=status,
        outcome=_outcome_for_report_status(status),
        diagnostics=tuple(diagnostics),
        metadata={},
    )


def workflow_observation_from_turn_event(
    event: Any,
    *,
    session_id: str,
    turn_id: str | None,
    private_context: RuntimePrivateContext | Mapping[str, Any] | None = None,
    runtime_context: Mapping[str, Any] | None = None,
) -> WorkflowObservationEvent | None:
    source_event_type = _coerce_optional_string(getattr(getattr(event, "event_type", None), "value", None)) or _coerce_optional_string(
        getattr(event, "event_type", None)
    )
    if source_event_type is None:
        return None
    child_run = getattr(event, "child_run", None)
    if child_run is not None and _looks_like_child_run_record(child_run):
        workflow = workflow_run_observability_from_child_run(child_run)
    else:
        resolved_private_context = coerce_runtime_private_context(private_context)
        workflow = _root_workflow_observability_from_event(
            session_id=session_id,
            turn_id=turn_id,
            event=event,
            private_context=resolved_private_context,
            runtime_context=runtime_context,
        )
        if workflow is None:
            return None
    event_metadata: dict[str, Any] = {}
    phase = getattr(event, "phase", None)
    if phase is not None:
        event_metadata["phase"] = _coerce_optional_string(getattr(phase, "value", None)) or str(phase)
    iteration = getattr(event, "iteration", None)
    if isinstance(iteration, int):
        event_metadata["iteration"] = iteration
    return WorkflowObservationEvent(
        session_id=session_id,
        surface=WorkflowObservationSurface.TURN_STREAM,
        source_event_type=source_event_type,
        workflow=workflow,
        turn_id=workflow.turn_id or turn_id,
        metadata=event_metadata,
    )


def workflow_host_extension_event_from_turn_event(event: Any) -> Any | None:
    observation = getattr(event, "workflow_observation", None)
    if not isinstance(observation, WorkflowObservationEvent):
        return None
    if observation.source_event_type not in {"request_start", "terminal", "child_run"}:
        return None
    from .hosts.base import HostExtensionEvent

    return HostExtensionEvent(
        namespace=WORKFLOW_EXTENSION_EVENT_NAMESPACE,
        schema_version=WORKFLOW_EXTENSION_EVENT_SCHEMA_VERSION,
        event_type=_host_extension_event_type(observation),
        event_id=uuid4().hex,
        correlation_id=observation.workflow.run_id,
        payload=observation.to_dict(),
    )


def _root_workflow_observability_from_event(
    *,
    session_id: str,
    turn_id: str | None,
    event: Any,
    private_context: RuntimePrivateContext,
    runtime_context: Mapping[str, Any] | None,
) -> WorkflowRunObservability | None:
    if turn_id is None:
        request = getattr(event, "request", None)
        turn_context = getattr(request, "turn_context", None)
        turn_id = _coerce_optional_string(getattr(turn_context, "turn_id", None))
    if turn_id is None:
        return None
    terminal = getattr(event, "terminal", None)
    if terminal is not None:
        return _root_workflow_observability_from_terminal(
            session_id=session_id,
            turn_id=turn_id,
            terminal=terminal,
            private_context=private_context,
            runtime_context=runtime_context,
        )
    return WorkflowRunObservability(
        run_kind=WorkflowRunKind.ROOT,
        identity=WorkflowRunIdentity(
            run_id=private_context.run_id or turn_id,
            session_id=session_id,
            turn_id=turn_id,
        ),
        lifecycle_status=WorkflowLifecycleStatus.RUNNING,
        outcome=WorkflowOutcome.RUNNING,
        linkage=WorkflowRunLinkage(
            parent_run_id=private_context.parent_run_id,
            parent_turn_id=None,
        ),
        diagnostics=(),
        query_source=_query_source_from_runtime_context(event=event, runtime_context=runtime_context),
        requested_model_route=private_context.requested_model_route,
        resolved_model_route=private_context.resolved_model_route,
        provider_name=private_context.provider_name,
        metadata={},
    )


def _root_workflow_observability_from_terminal(
    *,
    session_id: str,
    turn_id: str,
    terminal: Any,
    private_context: RuntimePrivateContext,
    runtime_context: Mapping[str, Any] | None,
) -> WorkflowRunObservability:
    status, outcome, diagnostics = _status_outcome_and_diagnostics_from_terminal(terminal)
    metadata = _coerce_mapping(getattr(terminal, "metadata", None))
    return WorkflowRunObservability(
        run_kind=WorkflowRunKind.ROOT,
        identity=WorkflowRunIdentity(
            run_id=private_context.run_id or turn_id,
            session_id=session_id,
            turn_id=turn_id,
        ),
        lifecycle_status=status,
        outcome=outcome,
        linkage=WorkflowRunLinkage(
            parent_run_id=private_context.parent_run_id,
            parent_turn_id=None,
        ),
        diagnostics=tuple(diagnostics),
        query_source=_query_source_from_runtime_context(runtime_context=runtime_context),
        requested_model_route=private_context.requested_model_route,
        resolved_model_route=private_context.resolved_model_route,
        provider_name=private_context.provider_name,
        metadata=metadata,
    )


def _status_outcome_and_diagnostics_from_terminal(
    terminal: Any,
) -> tuple[WorkflowLifecycleStatus, WorkflowOutcome, tuple[WorkflowDiagnostic, ...]]:
    stop_reason = _coerce_optional_string(getattr(terminal, "stop_reason", None)) or ""
    error = _coerce_optional_string(getattr(terminal, "error", None))
    abort_reason = _coerce_optional_string(getattr(terminal, "abort_reason", None))
    metadata = _coerce_mapping(getattr(terminal, "metadata", None))
    failure_class = _coerce_optional_string(metadata.get("failure_class"))

    if stop_reason in _SUCCESS_WORKFLOW_STOP_REASONS and error is None and abort_reason is None and failure_class in {None, "none"}:
        return WorkflowLifecycleStatus.COMPLETED, WorkflowOutcome.SUCCEEDED, ()
    if stop_reason == WorkflowLifecycleStatus.MAX_TURNS.value:
        return (
            WorkflowLifecycleStatus.MAX_TURNS,
            WorkflowOutcome.DEGRADED,
            (
                WorkflowDiagnostic(
                    code="workflow_max_turns_reached",
                    severity=WorkflowDiagnosticSeverity.ADVISORY,
                    outcome=WorkflowOutcome.DEGRADED,
                    message="Workflow reached its configured max-turn limit.",
                    details={"stop_reason": stop_reason, **metadata},
                ),
            ),
        )
    if stop_reason == WorkflowLifecycleStatus.BLOCKED.value or metadata.get("continuation_blocked"):
        return (
            WorkflowLifecycleStatus.BLOCKED,
            WorkflowOutcome.BLOCKED,
            (
                WorkflowDiagnostic(
                    code="workflow_blocked",
                    severity=WorkflowDiagnosticSeverity.BLOCKING,
                    outcome=WorkflowOutcome.BLOCKED,
                    message=error or abort_reason or "Workflow execution blocked.",
                    details={"stop_reason": stop_reason, **metadata},
                ),
            ),
        )
    if stop_reason == WorkflowLifecycleStatus.INTERRUPTED.value or abort_reason is not None:
        return (
            WorkflowLifecycleStatus.INTERRUPTED,
            WorkflowOutcome.INTERRUPTED,
            (
                WorkflowDiagnostic(
                    code="workflow_interrupted",
                    severity=WorkflowDiagnosticSeverity.BLOCKING,
                    outcome=WorkflowOutcome.INTERRUPTED,
                    message=abort_reason or error or "Workflow execution interrupted.",
                    details={"stop_reason": stop_reason, **metadata},
                ),
            ),
        )
    return (
        WorkflowLifecycleStatus.FAILED,
        WorkflowOutcome.FAILED,
        (
            WorkflowDiagnostic(
                code=failure_class or "workflow_failed",
                severity=WorkflowDiagnosticSeverity.BLOCKING,
                outcome=WorkflowOutcome.FAILED,
                message=error or abort_reason or "Workflow execution failed.",
                details={"stop_reason": stop_reason, **metadata},
            ),
        ),
    )


def _diagnostics_for_child_status(
    *,
    status: WorkflowLifecycleStatus,
    metadata: Mapping[str, Any],
) -> tuple[WorkflowDiagnostic, ...]:
    if status == WorkflowLifecycleStatus.COMPLETED or status == WorkflowLifecycleStatus.RUNNING:
        return ()
    if status == WorkflowLifecycleStatus.MAX_TURNS:
        return (
            WorkflowDiagnostic(
                code="workflow_max_turns_reached",
                severity=WorkflowDiagnosticSeverity.ADVISORY,
                outcome=WorkflowOutcome.DEGRADED,
                message="Workflow reached its configured max-turn limit.",
                details=dict(metadata),
            ),
        )
    if status == WorkflowLifecycleStatus.DENIED or metadata.get("permission_denied"):
        return (
            WorkflowDiagnostic(
                code="workflow_permission_denied",
                severity=WorkflowDiagnosticSeverity.BLOCKING,
                outcome=WorkflowOutcome.BLOCKED,
                message=_coerce_optional_string(metadata.get("error")) or "Workflow execution was denied.",
                details=dict(metadata),
            ),
        )
    if status in {WorkflowLifecycleStatus.BLOCKED, WorkflowLifecycleStatus.STOPPED}:
        return (
            WorkflowDiagnostic(
                code="workflow_blocked",
                severity=WorkflowDiagnosticSeverity.BLOCKING,
                outcome=WorkflowOutcome.BLOCKED,
                message=_coerce_optional_string(metadata.get("error")) or "Workflow execution blocked.",
                details=dict(metadata),
            ),
        )
    if status == WorkflowLifecycleStatus.INTERRUPTED:
        return (
            WorkflowDiagnostic(
                code="workflow_interrupted",
                severity=WorkflowDiagnosticSeverity.BLOCKING,
                outcome=WorkflowOutcome.INTERRUPTED,
                message=(
                    _coerce_optional_string(metadata.get("abort_reason"))
                    or _coerce_optional_string(metadata.get("error"))
                    or "Workflow execution interrupted."
                ),
                details=dict(metadata),
            ),
        )
    return (
        WorkflowDiagnostic(
            code=_coerce_optional_string(metadata.get("failure_class")) or "workflow_failed",
            severity=WorkflowDiagnosticSeverity.BLOCKING,
            outcome=WorkflowOutcome.FAILED,
            message=_coerce_optional_string(metadata.get("error")) or "Workflow execution failed.",
            details=dict(metadata),
        ),
    )


def _diagnostics_for_report_status(
    *,
    status: WorkflowLifecycleStatus,
) -> tuple[WorkflowDiagnostic, ...]:
    if status == WorkflowLifecycleStatus.COMPLETED:
        return ()
    if status == WorkflowLifecycleStatus.INTERRUPTED:
        return (
            WorkflowDiagnostic(
                code="workflow_interrupted",
                severity=WorkflowDiagnosticSeverity.BLOCKING,
                outcome=WorkflowOutcome.INTERRUPTED,
                message="Workflow execution interrupted.",
            ),
        )
    if status in {WorkflowLifecycleStatus.BLOCKED, WorkflowLifecycleStatus.STOPPED}:
        return (
            WorkflowDiagnostic(
                code="workflow_blocked",
                severity=WorkflowDiagnosticSeverity.BLOCKING,
                outcome=WorkflowOutcome.BLOCKED,
                message="Workflow execution blocked.",
            ),
        )
    return (
        WorkflowDiagnostic(
            code="workflow_failed",
            severity=WorkflowDiagnosticSeverity.BLOCKING,
            outcome=WorkflowOutcome.FAILED,
            message="Workflow execution failed.",
        ),
    )


def _outcome_for_child_status(status: WorkflowLifecycleStatus) -> WorkflowOutcome:
    if status == WorkflowLifecycleStatus.RUNNING:
        return WorkflowOutcome.RUNNING
    if status == WorkflowLifecycleStatus.COMPLETED:
        return WorkflowOutcome.SUCCEEDED
    if status == WorkflowLifecycleStatus.MAX_TURNS:
        return WorkflowOutcome.DEGRADED
    if status in {WorkflowLifecycleStatus.DENIED, WorkflowLifecycleStatus.BLOCKED, WorkflowLifecycleStatus.STOPPED}:
        return WorkflowOutcome.BLOCKED
    if status == WorkflowLifecycleStatus.INTERRUPTED:
        return WorkflowOutcome.INTERRUPTED
    return WorkflowOutcome.FAILED


def _outcome_for_report_status(status: WorkflowLifecycleStatus) -> WorkflowOutcome:
    if status == WorkflowLifecycleStatus.COMPLETED:
        return WorkflowOutcome.SUCCEEDED
    if status in {WorkflowLifecycleStatus.BLOCKED, WorkflowLifecycleStatus.STOPPED}:
        return WorkflowOutcome.BLOCKED
    if status == WorkflowLifecycleStatus.INTERRUPTED:
        return WorkflowOutcome.INTERRUPTED
    return WorkflowOutcome.FAILED


def _status_from_final_status(value: str | None) -> WorkflowLifecycleStatus | None:
    if value is None:
        return None
    mapping = {
        "completed": WorkflowLifecycleStatus.COMPLETED,
        "failed": WorkflowLifecycleStatus.FAILED,
        "interrupted": WorkflowLifecycleStatus.INTERRUPTED,
        "stopped": WorkflowLifecycleStatus.STOPPED,
        "blocked": WorkflowLifecycleStatus.BLOCKED,
    }
    return mapping.get(value)


def _query_source_from_runtime_context(
    *,
    event: Any | None = None,
    runtime_context: Mapping[str, Any] | None = None,
) -> str | None:
    request = getattr(event, "request", None)
    request_query_source = _coerce_optional_string(getattr(request, "query_source", None))
    if request_query_source is not None:
        return request_query_source
    if not isinstance(runtime_context, Mapping):
        return None
    return _coerce_optional_string(runtime_context.get("query_source"))


def _host_extension_event_type(observation: WorkflowObservationEvent) -> str:
    if observation.source_event_type == "request_start":
        return "workflow.started"
    if observation.source_event_type == "terminal":
        return "workflow.terminal"
    if observation.source_event_type == "child_run":
        return "workflow.child.updated"
    return "workflow.updated"


def _workflow_observability_from_projection_mapping(payload: Mapping[str, Any]) -> WorkflowRunObservability | None:
    run_id = _coerce_optional_string(payload.get("run_id"))
    session_id = _coerce_optional_string(payload.get("session_id"))
    status = _coerce_workflow_lifecycle_status(payload.get("status"))
    if run_id is None or session_id is None or status is None:
        return None
    metadata = _coerce_mapping(payload.get("terminal_metadata"))
    return WorkflowRunObservability(
        run_kind=WorkflowRunKind.CHILD,
        identity=WorkflowRunIdentity(
            run_id=run_id,
            session_id=session_id,
            turn_id=_coerce_optional_string(payload.get("turn_id")),
        ),
        lifecycle_status=status,
        outcome=_outcome_for_child_status(status),
        linkage=WorkflowRunLinkage(
            parent_run_id=_coerce_optional_string(payload.get("parent_run_id")),
            parent_turn_id=_coerce_optional_string(payload.get("parent_turn_id")),
        ),
        diagnostics=tuple(_diagnostics_for_child_status(status=status, metadata=metadata)),
        query_source=_coerce_optional_string(payload.get("query_source")),
        requested_model_route=_coerce_optional_string(payload.get("requested_model_route")),
        resolved_model_route=_coerce_optional_string(payload.get("resolved_model_route")),
        provider_name=_coerce_optional_string(payload.get("provider_name")),
        metadata=metadata,
    )


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): inner for key, inner in value.items()}
    return {}


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_workflow_run_kind(value: Any) -> WorkflowRunKind | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    try:
        return WorkflowRunKind(normalized)
    except ValueError:
        return None


def _coerce_workflow_lifecycle_status(value: Any) -> WorkflowLifecycleStatus | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    alias_map = {
        "completed": WorkflowLifecycleStatus.COMPLETED,
        "running": WorkflowLifecycleStatus.RUNNING,
        "failed": WorkflowLifecycleStatus.FAILED,
        "blocked": WorkflowLifecycleStatus.BLOCKED,
        "interrupted": WorkflowLifecycleStatus.INTERRUPTED,
        "max_turns": WorkflowLifecycleStatus.MAX_TURNS,
        "denied": WorkflowLifecycleStatus.DENIED,
        "stopped": WorkflowLifecycleStatus.STOPPED,
    }
    return alias_map.get(normalized)


def _coerce_workflow_outcome(value: Any) -> WorkflowOutcome | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    alias_map = {
        "running": WorkflowOutcome.RUNNING,
        "succeeded": WorkflowOutcome.SUCCEEDED,
        "success": WorkflowOutcome.SUCCEEDED,
        "degraded": WorkflowOutcome.DEGRADED,
        "blocked": WorkflowOutcome.BLOCKED,
        "interrupted": WorkflowOutcome.INTERRUPTED,
        "failed": WorkflowOutcome.FAILED,
    }
    return alias_map.get(normalized)


def _coerce_workflow_diagnostic_severity(value: Any) -> WorkflowDiagnosticSeverity | None:
    normalized = _coerce_optional_string(value)
    if normalized is None:
        return None
    alias_map = {
        "info": WorkflowDiagnosticSeverity.INFO,
        "advisory": WorkflowDiagnosticSeverity.ADVISORY,
        "warning": WorkflowDiagnosticSeverity.ADVISORY,
        "blocking": WorkflowDiagnosticSeverity.BLOCKING,
        "error": WorkflowDiagnosticSeverity.BLOCKING,
    }
    return alias_map.get(normalized)


def _looks_like_child_run_record(value: Any) -> bool:
    return all(hasattr(value, attribute) for attribute in ("run_id", "session_id", "status", "agent_name"))


def _looks_like_agent_run_result(value: Any) -> bool:
    return all(hasattr(value, attribute) for attribute in ("run_id", "status", "execution_spec", "agent_name"))


def _looks_like_report(value: Any) -> bool:
    return hasattr(value, "session_id") and (
        hasattr(value, "terminal") or hasattr(value, "terminal_stop_reason") or hasattr(value, "final_status")
    )


__all__ = [
    "WORKFLOW_EXTENSION_EVENT_NAMESPACE",
    "WORKFLOW_EXTENSION_EVENT_SCHEMA_VERSION",
    "WorkflowDiagnostic",
    "WorkflowDiagnosticSeverity",
    "WorkflowLifecycleStatus",
    "WorkflowObservationEvent",
    "WorkflowObservationSurface",
    "WorkflowOutcome",
    "WorkflowRunIdentity",
    "WorkflowRunKind",
    "WorkflowRunLinkage",
    "WorkflowRunObservability",
    "resolve_workflow_run_observability",
    "serialize_workflow_run_observability",
    "workflow_host_extension_event_from_turn_event",
    "workflow_observation_from_turn_event",
    "workflow_run_observability_from_agent_result",
    "workflow_run_observability_from_child_run",
    "workflow_run_observability_from_mapping",
    "workflow_run_observability_from_report",
]
