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
    validate_web_url_input,
    web_urlopen,
)

_GROUNDING_DEFAULT_SEARCH_LIMIT = 8
_GROUNDING_DEFAULT_FETCH_CHARS = 12_000
_GROUNDING_DEFAULT_FIND_LIMIT = 5

_grounding_urlopen = web_urlopen


def validate_grounding_web_search(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not str(tool_input.get("query") or "").strip():
        return ValidationOutcome(False, "query must be non-empty")
    return ValidationOutcome(True)


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
    if tool_input.get("source") is None and not str(tool_input.get("url") or "").strip():
        return ValidationOutcome(False, "source or url is required")
    url = _candidate_url(tool_input)
    if url is None:
        return ValidationOutcome(False, "Only http:// and https:// URLs are supported")
    policy = build_policy(
        tool_input,
        default_search_limit=_GROUNDING_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_GROUNDING_DEFAULT_FETCH_CHARS,
        default_find_matches=_GROUNDING_DEFAULT_FIND_LIMIT,
    )
    validation_error = validate_web_url_input(
        url,
        allowed_domains=policy.allowed_domains,
        blocked_domains=policy.blocked_domains,
        hostname_public_resolver=_grounding_hostname_resolves_publicly,
    )
    if validation_error is not None:
        return ValidationOutcome(False, validation_error)
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
            backend=DuckDuckGoHtmlBackend(urlopen=_grounding_urlopen),
            policy=policy,
        )

    return await asyncio.to_thread(fetch)


def validate_grounding_web_find(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not str(tool_input.get("pattern") or "").strip():
        return ValidationOutcome(False, "pattern must be non-empty")
    if not isinstance(tool_input.get("page"), Mapping):
        return ValidationOutcome(False, "page must be an inspected page object")
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


def _candidate_url(tool_input: Mapping[str, Any]) -> str | None:
    if isinstance(tool_input.get("source"), Mapping):
        candidate = str(tool_input["source"].get("url") or "").strip()
        return candidate or None
    candidate = str(tool_input.get("url") or "").strip()
    return candidate or None


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
]
