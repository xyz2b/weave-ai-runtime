from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

_HTML_TITLE_RE = re.compile(r"<title[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_HTML_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_DEFAULT_SEARCH_BASE_URL = "https://duckduckgo.com/html/"
_DEFAULT_REDIRECT_HOSTS = frozenset({"duckduckgo.com", "www.duckduckgo.com"})
_DEFAULT_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
    }
)
_DEFAULT_BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".localdomain",
    ".local",
    ".internal",
    ".home.arpa",
)
_DEFAULT_FETCH_BYTES = 256_000
_DEFAULT_FETCH_CHARS = 12_000
_DEFAULT_LOOP_TRACE_ITEMS = 8


@dataclass(frozen=True, slots=True)
class WebResearchPolicy:
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    freshness_days: int | None = None
    freshness_required: bool = False
    provider: str | None = None
    max_fetch_bytes: int = _DEFAULT_FETCH_BYTES
    max_text_chars: int = _DEFAULT_FETCH_CHARS
    max_search_results: int = 8
    max_find_matches: int = 5
    excerpt_chars: int = 280


@dataclass(frozen=True, slots=True)
class WebSearchProviderCapabilities:
    domain_filtering: bool = False
    blocked_domain_filtering: bool = False
    result_limit: bool = True
    freshness: bool = False
    fetch: bool = True
    page_find: bool = True
    usage: str | None = None


@dataclass(frozen=True, slots=True)
class WebSearchProviderMetadata:
    provider_id: str
    display_name: str
    capabilities: WebSearchProviderCapabilities
    credential_required: bool = False
    configured: bool = True
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class BackendSearchResult:
    title: str
    url: str
    excerpt: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BackendFetchResult:
    url: str
    status: int
    content_type: str
    body: str
    raw_bytes: int
    title: str | None


@dataclass(frozen=True, slots=True)
class BackendFindMatch:
    excerpt: str
    start: int
    end: int
    exact_text: str


class WebResearchBackend(Protocol):
    def search(
        self,
        query: str,
        *,
        limit: int,
        policy: WebResearchPolicy | None = None,
    ) -> list[BackendSearchResult]: ...

    def fetch(self, url: str, *, timeout: float, max_bytes: int) -> BackendFetchResult: ...

    def find(
        self,
        page: Mapping[str, Any],
        pattern: str,
        *,
        limit: int,
        excerpt_chars: int,
    ) -> list[BackendFindMatch]: ...


@dataclass(frozen=True, slots=True)
class ValidationResult:
    normalized_url: str


@dataclass(frozen=True, slots=True)
class PageValidationResult:
    url: str
    page_handle: str
    source_handle: str
    title: str
    source: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ResearchProfile:
    name: str
    query_templates: tuple[str, ...] = ()
    source_priorities: tuple[str, ...] = ()
    freshness_policy: Mapping[str, Any] = field(default_factory=dict)
    evidence_schema: Mapping[str, Any] = field(default_factory=dict)
    conflict_rules: tuple[str, ...] = ()
    stop_conditions: tuple[str, ...] = ()
    facet_keys: tuple[str, ...] = ()
    defaults: Mapping[str, Any] = field(default_factory=dict)


