from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from weavert.definitions import ValidationOutcome
from weavert.tool_runtime import ToolContext
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

_TECHNICAL_SEARCH_LIMIT = 8
_TECHNICAL_FETCH_CHARS = 16_000
_TECHNICAL_FIND_LIMIT = 6


def validate_technical_web_search(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    query = str(tool_input.get("query") or "").strip()
    if not query:
        return ValidationOutcome(False, "query must be non-empty")
    domains = tool_input.get("domains")
    if not isinstance(domains, list) or not any(str(item).strip() for item in domains):
        return ValidationOutcome(False, "domains must contain at least one domain")
    return ValidationOutcome(True)


async def technical_web_search_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    query = str(tool_input["query"]).strip()
    requested_version = _normalize_optional_string(tool_input.get("version"))
    policy = build_policy(
        tool_input,
        default_search_limit=_TECHNICAL_SEARCH_LIMIT,
        default_text_chars=_TECHNICAL_FETCH_CHARS,
        default_find_matches=_TECHNICAL_FIND_LIMIT,
    )

    def search() -> dict[str, Any]:
        result = search_web(query, backend=DuckDuckGoHtmlBackend(), policy=policy)
        annotated = _annotate_versioned_results(result["results"], requested_version=requested_version)
        return {
            **result,
            "results": annotated,
            "version_scope": _version_status(annotated, requested_version=requested_version),
        }

    return await asyncio.to_thread(search)


def validate_technical_web_fetch(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    policy = build_policy(
        tool_input,
        default_search_limit=_TECHNICAL_SEARCH_LIMIT,
        default_text_chars=_TECHNICAL_FETCH_CHARS,
        default_find_matches=_TECHNICAL_FIND_LIMIT,
    )
    try:
        validate_fetch_input(_source_reference(tool_input), policy=policy)
    except ValueError as exc:
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True)


async def technical_web_fetch_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    requested_version = _normalize_optional_string(tool_input.get("version"))
    policy = build_policy(
        tool_input,
        default_search_limit=_TECHNICAL_SEARCH_LIMIT,
        default_text_chars=_TECHNICAL_FETCH_CHARS,
        default_find_matches=_TECHNICAL_FIND_LIMIT,
    )
    source = _source_reference(tool_input)

    def fetch() -> dict[str, Any]:
        result = inspect_page(
            source,
            backend=DuckDuckGoHtmlBackend(
                urlopen=lambda request, *, timeout: web_urlopen(
                    request,
                    timeout=timeout,
                    allowed_domains=policy.allowed_domains,
                    blocked_domains=policy.blocked_domains,
                )
            ),
            policy=policy,
        )
        result["version_scope"] = _version_scope_for_mapping(result, requested_version=requested_version)
        return result

    return await asyncio.to_thread(fetch)


def validate_technical_web_find(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not str(tool_input.get("pattern") or "").strip():
        return ValidationOutcome(False, "pattern must be non-empty")
    policy = build_policy(
        tool_input,
        default_search_limit=_TECHNICAL_SEARCH_LIMIT,
        default_text_chars=_TECHNICAL_FETCH_CHARS,
        default_find_matches=_TECHNICAL_FIND_LIMIT,
    )
    try:
        validate_page_find_input(tool_input, policy=policy)
    except ValueError as exc:
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True)


async def technical_web_find_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    requested_version = _normalize_optional_string(tool_input.get("version"))
    policy = build_policy(
        tool_input,
        default_search_limit=_TECHNICAL_SEARCH_LIMIT,
        default_text_chars=_TECHNICAL_FETCH_CHARS,
        default_find_matches=_TECHNICAL_FIND_LIMIT,
    )

    def find() -> dict[str, Any]:
        result = find_in_page(tool_input, backend=DuckDuckGoHtmlBackend(), policy=policy)
        version_scope = _version_scope_for_mapping(tool_input["page"], requested_version=requested_version)
        result["version_scope"] = version_scope
        for match in result["matches"]:
            match["version_scope"] = dict(version_scope)
        return result

    return await asyncio.to_thread(find)


def _source_reference(tool_input: Mapping[str, Any]) -> Mapping[str, Any]:
    source = tool_input.get("source")
    if isinstance(source, Mapping):
        return source
    return {"url": tool_input.get("url")}


def _annotate_versioned_results(
    results: Sequence[Mapping[str, Any]],
    *,
    requested_version: str | None,
) -> list[dict[str, Any]]:
    annotated = [dict(item) for item in results]
    if requested_version is None:
        for item in annotated:
            item["version_scope"] = {"requested": None, "status": "unscoped", "matched": True}
        return annotated

    annotated.sort(
        key=lambda item: (
            -_version_match_score(item, requested_version=requested_version),
            str(item.get("title") or item.get("url") or ""),
        )
    )
    for item in annotated:
        matched = _version_match_score(item, requested_version=requested_version) > 0
        item["version_scope"] = {
            "requested": requested_version,
            "status": "matched" if matched else "version_mismatch",
            "matched": matched,
        }
    return annotated


def _version_scope_for_mapping(raw: Mapping[str, Any], *, requested_version: str | None) -> dict[str, Any]:
    if requested_version is None:
        return {"requested": None, "status": "unscoped", "matched": True}
    matched = _version_match_score(raw, requested_version=requested_version) > 0
    return {
        "requested": requested_version,
        "status": "matched" if matched else "version_mismatch",
        "matched": matched,
    }


def _version_status(results: Sequence[Mapping[str, Any]], *, requested_version: str | None) -> dict[str, Any]:
    if requested_version is None:
        return {"requested": None, "status": "unscoped", "matched": True}
    matched = any(bool(item.get("version_scope", {}).get("matched")) for item in results)
    return {
        "requested": requested_version,
        "status": "matched" if matched else "unsatisfied",
        "matched": matched,
    }


def _version_match_score(raw: Mapping[str, Any], *, requested_version: str) -> int:
    target = requested_version.strip().lower()
    if not target:
        return 0
    haystacks = (
        str(raw.get("title") or "").lower(),
        str(raw.get("url") or "").lower(),
        str(raw.get("content") or "").lower(),
        str(raw.get("excerpt") or "").lower(),
    )
    score = 0
    for index, haystack in enumerate(haystacks, start=1):
        if target in haystack:
            score += 5 - index
    return score


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
