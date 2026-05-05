from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from .agent_execution import AgentRunRecord
from .child_result_projection import (
    project_agent_run_result,
    project_child_run_record,
)
from .contracts import MessageRole, RuntimeMessage, ToolResultBlock, ToolUseBlock
from .workflow_observability import (
    WorkflowRunObservability,
    resolve_workflow_run_observability,
    workflow_run_observability_from_mapping,
)

_SUCCESS_STOP_REASONS = {"", "completed", "end_turn", "message_stop"}


@dataclass(frozen=True, slots=True)
class ToolOutcomeProjection:
    tool_name: str
    tool_use_id: str
    tool_input: Mapping[str, Any] = field(default_factory=dict)
    output: Any = None
    status: str | None = None
    is_error: bool = False
    message_id: str | None = None
    message_index: int | None = None
    block_index: int | None = None
    created_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    result_summary: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_input", dict(self.tool_input))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "result_summary", _copy_mapping(self.result_summary))


@dataclass(frozen=True, slots=True)
class ChildScopeSummaryProjection:
    visible_tools: tuple[str, ...] = ()
    visible_skills: tuple[str, ...] = ()
    permission_mode: str | None = None
    isolation_mode: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "visible_tools", _coerce_string_tuple(self.visible_tools))
        object.__setattr__(self, "visible_skills", _coerce_string_tuple(self.visible_skills))


@dataclass(frozen=True, slots=True)
class ChildSummaryProjection:
    agent_name: str = ""
    summary: str = ""
    status: str | None = None
    run_id: str | None = None
    parent_run_id: str | None = None
    turn_id: str | None = None
    parent_turn_id: str | None = None
    spawn_mode: str | None = None
    background: bool = False
    query_source: str | None = None
    delegation_depth: int | None = None
    terminal_metadata: Mapping[str, Any] = field(default_factory=dict)
    requested_model: str | None = None
    requested_effort: Any = None
    requested_model_route: str | None = None
    resolved_model_route: str | None = None
    provider_name: str | None = None
    invocation_mode: Any = None
    scope_summary: ChildScopeSummaryProjection | None = None
    workflow_observability: WorkflowRunObservability | None = None
    source_kind: str = "parent_result"
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "terminal_metadata", dict(self.terminal_metadata))
        object.__setattr__(self, "payload", dict(self.payload))

    @property
    def agent(self) -> str:
        return self.agent_name


@dataclass(frozen=True, slots=True)
class SkillOutcomeProjection:
    skill_name: str
    tool_use_id: str
    tool_input: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    mode: str | None = None
    status: str | None = None
    message_id: str | None = None
    message_index: int | None = None
    block_index: int | None = None
    created_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    agent_summary: ChildSummaryProjection | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_input", dict(self.tool_input))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def output(self) -> Mapping[str, Any]:
        return self.payload


@dataclass(frozen=True, slots=True)
class TerminalFailureProjection:
    stop_reason: str | None = None
    error: str | None = None
    abort_reason: str | None = None
    failure_class: str | None = None
    request_id: str | None = None
    provider_stop_reason: str | None = None
    workflow_observability: WorkflowRunObservability | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class _ProjectionSource:
    messages: tuple[RuntimeMessage, ...] = ()
    terminal: Any = None
    child_runs: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class _TerminalSnapshot:
    stop_reason: str | None = None
    error: str | None = None
    abort_reason: str | None = None
    request_id: str | None = None
    provider_stop_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))


ToolOutcomeMatcher = Callable[[ToolOutcomeProjection], bool]
SkillOutcomeMatcher = Callable[[SkillOutcomeProjection], bool]
ChildSummaryMatcher = Callable[[ChildSummaryProjection], bool]


def latest_tool_outcome(
    source: Any,
    tool_name: str,
    *,
    matcher: ToolOutcomeMatcher | None = None,
) -> ToolOutcomeProjection | None:
    resolved = _resolve_projection_source(source)
    latest_match: ToolOutcomeProjection | None = None
    for projection in _iter_tool_outcomes(resolved.messages):
        if projection.tool_name != tool_name:
            continue
        if matcher is not None and not matcher(projection):
            continue
        latest_match = projection
    return latest_match


