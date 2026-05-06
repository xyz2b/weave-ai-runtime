from __future__ import annotations

import asyncio
import html
import re
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .definitions import MemoryScope, ValidationOutcome
from .memory.models import MemoryDocument
from .tool_runtime import ToolContext

_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "been",
    "from",
    "have",
    "into",
    "just",
    "more",
    "that",
    "their",
    "them",
    "then",
    "they",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}
_HTML_TITLE_RE = re.compile(r"<title[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_HTML_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_FETCH_BYTES = 256_000
_DEFAULT_FETCH_CHARS = 12_000


@dataclass(frozen=True, slots=True)
class _GroundingCandidate:
    candidate_id: str
    title: str
    content: str
    url: str | None
    source_kind: str
    metadata: dict[str, Any]


def validate_retrieve_context_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    query = str(tool_input.get("query") or "").strip()
    if not query:
        return ValidationOutcome(False, "query must be non-empty")
    items = tool_input.get("items")
    if items is not None and not isinstance(items, list):
        return ValidationOutcome(False, "items must be an array when provided")
    include_memory = tool_input.get("include_memory", True)
    if not include_memory and not items:
        return ValidationOutcome(False, "items are required when include_memory is false")
    memory_scope = str(tool_input.get("memory_scope") or "").strip()
    if memory_scope and memory_scope not in {scope.value for scope in MemoryScope}:
        return ValidationOutcome(False, f"Unsupported memory_scope: {memory_scope}")
    return ValidationOutcome(True)


async def retrieve_context_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    query = str(tool_input["query"]).strip()
    limit = max(1, min(int(tool_input.get("limit", 5)), 12))
    include_memory = tool_input.get("include_memory", True)
    candidates = list(_inline_candidates(tool_input.get("items")))
    if include_memory:
        candidates.extend(_memory_candidates(context, tool_input.get("memory_scope")))

    query_tokens = _tokenize(query)
    if not candidates:
        return {"query": query, "results": [], "sources": {"external": 0, "memory": 0}}

    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        score = _candidate_score(query_tokens, candidate)
        if score <= 0:
            continue
        excerpt = _best_excerpt(query_tokens, candidate.content)
        scored.append(
            {
                "id": candidate.candidate_id,
                "title": candidate.title,
                "excerpt": excerpt,
                "content": _truncate_text(candidate.content, 600),
                "score": round(score, 3),
                "url": candidate.url,
                "source_kind": candidate.source_kind,
                "metadata": dict(candidate.metadata),
            }
        )
    scored.sort(key=lambda item: (-float(item["score"]), str(item["title"]).lower(), str(item["id"])))
    results = scored[:limit]
    return {
        "query": query,
        "results": results,
        "sources": {
            "external": sum(1 for item in results if item["source_kind"] == "external"),
            "memory": sum(1 for item in results if item["source_kind"] == "memory"),
        },
    }


def validate_prepare_citations_tool(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    items = tool_input.get("items")
    if not isinstance(items, list) or not items:
        return ValidationOutcome(False, "items must contain at least one citation candidate")
    return ValidationOutcome(True)


async def prepare_citations_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    limit = max(1, min(int(tool_input.get("limit", 5)), 12))
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in tool_input.get("items") or ():
        if not isinstance(raw, Mapping):
            continue
        title = str(raw.get("title") or raw.get("id") or "Untitled source").strip() or "Untitled source"
        excerpt = str(raw.get("excerpt") or raw.get("content") or "").strip()
        url = _normalize_optional_string(raw.get("url"))
        key = (str(raw.get("id") or title).strip() or title, url or "", excerpt)
        if key in seen:
            continue
        seen.add(key)
        label = f"[{len(citations) + 1}]"
        citation = {
            "label": label,
            "id": str(raw.get("id") or title).strip() or title,
            "title": title,
            "excerpt": _truncate_text(excerpt, 240),
            "url": url,
            "source_kind": str(raw.get("source_kind") or "external"),
            "metadata": dict(raw.get("metadata") or {}),
        }
        citations.append(citation)
        if len(citations) >= limit:
            break
    citation_block = "\n".join(_render_citation(citation) for citation in citations)
    return {"citations": citations, "citation_block": citation_block}


def validate_grounding_web_search(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    if not str(tool_input.get("query") or "").strip():
        return ValidationOutcome(False, "query must be non-empty")
    return ValidationOutcome(True)


async def grounding_web_search_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    query = str(tool_input["query"]).strip()
    limit = max(1, min(int(tool_input.get("limit", 5)), 8))
    encoded = urllib.parse.urlencode({"q": query})
    url = f"https://duckduckgo.com/html/?{encoded}"

    def search() -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "weavert/0.1"})
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
        results: list[dict[str, Any]] = []
        for match in re.finditer(
            r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            body,
        ):
            title = html.unescape(_HTML_TAG_RE.sub("", match.group("title"))).strip()
            href = html.unescape(match.group("href")).strip()
            if not href:
                continue
            results.append({"title": title or href, "url": href})
            if len(results) >= limit:
                break
        return {"query": query, "results": results}

    return await asyncio.to_thread(search)


def validate_grounding_web_fetch(tool_input: dict[str, Any], _: ToolContext) -> ValidationOutcome:
    url = str(tool_input.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return ValidationOutcome(False, "Only http:// and https:// URLs are supported")
    return ValidationOutcome(True)


async def grounding_web_fetch_tool(tool_input: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    timeout = max(1, int(tool_input.get("timeout_ms", 10_000))) / 1000
    max_chars = max(500, min(int(tool_input.get("max_chars", _DEFAULT_FETCH_CHARS)), 32_000))
    url = str(tool_input["url"]).strip()

    def fetch() -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "weavert/0.1"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_FETCH_BYTES + 1)
            content_type = response.headers.get_content_type()
            body = raw.decode("utf-8", errors="replace")
            normalized = _normalize_remote_text(body, content_type=content_type)
            truncated = len(raw) > _MAX_FETCH_BYTES or len(normalized) > max_chars
            title = _extract_html_title(body) if "html" in content_type else None
            return {
                "url": url,
                "status": getattr(response, "status", 200),
                "content_type": content_type,
                "title": title,
                "content": _truncate_text(normalized, max_chars),
                "truncated": truncated,
            }

    return await asyncio.to_thread(fetch)


def _inline_candidates(items: Any) -> tuple[_GroundingCandidate, ...]:
    if not isinstance(items, list):
        return ()
    candidates: list[_GroundingCandidate] = []
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, Mapping):
            continue
        content = str(raw.get("content") or raw.get("excerpt") or "").strip()
        if not content:
            continue
        title = str(raw.get("title") or raw.get("id") or f"Source {index}").strip() or f"Source {index}"
        candidate_id = str(raw.get("id") or f"source-{index}").strip() or f"source-{index}"
        metadata = dict(raw.get("metadata") or {})
        candidates.append(
            _GroundingCandidate(
                candidate_id=candidate_id,
                title=title,
                content=content,
                url=_normalize_optional_string(raw.get("url")),
                source_kind=str(raw.get("source_kind") or "external"),
                metadata=metadata,
            )
        )
    return tuple(candidates)


def _memory_candidates(context: ToolContext, scope_value: Any) -> tuple[_GroundingCandidate, ...]:
    services = context.runtime_services
    if services is None:
        return ()
    try:
        memory_service = services.resolve_memory_service()
    except Exception:
        return ()
    if memory_service is None:
        return ()
    resolver = getattr(memory_service, "context_for_scope", None)
    manager = getattr(memory_service, "manager", None)
    provider = getattr(manager, "provider", None)
    if not callable(resolver) or provider is None or not hasattr(provider, "list_documents"):
        return ()
    try:
        scope = _coerce_memory_scope(scope_value)
        resolved_scope = resolver(
            session_id=context.session_id,
            scope=scope,
            cwd=context.cwd,
        )
        documents = provider.list_documents(resolved_scope)
    except Exception:
        return ()
    return tuple(
        _candidate_from_memory_document(document, resolved_scope.memory_root)
        for document in documents
        if isinstance(document, MemoryDocument) and document.content.strip()
    )


def _candidate_from_memory_document(document: MemoryDocument, memory_root: Path) -> _GroundingCandidate:
    try:
        relative_path = document.path.relative_to(memory_root).as_posix()
    except ValueError:
        relative_path = document.path.name
    metadata = dict(document.metadata)
    metadata.setdefault("memory_scope", document.scope.value)
    metadata.setdefault("memory_path", relative_path)
    metadata.setdefault("memory_kind", document.kind)
    return _GroundingCandidate(
        candidate_id=relative_path,
        title=document.title,
        content=document.content,
        url=None,
        source_kind="memory",
        metadata=metadata,
    )


def _coerce_memory_scope(value: Any) -> MemoryScope:
    normalized = str(value or MemoryScope.PROJECT.value).strip() or MemoryScope.PROJECT.value
    try:
        return MemoryScope(normalized)
    except ValueError:
        return MemoryScope.PROJECT


def _candidate_score(query_tokens: set[str], candidate: _GroundingCandidate) -> float:
    combined = f"{candidate.title} {candidate.content}"
    combined_tokens = _tokenize(combined)
    if not query_tokens:
        return 0.0
    overlap = len(query_tokens & combined_tokens)
    if overlap <= 0:
        lowered_query = " ".join(sorted(query_tokens))
        if lowered_query and lowered_query not in combined.lower():
            return 0.0
    title_overlap = len(query_tokens & _tokenize(candidate.title))
    tag_overlap = len(query_tokens & _tokenize(" ".join(_string_values(candidate.metadata.get("tags")))))
    source_bonus = 0.25 if candidate.source_kind == "memory" else 0.0
    return float(overlap) + (0.5 * float(title_overlap)) + (0.25 * float(tag_overlap)) + source_bonus


def _best_excerpt(query_tokens: set[str], content: str, *, limit: int = 280) -> str:
    normalized = " ".join(content.strip().split())
    if not normalized:
        return ""
    for chunk in re.split(r"(?<=[.!?])\s+|\n+", normalized):
        candidate = chunk.strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if any(token in lowered for token in query_tokens):
            return _truncate_text(candidate, limit)
    return _truncate_text(normalized, limit)


def _render_citation(citation: Mapping[str, Any]) -> str:
    title = str(citation.get("title") or citation.get("id") or "Untitled source").strip() or "Untitled source"
    excerpt = str(citation.get("excerpt") or "").strip()
    url = _normalize_optional_string(citation.get("url"))
    suffix = f" — {url}" if url else ""
    if excerpt:
        return f"{citation['label']} {title}{suffix}: {excerpt}"
    return f"{citation['label']} {title}{suffix}"


def _normalize_remote_text(body: str, *, content_type: str) -> str:
    normalized = body
    if "html" in content_type:
        normalized = _HTML_SCRIPT_STYLE_RE.sub(" ", normalized)
        normalized = _HTML_TAG_RE.sub(" ", normalized)
        normalized = html.unescape(normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def _extract_html_title(body: str) -> str | None:
    match = _HTML_TITLE_RE.search(body)
    if not match:
        return None
    title = html.unescape(_HTML_TAG_RE.sub("", match.group("title"))).strip()
    return title or None


def _truncate_text(value: str, limit: int) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _string_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    }


__all__ = [
    "grounding_web_fetch_tool",
    "grounding_web_search_tool",
    "prepare_citations_tool",
    "retrieve_context_tool",
    "validate_grounding_web_fetch",
    "validate_grounding_web_search",
    "validate_prepare_citations_tool",
    "validate_retrieve_context_tool",
]
