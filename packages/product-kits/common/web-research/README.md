# Coding Web Research Common Kit

Canonical import root: `weavert_kit_common_web_research`

## What this package owns

- shared coding-oriented web research surfaces built on the framework-level web research core
- domain-scoped technical lookup for docs, release notes, and changelogs
- version-aware inspected-page and page-local evidence helpers for coding products
- provider and freshness metadata from the shared web research core

## Canonical names

- install name: `weavert-kit-common-web-research`
- import root: `weavert_kit_common_web_research`
- runtime activation: `weavert-shared-web-research`

The public install name stays separate from the lower-layer runtime package activation name.

## How not to confuse it

- Choose this package when a coding-oriented workflow needs reusable technical web lookup with explicit source metadata.
- Use `technical_web_search` for domain-scoped external references; it preserves `provider`, `provider_selection`, `provider_fallback`, `constraint_outcomes`, and `freshness_scope` metadata from the shared core.
- `freshness_days` and `recency_days` are enforced only by configured freshness-capable providers, such as the optional Brave Search provider. DuckDuckGo HTML fallback reports freshness as unsupported.
- Do not choose it for chat-safe grounded answers or the default high-level `web_research` entrypoint. That remains the job of `weavert-kit-common-web`.
- Do not choose it for browser navigation or interaction. That remains the job of `weavert-kit-common-browser`.

## See also

- `../README.md`
- `../../coding/README.md`
- `../../../framework-packs/capabilities/web-research/README.md`
