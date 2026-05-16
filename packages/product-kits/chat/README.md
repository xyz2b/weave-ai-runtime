# Chat Product Kit

Canonical import root: `weavert_kit_chat`

## What this package owns

- the `weavert-scenario-chat` scenario pack
- chat-oriented product-profile defaults layered on shared grounding packages

## Canonical names

- install name: `weavert-kit-chat`
- import root: `weavert_kit_chat`
- runtime activation: `weavert-scenario-chat`

The public install name stays separate from the runtime scenario-pack activation name.

## Shared packages it composes

- `weavert_kit_common_retrieval`
- `weavert_kit_common_web`

## When to choose this package instead of the nearby ones

- Choose `weavert-kit-chat` when you want a higher-layer profile that already combines retrieval and public-web grounding.
- Do not choose it if your app primarily needs host-mediated browser, local-machine, or PIM bridges. That is the job of `weavert-kit-local-assistant`.
- If you only want one lower-layer capability instead of a full chat profile, install `weavert-kit-common-retrieval` or `weavert-kit-common-web` directly.

## See also

- `../README.md`
- `../common/README.md`
- `../../../docs/guides/use-scenario-packs.md`
- `../../../docs/introduction/use-cases.md`