class ResearchProfileRegistry:
    def __init__(self, profiles: Sequence[ResearchProfile]) -> None:
        self._profiles = {profile.name: profile for profile in profiles}

    def get(self, name: str) -> ResearchProfile:
        try:
            return self._profiles[name]
        except KeyError as exc:
            raise KeyError(f"Unknown research profile: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._profiles)


def web_research_stop_reason_from_status(raw_status: Any) -> str:
    status = str(raw_status or "").strip()
    if status in {
        "sufficient_evidence",
        "partial_result",
        "budget_exhausted",
        "policy_blocked",
        "freshness_unsupported",
        "unresolved_conflict",
        "remaining_gaps",
    }:
        return status
    if status in {"conflicting_evidence", "conflict", "conflicts"}:
        return "unresolved_conflict"
    if status in {"needs_wider_scope", "gaps_remaining", "gap", "gaps"}:
        return "remaining_gaps"
    if status in {"freshness_enforced", "freshness_satisfied"}:
        return "sufficient_evidence"
    if status == "provider_fallback":
        return "partial_result"
    if status in {"max_turns", "cancelled"}:
        return "budget_exhausted"
    return "partial_result"


def web_research_confidence_from_stop_reason(stop_reason: str) -> str:
    if stop_reason == "sufficient_evidence":
        return "high"
    if stop_reason in {"partial_result", "freshness_unsupported"}:
        return "medium"
    return "low"


def _inspection_quality(result: Mapping[str, Any]) -> dict[str, Any] | None:
    source = result.get("source") if isinstance(result.get("source"), Mapping) else {}
    raw_quality = result.get("quality") if isinstance(result.get("quality"), Mapping) else source.get("quality")
    quality = dict(raw_quality) if isinstance(raw_quality, Mapping) else {}
    signals = list(quality.get("signals") or ())
    for signal in ("inspection_success", "content_relevance", "evidence_density"):
        if signal not in signals:
            signals.append(signal)
    if result.get("freshness_scope") or source.get("freshness_scope"):
        signals.append("freshness_metadata")
    source_class = result.get("source_class") or source.get("source_class")
    if source_class:
        quality.setdefault("source_class", source_class)
        signals.append(f"source_class:{source_class}")
    excerpt = _identity_value(result.get("excerpt") or _first_excerpt(result.get("content")))
    if excerpt:
        quality["inspected_excerpt_length"] = len(excerpt)
    quality["signals"] = list(dict.fromkeys(str(signal) for signal in signals if signal))
    quality["diagnostic_only"] = True
    return quality or None


def refine_web_research_stop_reason(
    stop_reason: str,
    *,
    child_status: Any,
    conflicts: Sequence[Mapping[str, Any]] = (),
    gaps: Sequence[Mapping[str, Any]] = (),
) -> str:
    child_stop = web_research_stop_reason_from_status(child_status)
    unresolved_conflicts = [conflict for conflict in conflicts if not conflict.get("resolved")]
    if child_stop == "unresolved_conflict" and unresolved_conflicts:
        return child_stop
    if child_stop == "remaining_gaps":
        return child_stop
    if unresolved_conflicts and stop_reason in {"sufficient_evidence", "partial_result"}:
        return "unresolved_conflict"
    if gaps and stop_reason == "sufficient_evidence":
        return "remaining_gaps"
    return stop_reason


@dataclass(slots=True)
class WebResearchLoopState:
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
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    provider_events: list[dict[str, Any]] = field(default_factory=list)
    freshness_outcomes: list[dict[str, Any]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    @property
    def profile(self) -> str:
        return str(self.request.get("profile") or "general")

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
                        "tool": f"web_{kind}",
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
            self._record_provider_and_freshness(result)
            query = _identity_value(result.get("query"))
            if query:
                self._append_query(query)
            for item in results:
                self._add_source(item)
            event = {
                "event": "searched",
                "tool": "web_search",
                "query": result.get("query"),
                "result_count": len(results),
            }
            provider = result.get("provider")
            if isinstance(provider, Mapping):
                event["provider"] = provider.get("id")
            freshness_scope = result.get("freshness_scope")
            if isinstance(freshness_scope, Mapping):
                event["freshness_status"] = freshness_scope.get("status")
            self._append_trace(event)

    def record_fetch(self, result: Mapping[str, Any]) -> None:
        with self._lock:
            self._record_provider_and_freshness(result, include_freshness=False)
            self._add_source(dict(result.get("source") or result))
            self._append_page_read(result)
            self._add_evidence(
                {
                    "id": result.get("id") or result.get("source_handle"),
                    "title": result.get("title"),
                    "url": result.get("url"),
                    "excerpt": result.get("excerpt") or _first_excerpt(result.get("content")),
                    "source_handle": result.get("source_handle"),
                    "page_handle": result.get("page_handle"),
                    "source_class": result.get("source_class")
                    or (result.get("source") if isinstance(result.get("source"), Mapping) else {}).get("source_class"),
                    "quality": _inspection_quality(result),
                }
            )
            self._append_trace(
                {
                    "event": "fetched",
                    "tool": "web_fetch",
                    "url": result.get("url"),
                }
            )

    def record_find(self, result: Mapping[str, Any]) -> None:
        matches = _list_of_mappings(result.get("matches"))
        with self._lock:
            self._record_provider_and_freshness(result, include_freshness=False)
            query = _identity_value(result.get("query"))
            if query:
                self._append_query(query)
            source = result.get("source")
            if isinstance(source, Mapping):
                self._add_source(dict(source))
            for item in matches:
                self._add_evidence(item)
            self._append_trace(
                {
                    "event": "found",
                    "tool": "web_find",
                    "query": result.get("query"),
                    "match_count": len(matches),
                }
            )

    def record_conflict(self, conflict: Mapping[str, Any]) -> None:
        with self._lock:
            self.conflicts.append(dict(conflict))

    def record_gap(self, gap: Mapping[str, Any]) -> None:
        with self._lock:
            self.gaps.append(dict(gap))

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

    def record_unverified_child_metadata_dropped(self, events: Sequence[Mapping[str, Any]]) -> None:
        with self._lock:
            for event in events:
                self._append_trace(event)

    def finalize_provider_and_freshness_trace(self) -> None:
        with self._lock:
            freshness_days = self.request.get("policy", {}).get("freshness_days")
            if freshness_days is None:
                return
            if any(str(event.get("event", "")).startswith("freshness_") for event in self.trace):
                return
            status = "unsupported"
            if any(outcome.get("status") == "enforced" for outcome in self.freshness_outcomes):
                status = "enforced"
            elif any(outcome.get("status") == "satisfied" for outcome in self.freshness_outcomes):
                status = "satisfied"
            self._append_trace(
                {
                    "event": "freshness_enforced" if status == "enforced" else "freshness_unsupported",
                    "requested_days": freshness_days,
                    "status": status,
                }
            )

    def sources_payload(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.sources]

    def evidence_payload(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.evidence]

    def conflicts_payload(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.conflicts]

    def gaps_payload(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.gaps]

    def trace_summary(self, *, max_items: int = _DEFAULT_LOOP_TRACE_ITEMS) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.trace[-max_items:]]

    def queries_payload(self) -> list[str]:
        queries: list[str] = []
        with self._lock:
            for event in self.trace:
                query = _identity_value(event.get("query"))
                if query and query not in queries:
                    queries.append(query)
        return queries

    def pages_read_payload(self) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        seen: set[str] = set()
        with self._lock:
            for source in self.sources:
                key = _identity_value(source.get("page_handle") or source.get("source_handle") or source.get("url"))
                if not key or key in seen:
                    continue
                source_handle = _identity_value(source.get("source_handle") or source.get("id"))
                page_handle = _identity_value(source.get("page_handle"))
                url = _identity_value(source.get("url"))
                if not any(
                    _identity_value(evidence.get("url")) == url
                    or (source_handle and _identity_value(evidence.get("source_handle")) == source_handle)
                    or (page_handle and _identity_value(evidence.get("page_handle")) == page_handle)
                    for evidence in self.evidence
                ):
                    continue
                seen.add(key)
                pages.append(
                    {
                        "url": source.get("url"),
                        "title": source.get("title"),
                        "source_handle": source.get("source_handle") or source.get("id"),
                        "page_handle": source.get("page_handle"),
                    }
                )
        return pages

    def provider_payload(self) -> dict[str, Any] | None:
        with self._lock:
            for event in reversed(self.provider_events):
                if isinstance(event.get("provider_selection"), Mapping):
                    provider = event.get("provider")
                    return dict(provider) if isinstance(provider, Mapping) else None
            for event in reversed(self.provider_events):
                provider = event.get("provider")
                if isinstance(provider, Mapping):
                    return dict(provider)
            return None

    def provider_selection_payload(self) -> dict[str, Any] | None:
        with self._lock:
            for event in reversed(self.provider_events):
                selection = event.get("provider_selection")
                if isinstance(selection, Mapping):
                    return dict(selection)
            return None

    def provider_fallback_payload(self) -> dict[str, Any] | None:
        with self._lock:
            for event in reversed(self.provider_events):
                fallback = event.get("provider_fallback")
                if isinstance(fallback, Mapping):
                    return dict(fallback)
            return None

    def freshness_scope_payload(self) -> dict[str, Any]:
        with self._lock:
            freshness_days = self.request.get("policy", {}).get("freshness_days")
            if freshness_days is None:
                return {}
            status = "unsupported"
            if any(outcome.get("status") == "enforced" for outcome in self.freshness_outcomes):
                status = "enforced"
            elif any(outcome.get("status") == "satisfied" for outcome in self.freshness_outcomes):
                status = "satisfied"
            return {"requested_days": freshness_days, "status": status}

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
            freshness_satisfied = any(
                outcome.get("status") in {"enforced", "satisfied"} for outcome in self.freshness_outcomes
            )
            inspected_sources = self._inspected_source_count_locked()
            desired_sources = int(self.request["budget"].get("desired_source_count") or 1)
        if not has_evidence:
            if policy_rejections:
                return "policy_blocked"
            if budget_rejections:
                return "budget_exhausted"
            if freshness_requested and not freshness_satisfied:
                return "freshness_unsupported"
            if operation_failures:
                return "partial_result"
            mapped_status = web_research_stop_reason_from_status(child_status)
            return "partial_result" if mapped_status == "sufficient_evidence" else mapped_status
        if freshness_requested and not freshness_satisfied:
            return "freshness_unsupported"
        if self.provider_fallback_payload() and self.provider_fallback_payload().get("used") and self.request.get(
            "freshness_required"
        ):
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
        for existing in self.sources:
            if existing.get("url") != url:
                continue
            for key in ("source_class", "quality"):
                if key in item:
                    existing[key] = item[key]
            return
        source = {
            "id": item.get("id") or item.get("source_handle") or url,
            "title": item.get("title") or url,
            "url": url,
            "source_handle": item.get("source_handle") or item.get("id"),
            "page_handle": item.get("page_handle"),
            "domain": item.get("domain"),
        }
        for key in ("source_class", "quality"):
            if key in item:
                source[key] = item[key]
        self._attach_provider_source_metadata(source, item)
        self.sources.append(source)

    def _add_evidence(self, item: Mapping[str, Any]) -> None:
        excerpt = str(item.get("excerpt") or item.get("content") or "").strip()
        url = str(item.get("url") or "").strip()
        if not excerpt and not url:
            return
        key = (url, excerpt)
        if any((existing.get("url"), existing.get("excerpt")) == key for existing in self.evidence):
            return
        evidence = {
            "id": item.get("id") or item.get("source_handle") or url,
            "title": item.get("title"),
            "url": url,
            "excerpt": excerpt,
            "source_handle": item.get("source_handle"),
            "page_handle": item.get("page_handle"),
            **_optional_fact_fields(item, ("exact_excerpt", "match_start", "match_end")),
        }
        for key in ("source_class", "quality"):
            if key in item:
                evidence[key] = item[key]
        self._attach_provider_source_metadata(evidence, item)
        self.evidence.append(evidence)

    def _inspected_source_count_locked(self) -> int:
        keys: set[str] = set()
        for item in self.evidence:
            key = _identity_value(item.get("source_handle") or item.get("page_handle") or item.get("url"))
            if key:
                keys.add(key)
        return len(keys)

    def _append_trace(self, event: Mapping[str, Any]) -> None:
        self.trace.append(dict(event))
        if len(self.trace) > _DEFAULT_LOOP_TRACE_ITEMS * 4:
            del self.trace[: len(self.trace) - _DEFAULT_LOOP_TRACE_ITEMS * 4]

    def _append_query(self, query: str) -> None:
        if any(event.get("event") == "query_planned" and event.get("query") == query for event in self.trace):
            return
        self._append_trace({"event": "query_planned", "query": query, "profile": self.profile})

    def _append_page_read(self, page: Mapping[str, Any]) -> None:
        url = _identity_value(page.get("url"))
        if not url:
            return
        if any(event.get("event") == "page_read" and event.get("url") == url for event in self.trace):
            return
        self._append_trace(
            {
                "event": "page_read",
                "url": url,
                "title": page.get("title"),
                "source_handle": page.get("source_handle"),
                "page_handle": page.get("page_handle"),
            }
        )

    def _record_provider_and_freshness(self, result: Mapping[str, Any], *, include_freshness: bool = True) -> None:
        provider = result.get("provider")
        selection = result.get("provider_selection")
        fallback = result.get("provider_fallback")
        if isinstance(provider, Mapping):
            event = {
                "provider": dict(provider),
                "provider_selection": dict(selection) if isinstance(selection, Mapping) else None,
                "provider_fallback": dict(fallback) if isinstance(fallback, Mapping) else None,
            }
            self.provider_events.append(event)
            if isinstance(fallback, Mapping) and fallback.get("used"):
                self._append_trace(
                    {
                        "event": "provider_fallback",
                        "from": fallback.get("from"),
                        "selected": fallback.get("selected"),
                    }
                )
        freshness_scope = result.get("freshness_scope") if include_freshness else None
        if isinstance(freshness_scope, Mapping):
            self.freshness_outcomes.append(dict(freshness_scope))
            status = freshness_scope.get("status")
            if status in {"enforced", "satisfied", "unsupported", "unsatisfied"}:
                self._append_trace(
                    {
                        "event": "freshness_enforced" if status in {"enforced", "satisfied"} else "freshness_unsupported",
                        "requested_days": freshness_scope.get("requested_days"),
                        "status": status,
                    }
                )

    def _attach_provider_source_metadata(self, target: dict[str, Any], item: Mapping[str, Any]) -> None:
        metadata = item.get("metadata")
        provider = item.get("provider")
        freshness_scope = item.get("freshness_scope")
        if isinstance(metadata, Mapping):
            provider = provider or metadata.get("provider")
            freshness_scope = freshness_scope or metadata.get("freshness_scope")
        if isinstance(provider, Mapping):
            target["provider"] = dict(provider)
        if isinstance(freshness_scope, Mapping):
            target["freshness_scope"] = dict(freshness_scope)


def build_policy(
    raw: Mapping[str, Any] | None = None,
    *,
    default_search_limit: int = 8,
    default_text_chars: int = _DEFAULT_FETCH_CHARS,
    default_find_matches: int = 5,
) -> WebResearchPolicy:
    payload = {} if raw is None else dict(raw)
    freshness_payload = payload.get("freshness")
    freshness_days = payload.get("freshness_days")
    if freshness_days is None:
        freshness_days = payload.get("recency_days")
    if freshness_days is None and isinstance(freshness_payload, Mapping):
        freshness_days = freshness_payload.get("days")
    freshness_required = payload.get("freshness_required")
    if freshness_required is None and isinstance(freshness_payload, Mapping):
        freshness_required = freshness_payload.get("required")
    return WebResearchPolicy(
        allowed_domains=_normalize_domains(payload.get("domains") or payload.get("allowed_domains")),
        blocked_domains=_normalize_domains(payload.get("blocked_domains")),
        freshness_days=_normalize_optional_int(freshness_days, minimum=0),
        freshness_required=_normalize_bool(freshness_required),
        provider=_normalize_optional_string(payload.get("provider") or payload.get("search_provider")),
        max_fetch_bytes=_normalize_optional_int(payload.get("max_fetch_bytes"), minimum=1) or _DEFAULT_FETCH_BYTES,
        max_text_chars=_normalize_optional_int(payload.get("max_chars"), minimum=500) or default_text_chars,
        max_search_results=_normalize_optional_int(payload.get("limit"), minimum=1) or default_search_limit,
        max_find_matches=_normalize_optional_int(payload.get("limit"), minimum=1) or default_find_matches,
        excerpt_chars=_normalize_optional_int(payload.get("excerpt_chars"), minimum=80) or 280,
    )


class DuckDuckGoHtmlBackend:
    provider_metadata = WebSearchProviderMetadata(
        provider_id="duckduckgo-html",
        display_name="DuckDuckGo HTML",
        capabilities=WebSearchProviderCapabilities(
            domain_filtering=False,
            blocked_domain_filtering=False,
            result_limit=True,
            freshness=False,
            fetch=True,
            page_find=True,
            usage="Built-in no-credential compatibility provider; search constraints are post-filtered by the core.",
        ),
        credential_required=False,
        configured=True,
        notes="DuckDuckGo HTML does not expose a stable freshness/recency filter through this adapter.",
    )

    def __init__(
        self,
        *,
        urlopen: Callable[..., Any] | None = None,
        search_base_url: str = _DEFAULT_SEARCH_BASE_URL,
    ) -> None:
        self._urlopen = urlopen or web_urlopen
        self._search_base_url = search_base_url

    def search(
        self,
        query: str,
        *,
        limit: int,
        policy: WebResearchPolicy | None = None,
    ) -> list[BackendSearchResult]:
        _ = policy
        encoded = urllib.parse.urlencode({"q": query})
        url = f"{self._search_base_url}?{encoded}"
        request = urllib.request.Request(url, headers={"User-Agent": "weavert/0.1"})
        with self._urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
        results: list[BackendSearchResult] = []
        for match in re.finditer(
            r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            body,
        ):
            title = html.unescape(_HTML_TAG_RE.sub("", match.group("title"))).strip()
            normalized_url = normalize_web_url(match.group("href"), search_base_url=self._search_base_url)
            if normalized_url is None:
                continue
            results.append(BackendSearchResult(title=title or normalized_url, url=normalized_url))
            if len(results) >= limit:
                break
        return results

    def fetch(self, url: str, *, timeout: float, max_bytes: int) -> BackendFetchResult:
        request = urllib.request.Request(url, headers={"User-Agent": "weavert/0.1"})
        with self._urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            body = raw.decode("utf-8", errors="replace")
            content_type = response.headers.get_content_type()
            resolved_url = normalize_web_url(response_url(response)) or url
            title = extract_html_title(body) if "html" in content_type else None
            return BackendFetchResult(
                url=resolved_url,
                status=getattr(response, "status", 200),
                content_type=content_type,
                body=body,
                raw_bytes=len(raw),
                title=title,
            )

    def find(
        self,
        page: Mapping[str, Any],
        pattern: str,
        *,
        limit: int,
        excerpt_chars: int,
    ) -> list[BackendFindMatch]:
        content = str(page.get("content") or "")
        if not content:
            return []
        compiled = re.compile(re.escape(pattern), re.IGNORECASE)
        matches: list[BackendFindMatch] = []
        for match in compiled.finditer(content):
            start, end = match.span()
            matches.append(
                BackendFindMatch(
                    excerpt=_excerpt_window(content, start=start, end=end, limit=excerpt_chars),
                    start=start,
                    end=end,
                    exact_text=content[start:end],
                )
            )
            if len(matches) >= limit:
                break
        return matches


class BraveSearchApiProvider:
    provider_metadata = WebSearchProviderMetadata(
        provider_id="brave-search",
        display_name="Brave Search API",
        capabilities=WebSearchProviderCapabilities(
            domain_filtering=True,
            blocked_domain_filtering=True,
            result_limit=True,
            freshness=True,
            fetch=False,
            page_find=False,
            usage=(
                "Optional live provider. Configure with BRAVE_SEARCH_API_KEY or "
                "WEAVERT_BRAVE_SEARCH_API_KEY; freshness maps to Brave's freshness parameter."
            ),
        ),
        credential_required=True,
        configured=False,
        notes="Domain allow/block constraints are mapped to Brave query operators and still revalidated by the core.",
    )

    def __init__(
        self,
        *,
        api_key: str | None = None,
        urlopen: Callable[..., Any] | None = None,
        endpoint: str = "https://api.search.brave.com/res/v1/web/search",
    ) -> None:
        self._api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY") or os.environ.get(
            "WEAVERT_BRAVE_SEARCH_API_KEY"
        )
        self._urlopen = urlopen or web_urlopen
        self._endpoint = endpoint
        configured = bool(self._api_key)
        self.provider_metadata = WebSearchProviderMetadata(
            provider_id="brave-search",
            display_name="Brave Search API",
            capabilities=self.__class__.provider_metadata.capabilities,
            credential_required=True,
            configured=configured,
            notes=self.__class__.provider_metadata.notes,
        )

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def search(
        self,
        query: str,
        *,
        limit: int,
        policy: WebResearchPolicy | None = None,
    ) -> list[BackendSearchResult]:
        if not self._api_key:
            raise ValueError("Brave Search API provider requires BRAVE_SEARCH_API_KEY")
        resolved_policy = policy or WebResearchPolicy()
        params: dict[str, Any] = {
            "q": _query_with_domain_operators(
                query,
                allowed_domains=resolved_policy.allowed_domains,
                blocked_domains=resolved_policy.blocked_domains,
            ),
            "count": max(1, min(int(limit), 20)),
        }
        freshness = _brave_freshness_parameter(resolved_policy.freshness_days)
        if freshness is not None:
            params["freshness"] = freshness
        request = urllib.request.Request(
            f"{self._endpoint}?{urllib.parse.urlencode(params)}",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "weavert/0.1",
                "X-Subscription-Token": self._api_key,
            },
        )
        with self._urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        raw_results = payload.get("web", {}).get("results", [])
        if not isinstance(raw_results, list):
            return []
        results: list[BackendSearchResult] = []
        for raw in raw_results:
            if not isinstance(raw, Mapping):
                continue
            normalized_url = normalize_web_url(raw.get("url"))
            if normalized_url is None:
                continue
            title = _normalize_optional_string(raw.get("title")) or normalized_url
            excerpt = _normalize_optional_string(raw.get("description")) or _normalize_optional_string(raw.get("snippet")) or ""
            metadata = {
                key: raw[key]
                for key in ("age", "page_age", "published", "language", "family_friendly")
                if key in raw
            }
            results.append(BackendSearchResult(title=title, url=normalized_url, excerpt=excerpt, metadata=metadata))
            if len(results) >= limit:
                break
        return results

    def fetch(self, url: str, *, timeout: float, max_bytes: int) -> BackendFetchResult:
        _ = url, timeout, max_bytes
        raise NotImplementedError("BraveSearchApiProvider only implements search")

    def find(
        self,
        page: Mapping[str, Any],
        pattern: str,
        *,
        limit: int,
        excerpt_chars: int,
    ) -> list[BackendFindMatch]:
        _ = page, pattern, limit, excerpt_chars
        raise NotImplementedError("BraveSearchApiProvider only implements search")