def latest_skill_outcome(
    source: Any,
    skill_name: str | None = None,
    *,
    matcher: SkillOutcomeMatcher | None = None,
) -> SkillOutcomeProjection | None:
    resolved = _resolve_projection_source(source)
    latest_match: SkillOutcomeProjection | None = None
    for tool_projection in _iter_tool_outcomes(resolved.messages):
        if tool_projection.tool_name != "skill" or not isinstance(tool_projection.output, Mapping):
            continue
        payload = dict(tool_projection.output)
        resolved_skill_name = _coerce_optional_string(payload.get("skill")) or _coerce_optional_string(
            tool_projection.tool_input.get("skill")
        )
        if resolved_skill_name is None:
            continue
        projection = SkillOutcomeProjection(
            skill_name=resolved_skill_name,
            tool_use_id=tool_projection.tool_use_id,
            tool_input=tool_projection.tool_input,
            payload=payload,
            mode=_coerce_optional_string(payload.get("mode")),
            status=tool_projection.status,
            message_id=tool_projection.message_id,
            message_index=tool_projection.message_index,
            block_index=tool_projection.block_index,
            created_at=tool_projection.created_at,
            metadata=tool_projection.metadata,
            agent_summary=_child_summary_from_value(
                payload.get("agent_result"),
                source_kind="skill_agent_result",
            ),
        )
        if skill_name is not None and projection.skill_name != skill_name:
            continue
        if matcher is not None and not matcher(projection):
            continue
        latest_match = projection
    return latest_match


def final_assistant_text(source: Any) -> str:
    resolved = _resolve_projection_source(source)
    for message in reversed(resolved.messages):
        if message.role == MessageRole.ASSISTANT and message.text:
            return message.text
    return ""


def terminal_failure(
    source: Any,
    *,
    terminal: Any | None = None,
) -> TerminalFailureProjection | None:
    resolved = _resolve_projection_source(source, terminal=terminal)
    normalized = _normalize_terminal(resolved.terminal)
    if normalized is None:
        return None
    metadata = dict(normalized.metadata)
    stop_reason = _coerce_optional_string(normalized.stop_reason)
    error = _coerce_optional_string(normalized.error) or _coerce_optional_string(metadata.get("error"))
    abort_reason = _coerce_optional_string(normalized.abort_reason) or _coerce_optional_string(
        metadata.get("abort_reason")
    )
    failure_class = _coerce_optional_string(metadata.get("failure_class"))
    if not _is_terminal_failure(
        stop_reason=stop_reason,
        error=error,
        abort_reason=abort_reason,
        failure_class=failure_class,
    ):
        return None
    return TerminalFailureProjection(
        stop_reason=stop_reason,
        error=error,
        abort_reason=abort_reason,
        failure_class=failure_class,
        request_id=_coerce_optional_string(normalized.request_id),
        provider_stop_reason=_coerce_optional_string(normalized.provider_stop_reason),
        workflow_observability=resolve_workflow_run_observability(source),
        metadata=metadata,
    )


def child_summary(
    source: Any,
    *,
    agent_name: str | None = None,
    matcher: ChildSummaryMatcher | None = None,
    child_runs: Sequence[Any] | None = None,
) -> ChildSummaryProjection | None:
    resolved = _resolve_projection_source(
        source,
        child_runs=child_runs,
        allow_child_runs=True,
    )
    latest_match: ChildSummaryProjection | None = None
    for projection in _iter_child_summaries_from_messages(resolved.messages):
        if agent_name is not None and projection.agent_name != agent_name:
            continue
        if matcher is not None and not matcher(projection):
            continue
        latest_match = projection
    if latest_match is not None:
        return latest_match
    for value in resolved.child_runs:
        projection = _child_summary_from_value(value, source_kind="child_run")
        if projection is None:
            continue
        if agent_name is not None and projection.agent_name != agent_name:
            continue
        if matcher is not None and not matcher(projection):
            continue
        latest_match = projection
    return latest_match


