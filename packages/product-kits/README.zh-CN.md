# Product Kits

这个 family root 索引具体的 product-kit packages。
它拥有 scenario packs 与共享 product-kit packages。

## 这个 family 拥有什么

- 发布产品画像默认值的 scenario packs
- 被多个 scenario packs 复用的共享 product-kit packages

## 公开发布范围

- 这个 family 下的每个 concrete package 都是公开 PyPI project。
- Scenario kits 是 higher-layer profile entrypoints。
- Shared common kits 仍然是可单独发布的 lower-layer building blocks。

## Scenario-pack kits

| Package root | Install name | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `chat/` | `weavert-kit-chat` | `weavert_kit_chat` | `weavert-scenario-chat` | Higher-layer profile entrypoint |
| `coding/` | `weavert-kit-coding` | `weavert_kit_coding` | `weavert-scenario-coding` | Higher-layer profile entrypoint |
| `local-assistant/` | `weavert-kit-local-assistant` | `weavert_kit_local_assistant` | `weavert-scenario-local-assistant` | Higher-layer profile entrypoint |

## 共享 product-kit packages

| Package root | Install name | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `common/retrieval/` | `weavert-kit-common-retrieval` | `weavert_kit_common_retrieval` | `weavert-shared-retrieval` | Lower-layer shared kit |
| `common/web-research/` | `weavert-kit-common-web-research` | `weavert_kit_common_web_research` | `weavert-shared-web-research` | 带 profile-driven `web_research`、provider metadata、freshness outcomes、facets 和低层只读 primitives 的统一 web research kit |
| `common/git/` | `weavert-kit-common-git` | `weavert_kit_common_git` | `weavert-shared-git` | Lower-layer shared kit |
| `common/workspace-intelligence/` | `weavert-kit-common-workspace-intelligence` | `weavert_kit_common_workspace_intelligence` | `weavert-shared-workspace-intelligence` | Lower-layer shared kit |
| `common/browser/` | `weavert-kit-common-browser` | `weavert_kit_common_browser` | `weavert-bridge-browser` | Lower-layer shared kit |
| `common/local-os/` | `weavert-kit-common-local-os` | `weavert_kit_common_local_os` | `weavert-bridge-local-os` | Lower-layer shared kit |
| `common/pim/` | `weavert-kit-common-pim` | `weavert_kit_common_pim` | `weavert-bridge-pim` | Lower-layer shared kit |

## 组合摘要

- `weavert_kit_chat` 组合 retrieval 与统一 web research kit，web research 默认使用 `general` profile。
- `weavert_kit_coding` 组合 git、带 coding defaults 的统一 web research kit，以及 workspace-intelligence common kits。
- `weavert_kit_local_assistant` 组合 retrieval、只读 web research、browser、local-OS 与 PIM common kits。
- Web research provider selection 通过 shared core 配置：带 credentials 时可设置 `WEAVERT_WEB_SEARCH_PROVIDER=bing-grounding`、`google-search`、`serpapi-google-search` 或 `brave-search`，public tool names 保持不变。

## 另见

- `../README.zh-CN.md`
- `common/README.zh-CN.md`
- `../../docs/zh-CN/concepts/packages-and-scenario-packs.md`
- `../../docs/zh-CN/guides/use-scenario-packs.md`
