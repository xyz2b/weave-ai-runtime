from __future__ import annotations

import asyncio
import socket
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

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

_grounding_urlopen = web_urlopen


def validate_grounding_web_search(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not str(tool_input.get("query") or "").strip():
        return ValidationOutcome(False, "query must be non-empty")
    return ValidationOutcome(True)


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
    child_result = await context.agent_runner(
        "web-searcher",
        _web_research_delegation_prompt(normalized),
        context,
        background=False,
        reason="web_research delegated read-only evidence gathering",
        max_turns=normalized["budget"]["max_turns"],
    )
    return _project_web_research_result(normalized, child_result)


async def grounding_web_search_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    query = str(tool_input["query"]).strip()
    policy = build_policy(
        tool_input,
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

    return await asyncio.to_thread(search)


def validate_grounding_web_fetch(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    policy = build_policy(
        tool_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )
    try:
        validate_fetch_input(
            _source_reference(tool_input),
            policy=policy,
            hostname_public_resolver=_grounding_hostname_resolves_publicly,
        )
    except ValueError as exc:
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True)


async def grounding_web_fetch_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    source = _source_reference(tool_input)
    policy = build_policy(
        tool_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )

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

    return await asyncio.to_thread(fetch)


def validate_grounding_web_find(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not str(tool_input.get("pattern") or "").strip():
        return ValidationOutcome(False, "pattern must be non-empty")
    policy = build_policy(
        tool_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )
    try:
        validate_page_find_input(
            tool_input,
            policy=policy,
            hostname_public_resolver=_grounding_hostname_resolves_publicly,
        )
    except ValueError as exc:
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True)


async def grounding_web_find_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    policy = build_policy(
        tool_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )

    def find() -> dict[str, Any]:
        return find_in_page(
            tool_input,
            backend=DuckDuckGoHtmlBackend(urlopen=_grounding_urlopen),
            policy=policy,
        )

    return await asyncio.to_thread(find)


def _source_reference(tool_input: Mapping[str, Any]) -> Mapping[str, Any]:
    source = tool_input.get("source")
    if isinstance(source, Mapping):
        return source
    return {"url": tool_input.get("url")}


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
    raw_policy = {
        "domains": tool_input.get("domains") or tool_input.get("allowed_domains"),
        "blocked_domains": tool_input.get("blocked_domains"),
        "freshness_days": tool_input.get("freshness_days") or tool_input.get("recency_days"),
        "limit": tool_input.get("search_budget") or _WEB_RESEARCH_DEFAULT_SEARCH_BUDGET,
        "max_chars": tool_input.get("max_chars") or _GROUNDING_DEFAULT_FETCH_CHARS,
    }
    policy = build_policy(
        raw_policy,
        default_search_limit=_WEB_RESEARCH_DEFAULT_SEARCH_BUDGET,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_WEB_RESEARCH_DEFAULT_FIND_BUDGET,
    )
    output_hints = tool_input.get("output_hints")
    if output_hints is not None and not isinstance(output_hints, Mapping):
        raise ValueError("output_hints must be an object when provided")
    return {
        "objective": objective,
        "policy": {
            "domains": list(policy.allowed_domains),
            "blocked_domains": list(policy.blocked_domains),
            "freshness_days": policy.freshness_days,
        },
        "budget": {
            "search_budget": _bounded_int(
                tool_input.get("search_budget"),
                "search_budget",
                1,
                8,
                _WEB_RESEARCH_DEFAULT_SEARCH_BUDGET,
            ),
            "fetch_budget": _bounded_int(
                tool_input.get("fetch_budget"),
                "fetch_budget",
                0,
                8,
                _WEB_RESEARCH_DEFAULT_FETCH_BUDGET,
            ),
            "find_budget": _bounded_int(
                tool_input.get("find_budget"),
                "find_budget",
                0,
                12,
                _WEB_RESEARCH_DEFAULT_FIND_BUDGET,
            ),
            "desired_source_count": _bounded_int(
                tool_input.get("desired_source_count"),
                "desired_source_count",
                1,
                8,
                _WEB_RESEARCH_DEFAULT_DESIRED_SOURCES,
            ),
            "max_turns": _bounded_int(tool_input.get("max_turns"), "max_turns", 1, 8, 4),
        },
        "output_hints": dict(output_hints or {}),
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
        "`grounding_web_search`, `grounding_web_fetch`, and `grounding_web_find` tools, stay "
        "inside the supplied policy and budgets, and return concise structured evidence.\n\n"
        f"Objective: {request['objective']}\n"
        f"Policy: {request['policy']}\n"
        f"Budget: {request['budget']}\n"
        f"Output hints: {request['output_hints']}\n\n"
        "Do not navigate browsers, run shell commands, mutate workspace state, or cite sources "
        "you did not inspect."
    )


def _project_web_research_result(request: Mapping[str, Any], child_result: Any) -> dict[str, Any]:
    child_payload = dict(child_result) if isinstance(child_result, Mapping) else {"summary": str(child_result)}
    terminal_metadata = child_payload.get("terminal_metadata")
    if not isinstance(terminal_metadata, Mapping):
        terminal_metadata = {}
    structured = terminal_metadata.get("web_research")
    if not isinstance(structured, Mapping):
        structured = child_payload.get("web_research")
    if not isinstance(structured, Mapping):
        structured = {}
    trace = _list_of_mappings(structured.get("trace") or structured.get("trace_summary"))
    if not trace and child_payload.get("summary"):
        trace = [{"event": "delegated_summary", "summary": str(child_payload["summary"])}]
    return {
        "objective": request["objective"],
        "answer": str(structured.get("answer") or child_payload.get("summary") or "").strip(),
        "sources": _list_of_mappings(structured.get("sources") or structured.get("source_references")),
        "evidence": _list_of_mappings(structured.get("evidence") or structured.get("inspected_evidence")),
        "policy": dict(request["policy"]),
        "budget": dict(request["budget"]),
        "stop_reason": str(
            structured.get("stop_reason")
            or terminal_metadata.get("stop_reason")
            or _stop_reason_from_status(child_payload.get("status"))
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
    if status == "completed":
        return "sufficient_evidence"
    if status in {"max_turns", "cancelled"}:
        return "budget_exhausted"
    return "partial_result"


def _list_of_mappings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


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
    "web_research_tool",
]
