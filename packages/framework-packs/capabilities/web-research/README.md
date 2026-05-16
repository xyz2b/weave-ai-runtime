# weavert-web-research

Framework-level shared web research core used by chat, coding, local-assistant, and devtools adapters.
This package is the primitive substrate, not the public owner of the high-level `web_research` workflow surface.

## What this package owns

- normalized source, page, and citation-ready web result structures
- shared public-host and domain-policy enforcement
- a provider registry for deterministic search provider selection, capability metadata, and fallback reporting
- framework-owned research-loop state for budget usage, source and evidence ledgers, provider/freshness events, bounded traces, conflicts, gaps, and stop classification
- a thin backend seam for search, page inspection, and page-local finding
- the default DuckDuckGo HTML plus direct-fetch backend used by first-party adapters
- an optional Brave Search API provider path for real recency/freshness-constrained search

## Provider and freshness behavior

- DuckDuckGo HTML remains the no-credential fallback provider. It reports freshness as unsupported and the core post-filters domain policy.
- Brave Search is the first real freshness-capable provider path. Set `BRAVE_SEARCH_API_KEY` or `WEAVERT_BRAVE_SEARCH_API_KEY`; optionally set `WEAVERT_WEB_SEARCH_PROVIDER=brave-search` to prefer it.
- `freshness_days`, `recency_days`, or compact `freshness.days` map to provider freshness only when the selected provider supports it. Otherwise results include `freshness_scope.status="unsupported"`.
- Brave domain allow/block constraints are mapped with `site:` and `-site:` query operators, then revalidated by the shared core.
- Default tests use deterministic `FixtureWebResearchProvider` instances. Live-provider smoke checks are opt-in by setting provider credentials and running targeted tests outside the default deterministic suite.

Higher-level packages such as `weavert-kit-common-web-research` compose this core through their package adapters. The shared common web research kit owns the public `web_research` tool and its package-owned delegated worker.

## Canonical names

- install name: `weavert-web-research`
- import root: `weavert_web_research`

## See also

- `../../README.md`
- `../../../product-kits/common/web-research/README.md`
