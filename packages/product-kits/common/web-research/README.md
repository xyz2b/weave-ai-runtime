# Web Research Common Kit

Canonical import root: `weavert_kit_common_web_research`

## What this package owns

- the unified public `web_research` entrypoint for read-only public-web information retrieval
- low-level `web_search`, single-page `web_fetch`, and `web_find` primitives backed by `weavert-web-research`
- a package-owned goal-driven research loop behind `web_research` that plans queries, selects pages, evaluates evidence coverage, and stops with explicit reasons
- the package-owned `web-searcher` delegated worker reserved for bounded implementation-period fallback paths
- first-party research profiles: `general`, `coding`, `business`, `academic`, `legal_compliance`, and `product_shopping`
- common result envelopes with sources, evidence, conflicts, gaps, freshness, provider metadata, research trace, and profile facets

## Canonical names

- package root: `packages/product-kits/common/web-research`
- install name: `weavert-kit-common-web-research`
- import root: `weavert_kit_common_web_research`
- runtime activation: `weavert-shared-web-research`

## Boundary

Use `web_research` for goal-driven AI-first research and pass `profile="coding"` or another supported profile when the scenario needs profile-specific source ranking or facets. `web_research` is the supported path for multi-page source discovery and inspection: it derives bounded queries from the objective, ranks candidate pages, inspects ledger-verified sources, reports gaps or conflicts, and exposes loop decisions in `research_trace` and `trace_summary`. Use low-level `web_fetch` only for one explicit page at a time; callers that need manual multi-page inspection should issue repeated single-page fetches.

This package is read-only. Browser navigation, clicks, form filling, authenticated browsing, and DOM interaction remain browser-bridge responsibilities.

## Search Provider Selection

Public tool names stay stable: callers continue to use `web_research`, `web_search`, `web_fetch`, and `web_find`. Search provider selection is handled by the shared `weavert-web-research` core.

- `google-search`: set `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_CX`; optionally set `WEAVERT_WEB_SEARCH_PROVIDER=google-search`.
- `brave-search`: set `BRAVE_SEARCH_API_KEY` or `WEAVERT_BRAVE_SEARCH_API_KEY`; optionally set `WEAVERT_WEB_SEARCH_PROVIDER=brave-search`.
- `duckduckgo-html`: no-credential fallback. It does not expose a stable freshness filter through this adapter.

Google and Brave map domain constraints into provider query operators where supported, while the shared core still revalidates accepted result URLs against allowed domains, blocked domains, and public-host policy. Freshness semantics are provider-specific: Google uses approximate `dateRestrict`, Brave uses its `freshness` parameter, and DuckDuckGo reports freshness as unsupported.

## Research Profiles and Quality Signals

`web_research` applies profile strategy before inspecting pages. Coding prioritizes official documentation, release notes, changelogs, source repositories, and issue trackers, with facets for API names, versions, compatibility notes, and breaking changes. Legal compliance prioritizes statutes, regulations, standards, and official guidance, and preserves jurisdiction, authority, freshness, and effective-date gaps. Business research favors company sources, filings, announcements, credible news, reviews, competitors, timelines, comparison axes, and market claims. Academic research favors papers, publishers, institutions, preprints, methods, experiments, conclusions, and citation metadata. Product shopping favors official specs, current prices, reviews, alternatives, comparison axes, and purchase-risk signals.

Candidate sources receive traceable quality metadata before fetch: objective relevance, profile priority, provider metadata, freshness signals, preferred or allowed domains, duplicate clusters, and deterministic tie-breaking by domain and URL. After inspection, ledger evidence keeps source class and quality metadata so callers and tests can explain why a source was selected.

## Claims, Conflicts, Gaps, and Limits

Claim annotations are accepted only when they bind to an inspected ledger source, page, or evidence item. Unbound annotations are dropped and traced. Rule-derived dates, versions, prices, numbers, source-type hints, and duplicate signals appear as `auxiliary_signals`; they help diagnostics and facets but do not prove claim correctness.

Conflicting ledger-bound claims are projected into `conflicts`. Unresolved conflicts lower confidence and produce `stop_reason="unresolved_conflict"`; resolved conflicts keep a resolution rationale when stronger evidence is identified. Gaps describe missing preferred evidence, unsupported freshness, provider fallback, policy blocks, or partial results.

Remaining limits are explicit: this kit does not drive a browser, click through pages, authenticate, inspect local workspaces, run shell-assisted searches, or guarantee truth beyond inspected public evidence. Host-level browser bridges, local workspace search, and shell tools remain separate surfaces.

## See also

- `../README.md`
- `../../../framework-packs/capabilities/web-research/README.md`