def _resolve_projection_source(
    source: Any,
    *,
    terminal: Any | None = None,
    child_runs: Sequence[Any] | None = None,
    allow_child_runs: bool = False,
) -> _ProjectionSource:
    resolved_terminal = terminal
    resolved_child_runs = tuple(child_runs or ())

    if _is_message_sequence(source):
        messages = tuple(source)
    else:
        raw_messages = getattr(source, "messages", ())
        messages = tuple(raw_messages or ()) if _is_message_sequence(raw_messages) else ()
        if resolved_terminal is None:
            candidate_terminal = getattr(source, "terminal", None)
            if candidate_terminal is not None:
                resolved_terminal = candidate_terminal
            else:
                resolved_terminal = _terminal_snapshot_from_report_like(source)
        if allow_child_runs and not resolved_child_runs:
            resolved_child_runs = _child_runs_from_report_like(source)

    if allow_child_runs and not resolved_child_runs:
        if _is_child_run_sequence(source):
            resolved_child_runs = tuple(source)
        else:
            single_child = _coerce_child_summary_source(source)
            if single_child is not None:
                resolved_child_runs = (single_child,)

    return _ProjectionSource(
        messages=messages,
        terminal=resolved_terminal,
        child_runs=resolved_child_runs,
    )


def _iter_tool_outcomes(messages: Sequence[RuntimeMessage]) -> Sequence[ToolOutcomeProjection]:
    projections: list[ToolOutcomeProjection] = []
    tool_uses: dict[str, ToolUseBlock] = {}
    for message_index, message in enumerate(messages):
        metadata_entries = message.metadata.get("tool_results", ())
        metadata_by_tool_use = {
            str(entry.get("tool_use_id") or ""): dict(entry)
            for entry in metadata_entries
            if isinstance(entry, Mapping)
        }
        for block_index, block in enumerate(message.content):
            if isinstance(block, ToolUseBlock):
                tool_uses[block.tool_use_id] = block
                continue
            if not isinstance(block, ToolResultBlock):
                continue
            tool_use = tool_uses.get(block.tool_use_id)
            metadata = metadata_by_tool_use.get(block.tool_use_id, {})
            tool_name = _coerce_optional_string(metadata.get("tool_name"))
            if tool_name is None and tool_use is not None:
                tool_name = _coerce_optional_string(tool_use.name)
            if tool_name is None and isinstance(block.content, Mapping) and "skill" in block.content:
                tool_name = "skill"
            if tool_name is None:
                continue
            result_summary = metadata.get("result_summary")
            projections.append(
                ToolOutcomeProjection(
                    tool_name=tool_name,
                    tool_use_id=block.tool_use_id,
                    tool_input=tool_use.input if tool_use is not None else {},
                    output=block.content,
                    status=_coerce_optional_string(metadata.get("status")),
                    is_error=block.is_error,
                    message_id=message.message_id,
                    message_index=message_index,
                    block_index=block_index,
                    created_at=message.created_at,
                    metadata=metadata,
                    result_summary=result_summary if isinstance(result_summary, Mapping) else None,
                )
            )
    return tuple(projections)


def _iter_child_summaries_from_messages(
    messages: Sequence[RuntimeMessage],
) -> Sequence[ChildSummaryProjection]:
    projections: list[ChildSummaryProjection] = []
    for tool_projection in _iter_tool_outcomes(messages):
        if tool_projection.tool_name == "agent":
            projection = _child_summary_from_value(tool_projection.output, source_kind="agent_result")
            if projection is not None:
                projections.append(projection)
            continue
        if tool_projection.tool_name != "skill" or not isinstance(tool_projection.output, Mapping):
            continue
        projection = _child_summary_from_value(
            tool_projection.output.get("agent_result"),
            source_kind="skill_agent_result",
        )
        if projection is not None:
            projections.append(projection)
    return tuple(projections)


