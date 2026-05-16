# Web Common Kit

Canonical import root: `weavert_kit_common_web`

## What this package owns

- reusable read-only web grounding surfaces
- shared web tooling used by chat and local-assistant product-kit composition

## Canonical names

- install name: `weavert-kit-common-web`
- import root: `weavert_kit_common_web`
- runtime activation: `weavert-bridge-web`

The public install name stays separate from the lower-layer runtime package activation name.

## How not to confuse it

- Choose this package when you need read-only public-web search or bounded remote page fetch for grounding.
- Pair it with `weavert-kit-common-retrieval` when you want to rank or cite the fetched material.
- Do not choose it when the assistant must navigate, click, or fill forms inside an app-owned browser. That belongs to `weavert-kit-common-browser`.

## See also

- `../README.md`
- `../../chat/README.md`
- `../../../../docs/introduction/use-cases.md`
