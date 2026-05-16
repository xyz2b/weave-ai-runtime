# Browser Common Kit

Canonical import root: `weavert_kit_common_browser`

## What this package owns

- reusable browser bridge surfaces
- shared browser-facing tooling used by local-assistant product-kit composition

## Canonical names

- install name: `weavert-kit-common-browser`
- import root: `weavert_kit_common_browser`
- runtime activation: `weavert-bridge-browser`

The public install name stays separate from the lower-layer runtime package activation name.

## How not to confuse it

- Choose this package when your app owns a browser bridge and the assistant needs browser state, navigation, click, form-fill, or extraction steps.
- Do not choose it for public-web search or remote page fetch. That belongs to `weavert-kit-common-web-research`.
- Do not choose it for generic local-machine surfaces such as files or clipboard. That belongs to `weavert-kit-common-local-os`.

## See also

- `../README.md`
- `../../local-assistant/README.md`
- `../../../../docs/concepts/packages-and-scenario-packs.md`
