from __future__ import annotations

import asyncio
import socket
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from weavert.definitions import ValidationOutcome
from weavert.tool_runtime import ToolContext
from weavert_web_research import ResearchProfile, ResearchProfileRegistry
from weavert_kit_common_retrieval._tool_impls import (
    prepare_citations_tool,
    retrieve_context_tool,
    validate_prepare_citations_tool,
    validate_retrieve_context_tool,
)
from weavert_web_research import (
    DuckDuckGoHtmlBackend,
    WebResearchLoopState,
    WebSearchProviderRegistry,
    build_policy,
    default_web_search_provider_registry,
    find_in_page,
    inspect_page,
    refine_web_research_stop_reason,
    search_web,
    validate_fetch_input,
    validate_page_find_input,
    web_research_confidence_from_stop_reason,
    web_urlopen,
)

_WEB_PRIMITIVE_DEFAULT_SEARCH_LIMIT = 8
_WEB_PRIMITIVE_DEFAULT_FETCH_CHARS = 12_000
_WEB_PRIMITIVE_DEFAULT_FIND_LIMIT = 5
_WEB_RESEARCH_DEFAULT_SEARCH_BUDGET = 4
_WEB_RESEARCH_DEFAULT_FETCH_BUDGET = 4
_WEB_RESEARCH_DEFAULT_FIND_BUDGET = 6
_WEB_RESEARCH_DEFAULT_DESIRED_SOURCES = 3
_WEB_RESEARCH_MAX_TRACE_ITEMS = 8
_WEB_RESEARCH_DEFAULT_MAX_CONCURRENT_FETCHES = 3
_WEB_RESEARCH_RUN_ID_METADATA_KEY = "web_research_run_id"
_WEB_FETCH_PUBLIC_BATCH_FIELDS = frozenset({"urls", "sources", "max_concurrent_fetches"})
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

_web_urlopen = web_urlopen
_web_search_provider_registry: WebSearchProviderRegistry | None = None
_web_research_runs: dict[str, WebResearchLoopState] = {}

SUPPORTED_RESEARCH_PROFILES = ("general", "coding", "business", "academic", "legal_compliance", "product_shopping")

RESEARCH_PROFILES = ResearchProfileRegistry(
    (
        ResearchProfile(
            name="general",
            source_priorities=("official", "authoritative", "news", "reference"),
            freshness_policy={"required": False},
            facet_keys=(),
        ),
        ResearchProfile(
            name="coding",
            source_priorities=("official_docs", "release_notes", "changelog", "source_repository", "issue_tracker"),
            freshness_policy={"required": False},
            facet_keys=("version_scope", "api_names", "compatibility_notes", "breaking_changes"),
        ),
        ResearchProfile(
            name="business",
            source_priorities=("official_company", "filings", "announcements", "news", "reviews"),
            freshness_policy={"required": False},
            facet_keys=("companies", "competitors", "timelines", "comparison_axes", "market_claims"),
        ),
        ResearchProfile(
            name="academic",
            source_priorities=("papers", "publishers", "institutions", "preprints"),
            freshness_policy={"required": False},
            facet_keys=("papers", "methods", "experiments", "conclusions", "citation_metadata"),
        ),
        ResearchProfile(
            name="legal_compliance",
            source_priorities=("statutes", "regulations", "standards", "official_guidance"),
            freshness_policy={"required": True},
            facet_keys=("jurisdiction", "authorities", "effective_dates", "compliance_gaps"),
        ),
        ResearchProfile(
            name="product_shopping",
            source_priorities=("official_specs", "prices", "reviews", "alternatives", "risk_notes"),
            freshness_policy={"required": True},
            facet_keys=("products", "prices", "alternatives", "comparison_axes", "purchase_risks"),
        ),
    )
)


