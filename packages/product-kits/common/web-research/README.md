# Web Research Common Kit

Canonical import root: `weavert_kit_common_web_research`

## What this package owns

- the unified public `web_research` entrypoint for read-only public-web information retrieval
- low-level `web_search`, single-page `web_fetch`, and `web_find` primitives backed by `weavert-web-research`
- package-owned research loops behind `web_research`: the deterministic goal-driven loop and the opt-in model-directed Pro loop
- the package-owned `web-searcher` delegated worker reserved for bounded implementation-period fallback paths
- first-party research profiles: `general`, `coding`, `business`, `academic`, `legal_compliance`, and `product_shopping`
- common result envelopes with sources, evidence, conflicts, gaps, freshness, provider metadata, research trace, and profile facets

## Canonical names

- package root: `packages/product-kits/common/web-research`
- install name: `weavert-kit-common-web-research`
- import root: `weavert_kit_common_web_research`
- runtime activation: `weavert-shared-web-research`

## Boundary

Use `web_research` for goal-driven AI-first research and pass `profile="coding"` or another supported profile when the scenario needs profile-specific source ranking or facets. `web_research` is the supported path for multi-page source discovery and inspection: it derives or plans bounded queries, ranks or validates candidate pages, inspects ledger-verified sources, reports gaps or conflicts, and exposes loop decisions in `research_trace` and `trace_summary`. Use low-level `web_fetch` only for one explicit page at a time; callers that need manual multi-page inspection should issue repeated single-page fetches.

This package is read-only. Browser navigation, clicks, form filling, authenticated browsing, and DOM interaction remain browser-bridge responsibilities.

## Strategy Selection

`web_research` supports backward-compatible strategy selection:

- Omit `strategy` to use the deterministic package-owned loop unless the host runtime explicitly opts eligible calls into Pro mode.
- Set `strategy="pro"` to request model-directed Pro research behind the same public tool name.
- Unknown strategy values are rejected during input validation instead of being silently reinterpreted.

Pro mode asks internal planner, synthesizer, answer verifier, and bounded repair model turns for schema-versioned structured JSON, then treats those outputs as proposals. Deterministic scripted test responses are consumed first, explicit Pro test hooks second, and the assembled runtime's ordinary model client after that. Runtime validation still owns allowed domains, blocked domains, public-host checks, search/fetch/find budgets, source-handle identity, direct-URL provenance, freshness metadata, the authoritative evidence ledger, public stop reason, and public confidence. If Pro model support is unavailable, hosts can keep deterministic behavior as the fallback baseline without changing callers from `web_research`.

In Pro mode the model may propose `search`, `fetch`, `find`, `direct_url_fetch`, or `stop`. `fetch` must reference a known source from prior search or inspected ledger state. Direct URL inspection must use explicit `direct_url_fetch`; accepted direct-URL evidence is traced with direct-URL provenance so callers can distinguish it from search-discovered evidence. Direct-URL-only evidence does not silently satisfy broader source-discovery or profile-coverage expectations.

## Model-Directed Synthesis

Pro synthesis is answer-proof-bound. The synthesizer receives bounded ledger evidence, conflicts, gaps, freshness metadata, provider metadata, proof-addressable runtime records, and the objective, then returns structured claims plus ordered `answer_units`. Runtime accepts only claims whose evidence ids exist in inspected ledger evidence. Public Pro `answer` text is assembled only from accepted answer units whose proof bindings resolve to accepted claim ids, gap ids, conflict ids, limitation ids, or verifier-approved `support="non_factual"` transition text; raw synthesizer answer text is treated as draft material and is never projected directly. Accepted public `answer_units` expose bounded text, kind, support status, and proof ids for downstream citation preparation.

Internal Pro model turns currently use these schema versions: `web_research.planner.v1`, `web_research.synthesizer.v1`, `web_research.verifier.v1`, and `web_research.repair.v1`. Runtime rejects non-object JSON, schema-version mismatches, missing required fields, invalid enum values, oversized fields, duplicate answer-unit ids, and references outside supplied proof state under structured validation classes recorded in bounded trace metadata.