class GoogleSearchApiProvider:
    provider_metadata = WebSearchProviderMetadata(
        provider_id="google-search",
        display_name="Google Programmable Search JSON API",
        capabilities=WebSearchProviderCapabilities(
            domain_filtering=True,
            blocked_domain_filtering=True,
            result_limit=True,
            freshness=True,
            fetch=False,
            page_find=False,
            usage=(
                "Optional live provider. Configure with GOOGLE_SEARCH_API_KEY and "
                "GOOGLE_SEARCH_CX; freshness maps to Google's dateRestrict parameter."
            ),
        ),
        credential_required=True,
        configured=False,
        notes="Domain allow/block constraints are mapped to Google query operators and still revalidated by the core.",
    )

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cx: str | None = None,
        urlopen: Callable[..., Any] | None = None,
        endpoint: str = "https://www.googleapis.com/customsearch/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("GOOGLE_SEARCH_API_KEY")
        self._cx = cx or os.environ.get("GOOGLE_SEARCH_CX")
        self._urlopen = urlopen or web_urlopen
        self._endpoint = endpoint
        configured = bool(self._api_key and self._cx)
        self.provider_metadata = WebSearchProviderMetadata(
            provider_id="google-search",
            display_name="Google Programmable Search JSON API",
            capabilities=self.__class__.provider_metadata.capabilities,
            credential_required=True,
            configured=configured,
            notes=self.__class__.provider_metadata.notes,
        )

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._cx)

    def search(
        self,
        query: str,
        *,
        limit: int,
        policy: WebResearchPolicy | None = None,
    ) -> list[BackendSearchResult]:
        if not self._api_key or not self._cx:
            raise ValueError("Google Search API provider requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX")
        resolved_policy = policy or WebResearchPolicy()
        params: dict[str, Any] = {
            "key": self._api_key,
            "cx": self._cx,
            "q": _query_with_domain_operators(
                query,
                allowed_domains=resolved_policy.allowed_domains,
                blocked_domains=resolved_policy.blocked_domains,
            ),
            "num": max(1, min(int(limit), 10)),
        }
        date_restrict = _google_date_restrict_parameter(resolved_policy.freshness_days)
        if date_restrict is not None:
            params["dateRestrict"] = date_restrict
        request = urllib.request.Request(
            f"{self._endpoint}?{urllib.parse.urlencode(params)}",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "weavert/0.1",
            },
        )
        with self._urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        raw_results = payload.get("items", [])
        if not isinstance(raw_results, list):
            return []
        results: list[BackendSearchResult] = []
        for raw in raw_results:
            if not isinstance(raw, Mapping):
                continue
            normalized_url = normalize_web_url(raw.get("link"))
            if normalized_url is None:
                continue
            title = _normalize_optional_string(raw.get("title")) or normalized_url
            excerpt = _normalize_optional_string(raw.get("snippet")) or _normalize_optional_string(
                raw.get("htmlSnippet")
            ) or ""
            metadata = {
                key: raw[key]
                for key in ("displayLink", "formattedUrl", "htmlFormattedUrl", "mime", "fileFormat")
                if key in raw
            }
            if "pagemap" in raw and isinstance(raw["pagemap"], Mapping):
                metadata["pagemap"] = dict(raw["pagemap"])
            results.append(BackendSearchResult(title=title, url=normalized_url, excerpt=excerpt, metadata=metadata))
            if len(results) >= limit:
                break
        return results

    def fetch(self, url: str, *, timeout: float, max_bytes: int) -> BackendFetchResult:
        _ = url, timeout, max_bytes
        raise NotImplementedError("GoogleSearchApiProvider only implements search")

    def find(
        self,
        page: Mapping[str, Any],
        pattern: str,
        *,
        limit: int,
        excerpt_chars: int,
    ) -> list[BackendFindMatch]:
        _ = page, pattern, limit, excerpt_chars
        raise NotImplementedError("GoogleSearchApiProvider only implements search")