def _terminal_snapshot_from_report_like(source: Any) -> _TerminalSnapshot | None:
    stop_reason = _coerce_optional_string(getattr(source, "terminal_stop_reason", None))
    metadata = _coerce_mapping(getattr(source, "terminal_metadata", None))
    error = _coerce_optional_string(metadata.get("error")) or _coerce_optional_string(
        getattr(source, "error_message", None)
    )
    abort_reason = _coerce_optional_string(metadata.get("abort_reason"))
    request_id = _coerce_optional_string(metadata.get("request_id"))
    provider_stop_reason = _coerce_optional_string(metadata.get("provider_stop_reason"))
    if stop_reason is None and not metadata and error is None and abort_reason is None:
        return None
    return _TerminalSnapshot(
        stop_reason=stop_reason,
        error=error,
        abort_reason=abort_reason,
        request_id=request_id,
        provider_stop_reason=provider_stop_reason,
        metadata=metadata,
    )


def _normalize_terminal(value: Any) -> _TerminalSnapshot | None:
    if value is None:
        return None
    if isinstance(value, _TerminalSnapshot):
        return value
    stop_reason = _coerce_optional_string(getattr(value, "stop_reason", None))
    error = _coerce_optional_string(getattr(value, "error", None))
    abort_reason = _coerce_optional_string(getattr(value, "abort_reason", None))
    request_id = _coerce_optional_string(getattr(value, "request_id", None))
    provider_stop_reason = _coerce_optional_string(getattr(value, "provider_stop_reason", None))
    metadata = _coerce_mapping(getattr(value, "metadata", None))
    if stop_reason is None and not metadata and error is None and abort_reason is None:
        return None
    return _TerminalSnapshot(
        stop_reason=stop_reason,
        error=error,
        abort_reason=abort_reason,
        request_id=request_id,
        provider_stop_reason=provider_stop_reason,
        metadata=metadata,
    )


def _is_terminal_failure(
    *,
    stop_reason: str | None,
    error: str | None,
    abort_reason: str | None,
    failure_class: str | None,
) -> bool:
    if failure_class is not None and failure_class != "none":
        return True
    if error is not None or abort_reason is not None:
        return True
    if stop_reason is None:
        return False
    return stop_reason not in _SUCCESS_STOP_REASONS


def _child_runs_from_report_like(source: Any) -> tuple[Any, ...]:
    for attribute in ("child_runs", "child_run_records"):
        value = getattr(source, attribute, None)
        if _is_child_run_sequence(value):
            return tuple(value)
    return ()


def _child_summary_from_value(
    value: Any,
    *,
    source_kind: str,
) -> ChildSummaryProjection | None:
    if value is None:
        return None
    if isinstance(value, ChildSummaryProjection):
        return value
    if isinstance(value, AgentRunRecord):
        payload = project_child_run_record(value)
        return _child_summary_from_mapping(payload, source_kind="child_run_record")
    if isinstance(value, Mapping):
        return _child_summary_from_mapping(value, source_kind=source_kind)
    if _looks_like_agent_run_result(value):
        payload = project_agent_run_result(value)
        return _child_summary_from_mapping(payload, source_kind=source_kind)
    return None


