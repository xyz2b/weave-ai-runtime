# Retrieval Common Kit

Canonical import root: `weavert_kit_common_retrieval`

## What this package owns

- reusable retrieval and citation surfaces
- shared grounding tooling used by chat and local-assistant product-kit composition

## Canonical names

- install name: `weavert-kit-common-retrieval`
- import root: `weavert_kit_common_retrieval`
- runtime activation: `weavert-shared-retrieval`

The public install name stays separate from the lower-layer runtime package activation name.

## How not to confuse it

- Choose this package when you already have grounding candidates such as notes, memory, or fetched passages and need ranking plus citation preparation.
- Pair it with `weavert-kit-common-web-research` when you need public-web search, remote fetch, page-local find, or profile-driven web research before retrieval.
- Do not choose it when you need browser navigation or interaction. That belongs to `weavert-kit-common-browser`.

## See also

- `../README.md`
- `../../chat/README.md`
- `../../local-assistant/README.md`
- `../../../../docs/concepts/memory-model.md`
