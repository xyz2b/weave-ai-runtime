# Web Common Kit

Canonical import root: `weavert_kit_common_web`

## What this package owns

- the public `web_research` entrypoint for bounded AI-first read-only web research
- reusable low-level `grounding_web_search`, `grounding_web_fetch`, and `grounding_web_find` primitives
- shared web tooling used by chat and local-assistant product-kit composition
- the package-owned `web-searcher` delegated worker behind `web_research`

## Canonical names

- install name: `weavert-kit-common-web`
- import root: `weavert_kit_common_web`
- runtime activation: `weavert-bridge-web`

The public install name stays separate from the lower-layer runtime package activation name.

## How not to confuse it

- Choose this package when you need the default high-level `web_research` surface for public-web grounding.
- Use the low-level primitives when you need explicit search, bounded inspected-page fetch, or page-local evidence finding.
- Pair it with `weavert-kit-common-retrieval` when you want to rank or cite the inspected material.
- The package preserves explicit source identity and browser handoff metadata, but it does not perform browser navigation itself.
- `web-searcher` is registered for runtime child-run delegation and package extension points; prefer calling `web_research` in user-facing integrations.
- Do not choose it when the assistant must navigate, click, or fill forms inside an app-owned browser. That belongs to `weavert-kit-common-browser`.

## See also

- `../README.md`
- `../../chat/README.md`
- `../../../../docs/introduction/use-cases.md`