def _child_summary_from_mapping(
    payload: Mapping[str, Any],
    *,
    source_kind: str,
) -> ChildSummaryProjection | None:
    copied = dict(payload)
    agent_name = _coerce_optional_string(copied.get("agent_name")) or _coerce_optional_string(
        copied.get("agent")
    ) or ""
    status = _coerce_optional_string(copied.get("status"))
    terminal_metadata = _coerce_mapping(copied.get("terminal_metadata"))
    summary = _coerce_optional_string(copied.get("summary")) or _fallback_child_summary(
        agent_name=agent_name,
        status=status,
        terminal_metadata=terminal_metadata,
    )
    if not agent_name and summary is None and status is None:
        return None
    delegation_depth = copied.get("delegation_depth")
    workflow_observability = workflow_run_observability_from_mapping(copied.get("workflow_observability"))
    scope_summary = _scope_summary_from_mapping(copied.get("scope_summary"))
    return ChildSummaryProjection(
        agent_name=agent_name,
        summary=summary or "",
        status=status,
        run_id=_coerce_optional_string(copied.get("run_id")),
        parent_run_id=_coerce_optional_string(copied.get("parent_run_id")),
        turn_id=_coerce_optional_string(copied.get("turn_id")),
        parent_turn_id=_coerce_optional_string(copied.get("parent_turn_id")),
        spawn_mode=_coerce_optional_string(copied.get("spawn_mode")),
        background=bool(copied.get("background", False)),
        query_source=_coerce_optional_string(copied.get("query_source")),
        delegation_depth=delegation_depth if isinstance(delegation_depth, int) else None,
        terminal_metadata=terminal_metadata,
        requested_model=_coerce_optional_string(copied.get("requested_model")),
        requested_effort=copied.get("requested_effort"),
        requested_model_route=_coerce_optional_string(copied.get("requested_model_route")),
        resolved_model_route=_coerce_optional_string(copied.get("resolved_model_route")),
        provider_name=_coerce_optional_string(copied.get("provider_name")),
        invocation_mode=copied.get("invocation_mode"),
        scope_summary=scope_summary,
        workflow_observability=workflow_observability,
        source_kind=source_kind,
        payload=copied,
    )


def _scope_summary_from_mapping(
    payload: Any,
) -> ChildScopeSummaryProjection | None:
    if not isinstance(payload, Mapping):
        return None
    visible_tools = _coerce_string_tuple(payload.get("visible_tools"))
    visible_skills = _coerce_string_tuple(payload.get("visible_skills"))
    permission_mode = _coerce_optional_string(payload.get("permission_mode"))
    isolation_mode = _coerce_optional_string(payload.get("isolation_mode"))
    if not visible_tools and not visible_skills and permission_mode is None and isolation_mode is None:
        return None
    return ChildScopeSummaryProjection(
        visible_tools=visible_tools,
        visible_skills=visible_skills,
        permission_mode=permission_mode,
        isolation_mode=isolation_mode,
    )


def _fallback_child_summary(
    *,
    agent_name: str,
    status: str | None,
    terminal_metadata: Mapping[str, Any],
) -> str | None:
    if status is None and not agent_name:
        return None
    error = _coerce_optional_string(terminal_metadata.get("error")) or _coerce_optional_string(
        terminal_metadata.get("abort_reason")
    )
    label = agent_name or "child"
    if status == "running":
        return f"Child run '{label}' is running."
    if error is not None and status is not None:
        return f"Child run '{label}' ended with status '{status}': {error}"
    if status == "completed":
        return f"Child run '{label}' completed without a textual assistant summary."
    if status is not None:
        return f"Child run '{label}' ended with status '{status}'."
    return None


def _coerce_child_summary_source(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, (ChildSummaryProjection, AgentRunRecord)):
        return value
    if isinstance(value, Mapping):
        if any(key in value for key in ("agent", "agent_name", "summary", "run_id", "status")):
            return value
        return None
    if _looks_like_agent_run_result(value):
        return value
    return None


def _looks_like_agent_run_result(value: Any) -> bool:
    return hasattr(value, "agent_name") and hasattr(value, "status") and hasattr(value, "messages")


def _is_message_sequence(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return False
    return all(isinstance(item, RuntimeMessage) for item in value)


def _is_child_run_sequence(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return False
    return all(_coerce_child_summary_source(item) is not None for item in value)


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return dict(value)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): inner for key, inner in value.items()}
    return {}


def _coerce_string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    resolved: list[str] = []
    for item in value:
        normalized = _coerce_optional_string(item)
        if normalized is not None:
            resolved.append(normalized)
    return tuple(resolved)


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "ChildScopeSummaryProjection",
    "ChildSummaryProjection",
    "SkillOutcomeProjection",
    "TerminalFailureProjection",
    "ToolOutcomeProjection",
    "child_summary",
    "final_assistant_text",
    "latest_skill_outcome",
    "latest_tool_outcome",
    "terminal_failure",
]
