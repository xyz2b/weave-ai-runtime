# Web Research Common Kit

Canonical import root: `weavert_kit_common_web_research`

## 这个包负责什么

- 统一的只读公网信息检索入口 `web_research`
- 基于 `weavert-web-research` 的低层 `web_search`、单页 `web_fetch`、`web_find` primitives
- `web_research` 背后的 package-owned research loops：deterministic goal-driven loop，以及 opt-in model-directed Pro loop
- 仅用于 bounded implementation-period fallback path 的 package-owned `web-searcher` delegated worker
- first-party research profiles：`general`、`coding`、`business`、`academic`、`legal_compliance`、`product_shopping`
- 统一结果 envelope：sources、evidence、conflicts、gaps、freshness、provider metadata、research trace 和 profile facets

## Canonical names

- package root: `packages/product-kits/common/web-research`
- install name: `weavert-kit-common-web-research`
- import root: `weavert_kit_common_web_research`
- runtime activation: `weavert-shared-web-research`

## 边界

需要 goal-driven AI-first web research 时使用 `web_research`；需要 coding 等特定策略时传入 `profile="coding"` 或其他支持的 profile。Profile-specific 字段放在 `facets.<profile>` 下。`web_research` 是多页 source discovery 与 inspection 的支持路径：它会从 objective 派生或规划 bounded queries、排序或验证 candidate pages、检查 ledger-verified sources、报告 gaps 或 conflicts，并在 `research_trace` 与 `trace_summary` 暴露 loop decisions。低层 `web_fetch` 只检查一个显式页面，手动多页检查应发起多次单页 `web_fetch`。

这个 package 只负责只读信息检索。浏览器导航、点击、表单填写、登录态 browsing 和 DOM interaction 仍由 browser bridge package 负责。

## Strategy Selection

`web_research` 支持向后兼容的 strategy selection：

- 省略 `strategy` 时使用 deterministic package-owned loop，除非 host runtime 显式把符合条件的调用 opt in 到 Pro mode。
- 传入 `strategy="pro"` 时，在同一个 public tool 名称背后请求 model-directed Pro research。
- 未知 strategy value 会在 input validation 阶段被拒绝，不会被静默解释成 Pro 或 deterministic 行为。

Pro mode 会向内部 planner 和 synthesizer model turns 请求 structured JSON，但这些 outputs 只是 proposals。Deterministic scripted test responses 会先被消费，其次是显式 Pro test hook，最后才使用 assembled runtime 的普通 model client。Runtime validation 仍然负责 allowed domains、blocked domains、public-host checks、search/fetch/find budgets、source-handle identity、direct-URL provenance、freshness metadata、authoritative evidence ledger、public stop reason 和 public confidence。若 Pro model support 不可用，host 可以继续把 deterministic behavior 作为 fallback baseline，调用方仍使用 `web_research`。

Pro planner 可以提出 `search`、`fetch`、`find`、`direct_url_fetch` 或 `stop`。`fetch` 必须引用之前 search 或 ledger state 中已知的 source。直接 URL 检查必须使用显式 `direct_url_fetch`；被接受的 direct-URL evidence 会带有 provenance trace，调用方可以区分它和 search-discovered evidence。仅有 direct-URL evidence 时，不会静默满足更宽的 source-discovery 或 profile-coverage 预期。

## Model-Directed Synthesis

Pro synthesis 是 evidence-bound 的。Synthesizer 收到 bounded ledger evidence、conflicts、gaps、freshness metadata、provider metadata 和 objective，然后返回 answer text 与 structured claims。Runtime 只接受 evidence ids 能绑定到 inspected ledger evidence 的 claims。Accepted claims 可以保留 bounded metadata，例如 `claim_key`、`stance`、`conflicts_with`、`incompatible_with`、`resolved` 和 `resolution_rationale`；unbound metadata 不能创建 public claims、evidence、conflicts 或 high confidence。可选 excerpt spans 或 exact excerpts 会在提供时校验；无效 span metadata 会被标记为 unsupported，不会让 model 成为事实来源。

当 unsupported synthesis 仍然存在时，runtime 最多允许一次 configured repair turn，之后丢弃仍不支持的 claims，通过 gaps 或 stop-reason refinement 降级 terminal result，并记录 bounded trace events。即使 planner 或 synthesizer 忽略 unresolved ledger-bound conflicts 和 unsupported freshness，它们仍会保留在结果中。

## 剩余限制

Runtime enforcement 可以阻止 unsupported confidence 和 uninspected citations 成为 public evidence，但不能证明已检查的网页内容在真实世界中一定正确。这个 kit 不负责 browser driving、点击、认证浏览、本地 workspace search 或 shell-assisted searches；这些仍属于独立 surfaces。
