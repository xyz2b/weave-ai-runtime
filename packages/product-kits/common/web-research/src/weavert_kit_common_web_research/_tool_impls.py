from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import urllib.error
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from weavert.contracts import MessageRole, RuntimeMessage, TurnContext
from weavert.definitions import ValidationOutcome
from weavert.tool_runtime import ToolContext
from weavert.turn_engine import ModelRequest, ModelStreamEventType
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
_WEB_RESEARCH_MAX_TRACE_ITEMS = 16
_WEB_RESEARCH_DEFAULT_MAX_CONCURRENT_FETCHES = 3
_WEB_RESEARCH_RUN_ID_METADATA_KEY = "web_research_run_id"
_WEB_RESEARCH_MAX_REPLAN_PASSES = 1
_WEB_RESEARCH_SUPPORTED_STRATEGIES = frozenset({"deterministic", "pro"})
_WEB_RESEARCH_MODEL_RESPONSE_METADATA_KEY = "web_research_model_responses"
_WEB_RESEARCH_PRO_DEFAULT_METADATA_KEY = "web_research_default_strategy"
_WEB_RESEARCH_PRO_OPT_IN_METADATA_KEY = "web_research_pro_default"
_WEB_RESEARCH_DEFAULT_SYNTHESIS_REPAIR_TURNS = 1
_WEB_RESEARCH_PLANNER_SCHEMA_VERSION = "web_research.planner.v1"
_WEB_RESEARCH_SYNTHESIZER_SCHEMA_VERSION = "web_research.synthesizer.v1"
_WEB_RESEARCH_VERIFIER_SCHEMA_VERSION = "web_research.verifier.v1"
_WEB_RESEARCH_REPAIR_SCHEMA_VERSION = "web_research.repair.v1"
_WEB_RESEARCH_ANSWER_UNIT_KINDS = frozenset({"claim", "limitation", "gap", "conflict", "transition"})
_WEB_RESEARCH_ANSWER_UNIT_SUPPORTS = frozenset(
    {"entailed", "limitation", "gap", "conflict", "non_factual", "unsupported", "contradicted"}
)
_WEB_RESEARCH_VERIFIER_STATUSES = _WEB_RESEARCH_ANSWER_UNIT_SUPPORTS | frozenset({"accepted", "rejected"})
_WEB_RESEARCH_MAX_ANSWER_UNITS = 24
_WEB_RESEARCH_MAX_ANSWER_UNIT_ID_CHARS = 80
_WEB_RESEARCH_MAX_ANSWER_UNIT_TEXT_CHARS = 900
_WEB_RESEARCH_MAX_REFERENCE_ID_CHARS = 120
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
        "claim_key",
        "stance",
        "supports",
        "supports_claim",
    }
)
_WEB_RESEARCH_CLAIM_ANNOTATION_FIELDS = frozenset(
    {
        "id",
        "claim",
        "claim_text",
        "claim_key",
        "key",
        "stance",
        "subquestion_id",
        "source_handle",
        "page_handle",
        "evidence_id",
        "conflicts_with",
        "explicit_incompatibility",
        "incompatible_with",
        "resolved",
        "resolution_rationale",
        "rationale",
    }
)
_WEB_RESEARCH_INTERNAL_INPUT_FIELDS = frozenset(
    {
        "answer",
        "auxiliary_signals",
        "budget",
        "candidate_sources",
        "child_run",
        "claims",
        "conflicts",
        "evidence",
        "facets",
        "freshness_scope",
        "gaps",
        "inspected_evidence",
        "loop_decisions",
        "plan",
        "policy",
        "query_candidates",
        "research_plan",
        "research_trace",
        "selected_pages",
        "source_references",
        "sources",
        "stop_reason",
        "subquestions",
        "trace",
        "trace_summary",
    }
)

_web_urlopen = web_urlopen
_web_search_provider_registry: WebSearchProviderRegistry | None = None
_web_research_runs: dict[str, WebResearchLoopState] = {}


class _DelegatedWebResearchFallbackRequested(Exception):
    """Raised only when the package-owned loop deliberately hands off before using web budget."""


class ModelTurnValidationError(ValueError):
    """Structured validation failure for an internal Pro model turn."""

    def __init__(
        self,
        turn_kind: str,
        validation_class: str,
        message: str,
        *,
        raw_response: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.turn_kind = turn_kind
        self.validation_class = validation_class
        self.raw_response = dict(raw_response) if isinstance(raw_response, Mapping) else None


@dataclass(frozen=True, slots=True)
class ResearchSubquestion:
    id: str
    question: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class ResearchQueryCandidate:
    query: str
    subquestion_ids: tuple[str, ...] = ()
    rationale: str = ""
    replan: bool = False


@dataclass(frozen=True, slots=True)
class CandidateSource:
    source: Mapping[str, Any]
    score: float
    rationale: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SelectedPage:
    source: Mapping[str, Any]
    rationale: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoopDecision:
    stage: str
    stop_reason: str | None = None
    replan: bool = False
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class ResearchGap:
    kind: str
    message: str
    subquestion_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchConflict:
    kind: str
    message: str
    source_handles: tuple[str, ...] = ()


@dataclass(slots=True)
class ResearchPlan:
    objective: str
    profile: str
    subquestions: tuple[ResearchSubquestion, ...]
    queries: list[ResearchQueryCandidate]
    desired_source_count: int
    source_priorities: tuple[str, ...] = ()
    decisions: list[LoopDecision] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResearchAction:
    type: str
    query: str | None = None
    source_handle: str | None = None
    page_handle: str | None = None
    url: str | None = None
    pattern: str | None = None
    rationale: str = ""
    stop_intent: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageAssessment:
    status: str
    confidence: str | None = None
    missing: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class PlannerGap:
    kind: str
    message: str
    subquestion_id: str | None = None


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    actions: tuple[ResearchAction, ...]
    rationale: str = ""
    coverage: CoverageAssessment | None = None
    expected_gaps: tuple[PlannerGap, ...] = ()
    stop_intent: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SynthesisClaim:
    claim: str
    evidence_ids: tuple[str, ...]
    id: str | None = None
    excerpt: str | None = None
    start: int | None = None
    end: int | None = None
    confidence: str | None = None
    claim_key: str | None = None
    stance: str | None = None
    conflicts_with: tuple[str, ...] = ()
    incompatible_with: tuple[str, ...] = ()
    resolved: bool | None = None
    resolution_rationale: str | None = None


@dataclass(frozen=True, slots=True)
class AnswerUnit:
    id: str
    text: str
    kind: str
    support: str
    claim_ids: tuple[str, ...] = ()
    gap_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    limitation_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    rationale: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnswerVerificationUnit:
    unit_id: str
    status: str
    support: str
    claim_ids: tuple[str, ...] = ()
    gap_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    limitation_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class AnswerVerificationResponse:
    units: tuple[AnswerVerificationUnit, ...]
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnswerProof:
    proposed_units: tuple[AnswerUnit, ...] = ()
    accepted_units: tuple[AnswerUnit, ...] = ()
    dropped_units: tuple[Mapping[str, Any], ...] = ()
    verification: AnswerVerificationResponse | None = None
    repair_used: bool = False
    fallback_used: bool = False


@dataclass(frozen=True, slots=True)
class SynthesisResponse:
    answer: str
    claims: tuple[SynthesisClaim, ...] = ()
    answer_units: tuple[AnswerUnit, ...] = ()
    limitations: tuple[str, ...] = ()
    conflict_treatment: str = ""
    confidence: str | None = None
    confidence_rationale: str = ""
    self_verification: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)


_WEB_RESEARCH_MODEL_TURN_CONTRACTS: dict[str, dict[str, Any]] = {
    "planner": {
        "schema_version": _WEB_RESEARCH_PLANNER_SCHEMA_VERSION,
        "required": ("schema_version",),
        "response": {
            "type": "object",
            "required_any": ("actions", "stop_intent"),
            "actions": "array of search/fetch/find/direct_url_fetch/stop actions",
            "stop_intent": "optional runtime-reviewed stop reason",
        },
        "instructions": "Choose bounded web_research actions or stop only from supplied state.",
        "authority": "Planner proposes actions only; runtime owns policy, budgets, source identity, evidence, stop reason, and confidence.",
    },
    "synthesizer": {
        "schema_version": _WEB_RESEARCH_SYNTHESIZER_SCHEMA_VERSION,
        "required": ("schema_version", "claims", "answer_units"),
        "response": {
            "type": "object",
            "required": ("schema_version", "claims", "answer_units"),
            "claims": "array of evidence-bound claim objects",
            "answer_units": "ordered array of proof-carrying answer units",
            "answer": "optional draft text; runtime never projects it directly",
        },
        "instructions": "Produce bounded evidence-bound claims and answer units. Do not create sources, evidence, stop reasons, or confidence.",
        "authority": "Runtime accepts only proof bindings to supplied ledger evidence, gaps, conflicts, and limitations.",
    },
    "verifier": {
        "schema_version": _WEB_RESEARCH_VERIFIER_SCHEMA_VERSION,
        "required": ("schema_version",),
        "response": {
            "type": "object",
            "required_any": ("unit_statuses", "units"),
            "unit_statuses": "array of unit_id/status/support records for proposed answer units",
        },
        "instructions": "Classify each proposed answer unit as entailed, contradicted, unsupported, limitation, gap, conflict, or non_factual.",
        "authority": "Verifier judges semantics only against supplied state; runtime owns reference checks and projection.",
    },
    "repair": {
        "schema_version": _WEB_RESEARCH_REPAIR_SCHEMA_VERSION,
        "required": ("schema_version", "repaired_response"),
        "response": {
            "type": "object",
            "required": ("schema_version", "repaired_response"),
            "repaired_response": "schema-valid response for the target turn",
        },
        "instructions": "Return one corrected structured response for the target turn and do not add state outside the payload.",
        "authority": "Repair may rewrite model output only; runtime still validates the repaired response.",
    },
}


SUPPORTED_RESEARCH_PROFILES = ("general", "coding", "business", "academic", "legal_compliance", "product_shopping")

