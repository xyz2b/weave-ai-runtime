# Web Research Common Kit

Canonical import root: `weavert_kit_common_web_research`

## What this package owns

- the unified public `web_research` entrypoint for read-only public-web information retrieval
- low-level `web_search`, single-page `web_fetch`, and `web_find` primitives backed by `weavert-web-research`
- the package-owned `web-searcher` delegated worker used behind `web_research`
- first-party research profiles: `general`, `coding`, `business`, `academic`, `legal_compliance`, and `product_shopping`
- common result envelopes with sources, evidence, conflicts, gaps, freshness, provider metadata, research trace, and profile facets

## Canonical names

- package root: `packages/product-kits/common/web-research`
- install name: `weavert-kit-common-web-research`
- import root: `weavert_kit_common_web_research`
- runtime activation: `weavert-shared-web-research`

## Boundary

Use `web_research` for AI-first research and pass `profile="coding"` or another supported profile when the scenario needs profile-specific source ranking or facets. `web_research` is the supported path for multi-page source discovery and inspection. Use low-level `web_fetch` only for one explicit page at a time; callers that need manual multi-page inspection should issue repeated single-page fetches.

This package is read-only. Browser navigation, clicks, form filling, authenticated browsing, and DOM interaction remain browser-bridge responsibilities.

## See also

- `../README.md`
- `../../../framework-packs/capabilities/web-research/README.md`
