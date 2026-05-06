# Product Kits

Concrete product-kit packages now live under this family root.

Available kits:

- `chat/` -> canonical import root `weavert_kit_chat`
- `coding/` -> canonical import root `weavert_kit_coding`
- `local-assistant/` -> canonical import root `weavert_kit_local_assistant`

Available common-kit packages:

- `common/retrieval/` -> `weavert_kit_common_retrieval`
- `common/web/` -> `weavert_kit_common_web`
- `common/git/` -> `weavert_kit_common_git`
- `common/workspace-intelligence/` -> `weavert_kit_common_workspace_intelligence`
- `common/browser/` -> `weavert_kit_common_browser`
- `common/local-os/` -> `weavert_kit_common_local_os`
- `common/pim/` -> `weavert_kit_common_pim`

Composition summary:

- `weavert_kit_chat` composes retrieval and web common kits.
- `weavert_kit_coding` composes git and workspace-intelligence common kits.
- `weavert_kit_local_assistant` composes retrieval, browser, local-OS, and PIM common kits.
