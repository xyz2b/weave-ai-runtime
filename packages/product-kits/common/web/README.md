# Web Common Kit

Canonical import root: `weavert_kit_common_web`

## What this package owns

- the public `web_research` entrypoint for bounded AI-first read-only web research
- reusable low-level `grounding_web_search`, `grounding_web_fetch`, and `grounding_web_find` primitives
- shared web tooling used by chat and local-assistant product-kit composition
- the package-owned `web-searcher` delegated worker behind `web_research`
- guarded open/focused research policy, evidence ledgers, and bounded concurrent page inspection for delegated research runs
- provider/freshness metadata propagated from shared-core search into final research results

## Canonical names

- install name: `weavert-kit-common-web`
- import root: `weavert_kit_common_web`
- runtime activation: `weavert-bridge-web`

The public install name stays separate from the lower-layer runtime package activation name.

## How not to confuse it

- Choose this package when you need the default high-level `web_research` surface for public-web grounding.
- For ordinary callers, prefer the compact request shape: `question`, optional `scope`, optional `freshness`, optional `depth`, and optional `source_preferences`.
- Use `mode="focused"` when domain scope is a hard allow-list. Use `mode="open"` for exploratory questions where legacy `domains` are preferred sources rather than hard limits.
- Put non-negotiable boundaries in `hard_policy` or `allowed_domains`; put ranking hints such as `preferred_domains` and freshness in `preferences`.
- Compact `scope.allowed_domains` and `scope.blocked_domains` normalize into hard policy; `source_preferences.preferred_domains` remains soft ranking guidance.
- `freshness.required=true` returns an enforced freshness outcome only when the selected provider supports it; otherwise `freshness_scope` and `stop_reason` make the limitation visible.
- Search results include `provider`, `provider_selection`, `provider_fallback`, `constraint_outcomes`, and `freshness_scope` fields while preserving legacy `query` and `results` payloads.
- Tune `budget_profile`, explicit search/fetch/find budgets, and `max_concurrent_fetches` to keep open research bounded.
- Use the low-level primitives when you need explicit search, bounded inspected-page fetch, or page-local evidence finding.
- Pair it with `weavert-kit-common-retrieval` when you want to rank or cite the inspected material.
- The package preserves explicit source identity and browser handoff metadata, but it does not perform browser navigation itself.
- `web-searcher` is registered for runtime child-run delegation and package extension points; prefer calling `web_research` in user-facing integrations.
- `web_research_fetch_many` is a package-owned helper for concurrent inspection inside an active `web_research` run. User-facing integrations should call `web_research` rather than this helper directly.
- Do not choose it when the assistant must navigate, click, or fill forms inside an app-owned browser. That belongs to `weavert-kit-common-browser`.

## Provider configuration

- DuckDuckGo HTML is the built-in no-credential fallback and reports freshness as unsupported.
- Brave Search API is the optional freshness-capable provider. Configure `BRAVE_SEARCH_API_KEY` or `WEAVERT_BRAVE_SEARCH_API_KEY`, and set `WEAVERT_WEB_SEARCH_PROVIDER=brave-search` when you want it selected ahead of the fallback.
- Live-provider smoke validation is intentionally opt-in. The default suite uses deterministic fixture providers and does not require credentials or public web availability.

## See also

- `../README.md`
- `../../chat/README.md`
- `../../../../docs/introduction/use-cases.md`