class FixtureWebResearchProvider:
    def __init__(
        self,
        *,
        provider_id: str = "fixture-web",
        display_name: str = "Fixture Web Provider",
        search_results: Mapping[str, Sequence[BackendSearchResult | Mapping[str, Any]]] | None = None,
        pages: Mapping[str, BackendFetchResult | Mapping[str, Any] | str] | None = None,
        supports_freshness: bool = False,
        fail_search: bool = False,
        fail_fetch_urls: Sequence[str] = (),
    ) -> None:
        self.provider_metadata = WebSearchProviderMetadata(
            provider_id=provider_id,
            display_name=display_name,
            capabilities=WebSearchProviderCapabilities(
                domain_filtering=True,
                blocked_domain_filtering=True,
                result_limit=True,
                freshness=supports_freshness,
                fetch=True,
                page_find=True,
                usage="Deterministic fixture provider for workflow and shared-core tests.",
            ),
        )
        self._search_results = {
            str(query): tuple(_coerce_search_result(item) for item in items)
            for query, items in dict(search_results or {}).items()
        }
        self._pages = dict(pages or {})
        self._fail_search = fail_search
        self._fail_fetch_urls = {str(url) for url in fail_fetch_urls}

    def search(
        self,
        query: str,
        *,
        limit: int,
        policy: WebResearchPolicy | None = None,
    ) -> list[BackendSearchResult]:
        if self._fail_search:
            raise ValueError("fixture search failure")
        resolved_policy = policy or WebResearchPolicy()
        results = list(self._search_results.get(query, ()))
        return _filter_search_results(results, policy=resolved_policy)[:limit]

    def fetch(self, url: str, *, timeout: float, max_bytes: int) -> BackendFetchResult:
        _ = timeout, max_bytes
        if url in self._fail_fetch_urls:
            raise ValueError("fixture fetch failure")
        raw = self._pages.get(url)
        if raw is None:
            raise ValueError(f"fixture page not found: {url}")
        if isinstance(raw, BackendFetchResult):
            return raw
        if isinstance(raw, str):
            return BackendFetchResult(
                url=url,
                status=200,
                content_type="text/html",
                body=raw,
                raw_bytes=len(raw.encode("utf-8")),
                title=extract_html_title(raw),
            )
        return BackendFetchResult(
            url=str(raw.get("url") or url),
            status=int(raw.get("status") or 200),
            content_type=str(raw.get("content_type") or "text/html"),
            body=str(raw.get("body") or raw.get("content") or ""),
            raw_bytes=int(raw.get("raw_bytes") or len(str(raw.get("body") or raw.get("content") or "").encode("utf-8"))),
            title=_normalize_optional_string(raw.get("title")),
        )

    def find(
        self,
        page: Mapping[str, Any],
        pattern: str,
        *,
        limit: int,
        excerpt_chars: int,
    ) -> list[BackendFindMatch]:
        return DuckDuckGoHtmlBackend().find(page, pattern, limit=limit, excerpt_chars=excerpt_chars)


