from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Protocol

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


@dataclass(frozen=True, slots=True)
class WebResearchPolicy:
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    freshness_days: int | None = None
    max_fetch_bytes: int = _DEFAULT_FETCH_BYTES
    max_text_chars: int = _DEFAULT_FETCH_CHARS
    max_search_results: int = 8
    max_find_matches: int = 5
    excerpt_chars: int = 280


@dataclass(frozen=True, slots=True)
class BackendSearchResult:
    title: str
    url: str


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
    def search(self, query: str, *, limit: int) -> list[BackendSearchResult]: ...

    def fetch(self, url: str, *, timeout: float, max_bytes: int) -> BackendFetchResult: ...

    def find(
        self,
        page: Mapping[str, Any],
        pattern: str,
        *,
        limit: int,
        excerpt_chars: int,
    ) -> list[BackendFindMatch]: ...


def build_policy(
    raw: Mapping[str, Any] | None = None,
    *,
    default_search_limit: int = 8,
    default_text_chars: int = _DEFAULT_FETCH_CHARS,
    default_find_matches: int = 5,
) -> WebResearchPolicy:
    payload = {} if raw is None else dict(raw)
    return WebResearchPolicy(
        allowed_domains=_normalize_domains(payload.get("domains") or payload.get("allowed_domains")),
        blocked_domains=_normalize_domains(payload.get("blocked_domains")),
        freshness_days=_normalize_optional_int(payload.get("freshness_days"), minimum=0),
        max_fetch_bytes=_normalize_optional_int(payload.get("max_fetch_bytes"), minimum=1) or _DEFAULT_FETCH_BYTES,
        max_text_chars=_normalize_optional_int(payload.get("max_chars"), minimum=500) or default_text_chars,
        max_search_results=_normalize_optional_int(payload.get("limit"), minimum=1) or default_search_limit,
        max_find_matches=_normalize_optional_int(payload.get("limit"), minimum=1) or default_find_matches,
        excerpt_chars=_normalize_optional_int(payload.get("excerpt_chars"), minimum=80) or 280,
    )


class DuckDuckGoHtmlBackend:
    def __init__(
        self,
        *,
        urlopen: Callable[..., Any] | None = None,
        search_base_url: str = _DEFAULT_SEARCH_BASE_URL,
    ) -> None:
        self._urlopen = urlopen or web_urlopen
        self._search_base_url = search_base_url

    def search(self, query: str, *, limit: int) -> list[BackendSearchResult]:
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


def search_web(
    query: str,
    *,
    backend: WebResearchBackend | None = None,
    policy: WebResearchPolicy | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or WebResearchPolicy()
    resolved_backend = backend or DuckDuckGoHtmlBackend()
    raw_results = resolved_backend.search(query, limit=resolved_policy.max_search_results)
    filtered = _filter_search_results(raw_results, policy=resolved_policy)
    search_handle = _stable_handle("search", f"{query}|{resolved_policy.allowed_domains}|{resolved_policy.blocked_domains}")
    return {
        "query": query,
        "search_handle": search_handle,
        "results": [
            _build_search_result(item, rank=index, policy=resolved_policy, search_handle=search_handle)
            for index, item in enumerate(filtered, start=1)
        ],
        "policy": _policy_dict(resolved_policy),
        "backend": "duckduckgo-html",
    }


def inspect_page(
    raw: Mapping[str, Any],
    *,
    backend: WebResearchBackend | None = None,
    policy: WebResearchPolicy | None = None,
) -> dict[str, Any]:
    resolved_policy = policy or WebResearchPolicy()
    resolved_backend = backend or DuckDuckGoHtmlBackend()
    url = _url_from_reference(raw)
    normalized = normalize_web_url(url)
    if normalized is None:
        raise ValueError("Only http:// and https:// URLs are supported")
    validation_error = validate_web_url(
        normalized,
        allowed_domains=resolved_policy.allowed_domains,
        blocked_domains=resolved_policy.blocked_domains,
    )
    if validation_error is not None:
        raise ValueError(validation_error)
    timeout = max(1, int(raw.get("timeout_ms", 10_000))) / 1000
    fetched = resolved_backend.fetch(normalized, timeout=timeout, max_bytes=resolved_policy.max_fetch_bytes)
    normalized_text = normalize_remote_text(fetched.body, content_type=fetched.content_type)
    truncated = fetched.raw_bytes > resolved_policy.max_fetch_bytes or len(normalized_text) > resolved_policy.max_text_chars
    content = truncate_text(normalized_text, resolved_policy.max_text_chars)
    page_handle = _stable_handle("page", fetched.url)
    source_handle = _stable_handle("source", fetched.url)
    title = fetched.title or _normalize_optional_string(raw.get("title")) or fetched.url
    source = _source_descriptor(title=title, url=fetched.url, page_handle=page_handle, source_handle=source_handle)
    policy_payload = _policy_dict(resolved_policy)
    policy_payload["truncated"] = truncated
    return {
        "id": source_handle,
        "title": title,
        "excerpt": truncate_text(content, 240),
        "content": content,
        "url": fetched.url,
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
        "policy": policy_payload,
        "browser_handoff": build_browser_handoff(source),
    }


def find_in_page(
    raw: Mapping[str, Any],
    *,
    backend: WebResearchBackend | None = None,
    policy: WebResearchPolicy | None = None,
) -> dict[str, Any]:
    page = raw.get("page")
    if not isinstance(page, Mapping):
        raise ValueError("page must be an inspected page object")
    pattern = _normalize_optional_string(raw.get("pattern"))
    if pattern is None:
        raise ValueError("pattern must be non-empty")
    resolved_policy = policy or WebResearchPolicy()
    resolved_backend = backend or DuckDuckGoHtmlBackend()
    page_handle = str(page.get("page_handle") or _stable_handle("page", _url_from_reference(page)))
    source_handle = str(page.get("source_handle") or _stable_handle("source", _url_from_reference(page)))
    title = str(page.get("title") or page.get("url") or "Untitled source").strip() or "Untitled source"
    url = _url_from_reference(page)
    source = page.get("source")
    if not isinstance(source, Mapping):
        source = _source_descriptor(title=title, url=url, page_handle=page_handle, source_handle=source_handle)
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
        "browser_handoff": build_browser_handoff(source),
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
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        normalized = normalize_web_url(newurl)
        if normalized is None:
            raise urllib.error.HTTPError(newurl, code, "Only http:// and https:// URLs are supported", headers, fp)
        validation_error = validate_web_url(normalized)
        if validation_error is not None:
            raise urllib.error.HTTPError(normalized, code, validation_error, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, normalized)


def web_urlopen(request: urllib.request.Request, *, timeout: float | int):
    opener = urllib.request.build_opener(_SafeWebRedirectHandler())
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
        "retrieval_budget": {
            "max_fetch_bytes": policy.max_fetch_bytes,
            "max_text_chars": policy.max_text_chars,
            "max_search_results": policy.max_search_results,
            "max_find_matches": policy.max_find_matches,
        },
    }


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