def validate_web_search(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
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
    state = WebResearchLoopState(normalized)
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


async def web_search_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    query = str(tool_input["query"]).strip()
    state = _web_research_state(context)
    effective_input = _effective_web_tool_input("search", tool_input, context)
    if state is not None:
        state.reserve("search")
    policy = build_policy(
        effective_input,
        default_search_limit=_WEB_PRIMITIVE_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_WEB_PRIMITIVE_DEFAULT_FETCH_CHARS,
        default_find_matches=_WEB_PRIMITIVE_DEFAULT_FIND_LIMIT,
    )

    def search() -> dict[str, Any]:
        return search_web(
            query,
            registry=_web_provider_registry(),
            policy=policy,
        )

    try:
        result = await asyncio.to_thread(search)
    except Exception as exc:
        if state is not None:
            state.record_operation_failure("web_search", str(exc), effective_input)
        raise
    if state is not None:
        state.record_search(result)
    return result


def validate_web_fetch(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    state = _web_research_state(context)
    batch_fields = _public_batch_fetch_fields(tool_input)
    if batch_fields:
        message = (
            "web_fetch accepts exactly one url or source; batch fetch fields are not public: "
            + ", ".join(batch_fields)
        )
        if state is not None:
            state.record_rejection("web_fetch", message, tool_input)
        return ValidationOutcome(False, message)
    if "url" in tool_input and "source" in tool_input:
        message = "web_fetch accepts either url or source, not both"
        if state is not None:
            state.record_rejection("web_fetch", message, tool_input)
        return ValidationOutcome(False, message)
    effective_input = _effective_web_tool_input("fetch", tool_input, context)
    policy = build_policy(
        effective_input,
        default_search_limit=_WEB_PRIMITIVE_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_WEB_PRIMITIVE_DEFAULT_FETCH_CHARS,
        default_find_matches=_WEB_PRIMITIVE_DEFAULT_FIND_LIMIT,
    )
    try:
        validate_fetch_input(
            _source_reference(effective_input),
            policy=policy,
            hostname_public_resolver=_web_hostname_resolves_publicly,
        )
    except ValueError as exc:
        if state is not None:
            state.record_rejection("web_fetch", str(exc), effective_input)
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True, updated_input=effective_input)


async def web_fetch_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _web_research_state(context)
    batch_fields = _public_batch_fetch_fields(tool_input)
    if batch_fields:
        message = (
            "web_fetch accepts exactly one url or source; batch fetch fields are not public: "
            + ", ".join(batch_fields)
        )
        if state is not None:
            state.record_rejection("web_fetch", message, tool_input)
        raise ValueError(message)
    if "url" in tool_input and "source" in tool_input:
        message = "web_fetch accepts either url or source, not both"
        if state is not None:
            state.record_rejection("web_fetch", message, tool_input)
        raise ValueError(message)
    result = await _web_fetch_impl(tool_input, context)
    if state is not None:
        state.record_fetch(result)
    return result


async def _web_fetch_impl(
    tool_input: Mapping[str, Any],
    context: ToolContext,
    *,
    failure_tool: str = "web_fetch",
    failure_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    state = _web_research_state(context)
    effective_input = _effective_web_tool_input("fetch", tool_input, context)
    source = _source_reference(effective_input)
    policy = build_policy(
        effective_input,
        default_search_limit=_WEB_PRIMITIVE_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_WEB_PRIMITIVE_DEFAULT_FETCH_CHARS,
        default_find_matches=_WEB_PRIMITIVE_DEFAULT_FIND_LIMIT,
    )
    try:
        validate_fetch_input(
            source,
            policy=policy,
            hostname_public_resolver=_web_hostname_resolves_publicly,
        )
    except ValueError as exc:
        if state is not None:
            state.record_rejection("web_fetch", str(exc), effective_input)
        raise
    if state is not None:
        state.reserve("fetch")

    def fetch() -> dict[str, Any]:
        return inspect_page(
            source,
            backend=DuckDuckGoHtmlBackend(
                urlopen=lambda request, *, timeout: _web_policy_urlopen(
                    request,
                    timeout=timeout,
                    allowed_domains=policy.allowed_domains,
                    blocked_domains=policy.blocked_domains,
                    hostname_public_resolver=_web_hostname_resolves_publicly,
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


def validate_web_find(tool_input: dict[str, Any], context: ToolContext) -> ValidationOutcome:
    if not str(tool_input.get("pattern") or "").strip():
        return ValidationOutcome(False, "pattern must be non-empty")
    effective_input = _effective_web_tool_input("find", tool_input, context)
    policy = build_policy(
        effective_input,
        default_search_limit=_WEB_PRIMITIVE_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_WEB_PRIMITIVE_DEFAULT_FETCH_CHARS,
        default_find_matches=_WEB_PRIMITIVE_DEFAULT_FIND_LIMIT,
    )
    try:
        validate_page_find_input(
            effective_input,
            policy=policy,
            hostname_public_resolver=_web_hostname_resolves_publicly,
        )
    except ValueError as exc:
        state = _web_research_state(context)
        if state is not None:
            state.record_rejection("web_find", str(exc), effective_input)
        return ValidationOutcome(False, str(exc))
    return ValidationOutcome(True, updated_input=effective_input)


async def web_find_tool(tool_input: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _web_research_state(context)
    effective_input = _effective_web_tool_input("find", tool_input, context)
    if state is not None:
        state.reserve("find")
    policy = build_policy(
        effective_input,
        default_search_limit=_WEB_PRIMITIVE_DEFAULT_SEARCH_LIMIT,
        default_text_chars=_WEB_PRIMITIVE_DEFAULT_FETCH_CHARS,
        default_find_matches=_WEB_PRIMITIVE_DEFAULT_FIND_LIMIT,
    )

    def find() -> dict[str, Any]:
        return find_in_page(
            effective_input,
            backend=DuckDuckGoHtmlBackend(urlopen=_web_urlopen),
            policy=policy,
        )

    try:
        result = await asyncio.to_thread(find)
    except Exception as exc:
        if state is not None:
            state.record_operation_failure("web_find", str(exc), effective_input)
        raise
    if state is not None:
        state.record_find(result)
    return result


def _source_reference(tool_input: Mapping[str, Any]) -> Mapping[str, Any]:
    source = tool_input.get("source")
    if isinstance(source, Mapping):
        return source
    return {"url": tool_input.get("url")}


def _public_batch_fetch_fields(tool_input: Mapping[str, Any]) -> list[str]:
    return sorted(field for field in _WEB_FETCH_PUBLIC_BATCH_FIELDS if field in tool_input)


def _web_policy_urlopen(request, **kwargs: Any):
    try:
        return _web_urlopen(request, **kwargs)
    except TypeError as exc:
        policy_keys = {"allowed_domains", "blocked_domains", "hostname_public_resolver"}
        if not policy_keys.intersection(kwargs):
            raise
        reduced_kwargs = {key: value for key, value in kwargs.items() if key not in policy_keys}
        try:
            return _web_urlopen(request, **reduced_kwargs)
        except TypeError:
            raise exc


def _web_provider_registry() -> WebSearchProviderRegistry:
    if _web_search_provider_registry is not None:
        return _web_search_provider_registry
    return default_web_search_provider_registry(duckduckgo_urlopen=_web_urlopen)


def _web_research_objective(tool_input: Mapping[str, Any]) -> str:
    return str(tool_input.get("objective") or tool_input.get("question") or "").strip()


def _normalize_web_research_input(tool_input: Mapping[str, Any]) -> dict[str, Any]:
    objective = _web_research_objective(tool_input)
    profile = _normalize_research_profile(tool_input.get("profile"))
    scope = tool_input.get("scope")
    if scope is not None and not isinstance(scope, Mapping):
        raise ValueError("scope must be an object when provided")
    source_preferences = tool_input.get("source_preferences")
    if source_preferences is not None and not isinstance(source_preferences, Mapping):
        raise ValueError("source_preferences must be an object when provided")
    freshness = tool_input.get("freshness")
    if freshness is not None and not isinstance(freshness, Mapping):
        raise ValueError("freshness must be an object when provided")
    hard_policy = tool_input.get("hard_policy")
    if hard_policy is not None and not isinstance(hard_policy, Mapping):
        raise ValueError("hard_policy must be an object when provided")
    preferences = tool_input.get("preferences")
    if preferences is not None and not isinstance(preferences, Mapping):
        raise ValueError("preferences must be an object when provided")
    hard_policy_map = dict(hard_policy or {})
    preferences_map = dict(preferences or {})
    scope_map = dict(scope or {})
    source_preferences_map = dict(source_preferences or {})
    freshness_map = dict(freshness or {})
    legacy_domains = tool_input.get("domains")
    legacy_allowed_domains = tool_input.get("allowed_domains")
    legacy_blocks = tool_input.get("blocked_domains")
    compact_allowed_domains = scope_map.get("allowed_domains")
    compact_blocked_domains = scope_map.get("blocked_domains")
    compact_preferred_domains = source_preferences_map.get("preferred_domains")
    compact_desired_source_count = source_preferences_map.get("desired_source_count")
    legacy_freshness = tool_input.get("freshness_days")
    if legacy_freshness is None:
        legacy_freshness = tool_input.get("recency_days")
    compact_freshness_days = freshness_map.get("days")
    mode_raw = tool_input.get("mode")
    if mode_raw is None:
        mode_raw = scope_map.get("mode")
    if mode_raw is None:
        has_compact_projection = any(
            key in tool_input for key in ("scope", "freshness", "depth", "source_preferences")
        ) or ("question" in tool_input and "objective" not in tool_input)
        mode_raw = (
            "focused"
            if legacy_domains is not None
            or legacy_allowed_domains is not None
            or compact_allowed_domains is not None
            or (not has_compact_projection and "objective" in tool_input)
            else "open"
        )
    mode = str(mode_raw or "focused").strip().lower()
    if mode not in {"focused", "open"}:
        raise ValueError("mode must be focused or open")
    scope_mode = scope_map.get("mode")
    if scope_mode is not None and str(scope_mode).strip().lower() not in {"focused", "open"}:
        raise ValueError("scope.mode must be focused or open")
    if legacy_blocks is not None and "blocked_domains" not in hard_policy_map:
        hard_policy_map["blocked_domains"] = legacy_blocks
    if compact_blocked_domains is not None and "blocked_domains" not in hard_policy_map:
        hard_policy_map["blocked_domains"] = compact_blocked_domains
    if legacy_freshness is not None and "freshness_days" not in preferences_map:
        preferences_map["freshness_days"] = legacy_freshness
    if compact_freshness_days is not None and "freshness_days" not in preferences_map:
        preferences_map["freshness_days"] = compact_freshness_days
    if legacy_allowed_domains is not None:
        hard_policy_map.setdefault("allowed_domains", legacy_allowed_domains)
    if compact_allowed_domains is not None:
        hard_policy_map.setdefault("allowed_domains", compact_allowed_domains)
    if legacy_domains is not None:
        if mode == "open":
            preferences_map.setdefault("preferred_domains", legacy_domains)
        else:
            hard_policy_map.setdefault("domains", legacy_domains)
    if compact_preferred_domains is not None:
        preferences_map.setdefault("preferred_domains", compact_preferred_domains)
    profile_definition = RESEARCH_PROFILES.get(profile)
    freshness_required = _normalize_bool(
        freshness_map.get("required"),
        default=bool(profile_definition.freshness_policy.get("required", False)),
    )
    if tool_input.get("freshness_required") is not None:
        freshness_required = _normalize_bool(tool_input.get("freshness_required"))
    budget_profile = str(tool_input.get("budget_profile") or tool_input.get("depth") or "standard").strip().lower()
    profile_defaults = _budget_profile_defaults(budget_profile)
    desired_source_default = (
        compact_desired_source_count
        if compact_desired_source_count is not None and tool_input.get("desired_source_count") is None
        else profile_defaults["desired_source_count"]
    )
    raw_policy = {
        "domains": hard_policy_map.get("domains") or hard_policy_map.get("allowed_domains"),
        "blocked_domains": hard_policy_map.get("blocked_domains"),
        "freshness_days": preferences_map.get("freshness_days"),
        "freshness_required": freshness_required,
        "provider": tool_input.get("provider") or preferences_map.get("provider"),
        "limit": tool_input.get("search_budget") or profile_defaults["search_budget"],
        "max_chars": tool_input.get("max_chars") or _WEB_PRIMITIVE_DEFAULT_FETCH_CHARS,
    }
    policy = build_policy(
        raw_policy,
        default_search_limit=profile_defaults["search_budget"],
        default_text_chars=_WEB_PRIMITIVE_DEFAULT_FETCH_CHARS,
        default_find_matches=profile_defaults["find_budget"],
    )
    output_hints = tool_input.get("output_hints")
    if output_hints is not None and not isinstance(output_hints, Mapping):
        raise ValueError("output_hints must be an object when provided")
    preferences_payload = {
        "preferred_domains": list(build_policy({"domains": preferences_map.get("preferred_domains")}).allowed_domains),
        "freshness_days": policy.freshness_days,
        "freshness_required": freshness_required,
        "source_priorities": list(profile_definition.source_priorities),
    }
    if tool_input.get("provider") is not None:
        preferences_payload["provider"] = tool_input.get("provider")
    for key, value in preferences_map.items():
        if key not in preferences_payload:
            preferences_payload[str(key)] = value
    return {
        "objective": objective,
        "profile": profile,
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
                int(desired_source_default),
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
        "freshness_required": freshness_required,
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


def _normalize_research_profile(raw: Any) -> str:
    profile = str(raw or "general").strip().lower().replace("-", "_")
    if profile not in SUPPORTED_RESEARCH_PROFILES:
        raise ValueError(
            "profile must be one of general, coding, business, academic, legal_compliance, or product_shopping"
        )
    return profile


def _bounded_int(raw: Any, field: str, minimum: int, maximum: int, default: int) -> int:
    if raw is None:
        return default
    if not isinstance(raw, int):
        raise ValueError(f"{field} must be an integer")
    if raw < minimum or raw > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return raw


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


def _web_research_delegation_prompt(request: Mapping[str, Any]) -> str:
    return (
        "Run bounded read-only web research for this objective. Use only the package-owned "
        "`web_search`, `web_fetch`, and `web_find` tools, stay inside the supplied hard policy and budgets, "
        "preserve provider/freshness metadata, and return concise structured evidence.\n\n"
        f"Objective: {request['objective']}\n"
        f"Profile: {request['profile']}\n"
        f"Mode: {request['mode']}\n"
        f"Hard policy: {request['hard_policy']}\n"
        f"Preferences: {request['preferences']}\n"
        f"Budget: {request['budget']}\n"
        f"Output hints: {request['output_hints']}\n\n"
        "In open mode, use preferred domains as ranking guidance, not as the only valid source "
        "scope. In focused mode, stay inside hard allowed domains. "
        "If freshness is required, do not claim sufficient fresh evidence unless search reports "
        "freshness_scope as enforced or satisfied; expose provider fallback or unsupported freshness. "
        "Do not navigate browsers, run shell commands, mutate workspace state, or cite sources "
        "you did not inspect."
    )


def _project_web_research_result(
    request: Mapping[str, Any],
    child_result: Any,
    *,
    state: WebResearchLoopState,
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
    child_status = structured.get("stop_reason") or terminal_metadata.get("stop_reason") or child_payload.get("status")
    stop_reason = state.stop_reason(child_status)
    state.finalize_provider_and_freshness_trace()
    trace = [*state.trace_summary(), *child_trace]
    if child_payload.get("summary"):
        trace.append({"event": "delegated_summary", "summary": str(child_payload["summary"])})
    conflicts = _list_of_mappings(structured.get("conflicts"))
    gaps = _derive_gaps(request, sources, evidence, stop_reason, structured.get("gaps"))
    stop_reason = refine_web_research_stop_reason(
        stop_reason,
        child_status=child_status,
        conflicts=conflicts,
        gaps=gaps,
    )
    if stop_reason == "remaining_gaps" and not gaps:
        gaps.append(
            {
                "kind": "remaining_gaps",
                "message": "Research ended with declared evidence gaps.",
                "profile": request.get("profile", "general"),
            }
        )
    result = {
        "objective": request["objective"],
        "mode": request.get("mode", "focused"),
        "answer": str(structured.get("answer") or child_payload.get("summary") or "").strip(),
        "confidence": web_research_confidence_from_stop_reason(stop_reason),
        "sources": sources,
        "evidence": evidence,
        "conflicts": conflicts,
        "gaps": gaps,
        "freshness": _freshness_payload(request, state),
        "policy": dict(request["policy"]),
        "hard_policy": dict(request.get("hard_policy") or {}),
        "preferences": dict(request.get("preferences") or {}),
        "budget": state.budget_payload(),
        "stop_reason": stop_reason,
        "research_trace": {
            "profile": request.get("profile", "general"),
            "queries": state.queries_payload(),
            "pages_read": state.pages_read_payload(),
            "iterations": len(trace),
            "trace_summary": trace[:_WEB_RESEARCH_MAX_TRACE_ITEMS],
        },
        "facets": _build_profile_facets(request, structured),
        "trace_summary": trace[:_WEB_RESEARCH_MAX_TRACE_ITEMS],
        "child_run": {
            "agent": child_payload.get("agent") or child_payload.get("agent_name") or "web-searcher",
            "status": child_payload.get("status"),
            "run_id": child_payload.get("run_id"),
            "parent_run_id": child_payload.get("parent_run_id"),
            "session_id": child_payload.get("session_id"),
            "delegation_depth": child_payload.get("delegation_depth"),
        },
        "provider": state.provider_payload() or {},
        "provider_selection": state.provider_selection_payload() or {},
        "provider_fallback": state.provider_fallback_payload() or {},
    }
    freshness_scope = state.freshness_scope_payload()
    if freshness_scope:
        result["freshness_scope"] = freshness_scope
    return result


def _freshness_payload(request: Mapping[str, Any], state: WebResearchLoopState) -> dict[str, Any]:
    freshness_scope = state.freshness_scope_payload()
    requested_days = request.get("policy", {}).get("freshness_days")
    if freshness_scope:
        status = freshness_scope.get("status") or freshness_scope.get("outcome") or "unknown"
    elif requested_days is None:
        status = "not_requested"
    else:
        status = "unsupported"
    return {"requested_days": requested_days, "required": bool(request.get("freshness_required")), "status": status}


def _derive_gaps(
    request: Mapping[str, Any],
    sources: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    stop_reason: str,
    child_gaps: Any,
) -> list[dict[str, Any]]:
    gaps = _list_of_mappings(child_gaps)
    if stop_reason != "sufficient_evidence" and not gaps:
        gaps.append(
            {
                "kind": stop_reason,
                "message": "Research ended before enough profile-appropriate evidence was verified.",
                "profile": request.get("profile", "general"),
            }
        )
    if sources and not evidence and not gaps:
        gaps.append({"kind": "missing_evidence", "message": "Sources were found but no inspected evidence was recorded."})
    return gaps


def _build_profile_facets(request: Mapping[str, Any], structured: Mapping[str, Any]) -> dict[str, Any]:
    profile = str(request.get("profile") or "general")
    facets = structured.get("facets")
    if isinstance(facets, Mapping):
        result = {str(key): dict(value) for key, value in facets.items() if isinstance(value, Mapping)}
    else:
        result = {}
    profile_facet = dict(result.get(profile) or {})
    if profile == "coding":
        for key in ("version_scope", "api_names", "compatibility_notes", "breaking_changes"):
            value = structured.get(key)
            if value is not None and key not in profile_facet:
                profile_facet[key] = value
    result[profile] = profile_facet
    return result


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


def _list_of_mappings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _web_research_state(context: Any) -> WebResearchLoopState | None:
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
    if state.request.get("freshness_required"):
        effective["freshness_required"] = bool(state.request["freshness_required"])
    provider = state.request.get("preferences", {}).get("provider")
    if provider:
        effective["provider"] = provider
    if kind == "search":
        remaining = max(1, int(state.request["budget"]["search_budget"]) - state.search_used)
        effective.setdefault("limit", min(_WEB_PRIMITIVE_DEFAULT_SEARCH_LIMIT, remaining))
    if kind == "find":
        remaining = max(1, int(state.request["budget"]["find_budget"]) - state.find_used)
        effective.setdefault("limit", min(_WEB_PRIMITIVE_DEFAULT_FIND_LIMIT, remaining))
    return effective


@lru_cache(maxsize=256)
def _web_hostname_resolves_publicly(hostname: str) -> bool | None:
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
    "web_fetch_tool",
    "web_find_tool",
    "web_search_tool",
    "prepare_citations_tool",
    "retrieve_context_tool",
    "validate_web_fetch",
    "validate_web_find",
    "validate_web_search",
    "validate_prepare_citations_tool",
    "validate_retrieve_context_tool",
    "validate_web_research",
    "web_research_tool",
]