RESEARCH_PROFILES = ResearchProfileRegistry(
    (
        ResearchProfile(
            name="general",
            query_templates=("{objective}", "{objective} official source"),
            source_priorities=("official", "authoritative", "news", "reference"),
            evidence_schema={"expected": ("facts", "source dates", "authoritative citations")},
            freshness_policy={"required": False},
            facet_keys=(),
        ),
        ResearchProfile(
            name="coding",
            query_templates=(
                "{objective} official documentation",
                "{objective} release notes changelog",
                "{objective} GitHub issue API version breaking change",
            ),
            source_priorities=("official_docs", "release_notes", "changelog", "source_repository", "issue_tracker"),
            evidence_schema={"expected": ("api_names", "versions", "compatibility_notes", "breaking_changes")},
            defaults={"quality_signals": ("official_docs", "release_notes", "repository", "issue_tracker", "version")},
            freshness_policy={"required": False},
            facet_keys=("version_scope", "api_names", "compatibility_notes", "breaking_changes"),
        ),
        ResearchProfile(
            name="business",
            query_templates=(
                "{objective} company official announcement",
                "{objective} filing annual report investor relations",
                "{objective} competitor comparison market claim",
            ),
            source_priorities=("official_company", "filings", "announcements", "news", "reviews"),
            evidence_schema={"expected": ("companies", "competitors", "timelines", "comparison_axes", "market_claims")},
            defaults={"quality_signals": ("official_company", "filing", "announcement", "credible_news", "review")},
            freshness_policy={"required": False},
            facet_keys=("companies", "competitors", "timelines", "comparison_axes", "market_claims"),
        ),
        ResearchProfile(
            name="academic",
            query_templates=(
                "{objective} paper method experiment conclusion",
                "{objective} publisher institution citation",
                "{objective} preprint study",
            ),
            source_priorities=("papers", "publishers", "institutions", "preprints"),
            evidence_schema={"expected": ("papers", "methods", "experiments", "conclusions", "citation_metadata")},
            defaults={"quality_signals": ("paper", "publisher", "institution", "preprint", "citation")},
            freshness_policy={"required": False},
            facet_keys=("papers", "methods", "experiments", "conclusions", "citation_metadata"),
        ),
        ResearchProfile(
            name="legal_compliance",
            query_templates=(
                "{objective} statute regulation official guidance",
                "{objective} standard jurisdiction authority effective date",
                "{objective} current compliance requirement",
            ),
            source_priorities=("statutes", "regulations", "standards", "official_guidance"),
            evidence_schema={"expected": ("jurisdiction", "authorities", "effective_dates", "compliance_gaps")},
            defaults={"quality_signals": ("statute", "regulation", "standard", "official_guidance", "effective_date")},
            freshness_policy={"required": True},
            facet_keys=("jurisdiction", "authorities", "effective_dates", "compliance_gaps"),
        ),
        ResearchProfile(
            name="product_shopping",
            query_templates=(
                "{objective} official specs current price",
                "{objective} review alternative comparison",
                "{objective} purchase risk warranty",
            ),
            source_priorities=("official_specs", "prices", "reviews", "alternatives", "risk_notes"),
            evidence_schema={"expected": ("products", "prices", "alternatives", "comparison_axes", "purchase_risks")},
            defaults={"quality_signals": ("official_specs", "price", "review", "alternative", "risk")},
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
    normalized = _normalized_web_research_execution_input(tool_input)
    if normalized.get("strategy_source") == "omitted" and _runtime_pro_strategy_opted_in(context):
        normalized = dict(normalized)
        normalized["strategy"] = "pro"
    if normalized.get("strategy") == "pro" and not _pro_model_provider_available(context):
        normalized = dict(normalized)
        normalized["requested_strategy"] = "pro"
        normalized["strategy"] = "deterministic"
        normalized["strategy_fallback_reason"] = "pro_model_unavailable"
    state = WebResearchLoopState(normalized)
    _web_research_runs[state.run_id] = state
    previous_run_id = context.metadata.get(_WEB_RESEARCH_RUN_ID_METADATA_KEY)
    context.metadata[_WEB_RESEARCH_RUN_ID_METADATA_KEY] = state.run_id
    try:
        if _select_web_research_strategy(normalized, context) == "pro":
            loop_result = await _run_pro_web_research_loop(normalized, context, state)
        else:
            loop_result = await _run_goal_driven_web_research_loop(normalized, context, state)
        return _project_web_research_result(normalized, loop_result, state=state)
    except _DelegatedWebResearchFallbackRequested:
        if context.agent_runner is None or state.search_used or state.fetch_used or state.find_used:
            raise
        child_result = await _run_delegated_web_research_fallback(normalized, context)
        return _project_web_research_result(normalized, child_result, state=state)
    finally:
        if previous_run_id is None:
            context.metadata.pop(_WEB_RESEARCH_RUN_ID_METADATA_KEY, None)
        else:
            context.metadata[_WEB_RESEARCH_RUN_ID_METADATA_KEY] = previous_run_id
        _web_research_runs.pop(state.run_id, None)


def _select_web_research_strategy(request: Mapping[str, Any], context: ToolContext) -> str:
    strategy = str(request.get("strategy") or "").strip().lower()
    if strategy:
        return strategy
    if _runtime_pro_strategy_opted_in(context):
        return "pro"
    return "deterministic"


def _pro_model_provider_available(context: ToolContext) -> bool:
    scripted = context.metadata.get(_WEB_RESEARCH_MODEL_RESPONSE_METADATA_KEY)
    if isinstance(scripted, list) and scripted:
        return True
    if callable(context.metadata.get("web_research_model_client")):
        return True
    return _runtime_model_client(context) is not None


def _runtime_pro_strategy_opted_in(context: ToolContext) -> bool:
    default_strategy = context.metadata.get(_WEB_RESEARCH_PRO_DEFAULT_METADATA_KEY)
    opt_in = context.metadata.get(_WEB_RESEARCH_PRO_OPT_IN_METADATA_KEY)
    services = getattr(context, "runtime_services", None)
    if services is not None:
        default_strategy = getattr(services, "web_research_default_strategy", default_strategy)
        opt_in = getattr(services, "web_research_pro_default", opt_in)
        metadata = getattr(services, "metadata", None)
        if isinstance(metadata, Mapping):
            default_strategy = metadata.get(_WEB_RESEARCH_PRO_DEFAULT_METADATA_KEY, default_strategy)
            opt_in = metadata.get(_WEB_RESEARCH_PRO_OPT_IN_METADATA_KEY, opt_in)
    return str(default_strategy or "").strip().lower() == "pro" or bool(opt_in)


def _runtime_model_client(context: ToolContext) -> Any | None:
    services = getattr(context, "runtime_services", None)
    runtime = getattr(services, "_runtime_assembly", None) if services is not None else None
    kernel = getattr(runtime, "kernel", None) if runtime is not None else None
    client = getattr(kernel, "model_client", None) if kernel is not None else None
    if client is not None and client.__class__.__name__ != "_UnconfiguredModelClient":
        return client
    return None


async def _run_delegated_web_research_fallback(request: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    if context.agent_runner is None:
        raise ValueError("web_research requires runtime web tools or a runtime agent runner")
    return await context.agent_runner(
        "web-searcher",
        _web_research_delegation_prompt(request),
        context,
        background=False,
        reason="web_research implementation-period delegated fallback",
        max_turns=request["budget"]["max_turns"],
    )


async def _run_goal_driven_web_research_loop(
    request: Mapping[str, Any],
    context: ToolContext,
    state: WebResearchLoopState,
) -> dict[str, Any]:
    plan = _build_research_plan(request)
    _record_loop_trace(
        state,
        {
            "event": "research_plan",
            "stage": "understand_objective",
            **(
                {"strategy_fallback_reason": request.get("strategy_fallback_reason"), "requested_strategy": request.get("requested_strategy")}
                if request.get("strategy_fallback_reason")
                else {}
            ),
            "subquestions": [subquestion.question for subquestion in plan.subquestions],
            "desired_source_count": plan.desired_source_count,
        },
    )
    searched_urls: set[str] = set()
    selected_urls: set[str] = set()
    low_yield_searches = 0
    replan_used = False
    search_index = 0

    while search_index < len(plan.queries):
        if state.search_used >= int(request["budget"]["search_budget"]):
            plan.decisions.append(LoopDecision(stage="search", stop_reason="budget_exhausted", rationale="search budget exhausted"))
            break
        query = plan.queries[search_index]
        search_index += 1
        try:
            search_result = await web_search_tool({"query": query.query}, context)
        except Exception as exc:
            if not _is_recoverable_web_operation_error(exc):
                raise
            low_yield_searches += 1
            state.record_gap(
                {
                    "kind": "operation_failed",
                    "message": "Search failed before returning inspectable candidates.",
                    "query": query.query,
                }
            )
            _record_loop_trace(
                state,
                {
                    "event": "low_yield_search",
                    "stage": "evaluate_progress",
                    "query": query.query,
                    "consecutive": low_yield_searches,
                    "reason": "search_failed",
                },
            )
            evaluation = _evaluate_loop_progress(
                request,
                state,
                plan,
                low_yield_searches=low_yield_searches,
                replan_used=replan_used,
            )
            plan.decisions.append(evaluation)
            _record_loop_trace(
                state,
                {
                    "event": "loop_decision",
                    "stage": "evaluate_progress",
                    "stop_reason": evaluation.stop_reason,
                    "replan": evaluation.replan,
                    "rationale": evaluation.rationale,
                },
            )
            if evaluation.replan and not replan_used:
                replan_used = True
                plan.queries.extend(_replan_queries(request, plan))
                _record_loop_trace(state, {"event": "replanned", "stage": "replan_or_stop", "pass": 1})
                continue
            if _loop_decision_is_terminal(evaluation, low_yield_searches=low_yield_searches, replan_used=replan_used):
                break
            continue
        candidates = _candidate_sources_from_search(
            search_result,
            request=request,
            selected_urls=selected_urls,
            searched_urls=searched_urls,
        )
        inspected_before = len(state.evidence_payload())
        for page in _select_pages_for_inspection(candidates, state=state, request=request):
            url = str(page.source.get("url") or "")
            selected_urls.add(url)
            _record_loop_trace(
                state,
                {
                    "event": "page_selected",
                    "stage": "select_pages",
                    "url": url,
                    "rationale": list(page.rationale),
                },
            )
            try:
                await web_fetch_tool({"source": dict(page.source)}, context)
            except Exception as exc:
                if not _is_recoverable_web_operation_error(exc):
                    raise
                continue
        inspected_after = len(state.evidence_payload())
        if inspected_after == inspected_before:
            low_yield_searches += 1
            _record_loop_trace(
                state,
                {
                    "event": "low_yield_search",
                    "stage": "evaluate_progress",
                    "query": query.query,
                    "consecutive": low_yield_searches,
                },
            )
        else:
            low_yield_searches = 0
        evaluation = _evaluate_loop_progress(
            request,
            state,
            plan,
            low_yield_searches=low_yield_searches,
            replan_used=replan_used,
        )
        plan.decisions.append(evaluation)
        _record_loop_trace(
            state,
            {
                "event": "loop_decision",
                "stage": "evaluate_progress",
                "stop_reason": evaluation.stop_reason,
                "replan": evaluation.replan,
                "rationale": evaluation.rationale,
            },
        )
        if evaluation.stop_reason == "sufficient_evidence":
            break
        if evaluation.replan and not replan_used:
            replan_used = True
            plan.queries.extend(_replan_queries(request, plan))
            _record_loop_trace(state, {"event": "replanned", "stage": "replan_or_stop", "pass": 1})
            continue
        if _loop_decision_is_terminal(evaluation, low_yield_searches=low_yield_searches, replan_used=replan_used):
            break

    state.finalize_provider_and_freshness_trace()
    stop_reason = (
        _evaluate_loop_progress(
            request,
            state,
            plan,
            low_yield_searches=low_yield_searches,
            replan_used=replan_used,
        ).stop_reason
        or state.stop_reason(None)
    )
    _record_loop_trace(
        state,
        {
            "event": "terminal_decision",
            "stage": "synthesize",
            "stop_reason": stop_reason,
        },
    )
    answer = _synthesize_from_verified_evidence(request, state)
    return {
        "agent": "web_research_loop",
        "status": stop_reason,
        "summary": answer,
        "terminal_metadata": {
            "web_research": {
                "answer": answer,
                "stop_reason": stop_reason,
                "trace_summary": [
                    {
                        "event": "synthesized",
                        "stage": "synthesize",
                        "verified_sources": len(state.sources_payload()),
                        "verified_evidence": len(state.evidence_payload()),
                    }
                ],
            }
        },
    }


async def _run_pro_web_research_loop(
    request: Mapping[str, Any],
    context: ToolContext,
    state: WebResearchLoopState,
) -> dict[str, Any]:
    _record_loop_trace(state, {"event": "strategy_selected", "strategy": "pro"})
    invalid_actions = 0
    stop_intent: str | None = None
    max_turns = int(request["budget"]["max_turns"])
    for turn_index in range(max_turns):
        payload = _build_planner_request_payload(request, state, turn_index=turn_index)
        _record_loop_trace(
            state,
            {
                "event": "planner_request",
                "turn": turn_index + 1,
                "known_sources": len(payload["known_sources"]),
                "inspected_evidence": len(payload["inspected_evidence"]),
            },
        )
        try:
            decision = await _request_planner_decision(payload, context)
        except ValueError as exc:
            _record_loop_trace(state, _model_turn_trace_event("planner", "rejected", exc=exc, fallback_path="loop_stop"))
            _record_loop_trace(
                state,
                {
                    "event": "planner_malformed",
                    "turn": turn_index + 1,
                    "validation_class": _validation_class(exc),
                    "error": _bounded_trace_text(exc),
                },
            )
            state.record_gap({"kind": "malformed_planner_output", "message": "Planner response could not be parsed as a bounded decision."})
            break
        _record_planner_decision_trace(state, decision, turn_index=turn_index)
        if decision.expected_gaps:
            for gap in decision.expected_gaps:
                state.record_gap({"kind": gap.kind, "message": gap.message, **({"subquestion_id": gap.subquestion_id} if gap.subquestion_id else {})})
        if decision.stop_intent:
            stop_intent = decision.stop_intent
        executed = False
        for action in decision.actions:
            accepted = await _execute_validated_planner_action(action, request, context, state)
            if accepted:
                executed = True
            else:
                invalid_actions += 1
        runtime_decision = _pro_runtime_terminal_decision(request, state, stop_intent=stop_intent)
        if runtime_decision == "sufficient_evidence" or (stop_intent and not executed) or invalid_actions >= 3:
            if stop_intent == "sufficient_evidence" and runtime_decision != "sufficient_evidence":
                _record_loop_trace(
                    state,
                    {
                        "event": "stop_intent_overridden",
                        "planner_stop_intent": stop_intent,
                        "runtime_stop_reason": runtime_decision,
                    },
                )
                state.record_gap({"kind": "invalid_stop_intent", "message": "Planner stop intent was not supported by ledger coverage."})
            break
    state.finalize_provider_and_freshness_trace()
    stop_reason = _pro_runtime_terminal_decision(request, state, stop_intent=stop_intent)
    synthesis = await _run_pro_synthesis(request, context, state)
    answer = synthesis["answer"] or _synthesize_from_verified_evidence(request, state)
    _record_loop_trace(
        state,
        {
            "event": "terminal_decision",
            "strategy": "pro",
            "stage": "synthesize",
            "stop_reason": stop_reason,
        },
    )
    return {
        "agent": "web_research_pro_loop",
        "status": stop_reason,
        "summary": answer,
        "terminal_metadata": {
            "web_research": {
                "answer": answer,
                "claims": synthesis["claims"],
                "gaps": synthesis["gaps"],
                "conflicts": synthesis.get("conflicts", []),
                "answer_units": synthesis.get("answer_units", []),
                "stop_reason": stop_reason,
                "trace_summary": synthesis["trace"],
                "strategy": {"selected": "pro"},
            }
        },
    }


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


def _build_research_plan(request: Mapping[str, Any]) -> ResearchPlan:
    objective = str(request["objective"]).strip()
    profile_definition = RESEARCH_PROFILES.get(str(request.get("profile") or "general"))
    subquestions = (
        ResearchSubquestion(id="sq-objective", question=objective),
    )
    queries = [
        ResearchQueryCandidate(
            query=_query_for_profile(objective, request),
            subquestion_ids=("sq-objective",),
            rationale="objective_terms",
        )
    ]
    for index, template in enumerate(profile_definition.query_templates or ("{objective}",)):
        queries.append(
            ResearchQueryCandidate(
                query=template.format(objective=objective),
                subquestion_ids=("sq-objective",),
                rationale="profile_template" if index else "profile_objective_template",
            )
        )
    preferred_domains = request.get("preferences", {}).get("preferred_domains") or request.get("policy", {}).get("domains") or []
    for domain in preferred_domains:
        domain_text = str(domain).strip()
        if domain_text:
            queries.append(
                ResearchQueryCandidate(
                    query=f"{objective} site:{domain_text}",
                    subquestion_ids=("sq-objective",),
                    rationale="preferred_domain",
                )
            )
    return ResearchPlan(
        objective=objective,
        profile=str(request.get("profile") or "general"),
        subquestions=subquestions,
        queries=_dedupe_queries(queries),
        desired_source_count=int(request["budget"]["desired_source_count"]),
        source_priorities=tuple(str(item) for item in request.get("preferences", {}).get("source_priorities") or ()),
    )


def _query_for_profile(objective: str, request: Mapping[str, Any]) -> str:
    profile = str(request.get("profile") or "general")
    terms = _meaningful_terms(objective)
    if "refund" in terms and "policy" in terms:
        return "refund policy"
    if profile == "coding":
        return f"{objective} documentation changelog"
    if profile == "academic":
        return f"{objective} paper study"
    if profile == "legal_compliance":
        return f"{objective} official guidance regulation"
    if profile == "product_shopping":
        return f"{objective} specs review price"
    return objective


def _dedupe_queries(queries: list[ResearchQueryCandidate]) -> list[ResearchQueryCandidate]:
    deduped: list[ResearchQueryCandidate] = []
    seen: set[str] = set()
    for query in queries:
        key = query.query.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    return deduped


def _candidate_sources_from_search(
    search_result: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    selected_urls: set[str],
    searched_urls: set[str],
) -> list[CandidateSource]:
    candidates: list[CandidateSource] = []
    duplicate_counts: dict[str, int] = {}
    for item in _list_of_mappings(search_result.get("results")):
        cluster = _duplicate_cluster_key(item)
        duplicate_counts[cluster] = duplicate_counts.get(cluster, 0) + 1
    for item in _list_of_mappings(search_result.get("results")):
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        rationale: list[str] = []
        score = 0.0
        if url in selected_urls:
            rationale.append("duplicate_selected")
            score -= 100.0
        if url in searched_urls:
            rationale.append("duplicate_search_result")
            score -= 10.0
        searched_urls.add(url)
        title = str(item.get("title") or "")
        excerpt = str(item.get("excerpt") or item.get("content") or "")
        objective_terms = _term_set(str(request.get("objective") or ""))
        matched_terms = objective_terms.intersection(_term_set(f"{title} {excerpt} {url}"))
        if matched_terms:
            score += float(len(matched_terms)) * 2.0
            rationale.append("objective_relevance")
        source_class = _classify_source(item, str(request.get("profile") or "general"))
        priority_score = _profile_source_priority_score(source_class, request)
        if priority_score:
            score += priority_score
            rationale.append(f"profile_priority:{source_class}")
        domain = _source_domain(item)
        preferred_domains = set(request.get("preferences", {}).get("preferred_domains") or ())
        allowed_domains = set(request.get("policy", {}).get("domains") or ())
        if domain in preferred_domains or domain in allowed_domains:
            score += 4.0
            rationale.append("preferred_or_allowed_domain")
        if item.get("freshness_scope"):
            score += 1.0
            rationale.append("freshness_metadata")
        provider = item.get("provider") or item.get("metadata", {}).get("provider") if isinstance(item.get("metadata"), Mapping) else item.get("provider")
        if isinstance(provider, Mapping) and provider.get("id"):
            score += 0.5
            rationale.append("provider_metadata")
        if _has_freshness_signal(item):
            score += 0.75
            rationale.append("freshness_signal")
        cluster_key = _duplicate_cluster_key(item)
        if duplicate_counts.get(cluster_key, 0) > 1:
            score -= 0.75
            rationale.append("duplicate_cluster")
        annotated = dict(item)
        quality = {
            "score": round(score, 3),
            "signals": list(rationale or ("available_result",)),
            "source_class": source_class,
            "duplicate_cluster": cluster_key,
        }
        annotated["quality"] = quality
        annotated["source_class"] = source_class
        candidates.append(CandidateSource(source=annotated, score=score, rationale=tuple(quality["signals"])))
    candidates.sort(
        key=lambda candidate: (
            -candidate.score,
            int(candidate.source.get("rank") or 999_999),
            _source_domain(candidate.source),
            str(candidate.source.get("url") or ""),
        )
    )
    return candidates


def _select_pages_for_inspection(
    candidates: list[CandidateSource],
    *,
    state: WebResearchLoopState,
    request: Mapping[str, Any],
) -> list[SelectedPage]:
    remaining_fetches = int(request["budget"]["fetch_budget"]) - state.fetch_used
    needed_sources = int(request["budget"]["desired_source_count"]) - len(state.evidence_payload())
    limit = max(0, min(remaining_fetches, max(needed_sources, 1), state.max_concurrent_fetches))
    selected: list[SelectedPage] = []
    seen_domains: set[str] = set()
    for candidate in candidates:
        if len(selected) >= limit:
            break
        if candidate.score < -50:
            continue
        domain = _source_domain(candidate.source)
        rationale = list(candidate.rationale)
        if domain and domain in seen_domains and len(candidates) > limit:
            rationale.append("domain_diversity_deprioritized")
            continue
        if domain:
            seen_domains.add(domain)
        selected.append(SelectedPage(source=candidate.source, rationale=tuple(rationale)))
    if not selected and candidates and limit > 0:
        candidate = candidates[0]
        selected.append(SelectedPage(source=candidate.source, rationale=candidate.rationale))
    return selected


def _evaluate_loop_progress(
    request: Mapping[str, Any],
    state: WebResearchLoopState,
    plan: ResearchPlan,
    *,
    low_yield_searches: int = 0,
    replan_used: bool = False,
) -> LoopDecision:
    stop_reason = state.stop_reason(None)
    evidence_count = len(state.evidence_payload())
    search_budget = int(request["budget"]["search_budget"])
    fetch_budget = int(request["budget"]["fetch_budget"])
    if any(not conflict.get("resolved") for conflict in state.conflicts_payload()):
        return LoopDecision(stage="evaluate_progress", stop_reason="unresolved_conflict", rationale="unresolved conflicts recorded")
    if stop_reason == "sufficient_evidence":
        return LoopDecision(stage="evaluate_progress", stop_reason="sufficient_evidence", rationale="desired source count and freshness satisfied")
    if state.policy_rejections and not evidence_count:
        return LoopDecision(stage="evaluate_progress", stop_reason="policy_blocked", rationale="policy rejected all inspected candidates")
    if state.budget_rejections or (
        state.search_used >= search_budget
        and state.fetch_used >= fetch_budget
        and evidence_count < plan.desired_source_count
    ):
        return LoopDecision(stage="evaluate_progress", stop_reason="budget_exhausted", rationale="loop budgets exhausted")
    if stop_reason == "freshness_unsupported":
        return LoopDecision(stage="evaluate_progress", stop_reason="freshness_unsupported", rationale="provider could not satisfy freshness")
    if stop_reason == "partial_result" and state.operation_failures and evidence_count:
        return LoopDecision(stage="evaluate_progress", stop_reason="partial_result", rationale="some evidence collected after an inspection failure")
    if low_yield_searches:
        if not replan_used and state.search_used < search_budget:
            return LoopDecision(
                stage="evaluate_progress",
                stop_reason="remaining_gaps",
                replan=True,
                rationale="low-yield search left source coverage below target",
            )
        if replan_used and evidence_count:
            return LoopDecision(
                stage="evaluate_progress",
                stop_reason="partial_result",
                rationale="repeated low-yield searches left partial verified evidence",
            )
        return LoopDecision(
            stage="evaluate_progress",
            stop_reason="remaining_gaps",
            rationale="repeated low-yield searches found no inspectable evidence",
        )
    if evidence_count < plan.desired_source_count and state.search_used < search_budget and not replan_used:
        return LoopDecision(stage="evaluate_progress", stop_reason="remaining_gaps", replan=True, rationale="source coverage remains below target")
    if evidence_count:
        return LoopDecision(stage="evaluate_progress", stop_reason="partial_result", rationale="some verified evidence collected")
    return LoopDecision(stage="evaluate_progress", stop_reason="remaining_gaps", rationale="no inspectable evidence found")


def _loop_decision_is_terminal(
    decision: LoopDecision,
    *,
    low_yield_searches: int,
    replan_used: bool,
) -> bool:
    if decision.stop_reason in {"budget_exhausted", "policy_blocked", "freshness_unsupported", "unresolved_conflict"}:
        return True
    return bool(
        replan_used
        and low_yield_searches
        and decision.stop_reason in {"remaining_gaps", "partial_result"}
        and not decision.replan
    )


def _replan_queries(request: Mapping[str, Any], plan: ResearchPlan) -> list[ResearchQueryCandidate]:
    if not plan.queries:
        return []
    objective = str(request.get("objective") or plan.objective)
    profile = str(request.get("profile") or "general")
    query = f"{objective} official source"
    if profile == "coding":
        query = f"{objective} official docs"
    if profile in {"legal_compliance", "product_shopping"}:
        query = f"{objective} current official source"
    return _dedupe_queries([ResearchQueryCandidate(query=query, subquestion_ids=("sq-objective",), rationale="bounded_replan", replan=True)])


def _synthesize_from_verified_evidence(request: Mapping[str, Any], state: WebResearchLoopState) -> str:
    conflicts = state.conflicts_payload()
    unresolved = [conflict for conflict in conflicts if not conflict.get("resolved")]
    prefix = "Unresolved conflict: " if unresolved else ""
    return prefix + _synthesize_answer_from_evidence(request, state.evidence_payload())


def _synthesize_answer_from_evidence(request: Mapping[str, Any], evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return ""
    excerpts = []
    for item in evidence[: int(request["budget"]["desired_source_count"])]:
        excerpt = str(item.get("excerpt") or "").strip()
        title = str(item.get("title") or "").strip()
        if title and excerpt.startswith(f"{title} {title} "):
            excerpt = excerpt[len(f"{title} {title} ") :]
        elif title and excerpt.startswith(f"{title} "):
            excerpt = excerpt[len(title) + 1 :]
        if ". " in excerpt:
            excerpt = excerpt.split(". ", 1)[0].strip() + "."
        if excerpt:
            excerpts.append(excerpt)
    return " ".join(excerpts).strip()


def _record_loop_trace(state: WebResearchLoopState, event: Mapping[str, Any]) -> None:
    state.record_unverified_child_metadata_dropped([event])


def _build_planner_request_payload(request: Mapping[str, Any], state: WebResearchLoopState, *, turn_index: int) -> dict[str, Any]:
    budget = state.budget_payload()
    used = budget.get("used") if isinstance(budget.get("used"), Mapping) else {}
    return {
        "objective": request["objective"],
        "profile": request.get("profile", "general"),
        "mode": request.get("mode", "focused"),
        "hard_policy": dict(request.get("hard_policy") or {}),
        "policy": dict(request.get("policy") or {}),
        "preferences": dict(request.get("preferences") or {}),
        "remaining_budgets": {
            "searches": max(0, int(request["budget"]["search_budget"]) - int(used.get("searches") or 0)),
            "fetches": max(0, int(request["budget"]["fetch_budget"]) - int(used.get("fetches") or 0)),
            "finds": max(0, int(request["budget"]["find_budget"]) - int(used.get("finds") or 0)),
            "planner_turns": max(0, int(request["budget"]["max_turns"]) - turn_index),
        },
        "known_sources": _bounded_items(state.sources_payload(), limit=12, text_limit=400),
        "inspected_evidence": _bounded_items(state.evidence_payload(), limit=12, text_limit=700),
        "conflicts": _bounded_items(state.conflicts_payload(), limit=8, text_limit=400),
        "gaps": _bounded_items(state.gaps_payload(), limit=8, text_limit=400),
        "trace_context": _bounded_items(state.trace_summary(max_items=8), limit=8, text_limit=300),
        "authority": "planner proposes actions only; runtime validates policy, identity, budgets, evidence, stop reason, and confidence",
    }


async def _request_planner_decision(payload: Mapping[str, Any], context: ToolContext) -> PlannerDecision:
    raw = await _request_internal_model_json("planner", payload, context)
    try:
        return _parse_planner_decision(raw)
    except ValueError as exc:
        repaired = await _request_internal_model_json(
            "planner_repair",
            {"invalid_response": _invalid_model_response_payload(exc, raw), "payload": payload},
            context,
            required=False,
        )
        if repaired is not None:
            return _parse_planner_decision(repaired)
        raise


async def _request_synthesis_response(payload: Mapping[str, Any], context: ToolContext) -> SynthesisResponse:
    raw = await _request_internal_model_json("synthesizer", payload, context)
    return _parse_synthesis_response(raw)


async def _request_answer_verification(payload: Mapping[str, Any], context: ToolContext) -> AnswerVerificationResponse:
    raw = await _request_internal_model_json("verifier", payload, context)
    return _parse_answer_verification_response(raw)


async def _request_internal_model_json(kind: str, payload: Mapping[str, Any], context: ToolContext, *, required: bool = True) -> Mapping[str, Any] | None:
    contract_payload = _build_model_turn_request_payload(kind, payload)
    scripted = context.metadata.get(_WEB_RESEARCH_MODEL_RESPONSE_METADATA_KEY)
    if isinstance(scripted, list) and scripted:
        item = scripted.pop(0)
        if callable(item):
            item = item(kind, contract_payload)
        if isinstance(item, str):
            return _validate_model_turn_response(kind, _json_object(item, kind=kind))
        if isinstance(item, Mapping):
            return _validate_model_turn_response(kind, item)
        raise ModelTurnValidationError(kind, "non_object_json", "model response must be a JSON object")
    client = context.metadata.get("web_research_model_client")
    if callable(client):
        item = client(kind, contract_payload)
        if hasattr(item, "__await__"):
            item = await item
        if isinstance(item, str):
            return _validate_model_turn_response(kind, _json_object(item, kind=kind))
        if isinstance(item, Mapping):
            return _validate_model_turn_response(kind, item)
        raise ModelTurnValidationError(kind, "non_object_json", "model response must be a JSON object")
    runtime_client = _runtime_model_client(context)
    if runtime_client is not None:
        text = await _request_runtime_model_text(runtime_client, kind, contract_payload, context)
        return _validate_model_turn_response(kind, _json_object(text, kind=kind))
    if required:
        raise ValueError("Pro web_research requires an internal model response provider")
    return None


async def _request_runtime_model_text(client: Any, kind: str, payload: Mapping[str, Any], context: ToolContext) -> str:
    schema_version = str(payload.get("schema_version") or _model_turn_schema_version(kind))
    request = ModelRequest(
        system_prompt=(
            "You are an internal web_research structured JSON adapter. Return one JSON object only. "
            "Follow the supplied schema_version, response_contract, and authority boundaries. "
            "Do not include markdown, citations, or prose outside the JSON object."
        ),
        turn_context=TurnContext(
            session_id=context.session_id,
            turn_id=context.turn_id,
            agent_name=context.agent_name,
            cwd=str(context.cwd),
            messages=tuple(context.messages),
            available_tools=tuple(tool.name for tool in context.tool_pool),
        ),
        messages=(
            RuntimeMessage(
                message_id=f"web-research-{kind}",
                role=MessageRole.USER,
                content=json.dumps(
                    {
                        "schema_version": schema_version,
                        "kind": kind,
                        "payload": payload.get("input_state") if isinstance(payload.get("input_state"), Mapping) else _bounded_model_payload(payload),
                        "instructions": payload.get("instructions"),
                        "authority": payload.get("authority"),
                        "response_contract": payload.get("response_contract"),
                    },
                    sort_keys=True,
                ),
            ),
        ),
        max_output_tokens=1200,
        metadata={"web_research_internal_model_turn": {"kind": kind, "schema_version": schema_version}},
    )
    if hasattr(client, "complete"):
        try:
            response = await client.complete(request)
        except NotImplementedError:
            response = None
        if response is not None:
            message = getattr(response, "message", None)
            text = getattr(message, "text", "") if message is not None else ""
            if text:
                return str(text)
    if not hasattr(client, "stream"):
        raise ValueError("Runtime model client does not support web_research JSON turns")
    chunks: list[str] = []
    async for event in client.stream(request):
        event_type = getattr(event, "event_type", None)
        if event_type == ModelStreamEventType.CONTENT_DELTA:
            chunks.append(str(event.payload.get("text") or ""))
        elif event_type == ModelStreamEventType.ERROR:
            error = str(event.payload.get("error") or "Runtime model stream failed")
            raise ValueError(error)
    return "".join(chunks).strip()


def _build_model_turn_request_payload(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    schema_kind = _model_turn_contract_kind(kind)
    contract = _WEB_RESEARCH_MODEL_TURN_CONTRACTS[schema_kind]
    input_state = _bounded_model_payload(payload)
    request_payload: dict[str, Any] = {
        "schema_version": contract["schema_version"],
        "kind": kind,
        "input_state": input_state,
        "instructions": contract["instructions"],
        "authority": contract["authority"],
        "response_contract": contract["response"],
    }
    # Keep bounded legacy top-level fields for existing explicit hooks while making
    # the schema-versioned contract available to the same scripted path.
    request_payload.update(input_state)
    return request_payload


def _model_turn_contract_kind(kind: str) -> str:
    return "repair" if kind.endswith("_repair") else kind


def _model_turn_schema_version(kind: str) -> str:
    return str(_WEB_RESEARCH_MODEL_TURN_CONTRACTS[_model_turn_contract_kind(kind)]["schema_version"])


def _repair_target_kind(kind: str) -> str:
    if kind == "planner_repair":
        return "planner"
    return "synthesizer"


def _validate_model_turn_response(kind: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    response = dict(raw)
    expected_schema_version = _model_turn_schema_version(kind)
    schema_version = _identity_value(response.get("schema_version"))
    if not schema_version:
        raise ModelTurnValidationError(kind, "missing_required_field", "model response missing schema_version", raw_response=response)
    if schema_version != expected_schema_version:
        raise ModelTurnValidationError(kind, "schema_version_mismatch", "model response schema_version is unsupported", raw_response=response)
    response_kind = _identity_value(response.get("kind"))
    if response_kind and response_kind not in {kind, _model_turn_contract_kind(kind)}:
        raise ModelTurnValidationError(kind, "invalid_enum", "model response kind does not match the requested turn", raw_response=response)
    if _model_turn_contract_kind(kind) == "repair":
        repaired = response.get("repaired_response")
        if not isinstance(repaired, Mapping):
            raise ModelTurnValidationError(kind, "missing_required_field", "repair response must include repaired_response", raw_response=response)
        return _validate_model_turn_response(_repair_target_kind(kind), repaired)
    if kind == "planner":
        actions = response.get("actions")
        if actions is not None and not isinstance(actions, list):
            raise ModelTurnValidationError(kind, "invalid_type", "planner actions must be a list", raw_response=response)
        if actions is None and not _identity_value(response.get("stop_intent") or response.get("stop_reason")):
            raise ModelTurnValidationError(kind, "missing_required_field", "planner response must include actions or stop_intent", raw_response=response)
    elif kind == "synthesizer":
        if not isinstance(response.get("claims"), list):
            raise ModelTurnValidationError(kind, "missing_required_field", "synthesizer response must include claims as a list", raw_response=response)
        if not isinstance(response.get("answer_units"), list):
            raise ModelTurnValidationError(kind, "missing_required_field", "synthesizer response must include answer_units as a list", raw_response=response)
    elif kind == "verifier":
        units = response.get("unit_statuses") if "unit_statuses" in response else response.get("units")
        if not isinstance(units, list):
            raise ModelTurnValidationError(kind, "missing_required_field", "verifier response must include unit_statuses as a list", raw_response=response)
    return response


def _invalid_model_response_payload(exc: ValueError, raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message": _bounded_trace_text(exc),
        "validation_class": _validation_class(exc),
    }
    raw_response = getattr(exc, "raw_response", None)
    if isinstance(raw_response, Mapping):
        payload["raw_response"] = _bounded_model_payload(raw_response)
    elif raw is not None:
        payload["raw_response"] = _bounded_model_payload(raw)
    return payload


def _validation_class(exc: BaseException) -> str:
    if isinstance(exc, ModelTurnValidationError):
        return exc.validation_class
    return "invalid_response"


def _model_turn_trace_event(kind: str, outcome: str, *, exc: BaseException | None = None, repair_attempt: bool = False, fallback_path: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event": "model_turn_validation",
        "kind": kind,
        "schema_version": _model_turn_schema_version(kind),
        "validation_outcome": outcome,
    }
    if exc is not None:
        event["validation_class"] = _validation_class(exc)
        event["error"] = _bounded_trace_text(exc)
    if repair_attempt:
        event["repair_attempt"] = True
    if fallback_path:
        event["fallback_path"] = fallback_path
    return event


def _bounded_model_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _bound_model_value(value, depth=0) for key, value in payload.items()}


def _bound_model_value(value: Any, *, depth: int) -> Any:
    if depth >= 4:
        return _bounded_trace_text(value)
    if isinstance(value, Mapping):
        return {str(key): _bound_model_value(inner, depth=depth + 1) for key, inner in list(value.items())[:24]}
    if isinstance(value, (list, tuple)):
        return [_bound_model_value(item, depth=depth + 1) for item in list(value)[:24]]
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, bool | int | float) or value is None:
        return value
    return _bounded_trace_text(value)


def _parse_planner_decision(raw: Mapping[str, Any]) -> PlannerDecision:
    actions: list[ResearchAction] = []
    for item in _list_of_mappings(raw.get("actions")):
        action_type = str(item.get("type") or item.get("action") or "").strip().lower()
        if action_type not in {"search", "fetch", "find", "direct_url_fetch", "stop"}:
            raise ModelTurnValidationError("planner", "invalid_enum", "planner action type must be search, fetch, find, direct_url_fetch, or stop", raw_response=raw)
        actions.append(
            ResearchAction(
                type=action_type,
                query=_optional_text(item.get("query")),
                source_handle=_optional_text(item.get("source_handle") or item.get("source_id")),
                page_handle=_optional_text(item.get("page_handle") or item.get("page_id")),
                url=_optional_text(item.get("url")),
                pattern=_optional_text(item.get("pattern")),
                rationale=_bounded_trace_text(item.get("rationale") or ""),
                stop_intent=_optional_text(item.get("stop_intent") or item.get("stop_reason")),
            )
        )
    stop_intent = _optional_text(raw.get("stop_intent") or raw.get("stop_reason"))
    coverage_raw = raw.get("coverage") or raw.get("coverage_assessment")
    coverage = None
    if isinstance(coverage_raw, Mapping):
        coverage = CoverageAssessment(
            status=str(coverage_raw.get("status") or "unknown"),
            confidence=_optional_text(coverage_raw.get("confidence")),
            missing=tuple(str(item) for item in coverage_raw.get("missing") or () if str(item).strip()) if isinstance(coverage_raw.get("missing"), list) else (),
            rationale=_bounded_trace_text(coverage_raw.get("rationale") or ""),
        )
    gaps = tuple(
        PlannerGap(kind=str(item.get("kind") or "planner_gap"), message=_bounded_trace_text(item.get("message") or item.get("gap") or ""), subquestion_id=_optional_text(item.get("subquestion_id")))
        for item in _list_of_mappings(raw.get("expected_gaps") or raw.get("gaps"))
        if str(item.get("message") or item.get("gap") or "").strip()
    )
    if not actions and not stop_intent:
        raise ModelTurnValidationError("planner", "missing_required_field", "planner decision must include actions or stop_intent", raw_response=raw)
    return PlannerDecision(actions=tuple(actions), rationale=_bounded_trace_text(raw.get("rationale") or ""), coverage=coverage, expected_gaps=gaps, stop_intent=stop_intent, raw=dict(raw))


def _parse_synthesis_response(raw: Mapping[str, Any]) -> SynthesisResponse:
    claims: list[SynthesisClaim] = []
    for index, item in enumerate(_list_of_mappings(raw.get("claims"))):
        evidence_ids = item.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            evidence_id = item.get("evidence_id")
            evidence_ids = [evidence_id] if evidence_id else []
        claims.append(
            SynthesisClaim(
                id=_optional_text(item.get("id")) or f"claim-{index + 1}",
                claim=str(item.get("claim") or item.get("text") or "").strip(),
                evidence_ids=tuple(str(value).strip() for value in evidence_ids if str(value).strip()),
                excerpt=_optional_text(item.get("excerpt") or item.get("exact_excerpt")),
                start=item.get("start") if isinstance(item.get("start"), int) else item.get("match_start") if isinstance(item.get("match_start"), int) else None,
                end=item.get("end") if isinstance(item.get("end"), int) else item.get("match_end") if isinstance(item.get("match_end"), int) else None,
                confidence=_optional_text(item.get("confidence")),
                claim_key=_optional_text(item.get("claim_key") or item.get("key")),
                stance=_optional_text(item.get("stance")),
                conflicts_with=tuple(str(value).strip() for value in item.get("conflicts_with") or () if str(value).strip()) if isinstance(item.get("conflicts_with"), list) else (),
                incompatible_with=tuple(str(value).strip() for value in item.get("incompatible_with") or item.get("explicit_incompatibility") or () if str(value).strip()) if isinstance(item.get("incompatible_with") or item.get("explicit_incompatibility"), list) else (),
                resolved=item.get("resolved") if isinstance(item.get("resolved"), bool) else None,
                resolution_rationale=_optional_text(item.get("resolution_rationale") or item.get("rationale")),
            )
        )
    limitations = raw.get("limitations") or raw.get("gaps") or ()
    if not isinstance(limitations, list):
        limitations = []
    self_verification = raw.get("self_verification")
    return SynthesisResponse(
        answer=str(raw.get("answer") or raw.get("summary") or "").strip(),
        claims=tuple(claims),
        answer_units=_parse_answer_units(raw.get("answer_units"), turn_kind="synthesizer"),
        limitations=tuple(_bounded_trace_text(item) for item in limitations if str(item).strip()),
        conflict_treatment=_bounded_trace_text(raw.get("conflict_treatment") or ""),
        confidence=_optional_text(raw.get("confidence")),
        confidence_rationale=_bounded_trace_text(raw.get("confidence_rationale") or raw.get("rationale") or ""),
        self_verification=dict(self_verification) if isinstance(self_verification, Mapping) else {},
        raw=dict(raw),
    )


def _parse_answer_units(raw: Any, *, turn_kind: str) -> tuple[AnswerUnit, ...]:
    if not isinstance(raw, list):
        raise ModelTurnValidationError(turn_kind, "missing_required_field", "answer_units must be a list")
    if len(raw) > _WEB_RESEARCH_MAX_ANSWER_UNITS:
        raise ModelTurnValidationError(turn_kind, "oversized_field", "answer_units exceeds the maximum unit count")
    units: list[AnswerUnit] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ModelTurnValidationError(turn_kind, "invalid_type", "answer_units entries must be objects")
        unit_id = _required_bounded_text(item.get("id"), "answer_units.id", turn_kind, max_chars=_WEB_RESEARCH_MAX_ANSWER_UNIT_ID_CHARS)
        if unit_id in seen:
            raise ModelTurnValidationError(turn_kind, "duplicate_id", "answer_unit ids must be unique")
        seen.add(unit_id)
        text = _required_bounded_text(item.get("text"), "answer_units.text", turn_kind, max_chars=_WEB_RESEARCH_MAX_ANSWER_UNIT_TEXT_CHARS)
        kind = _required_enum(item.get("kind"), "answer_units.kind", _WEB_RESEARCH_ANSWER_UNIT_KINDS, turn_kind)
        support = _required_enum(item.get("support"), "answer_units.support", _WEB_RESEARCH_ANSWER_UNIT_SUPPORTS, turn_kind)
        unit = AnswerUnit(
            id=unit_id,
            text=text,
            kind=kind,
            support=support,
            claim_ids=_reference_ids(item, "claim_ids", "claim_id", turn_kind),
            gap_ids=_reference_ids(item, "gap_ids", "gap_id", turn_kind),
            conflict_ids=_reference_ids(item, "conflict_ids", "conflict_id", turn_kind),
            limitation_ids=_reference_ids(item, "limitation_ids", "limitation_id", turn_kind),
            evidence_ids=_reference_ids(item, "evidence_ids", "evidence_id", turn_kind),
            rationale=_bounded_trace_text(item.get("rationale") or "", limit=360),
            raw=dict(item),
        )
        _validate_answer_unit_kind_support(unit, turn_kind=turn_kind, raw=item, index=index)
        units.append(unit)
    return tuple(units)


def _parse_answer_verification_response(raw: Mapping[str, Any]) -> AnswerVerificationResponse:
    raw_units = raw.get("unit_statuses") if "unit_statuses" in raw else raw.get("units")
    if not isinstance(raw_units, list):
        raise ModelTurnValidationError("verifier", "missing_required_field", "verifier unit_statuses must be a list", raw_response=raw)
    if len(raw_units) > _WEB_RESEARCH_MAX_ANSWER_UNITS:
        raise ModelTurnValidationError("verifier", "oversized_field", "verifier unit_statuses exceeds the maximum unit count", raw_response=raw)
    units: list[AnswerVerificationUnit] = []
    seen: set[str] = set()
    for item in raw_units:
        if not isinstance(item, Mapping):
            raise ModelTurnValidationError("verifier", "invalid_type", "verifier unit_status entries must be objects", raw_response=raw)
        unit_id = _required_bounded_text(item.get("unit_id") or item.get("id"), "unit_statuses.unit_id", "verifier", max_chars=_WEB_RESEARCH_MAX_ANSWER_UNIT_ID_CHARS)
        if unit_id in seen:
            raise ModelTurnValidationError("verifier", "duplicate_id", "verifier unit ids must be unique", raw_response=raw)
        seen.add(unit_id)
        status = _required_enum(item.get("status") or item.get("support"), "unit_statuses.status", _WEB_RESEARCH_VERIFIER_STATUSES, "verifier")
        support = _required_enum(item.get("support") or status, "unit_statuses.support", _WEB_RESEARCH_ANSWER_UNIT_SUPPORTS, "verifier")
        units.append(
            AnswerVerificationUnit(
                unit_id=unit_id,
                status=status,
                support=support,
                claim_ids=_reference_ids(item, "claim_ids", "claim_id", "verifier"),
                gap_ids=_reference_ids(item, "gap_ids", "gap_id", "verifier"),
                conflict_ids=_reference_ids(item, "conflict_ids", "conflict_id", "verifier"),
                limitation_ids=_reference_ids(item, "limitation_ids", "limitation_id", "verifier"),
                evidence_ids=_reference_ids(item, "evidence_ids", "evidence_id", "verifier"),
                rationale=_bounded_trace_text(item.get("rationale") or "", limit=360),
            )
        )
    return AnswerVerificationResponse(units=tuple(units), raw=dict(raw))


def _required_bounded_text(value: Any, field_name: str, turn_kind: str, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ModelTurnValidationError(turn_kind, "missing_required_field", f"{field_name} is required")
    if len(text) > max_chars:
        raise ModelTurnValidationError(turn_kind, "oversized_field", f"{field_name} exceeds {max_chars} characters")
    return text


def _required_enum(value: Any, field_name: str, allowed: frozenset[str], turn_kind: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise ModelTurnValidationError(turn_kind, "missing_required_field", f"{field_name} is required")
    if text not in allowed:
        raise ModelTurnValidationError(turn_kind, "invalid_enum", f"{field_name} has an unsupported value")
    return text


def _reference_ids(raw: Mapping[str, Any], plural_key: str, singular_key: str, turn_kind: str) -> tuple[str, ...]:
    values: list[Any]
    if isinstance(raw.get(plural_key), list):
        values = list(raw.get(plural_key) or [])
    elif raw.get(singular_key):
        values = [raw.get(singular_key)]
    else:
        values = []
    refs: list[str] = []
    for value in values:
        ref = str(value or "").strip()
        if not ref:
            continue
        if len(ref) > _WEB_RESEARCH_MAX_REFERENCE_ID_CHARS:
            raise ModelTurnValidationError(turn_kind, "oversized_field", f"{plural_key} contains an oversized id")
        refs.append(ref)
    return tuple(dict.fromkeys(refs))


def _validate_answer_unit_kind_support(unit: AnswerUnit, *, turn_kind: str, raw: Mapping[str, Any], index: int) -> None:
    _ = raw, index
    support_by_kind = {
        "claim": {"entailed", "unsupported", "contradicted"},
        "limitation": {"limitation", "unsupported"},
        "gap": {"gap", "unsupported"},
        "conflict": {"conflict", "unsupported", "contradicted"},
        "transition": {"non_factual", "unsupported", "contradicted"},
    }
    if unit.support not in support_by_kind[unit.kind]:
        raise ModelTurnValidationError(turn_kind, "invalid_enum", "answer_unit support is incompatible with its kind")
    if unit.kind == "claim" and unit.support == "entailed" and not unit.claim_ids:
        raise ModelTurnValidationError(turn_kind, "out_of_state_reference", "claim answer_units must reference accepted claim ids")
    if unit.kind == "gap" and unit.support == "gap" and not unit.gap_ids:
        raise ModelTurnValidationError(turn_kind, "out_of_state_reference", "gap answer_units must reference accepted gap ids")
    if unit.kind == "conflict" and unit.support == "conflict" and not unit.conflict_ids:
        raise ModelTurnValidationError(turn_kind, "out_of_state_reference", "conflict answer_units must reference accepted conflict ids")
    if unit.kind == "limitation" and unit.support == "limitation" and not unit.limitation_ids:
        raise ModelTurnValidationError(turn_kind, "out_of_state_reference", "limitation answer_units must reference accepted limitation ids")


def _record_planner_decision_trace(state: WebResearchLoopState, decision: PlannerDecision, *, turn_index: int) -> None:
    event: dict[str, Any] = {
        "event": "planner_decision",
        "turn": turn_index + 1,
        "actions": [action.type for action in decision.actions],
        "rationale": decision.rationale,
        "schema_version": _WEB_RESEARCH_PLANNER_SCHEMA_VERSION,
        "validation_outcome": "accepted",
    }
    if decision.stop_intent:
        event["stop_intent"] = decision.stop_intent
    if decision.coverage is not None:
        event["coverage"] = {
            "status": decision.coverage.status,
            "confidence": decision.coverage.confidence,
            "missing": list(decision.coverage.missing),
            "rationale": decision.coverage.rationale,
        }
    if decision.expected_gaps:
        event["expected_gaps"] = [{"kind": gap.kind, "message": gap.message} for gap in decision.expected_gaps]
    _record_loop_trace(state, event)


async def _execute_validated_planner_action(
    action: ResearchAction,
    request: Mapping[str, Any],
    context: ToolContext,
    state: WebResearchLoopState,
) -> bool:
    try:
        if action.type == "search":
            query = str(action.query or "").strip()
            if not query:
                raise ValueError("planner search query must be non-empty")
            await web_search_tool({"query": query}, context)
        elif action.type == "fetch":
            source = _resolve_planner_source(action, state)
            await web_fetch_tool({"source": source}, context)
        elif action.type == "direct_url_fetch":
            url = str(action.url or "").strip()
            if not url:
                raise ValueError("planner direct_url_fetch url must be non-empty")
            result = await _web_fetch_impl(
                {"url": url},
                context,
                failure_tool="web_direct_url_fetch",
                failure_metadata={"provenance": "direct_url"},
            )
            source = dict(result.get("source") or {})
            source["provenance"] = "direct_url"
            source["quality"] = {**(source.get("quality") if isinstance(source.get("quality"), Mapping) else {}), "provenance": "direct_url"}
            result = dict(result)
            result["source"] = source
            result["provenance"] = "direct_url"
            state.record_fetch(result)
            _record_loop_trace(state, {"event": "direct_url_fetch", "url": url, "provenance": "direct_url"})
        elif action.type == "find":
            page = _resolve_planner_page(action, state)
            pattern = str(action.pattern or "").strip()
            if not pattern:
                raise ValueError("planner find pattern must be non-empty")
            await web_find_tool({"page": page, "pattern": pattern}, context)
        elif action.type == "stop":
            return False
        else:
            raise ValueError(f"unsupported planner action: {action.type}")
    except Exception as exc:
        if not _is_recoverable_web_operation_error(exc):
            raise
        state.record_gap({"kind": "rejected_planner_action", "message": _bounded_trace_text(exc), "action": action.type})
        _record_loop_trace(
            state,
            {
                "event": "planner_action_rejected",
                "action": action.type,
                "reason": _bounded_trace_text(exc),
                **({"source_handle": action.source_handle} if action.source_handle else {}),
                **({"url": action.url} if action.url else {}),
            },
        )
        return False
    _record_loop_trace(state, {"event": "planner_action_accepted", "action": action.type, **({"rationale": action.rationale} if action.rationale else {})})
    return True


def _resolve_planner_source(action: ResearchAction, state: WebResearchLoopState) -> Mapping[str, Any]:
    handle = _identity_value(action.source_handle or action.page_handle)
    if not handle:
        raise ValueError("planner fetch requires a known source_handle")
    for source in state.sources_payload():
        values = {_identity_value(source.get(key)) for key in ("id", "source_handle", "page_handle", "url")}
        if handle in values:
            return source
    raise ValueError("planner fetch referenced an unknown source_handle")


def _resolve_planner_page(action: ResearchAction, state: WebResearchLoopState) -> Mapping[str, Any]:
    handle = _identity_value(action.page_handle or action.source_handle or action.url)
    if not handle:
        raise ValueError("planner find requires an inspected page identity")
    for page in state.pages_read_payload():
        values = {_identity_value(page.get(key)) for key in ("page_handle", "source_handle", "url")}
        if handle in values:
            return page
    raise ValueError("planner find referenced an uninspected page")


def _pro_runtime_terminal_decision(request: Mapping[str, Any], state: WebResearchLoopState, *, stop_intent: str | None) -> str:
    base = state.stop_reason(stop_intent)
    if any(not conflict.get("resolved") for conflict in state.conflicts_payload()):
        return "unresolved_conflict"
    if _direct_url_only_evidence(state) and int(request["budget"].get("desired_source_count") or 1) > 1:
        return "remaining_gaps"
    if stop_intent == "sufficient_evidence" and base != "sufficient_evidence":
        return base
    return base


def _direct_url_only_evidence(state: WebResearchLoopState) -> bool:
    evidence = state.evidence_payload()
    if not evidence:
        return False
    sources = state.sources_payload()
    direct_urls = {
        source.get("url")
        for source in sources
        if source.get("provenance") == "direct_url" or source.get("quality", {}).get("provenance") == "direct_url"
    }
    trace_direct_urls = {event.get("url") for event in state.trace_summary(max_items=32) if event.get("event") == "direct_url_fetch"}
    direct_urls.update(trace_direct_urls)
    return bool(direct_urls) and all(item.get("url") in direct_urls for item in evidence)


async def _run_pro_synthesis(request: Mapping[str, Any], context: ToolContext, state: WebResearchLoopState) -> dict[str, Any]:
    runtime_proof_state = _normalize_answer_proof_state(request, state, (), ())
    payload = {
        "objective": request["objective"],
        "evidence": _bounded_items(state.evidence_payload(), limit=16, text_limit=900),
        "conflicts": _bounded_items(state.conflicts_payload(), limit=8, text_limit=500),
        "gaps": _bounded_items(state.gaps_payload(), limit=8, text_limit=500),
        "answer_proof_state": {
            "gaps": _bounded_items(runtime_proof_state["gaps"], limit=8, text_limit=500),
            "conflicts": _bounded_items(runtime_proof_state["conflicts"], limit=8, text_limit=500),
            "limitations": _bounded_items(runtime_proof_state["limitations"], limit=8, text_limit=500),
        },
        "freshness": _freshness_payload(request, state),
        "provider": state.provider_payload() or {},
    }
    trace: list[dict[str, Any]] = []
    try:
        response = await _request_synthesis_response(payload, context)
        trace.append(_model_turn_trace_event("synthesizer", "accepted"))
    except ValueError as exc:
        state.record_gap({"kind": "unsupported_synthesis", "message": "Synthesizer response could not be parsed."})
        trace.append(_model_turn_trace_event("synthesizer", "rejected", exc=exc, fallback_path="ledger_synthesis"))
        return {"answer": "", "claims": [], "gaps": [], "conflicts": [], "answer_units": [], "trace": trace, "answer_accepted": False}
    accepted, rejected = _validate_synthesis_claims(response, state.evidence_payload())
    repair_used = False
    if (rejected or not response.answer_units) and _WEB_RESEARCH_DEFAULT_SYNTHESIS_REPAIR_TURNS > 0:
        repair_used = True
        trace.append(
            {
                "event": "synthesis_repair_attempt",
                "unsupported_claims": len(rejected),
                "missing_answer_units": not response.answer_units,
            }
        )
        try:
            repaired_raw = await _request_internal_model_json(
                "synthesis_repair",
                {"invalid_claims": rejected, "missing_answer_units": not response.answer_units, "payload": payload},
                context,
                required=False,
            )
            if repaired_raw is not None:
                trace.append(_model_turn_trace_event("synthesis_repair", "accepted", repair_attempt=True))
                repaired = _parse_synthesis_response(repaired_raw)
                response = repaired
                accepted, rejected = _validate_synthesis_claims(repaired, state.evidence_payload())
        except ValueError as exc:
            trace.append(_model_turn_trace_event("synthesis_repair", "rejected", exc=exc, repair_attempt=True))
    proof_state = _normalize_answer_proof_state(request, state, accepted, response.limitations)
    proof = await _verify_answer_proof(request, context, state, response, proof_state, trace, repair_used=repair_used)
    answer_accepted = bool(proof.accepted_units and not proof.fallback_used)
    answer = _assemble_answer_from_answer_units(proof.accepted_units) if answer_accepted else ""
    gaps = _public_proof_gaps(proof_state)
    conflicts = [dict(item) for item in proof_state["conflicts"]]
    if rejected:
        state.record_gap({"kind": "unsupported_synthesis", "message": "Unsupported synthesis claims were dropped."})
        gaps.append({"kind": "unsupported_synthesis", "message": "Unsupported synthesis claims were dropped."})
        trace.append({"event": "unsupported_synthesis_dropped", "claims": len(rejected), "repair_used": repair_used})
    if proof.dropped_units:
        state.record_gap({"kind": "answer_proof_failed", "message": "Unsupported answer units were not projected."})
        gaps.append({"kind": "answer_proof_failed", "message": "Unsupported answer units were not projected."})
        trace.append(
            {
                "event": "answer_units_dropped",
                "units": len(proof.dropped_units),
                "repair_used": proof.repair_used,
                "fallback_used": proof.fallback_used,
            }
        )
    if proof.fallback_used:
        trace.append({"event": "answer_proof_fallback", "fallback_path": "ledger_synthesis"})
    trace.append(
        {
            "event": "answer_proof_validated",
            "accepted_units": len(proof.accepted_units),
            "dropped_units": len(proof.dropped_units),
            "answer_accepted": answer_accepted,
            "repair_used": proof.repair_used,
            "fallback_used": proof.fallback_used,
        }
    )
    trace.append({"event": "synthesis_validated", "accepted_claims": len(accepted), "unsupported_claims": len(rejected), "answer_accepted": answer_accepted})
    state.record_unverified_child_metadata_dropped(trace)
    return {
        "answer": answer,
        "claims": accepted,
        "gaps": _dedupe_records(gaps),
        "conflicts": _dedupe_records(conflicts),
        "answer_units": [_public_answer_unit(unit) for unit in proof.accepted_units],
        "trace": trace,
        "answer_accepted": answer_accepted,
    }


async def _verify_answer_proof(
    request: Mapping[str, Any],
    context: ToolContext,
    state: WebResearchLoopState,
    response: SynthesisResponse,
    proof_state: Mapping[str, Any],
    trace: list[dict[str, Any]],
    *,
    repair_used: bool,
) -> AnswerProof:
    proposed = response.answer_units
    if not proposed:
        return AnswerProof(
            proposed_units=(),
            accepted_units=(),
            dropped_units=({"reason": "missing_answer_units"},),
            repair_used=repair_used,
            fallback_used=True,
        )
    payload = _build_answer_verifier_payload(request, state, proof_state, proposed)
    try:
        verification = await _request_answer_verification(payload, context)
        _validate_answer_verification_response(verification, proposed, proof_state)
        trace.append(_model_turn_trace_event("verifier", "accepted"))
    except ValueError as exc:
        state.record_gap({"kind": "answer_verification_failed", "message": "Answer verifier output failed schema or reference validation."})
        trace.append(_model_turn_trace_event("verifier", "rejected", exc=exc, fallback_path="ledger_synthesis"))
        return AnswerProof(
            proposed_units=proposed,
            accepted_units=(),
            dropped_units=({"reason": "verifier_failed", "validation_class": _validation_class(exc)},),
            repair_used=repair_used,
            fallback_used=True,
        )
    accepted, dropped = _accepted_answer_units(proposed, verification, proof_state)
    fallback = not accepted or any(item.get("support") in {"unsupported", "contradicted"} for item in dropped)
    return AnswerProof(
        proposed_units=proposed,
        accepted_units=tuple(accepted),
        dropped_units=tuple(dropped),
        verification=verification,
        repair_used=repair_used,
        fallback_used=fallback and not accepted,
    )


def _build_answer_verifier_payload(
    request: Mapping[str, Any],
    state: WebResearchLoopState,
    proof_state: Mapping[str, Any],
    proposed_units: Sequence[AnswerUnit],
) -> dict[str, Any]:
    return {
        "objective": request["objective"],
        "accepted_claims": _bounded_items([dict(item) for item in proof_state["claims"]], limit=24, text_limit=700),
        "evidence": _bounded_items(state.evidence_payload(), limit=16, text_limit=700),
        "gaps": _bounded_items([dict(item) for item in proof_state["gaps"]], limit=12, text_limit=500),
        "conflicts": _bounded_items([dict(item) for item in proof_state["conflicts"]], limit=12, text_limit=500),
        "limitations": _bounded_items([dict(item) for item in proof_state["limitations"]], limit=12, text_limit=500),
        "proposed_answer_units": [_public_answer_unit(unit) for unit in proposed_units],
        "authority": "verifier classifies answer units only against supplied proof state; runtime validates references and projection",
    }


def _normalize_answer_proof_state(
    request: Mapping[str, Any],
    state: WebResearchLoopState,
    accepted_claims: Sequence[Mapping[str, Any]],
    synthesis_limitations: Sequence[str],
) -> dict[str, Any]:
    evidence = state.evidence_payload()
    evidence_ids = {_identity_value(item.get("id")) for item in evidence if _identity_value(item.get("id"))}
    claims = _normalize_proof_records("claim", [dict(item) for item in accepted_claims])
    gaps = _normalize_proof_records("gap", state.gaps_payload())
    limitations = _normalize_proof_records("limitation", _runtime_limitations_payload(request, state, synthesis_limitations))
    conflicts = _normalize_proof_records("conflict", [*state.conflicts_payload(), *_detect_claim_conflicts([dict(item) for item in claims])])
    return {
        "claims": claims,
        "gaps": gaps,
        "conflicts": conflicts,
        "limitations": limitations,
        "evidence_ids": evidence_ids,
    }


def _runtime_limitations_payload(
    request: Mapping[str, Any],
    state: WebResearchLoopState,
    synthesis_limitations: Sequence[str],
) -> list[dict[str, Any]]:
    limitations: list[dict[str, Any]] = []
    freshness = _freshness_payload(request, state)
    if freshness.get("required") and freshness.get("status") not in {"enforced", "satisfied"}:
        limitations.append(
            {
                "kind": "freshness_limitation",
                "message": "Freshness requirements were not fully supported by the inspected provider evidence.",
                "freshness_status": freshness.get("status"),
            }
        )
    provider_fallback = state.provider_fallback_payload()
    if provider_fallback and provider_fallback.get("used"):
        limitations.append(
            {
                "kind": "provider_fallback_limitation",
                "message": "Research used a fallback provider; source freshness or coverage may be limited.",
                "provider_fallback": True,
            }
        )
    for item in synthesis_limitations:
        limitations.append({"kind": "synthesis_limitation", "message": _bounded_trace_text(item)})
    return limitations


def _normalize_proof_records(kind: str, records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        item = dict(record)
        proof_id = _bounded_proof_id(item.get("id")) or _stable_proof_id(kind, item, index)
        if proof_id in seen:
            proof_id = _stable_proof_id(kind, {**item, "_ordinal": index}, index)
        seen.add(proof_id)
        item["id"] = proof_id
        item.setdefault("proof_kind", kind)
        normalized.append(item)
    return normalized


def _bounded_proof_id(value: Any) -> str:
    proof_id = _identity_value(value)
    if not proof_id:
        return ""
    if len(proof_id) <= _WEB_RESEARCH_MAX_ANSWER_UNIT_ID_CHARS:
        return proof_id
    digest = hashlib.sha256(proof_id.encode("utf-8")).hexdigest()[:12]
    return f"id-{digest}"


def _stable_proof_id(kind: str, item: Mapping[str, Any], index: int) -> str:
    fields: list[str] = [kind, str(index)]
    for key in (
        "claim_key",
        "claim",
        "claim_text",
        "message",
        "kind",
        "source_handle",
        "page_handle",
        "url",
        "freshness_status",
    ):
        value = _identity_value(item.get(key))
        if value:
            fields.append(value)
    for key in ("evidence_ids", "source_handles", "claim_ids", "conflict_ids", "gap_ids", "limitation_ids"):
        raw = item.get(key)
        if isinstance(raw, list):
            fields.extend(str(value) for value in raw[:8])
    digest = hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()[:12]
    return f"{kind}-{digest}"


def _validate_answer_verification_response(
    verification: AnswerVerificationResponse,
    proposed_units: Sequence[AnswerUnit],
    proof_state: Mapping[str, Any],
) -> None:
    proposed_ids = {unit.id for unit in proposed_units}
    verified_ids = {unit.unit_id for unit in verification.units}
    unknown = verified_ids - proposed_ids
    if unknown:
        raise ModelTurnValidationError("verifier", "out_of_state_reference", "verifier referenced unknown answer unit ids")
    missing = proposed_ids - verified_ids
    if missing:
        raise ModelTurnValidationError("verifier", "missing_required_field", "verifier omitted proposed answer unit statuses")
    for unit in verification.units:
        if not _refs_resolve(unit.claim_ids, proof_state["claims"]):
            raise ModelTurnValidationError("verifier", "out_of_state_reference", "verifier referenced unknown claim ids")
        if not _refs_resolve(unit.gap_ids, proof_state["gaps"]):
            raise ModelTurnValidationError("verifier", "out_of_state_reference", "verifier referenced unknown gap ids")
        if not _refs_resolve(unit.conflict_ids, proof_state["conflicts"]):
            raise ModelTurnValidationError("verifier", "out_of_state_reference", "verifier referenced unknown conflict ids")
        if not _refs_resolve(unit.limitation_ids, proof_state["limitations"]):
            raise ModelTurnValidationError("verifier", "out_of_state_reference", "verifier referenced unknown limitation ids")
        unknown_evidence = set(unit.evidence_ids) - set(proof_state["evidence_ids"])
        if unknown_evidence:
            raise ModelTurnValidationError("verifier", "out_of_state_reference", "verifier referenced unknown evidence ids")


def _accepted_answer_units(
    proposed_units: Sequence[AnswerUnit],
    verification: AnswerVerificationResponse,
    proof_state: Mapping[str, Any],
) -> tuple[list[AnswerUnit], list[dict[str, Any]]]:
    status_by_id = {unit.unit_id: unit for unit in verification.units}
    accepted: list[AnswerUnit] = []
    dropped: list[dict[str, Any]] = []
    for unit in proposed_units:
        status = status_by_id.get(unit.id)
        if status is None:
            dropped.append(_dropped_answer_unit(unit, "missing_verifier_status"))
            continue
        if status.status in {"unsupported", "contradicted", "rejected"} or status.support in {"unsupported", "contradicted"}:
            dropped.append(_dropped_answer_unit(unit, status.status, support=status.support))
            continue
        resolved, reason = _answer_unit_references_resolve(unit, status, proof_state)
        if not resolved:
            dropped.append(_dropped_answer_unit(unit, reason, support=status.support))
            continue
        expected_support = {
            "claim": "entailed",
            "limitation": "limitation",
            "gap": "gap",
            "conflict": "conflict",
            "transition": "non_factual",
        }[unit.kind]
        if status.support != expected_support:
            dropped.append(_dropped_answer_unit(unit, "verifier_support_mismatch", support=status.support))
            continue
        accepted.append(
            AnswerUnit(
                id=unit.id,
                text=unit.text,
                kind=unit.kind,
                support=status.support,
                claim_ids=unit.claim_ids,
                gap_ids=unit.gap_ids,
                conflict_ids=unit.conflict_ids,
                limitation_ids=unit.limitation_ids,
                evidence_ids=unit.evidence_ids,
                rationale=status.rationale or unit.rationale,
                raw=unit.raw,
            )
        )
    return accepted, dropped


def _answer_unit_references_resolve(
    unit: AnswerUnit,
    status: AnswerVerificationUnit,
    proof_state: Mapping[str, Any],
) -> tuple[bool, str]:
    _ = status
    if unit.kind == "claim":
        if not unit.claim_ids:
            return False, "missing_claim_ids"
        if not _refs_resolve(unit.claim_ids, proof_state["claims"]):
            return False, "unknown_claim_id"
    if unit.kind == "gap":
        if not unit.gap_ids:
            return False, "missing_gap_ids"
        if not _refs_resolve(unit.gap_ids, proof_state["gaps"]):
            return False, "unknown_gap_id"
    if unit.kind == "conflict":
        if not unit.conflict_ids:
            return False, "missing_conflict_ids"
        if not _refs_resolve(unit.conflict_ids, proof_state["conflicts"]):
            return False, "unknown_conflict_id"
    if unit.kind == "limitation":
        if not unit.limitation_ids:
            return False, "missing_limitation_ids"
        if not _refs_resolve(unit.limitation_ids, proof_state["limitations"]):
            return False, "unknown_limitation_id"
    unknown_evidence = set(unit.evidence_ids) - set(proof_state["evidence_ids"])
    if unknown_evidence:
        return False, "unknown_evidence_id"
    return True, ""


def _refs_resolve(refs: Sequence[str], records: Sequence[Mapping[str, Any]]) -> bool:
    available = {_identity_value(record.get("id")) for record in records if _identity_value(record.get("id"))}
    return set(refs) <= available


def _dropped_answer_unit(unit: AnswerUnit, reason: str, *, support: str | None = None) -> dict[str, Any]:
    return {
        "unit_id": unit.id,
        "kind": unit.kind,
        "support": support or unit.support,
        "reason": reason,
        "text": _bounded_trace_text(unit.text),
    }


def _assemble_answer_from_answer_units(units: Sequence[AnswerUnit]) -> str:
    answer = " ".join(unit.text.strip() for unit in units if unit.text.strip()).strip()
    for needle, replacement in ((" ,", ","), (" .", "."), (" ;", ";"), (" :", ":"), (" )", ")"), ("( ", "(")):
        answer = answer.replace(needle, replacement)
    return answer


def _public_answer_unit(unit: AnswerUnit) -> dict[str, Any]:
    public: dict[str, Any] = {
        "id": unit.id,
        "text": unit.text,
        "kind": unit.kind,
        "support": unit.support,
    }
    for key in ("claim_ids", "gap_ids", "conflict_ids", "limitation_ids", "evidence_ids"):
        value = getattr(unit, key)
        if value:
            public[key] = list(value)
    if unit.rationale:
        public["rationale"] = _bounded_trace_text(unit.rationale, limit=360)
    return public


def _public_proof_gaps(proof_state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in [*proof_state["gaps"], *proof_state["limitations"]]]


def _dedupe_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        item = dict(record)
        key = (
            _identity_value(item.get("id")),
            _identity_value(item.get("kind")),
            _identity_value(item.get("message") or item.get("claim_key") or item.get("claim")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _validate_synthesis_claims(response: SynthesisResponse, evidence: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_by_id = {_identity_value(item.get("id")): item for item in evidence if _identity_value(item.get("id"))}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for claim in response.claims:
        if not claim.claim or not claim.evidence_ids:
            rejected.append({"claim": claim.claim, "reason": "missing_evidence_ids"})
            continue
        matches = [evidence_by_id[eid] for eid in claim.evidence_ids if eid in evidence_by_id]
        if len(matches) != len(claim.evidence_ids):
            rejected.append({"claim": claim.claim, "evidence_ids": list(claim.evidence_ids), "reason": "unknown_evidence_id"})
            continue
        span_valid = _synthesis_span_valid(claim, matches)
        item = {
            "id": claim.id or f"claim-{len(accepted) + 1}",
            "claim": claim.claim,
            "evidence_ids": list(claim.evidence_ids),
            "evidence_id": claim.evidence_ids[0],
            "source_handle": matches[0].get("source_handle"),
            "page_handle": matches[0].get("page_handle"),
            "url": matches[0].get("url"),
            "stance": _bounded_trace_text(claim.stance or "supports"),
            "claim_key": _bounded_trace_text(claim.claim_key or claim.claim[:80].lower()),
        }
        if claim.confidence:
            item["confidence"] = claim.confidence
        if claim.conflicts_with:
            item["conflicts_with"] = list(claim.conflicts_with[:8])
        if claim.incompatible_with:
            item["incompatible_with"] = list(claim.incompatible_with[:8])
        if claim.resolved is not None:
            item["resolved"] = claim.resolved
        if claim.resolution_rationale:
            item["resolution_rationale"] = _bounded_trace_text(claim.resolution_rationale)
        if claim.excerpt and span_valid:
            item["exact_excerpt"] = claim.excerpt
        if claim.start is not None and claim.end is not None and span_valid:
            item["match_start"] = claim.start
            item["match_end"] = claim.end
        if not span_valid:
            item["span_validation"] = "invalid"
        accepted.append(item)
    return accepted, rejected


def _synthesis_span_valid(claim: SynthesisClaim, evidence: list[dict[str, Any]]) -> bool:
    if claim.excerpt is None and (claim.start is None or claim.end is None):
        return True
    for item in evidence:
        excerpt = str(item.get("excerpt") or "")
        if claim.excerpt is not None and claim.excerpt not in excerpt:
            continue
        if claim.start is not None and claim.end is not None:
            if claim.start < 0 or claim.end < claim.start or claim.end > len(excerpt):
                continue
        return True
    return False


def _is_recoverable_web_operation_error(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (
            ValueError,
            OSError,
            TimeoutError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ),
    )


def _term_set(value: str) -> set[str]:
    return {term for term in "".join(ch.lower() if ch.isalnum() else " " for ch in value).split() if len(term) > 2}


def _meaningful_terms(value: str) -> set[str]:
    stopwords = {"what", "which", "when", "where", "why", "how", "the", "and", "for", "with", "current", "about"}
    return {term for term in _term_set(value) if term not in stopwords}


def _source_domain(source: Mapping[str, Any]) -> str:
    domain = str(source.get("domain") or "").strip().lower()
    if domain:
        return domain
    parsed = urlparse(str(source.get("url") or ""))
    return parsed.hostname or ""


def _classify_source(source: Mapping[str, Any], profile: str) -> str:
    text = " ".join(
        str(source.get(key) or "")
        for key in ("title", "url", "excerpt", "content")
    ).lower()
    domain = _source_domain(source)
    if profile == "coding":
        if "github.com" in domain or "gitlab.com" in domain:
            if "/issues" in text:
                return "issue_tracker"
            return "source_repository"
        if "changelog" in text:
            return "changelog"
        if "release" in text:
            return "release_notes"
        if any(token in text for token in ("docs", "documentation", "api reference")):
            return "official_docs"
    if profile == "legal_compliance":
        if any(token in domain for token in (".gov", ".gob", ".europa.eu")) or "official guidance" in text:
            return "official_guidance"
        if "statute" in text or "code" in text:
            return "statutes"
        if "regulation" in text or "rule" in text:
            return "regulations"
        if "standard" in text or "iso" in text:
            return "standards"
    if profile == "business":
        if any(token in text for token in ("investor", "press release", "company")):
            return "official_company"
        if any(token in text for token in ("10-k", "10-q", "sec filing", "annual report")):
            return "filings"
        if "announce" in text:
            return "announcements"
        if "review" in text:
            return "reviews"
        if "news" in text:
            return "news"
    if profile == "academic":
        if any(token in domain for token in ("arxiv.org", "biorxiv.org", "medrxiv.org")):
            return "preprints"
        if any(token in text for token in ("doi", "journal", "paper", "study")):
            return "papers"
        if any(token in text for token in ("publisher", "springer", "acm", "ieee", "elsevier")):
            return "publishers"
        if any(token in text for token in ("university", "institute", ".edu")):
            return "institutions"
    if profile == "product_shopping":
        if any(token in text for token in ("spec", "datasheet", "technical details")):
            return "official_specs"
        if any(token in text for token in ("price", "$", "deal")):
            return "prices"
        if "review" in text:
            return "reviews"
        if any(token in text for token in ("alternative", "compare", "versus", " vs ")):
            return "alternatives"
        if any(token in text for token in ("risk", "warranty", "return")):
            return "risk_notes"
    if any(token in text for token in ("official", "documentation", "guidance")):
        return "official"
    if "news" in text:
        return "news"
    if any(token in text for token in ("reference", "wiki", "encyclopedia")):
        return "reference"
    return "general_reference"


def _profile_source_priority_score(source_class: str, request: Mapping[str, Any]) -> float:
    priorities = [str(item) for item in request.get("preferences", {}).get("source_priorities") or ()]
    if source_class not in priorities:
        return 0.0
    return float(max(1, len(priorities) - priorities.index(source_class))) * 2.5


def _duplicate_cluster_key(source: Mapping[str, Any]) -> str:
    url = str(source.get("url") or "").strip().lower()
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    title_terms = "-".join(sorted(_meaningful_terms(str(source.get("title") or "")))[:6])
    return f"{parsed.hostname or ''}{path or '/'}:{title_terms}"


def _has_freshness_signal(source: Mapping[str, Any]) -> bool:
    metadata = source.get("metadata")
    values = [source.get("freshness_scope"), source.get("published"), source.get("date")]
    if isinstance(metadata, Mapping):
        values.extend(metadata.get(key) for key in ("freshness_scope", "provider_result_metadata", "published", "age", "page_age"))
    return any(value for value in values)


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


def _normalized_web_research_execution_input(tool_input: Mapping[str, Any]) -> dict[str, Any]:
    if _is_validated_web_research_input(tool_input):
        return {
            "objective": str(tool_input["objective"]),
            "profile": str(tool_input["profile"]),
            "mode": str(tool_input["mode"]),
            "strategy": str(tool_input.get("strategy") or "deterministic"),
            "strategy_source": str(tool_input.get("strategy_source") or "omitted"),
            "policy": dict(tool_input["policy"]),
            "hard_policy": dict(tool_input["hard_policy"]),
            "preferences": dict(tool_input["preferences"]),
            "budget": dict(tool_input["budget"]),
            "budget_profile": str(tool_input["budget_profile"]),
            "freshness_required": bool(tool_input["freshness_required"]),
            "output_hints": dict(tool_input["output_hints"]),
        }
    return _normalize_web_research_input(tool_input)


def _is_validated_web_research_input(tool_input: Mapping[str, Any]) -> bool:
    normalized_keys = {
        "objective",
        "profile",
        "mode",
        "strategy",
        "policy",
        "hard_policy",
        "preferences",
        "budget",
        "budget_profile",
        "freshness_required",
        "output_hints",
    }
    if any(field in tool_input for field in _WEB_RESEARCH_INTERNAL_INPUT_FIELDS - {"policy", "budget"}):
        return False
    if not normalized_keys.issubset(tool_input):
        return False
    if not str(tool_input.get("objective") or "").strip():
        return False
    mapping_fields = ("policy", "hard_policy", "preferences", "budget", "output_hints")
    if any(not isinstance(tool_input.get(field), Mapping) for field in mapping_fields):
        return False
    if not isinstance(tool_input.get("profile"), str) or str(tool_input["profile"]) not in RESEARCH_PROFILES.names():
        return False
    if not isinstance(tool_input.get("mode"), str) or tool_input["mode"] not in {"focused", "open"}:
        return False
    if str(tool_input.get("strategy") or "deterministic") not in _WEB_RESEARCH_SUPPORTED_STRATEGIES:
        return False
    if not isinstance(tool_input.get("budget_profile"), str):
        return False
    if not isinstance(tool_input.get("freshness_required"), bool):
        return False
    if "strategy_source" in tool_input and str(tool_input.get("strategy_source")) not in {"explicit", "omitted"}:
        return False
    budget = tool_input["budget"]
    budget_ranges = (
        ("search_budget", 1, 8),
        ("fetch_budget", 0, 8),
        ("find_budget", 0, 12),
        ("desired_source_count", 1, 8),
        ("max_turns", 1, 8),
        ("max_concurrent_fetches", 1, 5),
    )
    return all(_validated_budget_int(budget, key, minimum, maximum) for key, minimum, maximum in budget_ranges)


def _validated_budget_int(budget: Mapping[str, Any], key: str, minimum: int, maximum: int) -> bool:
    value = budget.get(key)
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _normalize_web_research_input(tool_input: Mapping[str, Any]) -> dict[str, Any]:
    internal_fields = sorted(field for field in _WEB_RESEARCH_INTERNAL_INPUT_FIELDS if field in tool_input)
    if internal_fields:
        raise ValueError("internal web_research metadata is not accepted as input: " + ", ".join(internal_fields))
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
    strategy_was_supplied = "strategy" in tool_input and tool_input.get("strategy") is not None
    strategy = str(tool_input.get("strategy") or "deterministic").strip().lower()
    if not strategy:
        strategy = "deterministic"
    if strategy not in _WEB_RESEARCH_SUPPORTED_STRATEGIES:
        raise ValueError("strategy must be deterministic or pro")
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
        "strategy": strategy,
        "strategy_source": "explicit" if strategy_was_supplied else "omitted",
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
    trace = [*state.trace_summary(max_items=_WEB_RESEARCH_MAX_TRACE_ITEMS), *child_trace]
    child_answer = str(structured.get("answer") or child_payload.get("summary") or "").strip()
    answer = _synthesize_answer_from_evidence(request, evidence)
    pro_answer_accepted = (
        request.get("strategy") == "pro"
        and any(
            event.get("event") in {"synthesis_validated", "answer_proof_validated"} and event.get("answer_accepted")
            for event in child_trace
        )
    )
    if child_answer:
        trace.append({"event": "delegated_summary", "summary": _bounded_trace_text(child_answer)})
        if pro_answer_accepted:
            answer = child_answer
        elif child_answer != answer:
            trace.append(
                {
                    "event": "unverified_child_answer_dropped",
                    "reason": "answer_not_synthesized_from_ledger_evidence",
                    "summary": _bounded_trace_text(child_answer),
                }
            )
    annotated_claims, dropped_claims = _ledger_bound_claims(structured, sources, evidence)
    if dropped_claims:
        state.record_unverified_child_metadata_dropped(dropped_claims)
        trace.extend(dropped_claims)
    for claim in annotated_claims:
        match = _find_unique_child_match(
            claim,
            evidence,
            identity_fields=("evidence_id", "source_handle", "page_handle", "id"),
            fallback_fields=("url",),
        )
        if match is not None:
            match.setdefault("claims", []).append(claim)
    child_conflicts, dropped_conflicts = _ledger_bound_conflicts(
        structured,
        sources,
        evidence,
        annotated_claims,
    )
    if dropped_conflicts:
        state.record_unverified_child_metadata_dropped(dropped_conflicts)
        trace.extend(dropped_conflicts)
    conflicts = _dedupe_records([
        *state.conflicts_payload(),
        *child_conflicts,
        *_detect_claim_conflicts(annotated_claims),
    ])
    gaps = _derive_gaps(request, sources, evidence, stop_reason, [*state.gaps_payload(), *_list_of_mappings(structured.get("gaps"))])
    gaps = _dedupe_records(gaps)
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
        "strategy": request.get("strategy", "deterministic"),
        **({"requested_strategy": request.get("requested_strategy")} if request.get("requested_strategy") else {}),
        "answer": answer,
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
            "strategy": request.get("strategy", "deterministic"),
            **({"strategy_fallback_reason": request.get("strategy_fallback_reason")} if request.get("strategy_fallback_reason") else {}),
            "queries": state.queries_payload(),
            "pages_read": state.pages_read_payload(),
            "iterations": len(trace),
            "trace_summary": trace[:_WEB_RESEARCH_MAX_TRACE_ITEMS],
        },
        "facets": _build_profile_facets(request, structured),
        "claims": annotated_claims,
        "auxiliary_signals": _auxiliary_signals(evidence),
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
    if request.get("strategy") == "pro":
        result["answer_units"] = _list_of_mappings(structured.get("answer_units"))
    freshness_scope = state.freshness_scope_payload()
    if freshness_scope:
        result["freshness_scope"] = freshness_scope
    result["trace_summary"] = list(result["trace_summary"])
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
    for key in RESEARCH_PROFILES.get(profile).facet_keys:
        value = structured.get(key)
        if value is not None and key not in profile_facet:
            profile_facet[key] = value
    result[profile] = profile_facet
    return result


def _ledger_bound_claims(
    structured: Mapping[str, Any],
    sources: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    raw_claims = _list_of_mappings(structured.get("claims") or structured.get("claim_annotations"))
    for index, raw in enumerate(raw_claims):
        claim = {field: raw[field] for field in _WEB_RESEARCH_CLAIM_ANNOTATION_FIELDS if field in raw}
        if "claim_key" not in claim and "key" in claim:
            claim["claim_key"] = claim["key"]
        claim_text = _identity_value(claim.get("claim") or claim.get("claim_text"))
        if claim_text:
            claim["claim"] = claim_text
        source_match = _find_unique_child_match(
            raw,
            sources,
            identity_fields=("source_handle", "page_handle", "id"),
            fallback_fields=("url",),
        )
        evidence_match = _find_unique_child_match(
            raw,
            evidence,
            identity_fields=("evidence_id", "source_handle", "page_handle", "id"),
            compound_fields=(("url", "excerpt"),),
            fallback_fields=("url",),
        )
        if source_match is None and evidence_match is None:
            dropped.append(_unverified_child_metadata_event("claim", raw, index))
            continue
        bound = evidence_match or source_match or {}
        claim.setdefault("id", _identity_value(raw.get("id")) or f"claim-{index + 1}")
        claim.setdefault("source_handle", bound.get("source_handle") or bound.get("id"))
        claim.setdefault("page_handle", bound.get("page_handle"))
        if evidence_match is not None:
            claim.setdefault("evidence_id", evidence_match.get("id"))
            claim.setdefault("url", evidence_match.get("url"))
        elif source_match is not None:
            claim.setdefault("url", source_match.get("url"))
        claim.setdefault("claim_key", _claim_key(claim))
        claim.setdefault("stance", _claim_stance(claim))
        accepted.append(claim)
    return accepted, dropped


def _detect_claim_conflicts(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        grouped.setdefault(_identity_value(claim.get("claim_key")) or _claim_key(claim), []).append(claim)
    conflicts: list[dict[str, Any]] = []
    for key, group in grouped.items():
        positive = [claim for claim in group if _claim_stance_family(claim) == "positive"]
        negative = [claim for claim in group if _claim_stance_family(claim) == "negative"]
        explicit = [
            claim
            for claim in group
            if claim.get("incompatible_with") or claim.get("conflicts_with") or claim.get("explicit_incompatibility")
        ]
        resolved_claims = [
            claim
            for claim in group
            if claim.get("resolved") is True or (claim.get("resolved") is not False and claim.get("resolution_rationale"))
        ]
        incompatible = bool(positive and negative) or bool(explicit) or bool(resolved_claims)
        if not incompatible:
            continue
        conflicts.append(
            {
                "kind": "claim_conflict",
                "claim_key": key,
                "message": "Ledger-bound claims disagree." if not resolved_claims else "Conflict resolved by stronger evidence.",
                "claims": group,
                "source_handles": sorted(
                    {
                        str(claim.get("source_handle"))
                        for claim in group
                        if _identity_value(claim.get("source_handle"))
                    }
                ),
                "resolved": bool(resolved_claims),
                **(
                    {"resolution_rationale": resolved_claims[0].get("resolution_rationale") or resolved_claims[0].get("rationale")}
                    if resolved_claims
                    else {}
                ),
            }
        )
    return conflicts


def _ledger_bound_conflicts(
    structured: Mapping[str, Any],
    sources: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    raw_conflicts = _list_of_mappings(structured.get("conflicts"))
    for index, raw in enumerate(raw_conflicts):
        conflict = dict(raw)
        if _conflict_is_ledger_bound(conflict, sources, evidence, claims):
            conflict.setdefault("kind", "claim_conflict")
            accepted.append(conflict)
            continue
        dropped.append(_unverified_child_metadata_event("conflict", raw, index))
    return accepted, dropped


def _conflict_is_ledger_bound(
    conflict: Mapping[str, Any],
    sources: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> bool:
    if _find_unique_child_match(
        conflict,
        sources,
        identity_fields=("source_handle", "page_handle", "id"),
        fallback_fields=("url",),
    ):
        return True
    if _find_unique_child_match(
        conflict,
        evidence,
        identity_fields=("evidence_id", "source_handle", "page_handle", "id"),
        fallback_fields=("url",),
    ):
        return True
    claim_ids = {_identity_value(claim.get("id")) for claim in claims if _identity_value(claim.get("id"))}
    claim_keys = {_identity_value(claim.get("claim_key")) for claim in claims if _identity_value(claim.get("claim_key"))}
    for value in _conflict_reference_values(conflict):
        if value in claim_ids or value in claim_keys:
            return True
    return False


def _conflict_reference_values(conflict: Mapping[str, Any]) -> set[str]:
    values = {
        _identity_value(conflict.get(key))
        for key in ("claim_id", "claim_key", "source_handle", "page_handle", "evidence_id")
    }
    for key in ("claim_ids", "claim_keys", "claims", "source_handles", "page_handles", "evidence_ids"):
        raw = conflict.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, Mapping):
                    values.update(
                        _identity_value(item.get(field))
                        for field in ("id", "claim_key", "source_handle", "page_handle", "evidence_id")
                    )
                else:
                    values.add(_identity_value(item))
    return {value for value in values if value}


def _claim_stance_family(claim: Mapping[str, Any]) -> str:
    stance = _identity_value(claim.get("stance")).lower()
    if stance in {"supports", "support", "for", "yes", "true", "affirmed", "positive"}:
        return "positive"
    if stance in {"disputes", "dispute", "against", "no", "false", "refutes", "negative"}:
        return "negative"
    return "neutral"


def _claim_key(claim: Mapping[str, Any]) -> str:
    return _identity_value(claim.get("subquestion_id")) or _identity_value(claim.get("claim")).lower()[:80] or "claim"


def _claim_stance(claim: Mapping[str, Any]) -> str:
    raw = _identity_value(claim.get("stance")).lower()
    if raw:
        return raw
    text = _identity_value(claim.get("claim")).lower()
    if any(token in text for token in (" not ", " no ", "false", "unsupported", "discontinued")):
        return "disputes"
    return "supports"


def _auxiliary_signals(evidence: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    signals: dict[str, list[dict[str, Any]]] = {"dates": [], "versions": [], "prices": [], "numbers": [], "source_types": [], "duplicates": []}
    seen_excerpt: dict[str, str] = {}
    for item in evidence:
        excerpt = str(item.get("excerpt") or "")
        ref = {"source_handle": item.get("source_handle"), "page_handle": item.get("page_handle"), "url": item.get("url")}
        for value in sorted(set(__import__("re").findall(r"\b(?:19|20)\d{2}(?:-\d{2}-\d{2})?\b", excerpt))):
            signals["dates"].append({"value": value, **ref})
        for value in sorted(set(__import__("re").findall(r"\bv?\d+(?:\.\d+){1,3}\b", excerpt, flags=__import__("re").I))):
            signals["versions"].append({"value": value, **ref})
        for value in sorted(set(__import__("re").findall(r"\$\s?\d+(?:,\d{3})*(?:\.\d{2})?", excerpt))):
            signals["prices"].append({"value": value, **ref})
        for value in sorted(set(__import__("re").findall(r"\b\d+(?:\.\d+)?%?\b", excerpt))):
            signals["numbers"].append({"value": value, **ref})
        source_type = _classify_source(item, "general")
        if source_type != "general_reference":
            signals["source_types"].append({"value": source_type, **ref})
        key = " ".join(excerpt.lower().split())[:120]
        if key and key in seen_excerpt:
            signals["duplicates"].append({"value": "similar_excerpt", "source_handle": item.get("source_handle"), "other_source_handle": seen_excerpt[key]})
        elif key:
            seen_excerpt[key] = str(item.get("source_handle") or item.get("url") or "")
    return {key: value for key, value in signals.items() if value}


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


def _bounded_trace_text(value: Any, *, limit: int = 280) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _identity_value(value: Any) -> str:
    return str(value or "").strip()


def _list_of_mappings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _json_object(raw: str, *, kind: str = "model") -> Mapping[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelTurnValidationError(kind, "malformed_json", "model response must be valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ModelTurnValidationError(kind, "non_object_json", "model response must be a JSON object")
    return parsed


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bounded_items(items: list[dict[str, Any]], *, limit: int, text_limit: int) -> list[dict[str, Any]]:
    bounded: list[dict[str, Any]] = []
    for item in items[:limit]:
        bounded_item: dict[str, Any] = {}
        for key, value in item.items():
            if isinstance(value, str):
                bounded_item[str(key)] = _bounded_trace_text(value, limit=text_limit)
            elif isinstance(value, (int, float, bool)) or value is None:
                bounded_item[str(key)] = value
            elif isinstance(value, Mapping):
                bounded_item[str(key)] = {
                    str(child_key): (_bounded_trace_text(child_value, limit=160) if isinstance(child_value, str) else child_value)
                    for child_key, child_value in list(value.items())[:12]
                    if isinstance(child_value, (str, int, float, bool)) or child_value is None
                }
            elif isinstance(value, list):
                bounded_item[str(key)] = value[:8]
        bounded.append(bounded_item)
    return bounded


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
        effective.setdefault("limit", _web_research_candidate_search_limit(state))
    if kind == "find":
        remaining = max(1, int(state.request["budget"]["find_budget"]) - state.find_used)
        effective.setdefault("limit", min(_WEB_PRIMITIVE_DEFAULT_FIND_LIMIT, remaining))
    return effective


def _web_research_candidate_search_limit(state: WebResearchLoopState) -> int:
    budget = state.request["budget"]
    remaining_fetches = max(1, int(budget["fetch_budget"]) - state.fetch_used)
    remaining_sources = max(1, int(budget["desired_source_count"]) - len(state.evidence_payload()))
    candidate_need = min(remaining_fetches, remaining_sources, max(1, state.max_concurrent_fetches))
    breadth = 4 if int(budget["desired_source_count"]) == 1 else int(budget["desired_source_count"])
    return min(_WEB_PRIMITIVE_DEFAULT_SEARCH_LIMIT, max(candidate_need, breadth))


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
