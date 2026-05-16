# Coding Web Research Common Kit

Canonical import root: `weavert_kit_common_web_research`

## What this package owns

- shared coding-oriented web research surfaces built on the framework-level web research core
- domain-scoped technical lookup for docs, release notes, and changelogs
- version-aware inspected-page and page-local evidence helpers for coding products

## Canonical names

- install name: `weavert-kit-common-web-research`
- import root: `weavert_kit_common_web_research`
- runtime activation: `weavert-shared-web-research`

The public install name stays separate from the lower-layer runtime package activation name.

## How not to confuse it

- Choose this package when a coding-oriented workflow needs reusable technical web lookup with explicit source metadata.
- Do not choose it for chat-safe grounded answers or the default high-level `web_research` entrypoint. That remains the job of `weavert-kit-common-web`.
- Do not choose it for browser navigation or interaction. That remains the job of `weavert-kit-common-browser`.

## See also

- `../README.md`
- `../../coding/README.md`
- `../../../framework-packs/capabilities/web-research/README.md`
