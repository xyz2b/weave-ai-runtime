# Web Common Kit

规范 import root：`weavert_kit_common_web`

## 这个 package 拥有什么

- 面向用户的只读高层入口 `web_research`
- 可复用的低层 `grounding_web_search`、`grounding_web_fetch`、`grounding_web_find` primitives
- 被 chat 与 local-assistant product-kit composition 使用的共享 web tooling
- `web_research` 背后的 package-owned delegated worker `web-searcher`

## 规范名称

- 安装名：`weavert-kit-common-web`
- import root：`weavert_kit_common_web`

## 不要把它和这些包混在一起

- 当你需要默认的 AI-first 公网 web grounding 入口时，选 `web_research`。
- 当你需要显式编排搜索、抓取或页面内查找时，再直接使用低层 primitives。
- 如果还要对抓回来的材料做排序或 citation 准备，再搭配 `weavert-kit-common-retrieval`。
- `web-searcher` 用于 runtime child-run delegation 与 package extension，不作为推荐的用户直接入口。
- 如果 assistant 需要在 app-owned browser 里导航、点击或填表，不要选它；那属于 `weavert-kit-common-browser`。

## 另见

- `../README.zh-CN.md`
- `../../chat/README.zh-CN.md`
- `../../../../docs/zh-CN/introduction/use-cases.md`
