# Product Kits

This family root indexes concrete product-kit packages.
It owns scenario packs plus shared product-kit packages.

## What this family owns

- scenario packs that publish product-profile defaults
- shared product-kit packages reused across multiple scenario packs

## Scenario-pack kits

- `chat/` -> canonical import root `weavert_kit_chat`, publishes `weavert-scenario-chat`
- `coding/` -> canonical import root `weavert_kit_coding`, publishes `weavert-scenario-coding`
- `local-assistant/` -> canonical import root `weavert_kit_local_assistant`, publishes `weavert-scenario-local-assistant`

## Shared product-kit packages

- `common/retrieval/` -> `weavert_kit_common_retrieval`
- `common/web/` -> `weavert_kit_common_web`
- `common/git/` -> `weavert_kit_common_git`
- `common/workspace-intelligence/` -> `weavert_kit_common_workspace_intelligence`
- `common/browser/` -> `weavert_kit_common_browser`
- `common/local-os/` -> `weavert_kit_common_local_os`
- `common/pim/` -> `weavert_kit_common_pim`

## Composition summary

- `weavert_kit_chat` composes retrieval and web common kits.
- `weavert_kit_coding` composes git and workspace-intelligence common kits.
- `weavert_kit_local_assistant` composes retrieval, browser, local-OS, and PIM common kits.

## See also

- `../README.md`
- `common/README.md`
- `../../docs/concepts/packages-and-scenario-packs.md`
- `../../docs/guides/use-scenario-packs.md`
