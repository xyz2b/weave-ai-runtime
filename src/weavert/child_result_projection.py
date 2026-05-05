from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .agent_execution import AgentRunRecord
from .contracts import MessageRole, RuntimeMessage, serialize_content_blocks
from .definitions import IsolationMode
from .execution_policy import DelegationPolicy, resolve_delegation_policy
from .workflow_observability import (
    serialize_workflow_run_observability,
    workflow_run_observability_from_agent_result,
    workflow_run_observability_from_child_run,
)


def project_agent_run_result(
    result: Any,
    *,
    runtime_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = resolve_delegation_policy(runtime_metadata)
    run_record = getattr(result, "run_record", None)
    messages = tuple(getattr(result, "messages", ()) or ())
    if isinstance(run_record, AgentRunRecord):
        messages = tuple(run_record.messages or messages)
    projection = _base_projection_from_result(
        result,
        run_record,
        policy=policy,
        messages=messages,
        request_metadata=_projection_request_metadata(result, run_record),
    )
    workflow_observability = workflow_run_observability_from_agent_result(result)
    if workflow_observability is not None:
        projection["workflow_observability"] = serialize_workflow_run_observability(workflow_observability)
    if policy.include_child_messages:
        projection["messages"] = [_serialize_message(message) for message in messages]
    return projection


def project_child_run_record(
    record: AgentRunRecord,
    *,
    runtime_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = resolve_delegation_policy(runtime_metadata)
    projection: dict[str, Any] = {
        "agent": record.agent_name,
        "agent_name": record.agent_name,
        "session_id": record.session_id,
        "status": record.status.value,
        "background": record.background if hasattr(record, "background") else record.spawn_mode.value == "background",
        "run_id": record.run_id,
        "parent_run_id": record.parent_run_id,
        "turn_id": record.turn_id,
        "parent_turn_id": record.parent_turn_id,
        "query_source": record.query_source,
        "spawn_mode": record.spawn_mode.value,
        "delegation_depth": record.delegation_depth,
        "scope_summary": _scope_summary_from_request_metadata(record.request_metadata),
        "summary": summarize_child_run_record(record, policy=policy),
        "terminal_metadata": dict(record.terminal_metadata),
        "requested_model": record.requested_model,
        "requested_effort": record.requested_effort,
        "requested_model_route": record.requested_model_route,
        "resolved_model_route": record.resolved_model_route,
        "provider_name": record.provider_name,
        "invocation_mode": record.invocation_mode,
    }
    projection["workflow_observability"] = serialize_workflow_run_observability(
        workflow_run_observability_from_child_run(record)
    )
    if policy.include_child_messages:
        projection["messages"] = [_serialize_message(message) for message in record.messages]
    return projection


def summarize_child_run_record(
    record: AgentRunRecord,
    *,
    policy: DelegationPolicy | None = None,
) -> str:
    resolved_policy = policy or DelegationPolicy()
    if record.status.value != "completed":
        return _fallback_summary(
            agent_name=record.agent_name,
            status=record.status.value,
            terminal_metadata=record.terminal_metadata,
            max_chars=resolved_policy.summary_max_chars,
        )
    for message in reversed(record.messages):
        if message.role != MessageRole.ASSISTANT:
            continue
        summary = _normalize_summary_text(message.text, max_chars=resolved_policy.summary_max_chars)
        if summary:
            return summary
    return _fallback_summary(
        agent_name=record.agent_name,
        status=record.status.value,
        terminal_metadata=record.terminal_metadata,
        max_chars=resolved_policy.summary_max_chars,
    )


def _base_projection_from_result(
    result: Any,
    run_record: AgentRunRecord | None,
    *,
    policy: DelegationPolicy,
    messages: Sequence[RuntimeMessage],
    request_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    execution_spec = getattr(result, "execution_spec", None)
    isolation_mode = getattr(result, "isolation_mode", None)
    if isinstance(isolation_mode, IsolationMode):
        serialized_isolation = isolation_mode.value
    else:
        serialized_isolation = isolation_mode
    terminal_metadata = dict(run_record.terminal_metadata) if run_record is not None else {}
    summary = (
        summarize_child_run_record(run_record, policy=policy)
        if run_record is not None
        else _fallback_summary(
            agent_name=str(getattr(result, "agent_name", "child")),
            status=str(getattr(result, "status", "unknown")),
            terminal_metadata=terminal_metadata,
            max_chars=policy.summary_max_chars,
        )
    )
    return {
        "agent": getattr(result, "agent_name", None),
        "session_id": getattr(execution_spec, "session_id", None),
        "status": getattr(result, "status", None),
        "background": bool(getattr(result, "background", False)),
        "run_id": getattr(result, "run_id", None),
        "parent_run_id": getattr(result, "parent_run_id", None),
        "turn_id": getattr(result, "turn_id", None),
        "parent_turn_id": execution_spec.parent_turn_id if execution_spec is not None else None,
        "query_source": getattr(result, "query_source", None),
        "spawn_mode": (
            execution_spec.spawn_mode.value if execution_spec is not None else None
        ),
        "scope_summary": _scope_summary_from_request_metadata(request_metadata),
        "summary": summary,
        "terminal_metadata": terminal_metadata,
        "task_id": getattr(result, "task_id", None),
        "requested_model": (
            execution_spec.requested_model if execution_spec is not None else None
        ),
        "requested_effort": (
            execution_spec.requested_effort if execution_spec is not None else None
        ),
        "requested_model_route": (
            execution_spec.requested_model_route if execution_spec is not None else None
        ),
        "resolved_model_route": run_record.resolved_model_route if run_record is not None else None,
        "isolation_mode": serialized_isolation,
        "notification": (
            _serialize_message(getattr(result, "notification"))
            if getattr(result, "notification", None) is not None
            else None
        ),
        "delegation_depth": (
            run_record.delegation_depth
            if run_record is not None
            else (execution_spec.delegation_depth if execution_spec is not None else 0)
        ),
    }


def _fallback_summary(
    *,
    agent_name: str,
    status: str,
    terminal_metadata: Mapping[str, Any],
    max_chars: int,
) -> str:
    error = terminal_metadata.get("error") or terminal_metadata.get("abort_reason")
    if status == "running":
        text = f"Child run '{agent_name}' is running."
    elif error:
        text = f"Child run '{agent_name}' ended with status '{status}': {error}"
    elif status == "completed":
        text = f"Child run '{agent_name}' completed without a textual assistant summary."
    else:
        text = f"Child run '{agent_name}' ended with status '{status}'."
    return _normalize_summary_text(text, max_chars=max_chars) or text[:max_chars]


def _normalize_summary_text(text: str, *, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 3:
        return normalized[:max_chars]
    return f"{normalized[: max_chars - 3].rstrip()}..."


def _serialize_message(message: RuntimeMessage) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "role": message.role.value,
        "content": serialize_content_blocks(message.content),
        "metadata": dict(message.metadata),
    }


def _projection_request_metadata(
    result: Any,
    run_record: AgentRunRecord | None,
) -> Mapping[str, Any] | None:
    if run_record is not None and isinstance(run_record.request_metadata, Mapping):
        return run_record.request_metadata
    execution_spec = getattr(result, "execution_spec", None)
    metadata = getattr(execution_spec, "metadata", None)
    if isinstance(metadata, Mapping):
        return metadata
    return None


def _scope_summary_from_request_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(metadata, Mapping):
        return None
    policy = metadata.get("policy")
    if not isinstance(policy, Mapping):
        return None
    effective = policy.get("effective")
    if not isinstance(effective, Mapping):
        return None
    trace = effective.get("trace") if isinstance(effective.get("trace"), Mapping) else {}
    visible_tools = _coerce_string_list(effective.get("tools"), fallback=trace.get("effective_tools"))
    visible_skills = _coerce_string_list(effective.get("skills"), fallback=trace.get("effective_skills"))
    permission_mode = _coerce_optional_string(effective.get("permission_mode")) or _coerce_optional_string(
        trace.get("effective_permission_mode")
    )
    isolation_mode = _coerce_optional_string(effective.get("isolation_mode")) or _coerce_optional_string(
        trace.get("effective_isolation_mode")
    )
    if not visible_tools and not visible_skills and permission_mode is None and isolation_mode is None:
        return None
    return {
        "visible_tools": visible_tools,
        "visible_skills": visible_skills,
        "permission_mode": permission_mode,
        "isolation_mode": isolation_mode,
    }


def _coerce_string_list(
    value: Any,
    *,
    fallback: Any = None,
) -> list[str]:
    candidate = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else fallback
    if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes, bytearray)):
        return []
    resolved: list[str] = []
    for item in candidate:
        normalized = _coerce_optional_string(item)
        if normalized is not None:
            resolved.append(normalized)
    return resolved


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
