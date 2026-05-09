# Product Kits

这个 family root 索引具体的 product-kit packages。
它拥有 scenario packs 与共享 product-kit packages。

## 这个 family 拥有什么

- 发布产品画像默认值的 scenario packs
- 被多个 scenario packs 复用的共享 product-kit packages

## Scenario-pack kits

- `chat/` -> 规范 import root `weavert_kit_chat`，发布 `weavert-scenario-chat`
- `coding/` -> 规范 import root `weavert_kit_coding`，发布 `weavert-scenario-coding`
- `local-assistant/` -> 规范 import root `weavert_kit_local_assistant`，发布 `weavert-scenario-local-assistant`

## 共享 product-kit packages

- `common/retrieval/` -> `weavert_kit_common_retrieval`
- `common/web/` -> `weavert_kit_common_web`
- `common/git/` -> `weavert_kit_common_git`
- `common/workspace-intelligence/` -> `weavert_kit_common_workspace_intelligence`
- `common/browser/` -> `weavert_kit_common_browser`
- `common/local-os/` -> `weavert_kit_common_local_os`
- `common/pim/` -> `weavert_kit_common_pim`

## 组合摘要

- `weavert_kit_chat` 组合 retrieval 与 web common kits。
- `weavert_kit_coding` 组合 git 与 workspace-intelligence common kits。
- `weavert_kit_local_assistant` 组合 retrieval、browser、local-OS 与 PIM common kits。

## 另见

- `../README.zh-CN.md`
- `common/README.zh-CN.md`
- `../../docs/zh-CN/concepts/packages-and-scenario-packs.md`
- `../../docs/zh-CN/guides/use-scenario-packs.md`
