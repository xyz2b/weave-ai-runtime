# Web Common Kit

规范 import root：`weavert_kit_common_web`

## 这个 package 拥有什么

- 面向用户的只读高层入口 `web_research`
- 可复用的低层 `grounding_web_search`、`grounding_web_fetch`、`grounding_web_find` primitives
- 被 chat 与 local-assistant product-kit composition 使用的共享 web tooling
- `web_research` 背后的 package-owned delegated worker `web-searcher`
- delegated research run 内的 open/focused 策略、证据账本与有界并发页面检查

## 规范名称

- 安装名：`weavert-kit-common-web`
- import root：`weavert_kit_common_web`

## 不要把它和这些包混在一起

- 当你需要默认的 AI-first 公网 web grounding 入口时，选 `web_research`。
- 需要把域名范围当成硬约束时使用 `mode="focused"`；开放探索问题使用 `mode="open"`，此时 legacy `domains` 会成为偏好来源而不是硬限制。
- 不可突破的边界放在 `hard_policy` 或 `allowed_domains`；排序提示、`preferred_domains`、freshness 等放在 `preferences`。
- 通过 `budget_profile`、显式 search/fetch/find budget 和 `max_concurrent_fetches` 控制开放研究的边界。
- 当你需要显式编排搜索、抓取或页面内查找时，再直接使用低层 primitives。
- 如果还要对抓回来的材料做排序或 citation 准备，再搭配 `weavert-kit-common-retrieval`。
- `web-searcher` 用于 runtime child-run delegation 与 package extension，不作为推荐的用户直接入口。
- `web_research_fetch_many` 是 active `web_research` run 内部使用的 package-owned 并发检查 helper；面向用户的集成仍应调用 `web_research`。
- 如果 assistant 需要在 app-owned browser 里导航、点击或填表，不要选它；那属于 `weavert-kit-common-browser`。

## 另见

- `../README.zh-CN.md`
- `../../chat/README.zh-CN.md`
- `../../../../docs/zh-CN/introduction/use-cases.md`
