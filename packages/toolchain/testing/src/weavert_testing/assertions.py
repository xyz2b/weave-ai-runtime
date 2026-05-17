from __future__ import annotations

from typing import Any, Mapping, Sequence

from weavert.contracts import RuntimeMessage, ToolResultBlock
from weavert.result_projections import (
    ChildSummaryMatcher,
    ChildSummaryProjection,
    SkillOutcomeMatcher,
    SkillOutcomeProjection,
    ToolOutcomeMatcher,
    ToolOutcomeProjection,
    child_summary,
    latest_skill_outcome,
    latest_tool_outcome,
    terminal_failure,
)



def assert_tool_outcome(
    source: Any,
    tool_name: str,
    *,
    matcher: ToolOutcomeMatcher | None = None,
) -> ToolOutcomeProjection:
    projection = latest_tool_outcome(source, tool_name, matcher=matcher)
    if projection is None:
        detail = " matching the provided predicate" if matcher is not None else ""
        raise AssertionError(f"Expected tool outcome for '{tool_name}'{detail}.")
    return projection



def assert_tool_result(source: Any, tool_use_id: str) -> Any:
    messages = _messages_from_source(source)
    for message in messages:
        for block in message.content:
            if isinstance(block, ToolResultBlock) and block.tool_use_id == tool_use_id:
                return block.content
    raise AssertionError(f"Missing tool result for '{tool_use_id}'.")



def extract_tool_result(source: Any, tool_use_id: str) -> Any:
    return assert_tool_result(source, tool_use_id)



def assert_skill_outcome(
    source: Any,
    skill_name: str | None = None,
    *,
    matcher: SkillOutcomeMatcher | None = None,
) -> SkillOutcomeProjection:
    projection = latest_skill_outcome(source, skill_name=skill_name, matcher=matcher)
    if projection is None:
        expected = f" '{skill_name}'" if skill_name is not None else ""
        detail = " matching the provided predicate" if matcher is not None else ""
        raise AssertionError(f"Expected skill outcome{expected}{detail}.")
    return projection



def assert_child_summary(
    source: Any,
    *,
    agent_name: str | None = None,
    matcher: ChildSummaryMatcher | None = None,
    child_runs: Sequence[Any] | None = None,
) -> ChildSummaryProjection:
    projection = child_summary(
        source,
        agent_name=agent_name,
        matcher=matcher,
        child_runs=child_runs,
    )
    if projection is None:
        expected = f" for agent '{agent_name}'" if agent_name is not None else ""
        detail = " matching the provided predicate" if matcher is not None else ""
        raise AssertionError(f"Expected child-run summary{expected}{detail}.")
    return projection



def assert_no_terminal_failure(source: Any) -> None:
    failure = terminal_failure(source)
    if failure is None:
        return
    detail = failure.error or failure.abort_reason or failure.stop_reason or "unknown failure"
    raise AssertionError(f"Workflow terminated unsuccessfully: {detail}")


def assert_web_research_outcome(
    source: Any,
    *,
    provider_id: str | None = None,
    freshness_status: str | None = None,
    stop_reason: str | None = None,
    min_sources: int | None = None,
) -> dict[str, Any]:
    payload = _web_research_payload(source)
    if provider_id is not None:
        observed = payload.get("provider", {}).get("id")
        if observed != provider_id:
            raise AssertionError(f"Expected web_research provider '{provider_id}', got '{observed}'.")
    if freshness_status is not None:
        observed = payload.get("freshness_scope", {}).get("status")
        if observed != freshness_status:
            raise AssertionError(f"Expected web_research freshness '{freshness_status}', got '{observed}'.")
    if stop_reason is not None and payload.get("stop_reason") != stop_reason:
        raise AssertionError(f"Expected web_research stop_reason '{stop_reason}', got '{payload.get('stop_reason')}'.")
    if min_sources is not None and len(_list_of_mappings(payload.get("sources"))) < min_sources:
        raise AssertionError(f"Expected at least {min_sources} web_research source(s).")
    return payload


def assert_delegated_web_research_tool_use(source: Any, tool_name: str) -> ToolOutcomeProjection:
    return assert_tool_outcome(source, tool_name)


def assert_web_research_ledger_evidence(source: Any, *, urls: Sequence[str] = ()) -> list[dict[str, Any]]:
    payload = _web_research_payload(source)
    evidence = _list_of_mappings(payload.get("evidence"))
    if not evidence:
        raise AssertionError("Expected ledger-derived web_research evidence.")
    missing = [url for url in urls if not any(item.get("url") == url for item in evidence)]
    if missing:
        raise AssertionError(f"Missing web_research evidence URL(s): {', '.join(missing)}.")
    return evidence


