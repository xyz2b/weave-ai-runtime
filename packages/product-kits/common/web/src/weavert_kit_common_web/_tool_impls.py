from __future__ import annotations

import asyncio
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from threading import Lock
from typing import Any
from uuid import uuid4

from weavert.definitions import ValidationOutcome
from weavert.tool_runtime import ToolContext
from weavert_kit_common_retrieval._tool_impls import (
    prepare_citations_tool,
    retrieve_context_tool,
    validate_prepare_citations_tool,
    validate_retrieve_context_tool,
)
from weavert_web_research import (
    DuckDuckGoHtmlBackend,
    build_policy,
    find_in_page,
    inspect_page,
    search_web,
    validate_fetch_input,
    validate_page_find_input,
    web_urlopen,
)

_GROUNDING_DEFAULT_SEARCH_LIMIT = 8
_GROUNDING_DEFAULT_FETCH_CHARS = 12_000
_GROUNDING_DEFAULT_FIND_LIMIT = 5
_WEB_RESEARCH_DEFAULT_SEARCH_BUDGET = 4
_WEB_RESEARCH_DEFAULT_FETCH_BUDGET = 4
_WEB_RESEARCH_DEFAULT_FIND_BUDGET = 6
_WEB_RESEARCH_DEFAULT_DESIRED_SOURCES = 3
_WEB_RESEARCH_MAX_TRACE_ITEMS = 8
_WEB_RESEARCH_DEFAULT_MAX_CONCURRENT_FETCHES = 3
_WEB_RESEARCH_RUN_ID_METADATA_KEY = "web_research_run_id"
_WEB_RESEARCH_SOURCE_ANNOTATION_FIELDS = frozenset(
    {
        "citation_label",
        "citation_note",
        "claim",
        "claim_text",
        "confidence",
        "confidence_score",
        "note",
        "notes",
        "rank_hint",
        "ranking_hint",
        "relevance",
        "relevance_score",
        "synthesis",
        "synthesis_note",
        "synthesis_notes",
    }
)
_WEB_RESEARCH_EVIDENCE_ANNOTATION_FIELDS = _WEB_RESEARCH_SOURCE_ANNOTATION_FIELDS | frozenset(
    {
        "supports",
        "supports_claim",
    }
)

_grounding_urlopen = web_urlopen
_web_research_runs: dict[str, "_WebResearchRunState"] = {}