When unsupported synthesis or answer proof failures remain, runtime allows at most one configured repair turn where applicable, drops still-unsupported claims or answer units, downgrades the terminal result through gaps or stop-reason refinement, and records bounded trace events. Bound gaps, limitations, and unresolved conflicts can remain visible in the answer, but they do not raise confidence. Unresolved ledger-bound conflicts and unsupported freshness remain visible even if the planner, synthesizer, or verifier ignores them.

## Search Provider Selection

Public tool names stay stable: callers continue to use `web_research`, `web_search`, `web_fetch`, and `web_find`. Search provider selection is handled by the shared `weavert-web-research` core.

- `google-search`: set `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_CX`; optionally set `WEAVERT_WEB_SEARCH_PROVIDER=google-search`.
- `brave-search`: set `BRAVE_SEARCH_API_KEY` or `WEAVERT_BRAVE_SEARCH_API_KEY`; optionally set `WEAVERT_WEB_SEARCH_PROVIDER=brave-search`.
- `bing-grounding`: set `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_DEPLOYMENT_NAME`, `BING_PROJECT_CONNECTION_ID`, and `AGENT_TOKEN`; optionally set `WEAVERT_WEB_SEARCH_PROVIDER=bing-grounding`.
- `duckduckgo-html`: no-credential fallback. It does not expose a stable freshness filter through this adapter.

Bing grounding uses Azure AI Foundry Responses API `bing_grounding` and normalizes stable public URL citations into the shared result shape. It is not the retired Bing Search API v7 endpoint. Google and Brave map domain constraints into provider query operators where supported, while Bing grounding and DuckDuckGo report those controls as framework-filtered. The shared core still revalidates accepted result URLs against allowed domains, blocked domains, and public-host policy. Freshness semantics are provider-specific: Google uses approximate `dateRestrict`, Brave uses its `freshness` parameter, Bing grounding maps supported 1/7/30 day freshness windows, and DuckDuckGo reports freshness as unsupported.

## Research Profiles and Quality Signals

`web_research` applies profile strategy before inspecting pages. Coding prioritizes official documentation, release notes, changelogs, source repositories, and issue trackers, with facets for API names, versions, compatibility notes, and breaking changes. Legal compliance prioritizes statutes, regulations, standards, and official guidance, and preserves jurisdiction, authority, freshness, and effective-date gaps. Business research favors company sources, filings, announcements, credible news, reviews, competitors, timelines, comparison axes, and market claims. Academic research favors papers, publishers, institutions, preprints, methods, experiments, conclusions, and citation metadata. Product shopping favors official specs, current prices, reviews, alternatives, comparison axes, and purchase-risk signals.

Candidate sources receive traceable quality metadata before fetch: objective relevance, profile priority, provider metadata, freshness signals, preferred or allowed domains, duplicate clusters, and deterministic tie-breaking by domain and URL. After inspection, ledger evidence keeps source class and quality metadata so callers and tests can explain why a source was selected.

## Claims, Conflicts, Gaps, and Limits

Claim annotations are accepted only when they bind to an inspected ledger source, page, or evidence item. Unbound annotations are dropped and traced. Rule-derived dates, versions, prices, numbers, source-type hints, and duplicate signals appear as `auxiliary_signals`; they help diagnostics and facets but do not prove claim correctness.

Conflicting ledger-bound claims are projected into `conflicts`. Unresolved conflicts lower confidence and produce `stop_reason="unresolved_conflict"`; resolved conflicts keep a resolution rationale when stronger evidence is identified. Gaps describe missing preferred evidence, unsupported freshness, provider fallback, policy blocks, or partial results.

Remaining limits are explicit: this kit does not drive a browser, click through pages, authenticate, inspect local workspaces, run shell-assisted searches, or guarantee truth beyond inspected public evidence. Runtime enforcement prevents unsupported confidence and uninspected citations from becoming public evidence, but it does not prove that inspected web content is true in the real world. Host-level browser bridges, local workspace search, and shell tools remain separate surfaces.

## See also

- `../README.md`
- `../../../framework-packs/capabilities/web-research/README.md`