def assert_web_research_source_classes(source: Any, expected: Sequence[str]) -> list[dict[str, Any]]:
    payload = _web_research_payload(source)
    sources = _list_of_mappings(payload.get("sources"))
    observed = [str(item.get("source_class") or "") for item in sources]
    missing = [item for item in expected if item not in observed]
    if missing:
        raise AssertionError(f"Missing web_research source class(es): {', '.join(missing)}.")
    return sources


def assert_web_research_selection_rationale(source: Any, *, contains: Sequence[str] = ()) -> list[dict[str, Any]]:
    payload = _web_research_payload(source)
    traces = _list_of_mappings(payload.get("trace_summary")) + _list_of_mappings(
        payload.get("research_trace", {}).get("trace_summary") if isinstance(payload.get("research_trace"), Mapping) else None
    )
    selected = [event for event in traces if event.get("event") == "page_selected"]
    if not selected:
        raise AssertionError("Expected web_research page selection rationale.")
    flattened = " ".join(" ".join(str(value) for value in _as_sequence(event.get("rationale"))) for event in selected)
    missing = [value for value in contains if value not in flattened]
    if missing:
        raise AssertionError(f"Missing web_research selection rationale signal(s): {', '.join(missing)}.")
    return selected


def assert_web_research_claims_bound(source: Any) -> list[dict[str, Any]]:
    payload = _web_research_payload(source)
    claims = _list_of_mappings(payload.get("claims"))
    if not claims:
        raise AssertionError("Expected ledger-bound web_research claims.")
    unbound = [
        claim
        for claim in claims
        if not (claim.get("source_handle") or claim.get("page_handle") or claim.get("evidence_id"))
    ]
    if unbound:
        raise AssertionError("Expected every web_research claim to reference ledger evidence.")
    return claims


def assert_web_research_conflicts(source: Any, *, resolved: bool | None = None, min_count: int = 1) -> list[dict[str, Any]]:
    payload = _web_research_payload(source)
    conflicts = _list_of_mappings(payload.get("conflicts"))
    if resolved is not None:
        conflicts = [item for item in conflicts if bool(item.get("resolved")) is resolved]
    if len(conflicts) < min_count:
        state = "resolved " if resolved is True else "unresolved " if resolved is False else ""
        raise AssertionError(f"Expected at least {min_count} {state}web_research conflict(s).")
    return conflicts


def assert_web_research_gaps(source: Any, *, kinds: Sequence[str] = ()) -> list[dict[str, Any]]:
    payload = _web_research_payload(source)
    gaps = _list_of_mappings(payload.get("gaps"))
    if not gaps:
        raise AssertionError("Expected web_research gap entries.")
    observed = {str(item.get("kind") or "") for item in gaps}
    missing = [kind for kind in kinds if kind not in observed]
    if missing:
        raise AssertionError(f"Missing web_research gap kind(s): {', '.join(missing)}.")
    return gaps



def _messages_from_source(source: Any) -> tuple[RuntimeMessage, ...]:
    if isinstance(source, tuple) and _is_message_tuple(source):
        return source
    if isinstance(source, list) and _is_message_tuple(tuple(source)):
        return tuple(source)
    messages = getattr(source, "messages", ())
    if _is_message_tuple(tuple(messages)):
        return tuple(messages)
    return ()



def _is_message_tuple(messages: tuple[Any, ...]) -> bool:
    return all(isinstance(message, RuntimeMessage) for message in messages)


def _web_research_payload(source: Any) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    projection = latest_tool_outcome(source, "web_research")
    if projection is not None and isinstance(projection.output, Mapping):
        return dict(projection.output)
    output = getattr(source, "output", None)
    if isinstance(output, Mapping):
        return dict(output)
    raise AssertionError("Expected a web_research result payload or report containing one.")


def _list_of_mappings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _as_sequence(raw: Any) -> tuple[Any, ...]:
    if isinstance(raw, tuple):
        return raw
    if isinstance(raw, list):
        return tuple(raw)
    if raw is None:
        return ()
    return (raw,)


__all__ = [
    "assert_child_summary",
    "assert_delegated_web_research_tool_use",
    "assert_no_terminal_failure",
    "assert_skill_outcome",
    "assert_tool_outcome",
    "assert_tool_result",
    "assert_web_research_ledger_evidence",
    "assert_web_research_claims_bound",
    "assert_web_research_conflicts",
    "assert_web_research_gaps",
    "assert_web_research_outcome",
    "assert_web_research_selection_rationale",
    "assert_web_research_source_classes",
    "extract_tool_result",
]
