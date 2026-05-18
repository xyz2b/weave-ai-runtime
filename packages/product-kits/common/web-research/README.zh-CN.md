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

Pro mode 会向内部 planner、synthesizer、answer verifier 和 bounded repair model turns 请求 schema-versioned structured JSON，但这些 outputs 只是 proposals。Deterministic scripted test responses 会先被消费，其次是显式 Pro test hook，最后才使用 assembled runtime 的普通 model client。Runtime validation 仍然负责 allowed domains、blocked domains、public-host checks、search/fetch/find budgets、source-handle identity、direct-URL provenance、freshness metadata、authoritative evidence ledger、public stop reason 和 public confidence。若 Pro model support 不可用，host 可以继续把 deterministic behavior 作为 fallback baseline，调用方仍使用 `web_research`。

Pro planner 可以提出 `search`、`fetch`、`find`、`direct_url_fetch` 或 `stop`。`fetch` 必须引用之前 search 或 ledger state 中已知的 source。直接 URL 检查必须使用显式 `direct_url_fetch`；被接受的 direct-URL evidence 会带有 provenance trace，调用方可以区分它和 search-discovered evidence。仅有 direct-URL evidence 时，不会静默满足更宽的 source-discovery 或 profile-coverage 预期。

## Model-Directed Synthesis

Pro synthesis 是 answer-proof-bound 的。Synthesizer 收到 bounded ledger evidence、conflicts、gaps、freshness metadata、provider metadata、proof-addressable runtime records 和 objective，然后返回 structured claims 与有序 `answer_units`。Runtime 只接受 evidence ids 能绑定到 inspected ledger evidence 的 claims。Public Pro `answer` 只从已接受 answer units 组装；这些 units 必须绑定到 accepted claim ids、gap ids、conflict ids、limitation ids，或被 verifier 以 `support="non_factual"` 接受为 transition text。Raw synthesizer answer text 只作为 draft，不会被直接投射为 public answer。Accepted public `answer_units` 会暴露 bounded text、kind、support status 和 proof ids，供后续 citation preparation 使用。

Internal Pro model turns 当前使用这些 schema versions：`web_research.planner.v1`、`web_research.synthesizer.v1`、`web_research.verifier.v1` 和 `web_research.repair.v1`。Runtime 会用 structured validation classes 拒绝 non-object JSON、schema-version mismatch、missing required fields、invalid enum values、oversized fields、duplicate answer-unit ids，以及引用 supplied proof state 之外 ids 的 responses，并在 bounded trace metadata 中记录。

当 unsupported synthesis 或 answer proof failures 仍然存在时，runtime 最多允许一次 configured repair turn（适用时），之后丢弃仍不支持的 claims 或 answer units，通过 gaps 或 stop-reason refinement 降级 terminal result，并记录 bounded trace events。已绑定的 gaps、limitations 和 unresolved conflicts 可以保留在 answer 中，但不会提高 confidence。即使 planner、synthesizer 或 verifier 忽略 unresolved ledger-bound conflicts 和 unsupported freshness，它们仍会保留在结果中。

## Search Provider Selection

Public tool names 保持稳定：调用方继续使用 `web_research`、`web_search`、`web_fetch` 和 `web_find`。Search provider selection 由 shared `weavert-web-research` core 处理。

- `google-search`：设置 `GOOGLE_SEARCH_API_KEY` 和 `GOOGLE_SEARCH_CX`；可选设置 `WEAVERT_WEB_SEARCH_PROVIDER=google-search`。
- `serpapi-google-search`：设置 `SERPAPI_API_KEY`；可选设置 `WEAVERT_WEB_SEARCH_PROVIDER=serpapi-google-search`。可选的 `WEAVERT_SERPAPI_GOOGLE_DOMAIN`、`WEAVERT_SERPAPI_HL` 和 `WEAVERT_SERPAPI_GL` 用于调整 Google domain、language 和 region 默认值。
- `brave-search`：设置 `BRAVE_SEARCH_API_KEY` 或 `WEAVERT_BRAVE_SEARCH_API_KEY`；可选设置 `WEAVERT_WEB_SEARCH_PROVIDER=brave-search`。
- `bing-grounding`：设置 `FOUNDRY_PROJECT_ENDPOINT`、`FOUNDRY_MODEL_DEPLOYMENT_NAME`、`BING_PROJECT_CONNECTION_ID` 和 `AGENT_TOKEN`；可选设置 `WEAVERT_WEB_SEARCH_PROVIDER=bing-grounding`。
- `duckduckgo-html`：不需要 credentials 的 fallback。这个 adapter 不暴露稳定的 freshness filter。