class WebSearchProviderRegistry:
    def __init__(
        self,
        providers: Sequence[WebResearchBackend],
        *,
        default_provider: str | None = None,
    ) -> None:
        ordered: list[WebResearchBackend] = []
        seen: set[str] = set()
        for provider in providers:
            provider_id = _provider_id(provider)
            if provider_id in seen:
                continue
            ordered.append(provider)
            seen.add(provider_id)
        if not ordered:
            raise ValueError("WebSearchProviderRegistry requires at least one provider")
        self._providers = tuple(ordered)
        self._default_provider = default_provider

    @property
    def providers(self) -> tuple[WebResearchBackend, ...]:
        return self._providers

    def plan(
        self,
        *,
        requested_provider: str | None = None,
        prefer_freshness: bool = False,
    ) -> tuple[list[dict[str, Any]], list[WebResearchBackend]]:
        requested = _normalize_optional_string(requested_provider or self._default_provider)
        initial_events: list[dict[str, Any]] = []
        if requested is not None:
            matched = [provider for provider in self._providers if _provider_id(provider) == requested]
            remaining = [provider for provider in self._providers if _provider_id(provider) != requested]
            if matched:
                return initial_events, [*matched, *remaining]
            initial_events.append(
                {
                    "provider": requested,
                    "status": "unavailable",
                    "reason": "requested_provider_not_registered_or_configured",
                }
            )
        providers = list(self._providers)
        if prefer_freshness:
            providers.sort(key=lambda provider: (not _provider_capabilities(provider).freshness, _provider_id(provider)))
        return initial_events, providers


def default_web_search_provider_registry(
    *,
    duckduckgo_urlopen: Callable[..., Any] | None = None,
) -> WebSearchProviderRegistry:
    requested = _normalize_optional_string(os.environ.get("WEAVERT_WEB_SEARCH_PROVIDER"))
    providers: list[WebResearchBackend] = []
    google = GoogleSearchApiProvider()
    if google.configured:
        providers.append(google)
    brave = BraveSearchApiProvider()
    if brave.configured:
        providers.append(brave)
    providers.append(DuckDuckGoHtmlBackend(urlopen=duckduckgo_urlopen))
    return WebSearchProviderRegistry(providers, default_provider=requested)