def validate_grounding_web_search(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    if not str(tool_input.get("query") or "").strip():
        return ValidationOutcome(False, "query must be non-empty")
    return ValidationOutcome(True, updated_input=_effective_web_tool_input("search", tool_input, context))


def validate_web_research(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not _web_research_objective(tool_input):
        return ValidationOutcome(False, "objective must be non-empty")
    try:
        normalized = _normalize_web_research_input(tool_input)
    except ValueError as exc:
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True, updated_input=normalized)


async def web_research_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if context.agent_runner is None:
        raise ValueError("web_research requires a runtime agent runner")
    normalized = _normalize_web_research_input(tool_input)
    state = _WebResearchRunState(normalized)
    _web_research_runs[state.run_id] = state
    previous_run_id = context.metadata.get(_WEB_RESEARCH_RUN_ID_METADATA_KEY)
    context.metadata[_WEB_RESEARCH_RUN_ID_METADATA_KEY] = state.run_id
    try:
        child_result = await context.agent_runner(
            "web-searcher",
            _web_research_delegation_prompt(normalized),
            context,
            background=False,
            reason="web_research delegated read-only evidence gathering",
            max_turns=normalized["budget"]["max_turns"],
        )
        return _project_web_research_result(normalized, child_result, state=state)
    finally:
        if previous_run_id is None:
            context.metadata.pop(_WEB_RESEARCH_RUN_ID_METADATA_KEY, None)
        else:
            context.metadata[_WEB_RESEARCH_RUN_ID_METADATA_KEY] = previous_run_id
        _web_research_runs.pop(state.run_id, None)


async def grounding_web_search_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    query = str(tool_input["query"]).strip()
    state = _web_research_state(context)
    effective_input = _effective_web_tool_input("search", tool_input, context)
    if state is not None:
        state.reserve("search")
    policy = build_policy(
        effective_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )

    def search() -> dict[str, Any]:
        return search_web(
            query,
            backend=DuckDuckGoHtmlBackend(urlopen=_grounding_urlopen),
            policy=policy,
        )

    try:
        result = await asyncio.to_thread(search)
    except Exception as exc:
        if state is not None:
            state.record_operation_failure("grounding_web_search", str(exc), effective_input)
        raise
    if state is not None:
        state.record_search(result)
    return result


def validate_grounding_web_fetch(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    effective_input = _effective_web_tool_input("fetch", tool_input, context)
    policy = build_policy(
        effective_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )
    try:
        validate_fetch_input(
            _source_reference(effective_input),
            policy=policy,
            hostname_public_resolver=_grounding_hostname_resolves_publicly,
        )
    except ValueError as exc:
        state = _web_research_state(context)
        if state is not None:
            state.record_rejection("grounding_web_fetch", str(exc), effective_input)
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True, updated_input=effective_input)


async def grounding_web_fetch_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _web_research_state(context)
    result = await _grounding_web_fetch_impl(tool_input, context)
    if state is not None:
        state.record_fetch(result)
    return result


async def _grounding_web_fetch_impl(
    tool_input: Mapping[str, Any],
    context: ToolContext,
    *,
    failure_tool: str = "grounding_web_fetch",
    failure_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    state = _web_research_state(context)
    effective_input = _effective_web_tool_input("fetch", tool_input, context)
    source = _source_reference(effective_input)
    policy = build_policy(
        effective_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )
    try:
        validate_fetch_input(
            source,
            policy=policy,
            hostname_public_resolver=_grounding_hostname_resolves_publicly,
        )
    except ValueError as exc:
        if state is not None:
            state.record_rejection("grounding_web_fetch", str(exc), effective_input)
        raise
    if state is not None:
        state.reserve("fetch")

    def fetch() -> dict[str, Any]:
        return inspect_page(
            source,
            backend=DuckDuckGoHtmlBackend(
                urlopen=lambda request, *, timeout: _grounding_policy_urlopen(
                    request,
                    timeout=timeout,
                    allowed_domains=policy.allowed_domains,
                    blocked_domains=policy.blocked_domains,
                    hostname_public_resolver=_grounding_hostname_resolves_publicly,
                )
            ),
            policy=policy,
        )

    try:
        return await asyncio.to_thread(fetch)
    except Exception as exc:
        if state is not None:
            state.record_operation_failure(
                failure_tool,
                str(exc),
                effective_input,
                metadata=failure_metadata,
            )
        raise


def validate_grounding_web_find(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    if not str(tool_input.get("pattern") or "").strip():
        return ValidationOutcome(False, "pattern must be non-empty")
    effective_input = _effective_web_tool_input("find", tool_input, context)
    policy = build_policy(
        effective_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )
    try:
        validate_page_find_input(
            effective_input,
            policy=policy,
            hostname_public_resolver=_grounding_hostname_resolves_publicly,
        )
    except ValueError as exc:
        state = _web_research_state(context)
        if state is not None:
            state.record_rejection("grounding_web_find", str(exc), effective_input)
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True, updated_input=effective_input)


async def grounding_web_find_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _web_research_state(context)
    effective_input = _effective_web_tool_input("find", tool_input, context)
    if state is not None:
        state.reserve("find")
    policy = build_policy(
        effective_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )

    def find() -> dict[str, Any]:
        return find_in_page(
            effective_input,
            backend=DuckDuckGoHtmlBackend(urlopen=_grounding_urlopen),
            policy=policy,
        )

    try:
        result = await asyncio.to_thread(find)
    except Exception as exc:
        if state is not None:
            state.record_operation_failure("grounding_web_find", str(exc), effective_input)
        raise
    if state is not None:
        state.record_find(result)
    return result


def validate_web_research_fetch_many(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    if _web_research_state(context) is None:
        return ValidationOutcome(False, "web_research_fetch_many is only available inside web_research")
    refs = _fetch_many_references(tool_input)
    if not refs:
        return ValidationOutcome(False, "urls or sources must contain at least one item")
    if len(refs) > 8:
        return ValidationOutcome(False, "urls or sources must contain at most 8 items")
    max_concurrent = tool_input.get("max_concurrent_fetches")
    if max_concurrent is not None and not isinstance(max_concurrent, int):
        return ValidationOutcome(False, "max_concurrent_fetches must be an integer")
    return ValidationOutcome(True)


async def web_research_fetch_many_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _web_research_state(context)
    if state is None:
        raise ValueError("web_research_fetch_many is only available inside web_research")
    refs = _fetch_many_references(tool_input)
    max_concurrent = _bounded_int(
        tool_input.get("max_concurrent_fetches"),
        "max_concurrent_fetches",
        1,
        state.max_concurrent_fetches,
        state.max_concurrent_fetches,
    )
    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_one(index: int, ref: Mapping[str, Any]) -> dict[str, Any]:
        async with semaphore:
            try:
                page = await _grounding_web_fetch_impl(
                    ref,
                    context,
                    failure_tool="web_research_fetch_many",
                    failure_metadata={"input_index": index},
                )
            except Exception as exc:
                return {
                    "index": index,
                    "status": "error",
                    "error": str(exc),
                    "url": str(ref.get("url") or ""),
                }
            return {"index": index, "status": "success", "page": page}

    pages = await asyncio.gather(*(fetch_one(index, ref) for index, ref in enumerate(refs)))
    pages.sort(key=lambda item: int(item.get("index", 0)))
    for item in pages:
        page = item.get("page")
        if isinstance(page, Mapping):
            state.record_fetch(page)
    return {
        "pages": pages,
        "budget": state.budget_payload(),
        "policy": dict(state.public_policy),
    }


def _source_reference(tool_input: Mapping[str, Any]) -> Mapping[str, Any]:
    source = tool_input.get("source")
    if isinstance(source, Mapping):
        return source
    return {"url": tool_input.get("url")}


def _fetch_many_references(tool_input: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources = tool_input.get("sources")
    if isinstance(sources, list):
        return [item for item in sources if isinstance(item, Mapping)]
    urls = tool_input.get("urls")
    if isinstance(urls, list):
        return [{"url": item} for item in urls]
    return []


def _grounding_policy_urlopen(request, **kwargs: Any):
    try:
        return _grounding_urlopen(request, **kwargs)
    except TypeError as exc:
        policy_keys = {"allowed_domains", "blocked_domains", "hostname_public_resolver"}
        if not policy_keys.intersection(kwargs):
            raise
        reduced_kwargs = {key: value for key, value in kwargs.items() if key not in policy_keys}
        try:
            return _grounding_urlopen(request, **reduced_kwargs)
        except TypeError:
            raise exc


def _web_research_objective(tool_input: Mapping[str, Any]) -> str:
    return str(tool_input.get("objective") or tool_input.get("question") or "").strip()


def _normalize_web_research_input(tool_input: Mapping[str, Any]) -> dict[str, Any]:
    objective = _web_research_objective(tool_input)
    mode = str(tool_input.get("mode") or "focused").strip().lower()
    if mode not in {"focused", "open"}:
        raise ValueError("mode must be focused or open")
    hard_policy = tool_input.get("hard_policy")
    if hard_policy is not None and not isinstance(hard_policy, Mapping):
        raise ValueError("hard_policy must be an object when provided")
    preferences = tool_input.get("preferences")
    if preferences is not None and not isinstance(preferences, Mapping):
        raise ValueError("preferences must be an object when provided")
    hard_policy_map = dict(hard_policy or {})
    preferences_map = dict(preferences or {})
    legacy_domains = tool_input.get("domains")
    legacy_allowed_domains = tool_input.get("allowed_domains")
    legacy_blocks = tool_input.get("blocked_domains")
    legacy_freshness = tool_input.get("freshness_days") or tool_input.get("recency_days")
    if legacy_blocks is not None and "blocked_domains" not in hard_policy_map:
        hard_policy_map["blocked_domains"] = legacy_blocks
    if legacy_freshness is not None and "freshness_days" not in preferences_map:
        preferences_map["freshness_days"] = legacy_freshness
    if legacy_allowed_domains is not None:
        hard_policy_map.setdefault("allowed_domains", legacy_allowed_domains)
    if legacy_domains is not None:
        if mode == "open":
            preferences_map.setdefault("preferred_domains", legacy_domains)
        else:
            hard_policy_map.setdefault("domains", legacy_domains)
    budget_profile = str(tool_input.get("budget_profile") or "standard").strip().lower()
    profile_defaults = _budget_profile_defaults(budget_profile)
    raw_policy = {
        "domains": hard_policy_map.get("domains") or hard_policy_map.get("allowed_domains"),
        "blocked_domains": hard_policy_map.get("blocked_domains"),
        "freshness_days": preferences_map.get("freshness_days"),
        "limit": tool_input.get("search_budget") or profile_defaults["search_budget"],
        "max_chars": tool_input.get("max_chars") or _GROUNDING_DEFAULT_FETCH_CHARS,
    }
    policy = build_policy(
        raw_policy,
        default_search_limit=profile_defaults["search_budget"],
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=profile_defaults["find_budget"],
    )
    output_hints = tool_input.get("output_hints")
    if output_hints is not None and not isinstance(output_hints, Mapping):
        raise ValueError("output_hints must be an object when provided")
    preferences_payload = {
        "preferred_domains": list(build_policy({"domains": preferences_map.get("preferred_domains")}).allowed_domains),
        "freshness_days": policy.freshness_days,
    }
    for key, value in preferences_map.items():
        if key not in preferences_payload:
            preferences_payload[str(key)] = value
    return {
        "objective": objective,
        "mode": mode,
        "policy": {
            "domains": list(policy.allowed_domains),
            "blocked_domains": list(policy.blocked_domains),
            "freshness_days": policy.freshness_days,
        },
        "hard_policy": {
            "allowed_domains": list(policy.allowed_domains),
            "blocked_domains": list(policy.blocked_domains),
        },
        "preferences": preferences_payload,
        "budget": {
            "search_budget": _bounded_int(
                tool_input.get("search_budget"),
                "search_budget",
                1,
                8,
                profile_defaults["search_budget"],
            ),
            "fetch_budget": _bounded_int(
                tool_input.get("fetch_budget"),
                "fetch_budget",
                0,
                8,
                profile_defaults["fetch_budget"],
            ),
            "find_budget": _bounded_int(
                tool_input.get("find_budget"),
                "find_budget",
                0,
                12,
                profile_defaults["find_budget"],
            ),
            "desired_source_count": _bounded_int(
                tool_input.get("desired_source_count"),
                "desired_source_count",
                1,
                8,
                profile_defaults["desired_source_count"],
            ),
            "max_turns": _bounded_int(tool_input.get("max_turns"), "max_turns", 1, 8, profile_defaults["max_turns"]),
            "max_concurrent_fetches": _bounded_int(
                tool_input.get("max_concurrent_fetches"),
                "max_concurrent_fetches",
                1,
                5,
                profile_defaults["max_concurrent_fetches"],
            ),
        },
        "budget_profile": budget_profile,
        "output_hints": dict(output_hints or {}),
    }


def _budget_profile_defaults(profile: str) -> dict[str, int]:
    if profile == "quick":
        return {
            "search_budget": 2,
            "fetch_budget": 2,
            "find_budget": 3,
            "desired_source_count": 2,
            "max_turns": 3,
            "max_concurrent_fetches": 2,
        }
    if profile == "deep":
        return {
            "search_budget": 6,
            "fetch_budget": 8,
            "find_budget": 10,
            "desired_source_count": 5,
            "max_turns": 8,
            "max_concurrent_fetches": 4,
        }
    if profile != "standard":
        raise ValueError("budget_profile must be quick, standard, or deep")
    return {
        "search_budget": _WEB_RESEARCH_DEFAULT_SEARCH_BUDGET,
        "fetch_budget": _WEB_RESEARCH_DEFAULT_FETCH_BUDGET,
        "find_budget": _WEB_RESEARCH_DEFAULT_FIND_BUDGET,
        "desired_source_count": _WEB_RESEARCH_DEFAULT_DESIRED_SOURCES,
        "max_turns": 4,
        "max_concurrent_fetches": _WEB_RESEARCH_DEFAULT_MAX_CONCURRENT_FETCHES,
    }


def _bounded_int(raw: Any, field: str, minimum: int, maximum: int, default: int) -> int:
    if raw is None:
        return default
    if not isinstance(raw, int):
        raise ValueError(f"{field} must be an integer")
    if raw < minimum or raw > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return raw


def _web_research_delegation_prompt(request: Mapping[str, Any]) -> str:
    return (
        "Run bounded read-only web research for this objective. Use only the package-owned "
        "`grounding_web_search`, `grounding_web_fetch`, `grounding_web_find`, and "
        "`web_research_fetch_many` tools, stay inside the supplied hard policy and budgets, "
        "and return concise structured evidence.\n\n"
        f"Objective: {request['objective']}\n"
        f"Mode: {request['mode']}\n"
        f"Hard policy: {request['hard_policy']}\n"
        f"Preferences: {request['preferences']}\n"
        f"Budget: {request['budget']}\n"
        f"Output hints: {request['output_hints']}\n\n"
        "In open mode, use preferred domains as ranking guidance, not as the only valid source "
        "scope. In focused mode, stay inside hard allowed domains. "
        "Do not navigate browsers, run shell commands, mutate workspace state, or cite sources "
        "you did not inspect."
    )


def _project_web_research_result(
    request: Mapping[str, Any],
    child_result: Any,
    *,
    state: "_WebResearchRunState",
) -> dict[str, Any]:
    child_payload = dict(child_result) if isinstance(child_result, Mapping) else {"summary": str(child_result)}
    terminal_metadata = child_payload.get("terminal_metadata")
    if not isinstance(terminal_metadata, Mapping):
        terminal_metadata = {}
    structured = terminal_metadata.get("web_research")
    if not isinstance(structured, Mapping):
        structured = child_payload.get("web_research")
    if not isinstance(structured, Mapping):
        structured = {}
    child_sources = _list_of_mappings(structured.get("sources") or structured.get("source_references"))
    child_evidence = _list_of_mappings(structured.get("evidence") or structured.get("inspected_evidence"))
    sources, evidence, dropped_events = _merge_verified_child_web_research_metadata(
        state.sources_payload(),
        state.evidence_payload(),
        child_sources=child_sources,
        child_evidence=child_evidence,
    )
    if dropped_events:
        state.record_unverified_child_metadata_dropped(dropped_events)
    child_trace = _list_of_mappings(structured.get("trace") or structured.get("trace_summary"))
    trace = [*state.trace_summary(), *child_trace]
    if child_payload.get("summary"):
        trace.append({"event": "delegated_summary", "summary": str(child_payload["summary"])})
    return {
        "objective": request["objective"],
        "mode": request.get("mode", "focused"),
        "answer": str(structured.get("answer") or child_payload.get("summary") or "").strip(),
        "sources": sources,
        "evidence": evidence,
        "policy": dict(request["policy"]),
        "hard_policy": dict(request.get("hard_policy") or {}),
        "preferences": dict(request.get("preferences") or {}),
        "budget": state.budget_payload(),
        "stop_reason": state.stop_reason(
            structured.get("stop_reason") or terminal_metadata.get("stop_reason") or child_payload.get("status"),
        ),
        "trace_summary": trace[:_WEB_RESEARCH_MAX_TRACE_ITEMS],
        "child_run": {
            "agent": child_payload.get("agent") or child_payload.get("agent_name") or "web-searcher",
            "status": child_payload.get("status"),
            "run_id": child_payload.get("run_id"),
            "parent_run_id": child_payload.get("parent_run_id"),
            "session_id": child_payload.get("session_id"),
            "delegation_depth": child_payload.get("delegation_depth"),
        },
    }


def _stop_reason_from_status(raw_status: Any) -> str:
    status = str(raw_status or "").strip()
    if status in {
        "partial_result",
        "budget_exhausted",
        "policy_blocked",
        "needs_wider_scope",
        "freshness_unsupported",
    }:
        return status
    if status in {"max_turns", "cancelled"}:
        return "budget_exhausted"
    return "partial_result"


def _merge_verified_child_web_research_metadata(
    ledger_sources: list[dict[str, Any]],
    ledger_evidence: list[dict[str, Any]],
    *,
    child_sources: list[dict[str, Any]],
    child_evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    sources = [dict(item) for item in ledger_sources]
    evidence = [dict(item) for item in ledger_evidence]
    dropped: list[dict[str, Any]] = []

    for index, child in enumerate(child_sources):
        match = _find_unique_child_match(
            child,
            sources,
            identity_fields=("url", "source_handle", "page_handle", "id"),
        )
        if match is None:
            dropped.append(_unverified_child_metadata_event("source", child, index))
            continue
        _merge_child_annotations(match, child, _WEB_RESEARCH_SOURCE_ANNOTATION_FIELDS)

    for index, child in enumerate(child_evidence):
        match = _find_unique_child_match(
            child,
            evidence,
            identity_fields=("source_handle", "page_handle", "id"),
            compound_fields=(("url", "excerpt"),),
            fallback_fields=("url",),
        )
        if match is None:
            dropped.append(_unverified_child_metadata_event("evidence", child, index))
            continue
        _merge_child_annotations(match, child, _WEB_RESEARCH_EVIDENCE_ANNOTATION_FIELDS)

    return sources, evidence, dropped


def _find_unique_child_match(
    child: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    *,
    identity_fields: tuple[str, ...],
    compound_fields: tuple[tuple[str, ...], ...] = (),
    fallback_fields: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    for fields in compound_fields:
        values = {field: _identity_value(child.get(field)) for field in fields}
        if not all(values.values()):
            continue
        matches = [
            item
            for item in candidates
            if all(_identity_value(item.get(field)) == value for field, value in values.items())
        ]
        if len(matches) == 1:
            return matches[0]
    for field in identity_fields:
        value = _identity_value(child.get(field))
        if not value:
            continue
        matches = [item for item in candidates if _identity_value(item.get(field)) == value]
        if len(matches) == 1:
            return matches[0]
    for field in fallback_fields:
        value = _identity_value(child.get(field))
        if not value:
            continue
        matches = [item for item in candidates if _identity_value(item.get(field)) == value]
        if len(matches) == 1:
            return matches[0]
    return None


def _merge_child_annotations(
    target: dict[str, Any],
    child: Mapping[str, Any],
    supported_fields: frozenset[str],
) -> None:
    for field in supported_fields:
        if field not in child:
            continue
        value = child[field]
        if value is None or value == "":
            continue
        target[field] = value


def _unverified_child_metadata_event(kind: str, item: Mapping[str, Any], index: int) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event": "unverified_child_metadata_dropped",
        "kind": kind,
        "child_index": index,
        "reason": "no_ledger_match",
    }
    for key in ("url", "source_handle", "page_handle", "id"):
        value = _identity_value(item.get(key))
        if value:
            event[key] = value
    return event


def _identity_value(value: Any) -> str:
    return str(value or "").strip()


def _url_from_tool_input(tool_input: Mapping[str, Any]) -> str:
    source = tool_input.get("source")
    if isinstance(source, Mapping):
        url = source.get("url")
    else:
        url = None
    return _identity_value(tool_input.get("url") or url)


def _optional_fact_fields(item: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: item[field] for field in fields if field in item}


def _list_of_mappings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


@dataclass(slots=True)
class _WebResearchRunState:
    request: Mapping[str, Any]
    run_id: str = field(default_factory=lambda: f"webresearch-{uuid4().hex}")
    search_used: int = 0
    fetch_used: int = 0
    find_used: int = 0
    policy_rejections: int = 0
    budget_rejections: int = 0
    operation_failures: int = 0
    sources: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def __post_init__(self) -> None:
        freshness_days = self.request.get("policy", {}).get("freshness_days")
        if freshness_days is not None:
            self._append_trace(
                {
                    "event": "freshness_unsupported",
                    "requested_days": freshness_days,
                    "status": "unsupported",
                }
            )

    @property
    def public_policy(self) -> Mapping[str, Any]:
        return self.request["policy"]

    @property
    def max_concurrent_fetches(self) -> int:
        return int(self.request["budget"]["max_concurrent_fetches"])

    def reserve(self, kind: str) -> None:
        budget_key = f"{kind}_budget"
        used_attr = f"{kind}_used"
        if budget_key not in self.request["budget"] or not hasattr(self, used_attr):
            return
        with self._lock:
            used = int(getattr(self, used_attr))
            budget = int(self.request["budget"][budget_key])
            if used >= budget:
                self.budget_rejections += 1
                self._append_trace(
                    {
                        "event": "budget_rejected",
                        "tool": f"grounding_web_{kind}",
                        "budget": budget_key,
                        "used": used,
                        "limit": budget,
                    }
                )
                raise ValueError(f"web_research {kind} budget exhausted")
            setattr(self, used_attr, used + 1)

    def record_search(self, result: Mapping[str, Any]) -> None:
        results = _list_of_mappings(result.get("results"))
        with self._lock:
            for item in results:
                self._add_source(item)
            self._append_trace(
                {
                    "event": "searched",
                    "tool": "grounding_web_search",
                    "query": result.get("query"),
                    "result_count": len(results),
                }
            )

    def record_fetch(self, result: Mapping[str, Any]) -> None:
        with self._lock:
            self._add_source(dict(result.get("source") or result))
            self._add_evidence(
                {
                    "id": result.get("id") or result.get("source_handle"),
                    "title": result.get("title"),
                    "url": result.get("url"),
                    "excerpt": result.get("excerpt") or _first_excerpt(result.get("content")),
                    "source_handle": result.get("source_handle"),
                    "page_handle": result.get("page_handle"),
                }
            )
            self._append_trace(
                {
                    "event": "fetched",
                    "tool": "grounding_web_fetch",
                    "url": result.get("url"),
                }
            )

    def record_find(self, result: Mapping[str, Any]) -> None:
        matches = _list_of_mappings(result.get("matches"))
        with self._lock:
            source = result.get("source")
            if isinstance(source, Mapping):
                self._add_source(dict(source))
            for item in matches:
                self._add_evidence(item)
            self._append_trace(
                {
                    "event": "found",
                    "tool": "grounding_web_find",
                    "query": result.get("query"),
                    "match_count": len(matches),
                }
            )

    def record_rejection(self, tool: str, error: str, tool_input: Mapping[str, Any]) -> None:
        with self._lock:
            if "budget exhausted" in error:
                self.budget_rejections += 1
            else:
                self.policy_rejections += 1
            self._append_trace(
                {
                    "event": "rejected",
                    "tool": tool,
                    "error": error,
                    "url": tool_input.get("url"),
                }
            )

    def record_operation_failure(
        self,
        tool: str,
        error: str,
        tool_input: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.operation_failures += 1
            event: dict[str, Any] = {
                "event": "operation_failed",
                "tool": tool,
                "error": _first_excerpt(error),
            }
            url = _url_from_tool_input(tool_input)
            if url:
                event["url"] = url
            if metadata:
                for key, value in metadata.items():
                    if value is not None:
                        event[str(key)] = value
            self._append_trace(event)

    def record_unverified_child_metadata_dropped(self, events: list[dict[str, Any]]) -> None:
        with self._lock:
            for event in events:
                self._append_trace(event)

    def sources_payload(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.sources]

    def evidence_payload(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.evidence]

    def trace_summary(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.trace[-_WEB_RESEARCH_MAX_TRACE_ITEMS:]]

    def budget_payload(self) -> dict[str, Any]:
        with self._lock:
            budget = dict(self.request["budget"])
            budget["used"] = {
                "searches": self.search_used,
                "fetches": self.fetch_used,
                "finds": self.find_used,
            }
            budget["rejections"] = {
                "policy": self.policy_rejections,
                "budget": self.budget_rejections,
            }
            budget["operation_failures"] = self.operation_failures
            return budget

    def stop_reason(self, child_status: Any) -> str:
        with self._lock:
            has_evidence = bool(self.evidence)
            policy_rejections = self.policy_rejections
            budget_rejections = self.budget_rejections
            operation_failures = self.operation_failures
            freshness_requested = self.request["policy"].get("freshness_days") is not None
            inspected_sources = self._inspected_source_count_locked()
            desired_sources = int(self.request["budget"].get("desired_source_count") or 1)
        if not has_evidence:
            if policy_rejections:
                return "policy_blocked"
            if budget_rejections:
                return "budget_exhausted"
            if freshness_requested:
                return "freshness_unsupported"
            if operation_failures:
                return "partial_result"
            return _stop_reason_from_status(child_status)
        if freshness_requested:
            return "freshness_unsupported"
        if budget_rejections or operation_failures:
            return "partial_result"
        if inspected_sources < desired_sources:
            return "partial_result"
        return "sufficient_evidence"

    def _add_source(self, item: Mapping[str, Any]) -> None:
        url = str(item.get("url") or "").strip()
        if not url:
            return
        if any(existing.get("url") == url for existing in self.sources):
            return
        self.sources.append(
            {
                "id": item.get("id") or item.get("source_handle") or url,
                "title": item.get("title") or url,
                "url": url,
                "source_handle": item.get("source_handle") or item.get("id"),
                "page_handle": item.get("page_handle"),
                "domain": item.get("domain"),
            }
        )

    def _add_evidence(self, item: Mapping[str, Any]) -> None:
        excerpt = str(item.get("excerpt") or item.get("content") or "").strip()
        url = str(item.get("url") or "").strip()
        if not excerpt and not url:
            return
        key = (url, excerpt)
        if any((existing.get("url"), existing.get("excerpt")) == key for existing in self.evidence):
            return
        self.evidence.append(
            {
                "id": item.get("id") or item.get("source_handle") or url,
                "title": item.get("title"),
                "url": url,
                "excerpt": excerpt,
                "source_handle": item.get("source_handle"),
                "page_handle": item.get("page_handle"),
                **_optional_fact_fields(item, ("exact_excerpt", "match_start", "match_end")),
            }
        )

    def _inspected_source_count_locked(self) -> int:
        keys: set[str] = set()
        for item in self.evidence:
            key = _identity_value(item.get("source_handle") or item.get("page_handle") or item.get("url"))
            if key:
                keys.add(key)
        return len(keys)

    def _append_trace(self, event: Mapping[str, Any]) -> None:
        self.trace.append(dict(event))
        if len(self.trace) > _WEB_RESEARCH_MAX_TRACE_ITEMS * 4:
            del self.trace[: len(self.trace) - _WEB_RESEARCH_MAX_TRACE_ITEMS * 4]


def _web_research_state(context: Any) -> _WebResearchRunState | None:
    metadata = getattr(context, "metadata", None)
    if not isinstance(metadata, Mapping):
        query = getattr(context, "query", None) or getattr(context, "query_context", None)
        metadata = getattr(query, "continuation_metadata", None)
    if not isinstance(metadata, Mapping):
        return None
    run_id = metadata.get(_WEB_RESEARCH_RUN_ID_METADATA_KEY)
    if run_id is None:
        return None
    return _web_research_runs.get(str(run_id))


def _effective_web_tool_input(kind: str, tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    effective = dict(tool_input)
    state = _web_research_state(context)
    if state is None:
        return effective
    policy = state.public_policy
    if policy.get("domains"):
        effective["domains"] = list(policy["domains"])
    if policy.get("blocked_domains"):
        effective["blocked_domains"] = list(policy["blocked_domains"])
    if policy.get("freshness_days") is not None:
        effective["freshness_days"] = policy["freshness_days"]
    if kind == "search":
        remaining = max(1, int(state.request["budget"]["search_budget"]) - state.search_used)
        effective.setdefault("limit", min(_GROUNDING_DEFAULT_SEARCH_LIMIT, remaining))
    if kind == "find":
        remaining = max(1, int(state.request["budget"]["find_budget"]) - state.find_used)
        effective.setdefault("limit", min(_GROUNDING_DEFAULT_FIND_LIMIT, remaining))
    return effective


def _first_excerpt(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= 240:
        return text
    return text[:237].rstrip() + "..."


@lru_cache(maxsize=256)
def _grounding_hostname_resolves_publicly(hostname: str) -> bool | None:
    try:
        resolutions = socket.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError:
        return None
    saw_address = False
    for _family, _kind, _proto, _canonname, sockaddr in resolutions:
        if not sockaddr:
            continue
        try:
            address = sockaddr[0]
        except (IndexError, TypeError):
            continue
        saw_address = True
        if not _is_public_address(str(address)):
            return False
    return True if saw_address else None


def _is_public_address(value: str) -> bool:
    import ipaddress

    try:
        return ipaddress.ip_address(value.strip()).is_global
    except ValueError:
        return False


__all__ = [
    "grounding_web_fetch_tool",
    "grounding_web_find_tool",
    "grounding_web_search_tool",
    "prepare_citations_tool",
    "retrieve_context_tool",
    "validate_grounding_web_fetch",
    "validate_grounding_web_find",
    "validate_grounding_web_search",
    "validate_prepare_citations_tool",
    "validate_retrieve_context_tool",
    "validate_web_research",
    "validate_web_research_fetch_many",
    "web_research_fetch_many_tool",
    "web_research_tool",
]