Bing grounding 使用 Azure AI Foundry Responses API `bing_grounding`，并把稳定公网 URL citations 规范化成 shared result shape；它不是已退役的 Bing Search API v7 endpoint。Google Programmable Search、SerpAPI Google Search 和 Brave 会在支持时把 domain constraints 映射为 provider query operators；Bing grounding 和 DuckDuckGo 会把这些 controls 报告为 framework-filtered。Shared core 仍会根据 allowed domains、blocked domains 和 public-host policy 重新校验 accepted result URLs。Freshness semantics 是 provider-specific：Google 使用近似的 `dateRestrict`，Brave 使用它的 `freshness` parameter，Bing grounding 映射支持的 1/7/30 天 freshness windows，SerpAPI 和 DuckDuckGo 会报告 freshness unsupported。SerpAPI 只把 `organic_results` 转为 source candidates；SERP answer blocks 和 related-search payloads 不会提升为 ledger evidence。

## Research Profiles and Quality Signals

`web_research` 会在 inspection pages 之前应用 profile strategy。Coding 优先官方文档、release notes、changelogs、source repositories 和 issue trackers，并提供 API names、versions、compatibility notes 与 breaking changes facets。Legal compliance 优先 statutes、regulations、standards 和 official guidance，并保留 jurisdiction、authority、freshness 和 effective-date gaps。Business research 偏向 company sources、filings、announcements、credible news、reviews、competitors、timelines、comparison axes 和 market claims。Academic research 偏向 papers、publishers、institutions、preprints、methods、experiments、conclusions 和 citation metadata。Product shopping 偏向 official specs、current prices、reviews、alternatives、comparison axes 和 purchase-risk signals。

Candidate sources 在 fetch 前会得到可追踪的 quality metadata：objective relevance、profile priority、provider metadata、freshness signals、preferred 或 allowed domains、duplicate clusters，以及按 domain 和 URL 做的 deterministic tie-breaking。Inspection 后，ledger evidence 会保留 source class 和 quality metadata，方便调用方和测试解释 source selection。

## Claims, Conflicts, Gaps, and Limits

Claim annotations 只有在绑定到已检查的 ledger source、page 或 evidence item 时才会被接受。Unbound annotations 会被丢弃并进入 trace。Rule-derived dates、versions、prices、numbers、source-type hints 和 duplicate signals 会出现在 `auxiliary_signals` 中；它们帮助 diagnostics 和 facets，但不证明 claim correctness。

Conflicting ledger-bound claims 会投射到 `conflicts`。Unresolved conflicts 会降低 confidence，并产生 `stop_reason="unresolved_conflict"`；当更强 evidence 被识别时，resolved conflicts 会保留 resolution rationale。Gaps 描述 missing preferred evidence、unsupported freshness、provider fallback、policy blocks 或 partial results。

Remaining limits 是显式的：这个 kit 不负责 browser driving、点击、认证浏览、本地 workspace search、shell-assisted searches，也不保证 inspected public evidence 之外的真实性。Runtime enforcement 可以阻止 unsupported confidence 和 uninspected citations 成为 public evidence，但不能证明已检查的网页内容在真实世界中一定正确。Host-level browser bridges、local workspace search 和 shell tools 仍属于独立 surfaces。

## See also

- `../README.zh-CN.md`
- `../../../framework-packs/capabilities/web-research/README.md`