def search_web(
    query: str,
    *,
    backend: WebResearchBackend | None = None,
    registry: WebSearchProviderRegistry | None = None,
    provider: str | None = None,
    allow_provider_fallback: bool = True,
    policy: WebResearchPolicy | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or WebResearchPolicy()
    requested_provider = provider or resolved_policy.provider
    resolved_registry = registry
    if resolved_registry is None:
        if backend is not None:
            resolved_registry = WebSearchProviderRegistry((backend,))
        else:
            resolved_registry = default_web_search_provider_registry()
    initial_attempts, candidates = resolved_registry.plan(
        requested_provider=requested_provider,
        prefer_freshness=resolved_policy.freshness_days is not None,
    )
    attempts: list[dict[str, Any]] = list(initial_attempts)
    selected_provider: WebResearchBackend | None = None
    raw_results: list[BackendSearchResult] = []
    last_error: Exception | None = None
    for candidate in candidates:
        provider_id = _provider_id(candidate)
        try:
            raw_results = _provider_search(
                candidate,
                query,
                limit=resolved_policy.max_search_results,
                policy=resolved_policy,
            )
        except Exception as exc:
            attempts.append({"provider": provider_id, "status": "failed", "error": _first_error_line(exc)})
            last_error = exc
            if not allow_provider_fallback:
                raise
            continue
        attempts.append({"provider": provider_id, "status": "selected"})
        selected_provider = candidate
        break
    if selected_provider is None:
        if last_error is not None:
            raise last_error
        raise ValueError("No web search provider is available")
    provider_metadata = _provider_metadata(selected_provider)
    filtered = _filter_search_results(raw_results, policy=resolved_policy)
    search_handle = _stable_handle("search", f"{query}|{resolved_policy.allowed_domains}|{resolved_policy.blocked_domains}")
    freshness_scope = _freshness_scope_dict(resolved_policy, provider=selected_provider)
    constraint_outcomes = _constraint_outcomes(resolved_policy, provider=selected_provider, freshness_scope=freshness_scope)
    provider_selection = _provider_selection_payload(
        requested_provider=requested_provider,
        selected_provider=selected_provider,
        attempts=attempts,
    )
    return {
        "query": query,
        "search_handle": search_handle,
        "results": [
            _build_search_result(
                item,
                rank=index,
                policy=resolved_policy,
                search_handle=search_handle,
                provider_metadata=provider_metadata,
                freshness_scope=freshness_scope,
                constraint_outcomes=constraint_outcomes,
            )
            for index, item in enumerate(filtered, start=1)
        ],
        "policy": _policy_dict(resolved_policy),
        "backend": provider_metadata["id"],
        "provider": provider_metadata,
        "provider_selection": provider_selection,
        "provider_fallback": _provider_fallback_payload(provider_selection),
        "constraint_outcomes": constraint_outcomes,
        **_freshness_scope_payload(resolved_policy, provider=selected_provider),
    }


def inspect_page(
    raw: Mapping[str, Any],
    *,
    backend: WebResearchBackend | None = None,
    policy: WebResearchPolicy | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or WebResearchPolicy()
    resolved_backend = backend or DuckDuckGoHtmlBackend()
    provider_metadata = _provider_metadata(resolved_backend)
    normalized = validate_fetch_input(raw, policy=resolved_policy).normalized_url
    timeout = max(1, int(raw.get("timeout_ms", 10_000))) / 1000
    fetched = resolved_backend.fetch(normalized, timeout=timeout, max_bytes=resolved_policy.max_fetch_bytes)
    resolved_url = _revalidate_final_fetch_url(fetched.url, policy=resolved_policy)
    normalized_text = normalize_remote_text(fetched.body, content_type=fetched.content_type)
    truncated = fetched.raw_bytes > resolved_policy.max_fetch_bytes or len(normalized_text) > resolved_policy.max_text_chars
    content = truncate_text(normalized_text, resolved_policy.max_text_chars)
    page_handle = _stable_handle("page", resolved_url)
    source_handle = _stable_handle("source", resolved_url)
    title = fetched.title or _normalize_optional_string(raw.get("title")) or resolved_url
    source = _source_descriptor(title=title, url=resolved_url, page_handle=page_handle, source_handle=source_handle)
    for key in ("source_class", "quality"):
        if key in raw:
            source[key] = raw[key]
    policy_payload = _policy_dict(resolved_policy)
    policy_payload["truncated"] = truncated
    return {
        "id": source_handle,
        "title": title,
        "excerpt": truncate_text(content, 240),
        "content": content,
        "url": resolved_url,
        "status": fetched.status,
        "content_type": fetched.content_type,
        "truncated": truncated,
        "source_kind": "external",
        "metadata": {
            "source_handle": source_handle,
            "page_handle": page_handle,
            "status": fetched.status,
            "content_type": fetched.content_type,
            "fetched_at": _timestamp(),
            "policy": dict(policy_payload),
        },
        "source_handle": source_handle,
        "page_handle": page_handle,
        "source": source,
        **({"source_class": raw["source_class"]} if "source_class" in raw else {}),
        **({"quality": dict(raw["quality"])} if isinstance(raw.get("quality"), Mapping) else {}),
        "policy": policy_payload,
        "provider": provider_metadata,
        "browser_handoff": build_browser_handoff(source),
        **_freshness_scope_payload(resolved_policy, provider=resolved_backend),
    }


def find_in_page(
    raw: Mapping[str, Any],
    *,
    backend: WebResearchBackend | None = None,
    policy: WebResearchPolicy | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or WebResearchPolicy()
    page_validation = validate_page_find_input(raw, policy=resolved_policy)
    page = raw.get("page")
    assert isinstance(page, Mapping)
    pattern = _normalize_optional_string(raw.get("pattern"))
    if pattern is None:
        raise ValueError("pattern must be non-empty")
    resolved_backend = backend or DuckDuckGoHtmlBackend()
    provider_metadata = _provider_metadata(resolved_backend)
    page_handle = page_validation.page_handle
    source_handle = page_validation.source_handle
    title = page_validation.title
    url = page_validation.url
    source = dict(page_validation.source)
    matches = resolved_backend.find(
        page,
        pattern,
        limit=resolved_policy.max_find_matches,
        excerpt_chars=resolved_policy.excerpt_chars,
    )
    items: list[dict[str, Any]] = []
    for index, match in enumerate(matches, start=1):
        match_handle = _stable_handle("match", f"{page_handle}:{index}:{match.start}:{match.end}:{pattern.lower()}")
        items.append(
            {
                "id": match_handle,
                "title": title,
                "excerpt": match.excerpt,
                "content": match.exact_text,
                "url": url,
                "source_kind": "external",
                "metadata": {
                    "source_handle": source_handle,
                    "page_handle": page_handle,
                    "match_start": match.start,
                    "match_end": match.end,
                    "exact_excerpt": match.exact_text,
                },
                "source_handle": source_handle,
                "page_handle": page_handle,
                "match_start": match.start,
                "match_end": match.end,
                "exact_excerpt": match.exact_text,
                "source": dict(source),
                "browser_handoff": build_browser_handoff(source),
            }
        )
    return {
        "query": pattern,
        "page_handle": page_handle,
        "source_handle": source_handle,
        "matches": items,
        "source": dict(source),
        "policy": dict(page.get("policy") or _policy_dict(resolved_policy)),
        "provider": provider_metadata,
        "browser_handoff": build_browser_handoff(source),
        **_freshness_scope_payload(resolved_policy, provider=resolved_backend),
    }


def build_browser_handoff(source: Mapping[str, Any]) -> dict[str, Any]:
    url = _url_from_reference(source)
    title = str(source.get("title") or url or "Untitled source").strip() or "Untitled source"
    source_handle = str(source.get("source_handle") or source.get("id") or _stable_handle("source", url))
    page_handle = str(source.get("page_handle") or _stable_handle("page", url))
    return {
        "kind": "web_page",
        "title": title,
        "url": url,
        "source_handle": source_handle,
        "page_handle": page_handle,
        "domain": _domain(url),
        "approval_owner": "app",
        "allowlist_owner": "app",
        "audit_sink_owner": "app",
    }


def normalize_web_url(
    value: Any,
    *,
    search_base_url: str = _DEFAULT_SEARCH_BASE_URL,
) -> str | None:
    candidate = _normalize_optional_string(value)
    if candidate is None:
        return None
    candidate = html.unescape(candidate)
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    elif candidate.startswith("/"):
        candidate = urllib.parse.urljoin(search_base_url, candidate)
    parsed = urllib.parse.urlparse(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        return None
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if hostname in _DEFAULT_REDIRECT_HOSTS and parsed.path in {"/l", "/l/"}:
        redirect_targets = urllib.parse.parse_qs(parsed.query).get("uddg")
        if redirect_targets:
            return normalize_web_url(redirect_targets[0], search_base_url=search_base_url)
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def validate_web_url_input(
    value: Any,
    *,
    allowed_domains: Sequence[str] = (),
    blocked_domains: Sequence[str] = (),
    hostname_public_resolver: Callable[[str], bool | None] | None = None,
) -> str | None:
    normalized = normalize_web_url(value)
    if normalized is None:
        return "Only http:// and https:// URLs are supported"
    return validate_web_url(
        normalized,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
        hostname_public_resolver=hostname_public_resolver,
    )


def validate_fetch_input(
    raw: Mapping[str, Any],
    *,
    policy: WebResearchPolicy | None = None,
    hostname_public_resolver: Callable[[str], bool | None] | None = None,
) -> ValidationResult:
    normalized = normalize_web_url(_url_from_reference(raw))
    if normalized is None:
        raise ValueError("Only http:// and https:// URLs are supported")
    resolved_policy = policy or WebResearchPolicy()
    validation_error = validate_web_url(
        normalized,
        allowed_domains=resolved_policy.allowed_domains,
        blocked_domains=resolved_policy.blocked_domains,
        hostname_public_resolver=hostname_public_resolver,
    )
    if validation_error is not None:
        raise ValueError(validation_error)
    return ValidationResult(normalized_url=normalized)


def validate_page_find_input(
    raw: Mapping[str, Any],
    *,
    policy: WebResearchPolicy | None = None,
    hostname_public_resolver: Callable[[str], bool | None] | None = None,
) -> PageValidationResult:
    page = raw.get("page")
    if not isinstance(page, Mapping):
        raise ValueError("page must be an inspected page object")
    normalized = validate_fetch_input(page, policy=policy, hostname_public_resolver=hostname_public_resolver).normalized_url
    page_handle = str(page.get("page_handle") or _stable_handle("page", normalized))
    source_handle = str(page.get("source_handle") or _stable_handle("source", normalized))
    title = str(page.get("title") or page.get("url") or "Untitled source").strip() or "Untitled source"
    source = page.get("source")
    if not isinstance(source, Mapping):
        source = _source_descriptor(title=title, url=normalized, page_handle=page_handle, source_handle=source_handle)
    return PageValidationResult(
        url=normalized,
        page_handle=page_handle,
        source_handle=source_handle,
        title=title,
        source=source,
    )


def validate_web_url(
    url: str,
    *,
    allowed_domains: Sequence[str] = (),
    blocked_domains: Sequence[str] = (),
    hostname_public_resolver: Callable[[str], bool | None] | None = None,
) -> str | None:
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname:
        return "Grounding fetch requires a public web hostname"
    if parsed.username is not None or parsed.password is not None:
        return "Grounding fetch does not allow embedded URL credentials"
    if hostname in _DEFAULT_BLOCKED_HOSTS or any(hostname.endswith(suffix) for suffix in _DEFAULT_BLOCKED_HOST_SUFFIXES):
        return "Grounding fetch only supports public web hosts"
    if allowed_domains and not _host_in_domains(hostname, allowed_domains):
        return "Grounding fetch is outside the allowed domains"
    if blocked_domains and _host_in_domains(hostname, blocked_domains):
        return "Grounding fetch is blocked for this domain"
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if "." not in hostname:
            return "Grounding fetch only supports public web hosts"
        resolver = hostname_public_resolver or web_hostname_resolves_publicly
        resolution_is_public = resolver(hostname)
        if resolution_is_public is False:
            return "Grounding fetch only supports public web hosts"
        return None
    if not address.is_global:
        return "Grounding fetch only supports public web hosts"
    return None


@lru_cache(maxsize=256)
def web_hostname_resolves_publicly(hostname: str) -> bool | None:
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
            address = ipaddress.ip_address(str(sockaddr[0]).strip())
        except ValueError:
            continue
        saw_address = True
        if not address.is_global:
            return False
    return True if saw_address else None


class _SafeWebRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(
        self,
        *,
        allowed_domains: Sequence[str] = (),
        blocked_domains: Sequence[str] = (),
        hostname_public_resolver: Callable[[str], bool | None] | None = None,
    ) -> None:
        super().__init__()
        self._allowed_domains = tuple(allowed_domains)
        self._blocked_domains = tuple(blocked_domains)
        self._hostname_public_resolver = hostname_public_resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        normalized = normalize_web_url(newurl)
        if normalized is None:
            raise urllib.error.HTTPError(newurl, code, "Only http:// and https:// URLs are supported", headers, fp)
        validation_error = validate_web_url(
            normalized,
            allowed_domains=self._allowed_domains,
            blocked_domains=self._blocked_domains,
            hostname_public_resolver=self._hostname_public_resolver,
        )
        if validation_error is not None:
            raise urllib.error.HTTPError(normalized, code, validation_error, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, normalized)


def web_urlopen(
    request: urllib.request.Request,
    *,
    timeout: float | int,
    allowed_domains: Sequence[str] = (),
    blocked_domains: Sequence[str] = (),
    hostname_public_resolver: Callable[[str], bool | None] | None = None,
):
    opener = urllib.request.build_opener(
        _SafeWebRedirectHandler(
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
            hostname_public_resolver=hostname_public_resolver,
        )
    )
    return opener.open(request, timeout=timeout)


def response_url(response: Any) -> str | None:
    resolver = getattr(response, "geturl", None)
    if callable(resolver):
        return _normalize_optional_string(resolver())
    return _normalize_optional_string(getattr(response, "url", None))


def normalize_remote_text(body: str, *, content_type: str) -> str:
    normalized = body
    if "html" in content_type:
        normalized = _HTML_SCRIPT_STYLE_RE.sub(" ", normalized)
        normalized = _HTML_TAG_RE.sub(" ", normalized)
        normalized = html.unescape(normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def extract_html_title(body: str) -> str | None:
    match = _HTML_TITLE_RE.search(body)
    if not match:
        return None
    title = html.unescape(_HTML_TAG_RE.sub("", match.group("title"))).strip()
    return title or None


def truncate_text(value: str, limit: int) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _build_search_result(
    item: BackendSearchResult,
    *,
    rank: int,
    policy: WebResearchPolicy,
    search_handle: str,
    provider_metadata: Mapping[str, Any],
    freshness_scope: Mapping[str, Any] | None,
    constraint_outcomes: Mapping[str, Any],
) -> dict[str, Any]:
    page_handle = _stable_handle("page", item.url)
    source_handle = _stable_handle("source", item.url)
    source = _source_descriptor(title=item.title, url=item.url, page_handle=page_handle, source_handle=source_handle)
    return {
        "id": source_handle,
        "title": item.title,
        "excerpt": "",
        "content": "",
        "url": item.url,
        "source_kind": "external",
        "metadata": {
            "search_handle": search_handle,
            "rank": rank,
            "source_handle": source_handle,
            "page_handle": page_handle,
            "policy": _policy_dict(policy),
            "provider": dict(provider_metadata),
            "constraint_outcomes": dict(constraint_outcomes),
            **({"freshness_scope": dict(freshness_scope)} if freshness_scope else {}),
            **({"provider_result_metadata": dict(item.metadata)} if item.metadata else {}),
        },
        "rank": rank,
        "source_handle": source_handle,
        "page_handle": page_handle,
        "source": source,
        "browser_handoff": build_browser_handoff(source),
    }


def _filter_search_results(
    results: Sequence[BackendSearchResult],
    *,
    policy: WebResearchPolicy,
) -> list[BackendSearchResult]:
    filtered: list[BackendSearchResult] = []
    for item in results:
        validation_error = validate_web_url(
            item.url,
            allowed_domains=policy.allowed_domains,
            blocked_domains=policy.blocked_domains,
        )
        if validation_error is not None:
            continue
        filtered.append(item)
        if len(filtered) >= policy.max_search_results:
            break
    return filtered


def _source_descriptor(
    *,
    title: str,
    url: str,
    page_handle: str,
    source_handle: str,
) -> dict[str, Any]:
    return {
        "id": source_handle,
        "title": title,
        "url": url,
        "domain": _domain(url),
        "source_handle": source_handle,
        "page_handle": page_handle,
        "fetched_at": _timestamp(),
    }


def _policy_dict(policy: WebResearchPolicy) -> dict[str, Any]:
    return {
        "allowed_domains": list(policy.allowed_domains),
        "blocked_domains": list(policy.blocked_domains),
        "freshness_hint_days": policy.freshness_days,
        "freshness_required": policy.freshness_required,
        "provider": policy.provider,
        "retrieval_budget": {
            "max_fetch_bytes": policy.max_fetch_bytes,
            "max_text_chars": policy.max_text_chars,
            "max_search_results": policy.max_search_results,
            "max_find_matches": policy.max_find_matches,
        },
    }


def _freshness_scope_payload(
    policy: WebResearchPolicy,
    *,
    provider: WebResearchBackend | None = None,
) -> dict[str, Any]:
    scope = _freshness_scope_dict(policy, provider=provider)
    return {"freshness_scope": scope} if scope else {}


def _freshness_scope_dict(
    policy: WebResearchPolicy,
    *,
    provider: WebResearchBackend | None = None,
) -> dict[str, Any] | None:
    if policy.freshness_days is None:
        return None
    status = "enforced" if provider is not None and _provider_capabilities(provider).freshness else "unsupported"
    return {
        "requested_days": policy.freshness_days,
        "status": status,
    }


def _constraint_outcomes(
    policy: WebResearchPolicy,
    *,
    provider: WebResearchBackend,
    freshness_scope: Mapping[str, Any] | None,
) -> dict[str, Any]:
    capabilities = _provider_capabilities(provider)
    return {
        "allowed_domains": {
            "requested": list(policy.allowed_domains),
            "status": _constraint_status(bool(policy.allowed_domains), capabilities.domain_filtering),
        },
        "blocked_domains": {
            "requested": list(policy.blocked_domains),
            "status": _constraint_status(bool(policy.blocked_domains), capabilities.blocked_domain_filtering),
        },
        "result_limit": {
            "requested": policy.max_search_results,
            "status": "enforced" if capabilities.result_limit else "best_effort",
        },
        "freshness": (
            dict(freshness_scope)
            if freshness_scope
            else {"requested_days": None, "status": "not_requested"}
        ),
    }


def _constraint_status(requested: bool, provider_supports: bool) -> str:
    if not requested:
        return "not_requested"
    return "enforced" if provider_supports else "post_filtered"


def _provider_selection_payload(
    *,
    requested_provider: str | None,
    selected_provider: WebResearchBackend,
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected = _provider_id(selected_provider)
    failed_or_unavailable = [dict(item) for item in attempts if item.get("status") != "selected"]
    return {
        "requested": requested_provider,
        "selected": selected,
        "status": "fallback" if failed_or_unavailable else "selected",
        "attempts": [dict(item) for item in attempts],
    }


def _provider_fallback_payload(selection: Mapping[str, Any]) -> dict[str, Any]:
    attempts = _list_of_mappings(selection.get("attempts"))
    failed_or_unavailable = [item for item in attempts if item.get("status") != "selected"]
    return {
        "used": bool(failed_or_unavailable),
        "selected": selection.get("selected"),
        "from": failed_or_unavailable[0].get("provider") if failed_or_unavailable else None,
        "attempts": failed_or_unavailable,
    }


def _provider_search(
    provider: WebResearchBackend,
    query: str,
    *,
    limit: int,
    policy: WebResearchPolicy,
) -> list[BackendSearchResult]:
    try:
        raw_results = provider.search(query, limit=limit, policy=policy)
    except TypeError as exc:
        try:
            raw_results = provider.search(query, limit=limit)  # type: ignore[call-arg]
        except TypeError:
            raise exc
    return [_coerce_search_result(item) for item in raw_results]


def _provider_id(provider: WebResearchBackend) -> str:
    metadata = getattr(provider, "provider_metadata", None)
    if isinstance(metadata, WebSearchProviderMetadata):
        return metadata.provider_id
    if isinstance(metadata, Mapping):
        value = _normalize_optional_string(metadata.get("id") or metadata.get("provider_id"))
        if value is not None:
            return value
    return provider.__class__.__name__.replace("_", "-").lower()


def _provider_capabilities(provider: WebResearchBackend) -> WebSearchProviderCapabilities:
    metadata = getattr(provider, "provider_metadata", None)
    if isinstance(metadata, WebSearchProviderMetadata):
        return metadata.capabilities
    if isinstance(metadata, Mapping):
        raw = metadata.get("capabilities")
        if isinstance(raw, WebSearchProviderCapabilities):
            return raw
        if isinstance(raw, Mapping):
            return WebSearchProviderCapabilities(
                domain_filtering=_normalize_bool(raw.get("domain_filtering")),
                blocked_domain_filtering=_normalize_bool(raw.get("blocked_domain_filtering")),
                result_limit=_normalize_bool(raw.get("result_limit"), default=True),
                freshness=_normalize_bool(raw.get("freshness")),
                fetch=_normalize_bool(raw.get("fetch"), default=True),
                page_find=_normalize_bool(raw.get("page_find"), default=True),
            )
    return WebSearchProviderCapabilities()


def _provider_metadata(provider: WebResearchBackend) -> dict[str, Any]:
    metadata = getattr(provider, "provider_metadata", None)
    if isinstance(metadata, WebSearchProviderMetadata):
        return _provider_metadata_dict(metadata)
    if isinstance(metadata, Mapping):
        provider_id = _normalize_optional_string(metadata.get("id") or metadata.get("provider_id")) or _provider_id(provider)
        display_name = _normalize_optional_string(metadata.get("name") or metadata.get("display_name")) or provider_id
        capabilities = _provider_capabilities(provider)
        return {
            "id": provider_id,
            "name": display_name,
            "capabilities": _capabilities_dict(capabilities),
            "credential_required": _normalize_bool(metadata.get("credential_required")),
            "configured": _normalize_bool(metadata.get("configured"), default=True),
            **({"notes": str(metadata["notes"])} if metadata.get("notes") else {}),
        }
    provider_id = _provider_id(provider)
    return {
        "id": provider_id,
        "name": provider_id,
        "capabilities": _capabilities_dict(_provider_capabilities(provider)),
        "credential_required": False,
        "configured": True,
    }


def _provider_metadata_dict(metadata: WebSearchProviderMetadata) -> dict[str, Any]:
    return {
        "id": metadata.provider_id,
        "name": metadata.display_name,
        "capabilities": _capabilities_dict(metadata.capabilities),
        "credential_required": metadata.credential_required,
        "configured": metadata.configured,
        **({"notes": metadata.notes} if metadata.notes else {}),
    }


def _capabilities_dict(capabilities: WebSearchProviderCapabilities) -> dict[str, Any]:
    return {
        "domain_filtering": capabilities.domain_filtering,
        "blocked_domain_filtering": capabilities.blocked_domain_filtering,
        "result_limit": capabilities.result_limit,
        "freshness": capabilities.freshness,
        "fetch": capabilities.fetch,
        "page_find": capabilities.page_find,
        **({"usage": capabilities.usage} if capabilities.usage else {}),
    }


def _coerce_search_result(raw: BackendSearchResult | Mapping[str, Any]) -> BackendSearchResult:
    if isinstance(raw, BackendSearchResult):
        return raw
    url = normalize_web_url(raw.get("url"))
    if url is None:
        url = str(raw.get("url") or "")
    return BackendSearchResult(
        title=str(raw.get("title") or url).strip() or url,
        url=url,
        excerpt=str(raw.get("excerpt") or raw.get("description") or raw.get("content") or "").strip(),
        metadata=dict(raw.get("metadata") or {}),
    )


def _query_with_domain_operators(
    query: str,
    *,
    allowed_domains: Sequence[str],
    blocked_domains: Sequence[str],
) -> str:
    parts = [query.strip()]
    allowed = [f"site:{domain}" for domain in allowed_domains if domain]
    if allowed:
        parts.append("(" + " OR ".join(allowed) + ")")
    parts.extend(f"-site:{domain}" for domain in blocked_domains if domain)
    return " ".join(part for part in parts if part).strip()


def _brave_freshness_parameter(days: int | None) -> str | None:
    if days is None:
        return None
    if days <= 1:
        return "pd"
    if days <= 7:
        return "pw"
    if days <= 31:
        return "pm"
    if days <= 365:
        return "py"
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days)
    return f"{start.strftime('%Y-%m-%d')}to{today.strftime('%Y-%m-%d')}"


def _google_date_restrict_parameter(days: int | None) -> str | None:
    if days is None:
        return None
    if days <= 31:
        return f"d{max(1, days)}"
    if days <= 365:
        return f"m{max(1, round(days / 30))}"
    return f"y{max(1, round(days / 365))}"


def _first_error_line(exc: Exception) -> str:
    return str(exc).splitlines()[0][:240]


def _revalidate_final_fetch_url(url: str, *, policy: WebResearchPolicy) -> str:
    normalized = normalize_web_url(url)
    if normalized is None:
        raise ValueError("Only http:// and https:// URLs are supported")
    validation_error = validate_web_url(
        normalized,
        allowed_domains=policy.allowed_domains,
        blocked_domains=policy.blocked_domains,
    )
    if validation_error is not None:
        raise ValueError(validation_error)
    return normalized


def _normalize_domains(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = [str(item) for item in value]
    else:
        return ()
    normalized: list[str] = []
    for raw in values:
        item = raw.strip().lower()
        if not item:
            continue
        if item.startswith("www."):
            item = item[4:]
        normalized.append(item)
    return tuple(dict.fromkeys(normalized))


def _normalize_optional_int(value: Any, *, minimum: int) -> int | None:
    if value is None or value == "":
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, normalized)


def _normalize_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "required"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return default


def _list_of_mappings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


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


def _first_excerpt(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= 240:
        return text
    return text[:237].rstrip() + "..."


def _url_from_reference(raw: Mapping[str, Any]) -> str:
    url = _normalize_optional_string(raw.get("url"))
    if url is not None:
        return url
    source = raw.get("source")
    if isinstance(source, Mapping):
        nested_url = _normalize_optional_string(source.get("url"))
        if nested_url is not None:
            return nested_url
    raise ValueError("url is required")


def _domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return (parsed.hostname or "").rstrip(".").lower()


def _host_in_domains(hostname: str, domains: Sequence[str]) -> bool:
    normalized_hostname = hostname.rstrip(".").lower()
    for raw_domain in domains:
        domain = str(raw_domain).strip().lower().lstrip(".")
        if not domain:
            continue
        if normalized_hostname == domain or normalized_hostname.endswith(f".{domain}"):
            return True
    return False


def _stable_handle(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}::{digest}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _excerpt_window(content: str, *, start: int, end: int, limit: int) -> str:
    if not content:
        return ""
    half = max(20, limit // 2)
    left = max(0, start - half)
    right = min(len(content), end + half)
    return truncate_text(content[left:right].strip(), limit)
