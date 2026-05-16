# Local Assistant Product Kit

Canonical import root: `weavert_kit_local_assistant`

## What this package owns

- the `weavert-scenario-local-assistant` scenario pack
- host-centric local-assistant product-profile defaults layered on shared bridge packages

## Canonical names

- install name: `weavert-kit-local-assistant`
- import root: `weavert_kit_local_assistant`
- runtime activation: `weavert-scenario-local-assistant`

The public install name stays separate from the runtime scenario-pack activation name.

## Shared packages it composes

- `weavert_kit_common_retrieval`
- `weavert_kit_common_browser`
- `weavert_kit_common_local_os`
- `weavert_kit_common_pim`

## When to choose this package instead of the nearby ones

- Choose `weavert-kit-local-assistant` when your app owns host approvals and needs browser, local-machine, or PIM bridges as one higher-layer profile.
- Do not choose it if you only need grounded answers from retrieval plus the public web. That is the lighter role of `weavert-kit-chat`.
- If you only want one lower-layer bridge instead of the full profile, install the corresponding common kit directly.

## See also

- `../README.md`
- `../common/README.md`
- `../../../docs/guides/use-scenario-packs.md`
- `../../../docs/concepts/hosts-permissions-memory.md`
