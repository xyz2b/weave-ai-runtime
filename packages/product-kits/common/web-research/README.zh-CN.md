# Web Research Common Kit

Canonical import root: `weavert_kit_common_web_research`

## 这个包负责什么

- 统一的只读公网信息检索入口 `web_research`
- 基于 `weavert-web-research` 的低层 `web_search`、`web_fetch`、`web_find` primitives
- `web_research` 背后的 package-owned `web-searcher` delegated worker
- first-party research profiles：`general`、`coding`、`business`、`academic`、`legal_compliance`、`product_shopping`
- 统一结果 envelope：sources、evidence、conflicts、gaps、freshness、provider metadata、research trace 和 profile facets

## Canonical names

- package root: `packages/product-kits/common/web-research`
- install name: `weavert-kit-common-web-research`
- import root: `weavert_kit_common_web_research`
- runtime activation: `weavert-shared-web-research`

## 边界

需要 AI-first web research 时使用 `web_research`；需要 coding 等特定策略时传入 `profile="coding"` 或其他支持的 profile。Profile-specific 字段放在 `facets.<profile>` 下。

这个 package 只负责只读信息检索。浏览器导航、点击、表单填写、登录态 browsing 和 DOM interaction 仍由 browser bridge package 负责。
