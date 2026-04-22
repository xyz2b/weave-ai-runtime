## Context

runtime 现在已经有三块相关基础设施：

- named `model_route`，由 route 解析 provider ownership、default model 与 normalized capabilities；
- context preparation / compaction manager，可以在 turn preparation 阶段执行 request shaping 与 compaction；
- `context_limit` / `prompt_too_long` 后的 compact-and-retry recovery。

缺口在于“已知 context window”没有成为 route 或模型接入层的一部分。这样会导致两种不理想状态：

- 若框架要求最终用户在 runtime 顶层维护一张全局模型 context window 表，那么当接入很多不同模型、私有网关或代理模型时，业务配置会快速膨胀；
- 若框架完全不建模 context window ownership，则 proactive compaction 无法稳定建立，所有模型都只能等 provider 报错后再 reactive recovery。

这次设计需要在不破坏现有 route contract 的前提下，把 context window 与最小恢复分类提示放到更合理的层次：模型接入层和 resolved route，而不是 agent definition 或业务组件配置。

约束：

- 需要兼容大量 heterogeneous models，包括已知公开模型、私有 gateway 模型和 context window 未知模型；
- 现有 route / provider / agent contract 需要保持向后兼容；
- context window 未知的模型必须仍然可运行，不能因为没填 window 就被框架拒绝；
- business-facing agent/component 仍然应主要引用 route/profile，而不是 provider-specific 裸模型细节。

## Goals / Non-Goals

**Goals:**

- 定义 integration-owned model context window profile contract，使模型接入逻辑可以注册 context window 元数据与面向恢复路径的最小分类提示，其中至少覆盖 `context_limit`，可选覆盖 `output_limit`。
- 定义 route-owned context window policy contract，使 named routes 可以持有 context window ownership、override 和 fallback policy。
- 让 runtime 在已知 context window 时执行 proactive compaction，在 context window 未知时稳定降级为 reactive-only。
- 保持 agent / component 通过 `model_route` 或等价 profile 选择模型，不暴露 agent-level context-window fields。
- 为 context preparation、request-shaping hooks 和 observability surfaces 提供统一 context window hints。
- 让框架默认随附 first-party OpenAI provider integration 与对应的 named route / context window profile 基线。

**Non-Goals:**

- 不在本 change 中重做完整 provider/plugin 平台。
- 不要求所有模型都必须提供精确 tokenizer 或精确 context window。
- 不在本 change 中复刻某一特定 provider 的全部 autocompact 算法细节。
- 不把 context-window 字段直接加入 `AgentDefinition` 或要求业务层手工维护全量模型 context window 表。
- 不修改真正资源/计费/检索配额类的 budget 语义；本 change 只处理 context window 相关 contract 与命名。

## Decisions

### Decision: Separate context window profiles from normalized model capabilities

`NormalizedModelCapabilities` 继续只描述协议/执行层能力，例如 streaming、tool-call shape、abort passthrough；context window 相关语义单独建模为 `ModelContextWindowProfile` 或等价结构。

理由：

- protocol capability 和 context-window/容量语义是两类不同信息，前者更稳定，后者更容易随模型版本、网关策略或 provider policy 变化；
- 若把 context window 直接塞进 normalized capabilities，会让“工具调用能力协商”和“上下文窗口推导”耦合；
- context window 语义常常需要 pattern/default/override 和 unknown fallback，这比简单的布尔 capability 更像独立 contract。

备选方案：

- 把 `max_input_tokens` 等字段直接加进 `NormalizedModelCapabilities`。拒绝，因为语义层次不一致。
- 把 context window 信息完全放在自由形态 metadata。拒绝，因为 runtime 无法稳定消费，也不利于扩展包复用。

建议的 v1 最小结构如下：

```text
ModelContextWindowProfile
- provider_name: str | None
- model_selector: str | None
  exact model name or pattern such as "gpt-4.1" / "gpt-4.1-*"
- max_input_tokens: int | None
- reserved_output_tokens: int | None
- token_estimation_hint: TokenEstimationHint | None
- recovery_classification_hints: MinimalRecoveryClassificationHints | None
- source: "bundled" | "integration" | "route_override" | "user"
- confidence: "high" | "medium" | "low"

TokenEstimationHint
- tokenizer_name: str | None
- chars_per_token: float | None
- advisory_only: bool

MinimalRecoveryClassificationHints
- context_limit: RecoveryClassificationRule | None
- output_limit: RecoveryClassificationRule | None

RecoveryClassificationRule
- stop_reasons: tuple[str, ...]
- provider_error_codes: tuple[str, ...]
- http_statuses: tuple[int, ...]
- message_substrings: tuple[str, ...]
- retryable: bool | None

RouteContextWindowPolicy
- narrow_to_max_input_tokens: int | None
- reserved_output_tokens_override: int | None
- trigger_buffer_tokens: int | None
- fallback_mode: "proactive_and_reactive" | "reactive_only"
- profile_ref: str | None
```

约束：

- `model_selector=None` 表示 provider-default profile；
- `recovery_classification_hints` 只承载最小恢复分类，不承载完整 provider error taxonomy；
- `source`/`confidence` 属于 host-visible observability surface，而不是 provider-specific transport field。

### Decision: Profile matching precedence is deterministic

v1 明确采用固定匹配优先级，而不是留给实现自行决定：

1. exact model profile
2. pattern model profile
3. provider-default profile
4. unknown

route-level policy 总是在 integration profile 选定之后再应用，因此 precedence 是：

1. 先选 integration baseline
2. 再应用 route narrowing / override
3. 最后得出 `ResolvedContextWindowSnapshot`

同一 provider 下若出现两个同优先级 profile 同时命中同一个模型，视为配置冲突，runtime 在装配或注册阶段拒绝，而不是靠声明顺序隐式决策。

理由：

- compaction 与 recovery 需要稳定、可测试的匹配规则；
- 若依赖声明顺序，bundled integration 与第三方扩展混用时容易出现隐式漂移；
- route 的职责是“收窄/覆盖已选中的 profile”，不是参与 baseline profile 的竞争。

备选方案：

- 把匹配 precedence 留到实现时决定。拒绝，因为会让 route/profile resolution tests 很难稳定。
- 允许同优先级命中后按声明顺序取第一个。拒绝，因为可维护性和可解释性都太差。

### Decision: Rename context-control vocabulary from budget terms to context-window terms

当前 runtime 已经存在一组面向接入方和 runtime 内部协作的 context-control / request-shaping vocabulary，例如 `ContextBudgetHook`、`ContextBudgetRequest`、`ProviderBudgetHints`、`BudgetCandidate`、`BudgetDecision`、`BudgetPlan` 以及 `budget_hook`、`budget_policy_tag`、`context_budget_hook_error` 这类配置和 metadata 名称。从实现语义看，这些结构描述的是上下文准备阶段在 context window 压力下如何重写 tool-result replay payload，而不是 billing、quota 或其他“真实 budget”语义。因此本 change 应把这组 context-control vocabulary 统一迁移到 context-window 命名，例如 `ContextWindowHook`、`ContextWindowRequest`、`ProviderContextWindowHints`、`ContextWindowCandidate`、`ContextWindowDecision`、`ContextWindowPlan`，并同步清理直接关联的 config、diagnostics 与 effect kind 命名；旧名字通过兼容别名或 deprecated alias 过渡。

理由：

- 这些 contract 和 metadata 都围绕 context preparation、tool-result 降载、provider/model hints 和上下文窗口压力，不是 billing 预算；
- 若继续保留 `budget` 命名，会让“context window 压缩触发”和“真实预算/配额”长期混淆；
- 在 route-owned context window profile 落地时同步统一 vocabulary，能避免新旧 contract 同时存在两套含义接近但名称冲突的术语。
- 这些 surface 已经是用户扩展点，因此需要提供兼容迁移，而不是静默硬切。

建议的第一批 canonical rename 至少包括：

- `ContextBudgetHook` -> `ContextWindowHook`
- `ContextBudgetRequest` -> `ContextWindowRequest`
- `ProviderBudgetHints` -> `ProviderContextWindowHints`
- `BudgetCandidate` -> `ContextWindowCandidate`
- `BudgetDecision` -> `ContextWindowDecision`
- `BudgetPlan` -> `ContextWindowPlan`
- `ContextBudgetHookFailureMode` -> `ContextWindowHookFailureMode`
- `budget_hook` -> `context_window_hook`
- `budget_hook_failure_mode` -> `context_window_hook_failure_mode`
- `budget_hook_timeout_seconds` -> `context_window_hook_timeout_seconds`
- `budget_policy_tag` -> `context_window_policy_tag`
- `context_budget_hook_error` / `context_budget_hook_unparseable` -> `context_window_hook_error` / `context_window_hook_unparseable`
- `BUDGET_DECISION` effect kind -> `CONTEXT_WINDOW_DECISION`

备选方案：

- 只改三种类型名，保留 `BudgetPlan`、`BudgetDecision`、`budget_hook` 等相邻 vocabulary。拒绝，因为会留下半套 `budget`、半套 `context window` 的混合命名，迁移后仍然不清晰。
- 直接硬切到新名字，不提供兼容 alias。拒绝，因为这些是用户可实现的 public extension points，迁移成本过高。

### Decision: Context window ownership lives in model integrations and resolved routes, not agents

模型接入层负责注册“自己知道的模型 context window 和最小恢复分类提示”，其中至少包括 `context_limit`，可选包括 `output_limit`；route 负责声明要消费哪个 integration-owned catalog、是否应用 route-level override/narrowing，以及 unknown-window fallback policy。agent 只选择 route。

理由：

- integration 最了解 provider/model family 的 context window 与最小恢复分类提示；
- route 已经承担 provider ownership 和 default model 解析，是最自然的 context window ownership 汇聚点；
- agent 若直接持有 context-window fields，会把业务组件和 provider/model 细节耦合。

备选方案：

- runtime 顶层维护全局大表。拒绝，因为当模型很多时维护成本过高，且和具体 integration 分离后容易失真。
- 每个 agent 直接配置 context window。拒绝，因为重复、脆弱且破坏 route abstraction。

### Decision: Recovery classification hints stay narrow and optional

本 change 不要求 integration author 或业务用户维护完整 provider error taxonomy。context window profile 旁边只暴露面向恢复路径的最小分类提示：

- 必需关注 `context_limit`
- 可选补充 `output_limit`
- 其他错误继续优先走 runtime 现有 provider-neutral fallback classification

理由：

- 真正会改变 proactive/reactive compaction 路径的核心分类主要就是 `context_limit`；
- 若要求每个 integration 定义完整 provider error taxonomy，接入成本会显著抬高，而且很多使用者并不了解底层 provider 实现细节；
- runtime 已经有 provider-neutral failure classification 和保守兜底路径，不需要把所有错误都前置配置化。

备选方案：

- 要求每个 integration 提供完整 provider error taxonomy。拒绝，因为复杂度过高，且对大多数使用者不现实。
- 完全不暴露任何恢复分类提示。拒绝，因为那样已知 `context_limit` 无法稳定驱动 compact-and-retry。

最小示例：

```text
recovery_classification_hints:
  context_limit:
    http_statuses: [413]
    provider_error_codes: ["context_length_exceeded", "prompt_too_long"]
    stop_reasons: ["context_limit", "prompt_too_long"]
    retryable: true
  output_limit:
    provider_error_codes: ["max_output_tokens", "output_limit"]
    stop_reasons: ["max_tokens", "output_limit"]
    retryable: true
```

语义上只要求接入方告诉 runtime：

- 哪些 provider signals 可以稳定视为 `context_limit`
- 可选地，哪些 signals 可以稳定视为 `output_limit`
- 其他错误继续由 runtime fallback classification 处理

### Decision: Resolve a per-request context window snapshot before context preparation

在 request/turn 进入 compaction 之前，runtime 先基于 `resolved_model_route`、最终 `model`、integration catalog 和 route override 解析出一个 `ResolvedContextWindowSnapshot` 或等价结构，再把它注入 context preparation 与 provider context-window hints。

这个 snapshot 至少应覆盖：

- `max_input_tokens`
- `reserved_output_tokens`
- `remaining_input_tokens` 或等价可推导 headroom
- token estimation / tokenizer hint
- `fallback_mode`，例如 `proactive_and_reactive` 或 `reactive_only`
- minimal recovery classification hints, at least `context_limit` and optionally `output_limit`

理由：

- compaction、request-shaping hook、request shaping、observability 都需要看同一份 context window 真值；
- 若每个子系统各自从 route/model metadata 重新推导，行为会分叉。

备选方案：

- 让 compaction manager 自己直接查 route binding。拒绝，因为 context window 解析会散落到 compaction 内部，后续 hook 和 observability 还得重复实现。

建议的 resolved shape：

```text
ResolvedContextWindowSnapshot
- max_input_tokens: int | None
- reserved_output_tokens: int | None
- remaining_input_tokens: int | None
- token_estimation_hint: TokenEstimationHint | None
- fallback_mode: "proactive_and_reactive" | "reactive_only"
- recovery_classification_hints: MinimalRecoveryClassificationHints | None
- source: "bundled" | "integration" | "route_override" | "unknown"
- confidence: "high" | "medium" | "low" | "unknown"
```

### Decision: Unknown context window metadata degrades to reactive-only instead of failing closed

若当前 route/model 没有已知 context window 信息，runtime 仍允许请求继续执行，只是不启用 proactive context-window-derived compaction，并依赖 `context_limit` / `prompt_too_long` 分类后的 reactive compact-and-retry。

理由：

- 这是支持大量异构模型时最重要的兼容性要求；
- 很多私有网关或代理模型无法提供可靠 window metadata，强制要求配置会显著抬高接入门槛；
- runtime 已有 reactive recovery 路径，可以作为稳定兜底。

备选方案：

- 未知 context window 直接拒绝执行。拒绝，因为对扩展模型极不友好。
- 未知 context window 强行猜一个默认窗口。拒绝，因为误判风险更大，且会把 provider-specific 假设硬编码进 framework。

### Decision: Bundle OpenAI as the default first-party provider integration

框架本身默认随附 first-party OpenAI provider integration，并提供可直接引用的 named route、context window profile 基线以及最小恢复分类提示。第三方 provider、私有 gateway 或 OpenAI-compatible adapter 仍通过同一 integration contract 扩展。

理由：

- OpenAI 是最常见的默认接入面，作为框架内置能力能显著降低首次落地成本；
- 本 change 正在定义 integration-owned context window profile contract，内置一个 first-party integration 可以作为该 contract 的基线参考实现；
- 这不妨碍后续继续接入 Anthropic、Qwen、DeepSeek 或私有网关，只是框架默认先保证 OpenAI 路径可用。

备选方案：

- 框架不内置任何 provider，全部留给使用者自己装配。拒绝，因为初始接入门槛过高，也缺少 first-party contract 样板。
- 同时内置大量 provider。暂不作为 v1 要求，因为会扩大本 change 范围。

建议的 v1 baseline 约定：

- bundled provider binding name: `openai-prod`
- bundled named route: `openai_default`
- credential env var: `OPENAI_API_KEY`
- optional endpoint override env var: `OPENAI_BASE_URL`
- optional default model env var: `OPENAI_MODEL`
- 若 host 未提供 `OPENAI_API_KEY` 且未通过 runtime config 覆盖 credentials，route 仍可被发现，但实际调用在 provider invocation 前报结构化配置错误

说明：

- `openai_default` 是 route-level 入口，业务组件继续只引用 route；
- `OPENAI_MODEL` 只决定 bundled OpenAI baseline 的默认模型，不影响 route precedence 或显式 `model` override；
- host 若要改 base URL、credentials 或默认模型，可以覆盖 bundled route/binding，而不需要替换整套 first-party integration contract。

示例：

```yaml
default_model_route: openai_default
model_routes:
  openai_default:
    provider_binding: openai-prod
    default_model: ${OPENAI_MODEL}
providers:
  - name: openai-prod
    provider: openai
    api_key_env: OPENAI_API_KEY
    base_url_env: OPENAI_BASE_URL
```

### Decision: Business-facing components choose semantic routes, not raw models

agent、skill-driven child execution 和其他业务组件仍以 `model_route` 或等价 semantic profile 作为主入口；显式 `model` override 只允许在已解析 route 内替换默认模型，不用于重路由，也不直接承载 context window ownership。

理由：

- route 是 provider ownership、default model、context window policy 的统一边界；
- semantic route 比裸模型名更适合长期维护和批量替换；
- 可以继续复用现有 route precedence contract。

备选方案：

- 让业务组件直接引用 provider/model 字符串。拒绝，因为会把 provider naming 细节泄漏到业务层。

### Decision: Migration uses canonical-new plus compatibility-old surfaces

rename 迁移契约在 v1 明确如下：

- 文档、示例、测试基线只使用新的 `ContextWindow*` vocabulary；
- 旧的 `ContextBudget*` public symbols 继续作为 compatibility alias 暂时保留；
- config 解析同时接受新旧 key，若同一作用域同时提供新旧 key，则新 key 优先；
- host-visible metadata 与 diagnostics 在迁移窗口内允许 dual-write，新 key 为 canonical，旧 key 仅作兼容；
- 迁移窗口内使用 legacy config key 时，runtime 应产生结构化 deprecation diagnostic，而不是静默接受

理由：

- 仅靠 alias 不足以保护 metadata/diagnostics consumer；
- 若新旧 key 同时出现却不规定 precedence，实现和用户都很难判断最终行为；
- 用结构化 diagnostic 比纯文本 warning 更适合 host 和测试消费。

### Decision: Context-window observability is structured and bounded

host-visible observability 至少应稳定暴露下列字段：

```text
context_window:
  max_input_tokens
  reserved_output_tokens
  remaining_input_tokens
  fallback_mode
  source
  confidence

context_window_policy_tag
context_window_hook_failure_mode
```

diagnostics / effects 至少应包含：

- `context_window_hook_error:<ExceptionType>`
- `context_window_hook_unparseable`
- `CONTEXT_WINDOW_DECISION`

说明：

- `context_window` 推荐作为结构化子对象暴露，避免继续扩散大量平铺字段；
- `context_window_policy_tag` 保持单独顶层字段，便于 host/trace/filter 使用；
- 若迁移期 dual-write 旧字段，旧字段仅作 compatibility projection，不得反过来成为 canonical source。

### Decision: Migration is additive and backwards-compatible

现有 `model_routes`、agent definitions 和 model integrations 即使不提供任何 context window metadata，也应继续工作。新增 context window profile/candidate resolver 只作为可选增强：

- 有 context window profile：runtime 启用 proactive context-window-aware compaction
- 无 context window profile：runtime 自动走 `reactive_only`

理由：

- 这能让已有 runtime config 与第三方 integration 逐步迁移，而不是一次性重配。

## Risks / Trade-offs

- [Risk] context window profile 过期或不准确会导致 proactive compaction 触发偏早或偏晚。 → Mitigation: 明确 `source`/`confidence` 语义，保留 reactive fallback，并允许 route-level narrowing。
- [Risk] route surface 变得过大，重新把 provider-specific 细节暴露到业务配置。 → Mitigation: route 只允许持有最小 context window policy，不承载原始 transport 或复杂 provider 私有字段。
- [Risk] integration authors 提供的最小恢复分类提示不一致，导致 reactive fallback 行为不稳定。 → Mitigation: 规范 `context_limit` 优先、`output_limit` 可选的最小 contract，并在 runtime 里保留 provider-neutral fallback classification。
- [Risk] context window 未知的模型只能 reactive compact，体验不如已知 context window 的模型。 → Mitigation: 把这作为明确的 graceful degradation，而不是失败；后续允许 integration 渐进补齐 catalog。
- [Risk] 内置 OpenAI provider baseline 可能被误解为框架只服务 OpenAI。 → Mitigation: 明确它是 first-party bundled integration，不限制第三方 provider contract，也不影响 route-level 扩展。

## Migration Plan

1. 为 route/model resolution 增加可选 context window profile resolution contract，不改变现有 route precedence。
2. 默认随附 first-party OpenAI provider integration，并为其提供内置 context window profiles、默认 named routes 与最小恢复分类提示；第三方 integrations 可以按相同 contract 注册自己的 profiles。
3. 扩展 route config，允许声明 context window ownership、override 或 fallback policy；未声明者默认 `reactive_only`。
4. 将 `ContextBudgetHook`、`ContextBudgetRequest`、`ProviderBudgetHints`、`BudgetCandidate`、`BudgetDecision`、`BudgetPlan` 及其直接关联配置命名迁移到 `ContextWindow*` vocabulary，并提供兼容 alias / deprecation path。
5. 在 context preparation / compaction path 中消费 resolved context window snapshot；若 snapshot 不存在，保持当前 reactive recovery 行为。
6. 更新示例与文档，明确 agent/component 继续引用 `model_route`，而不是 context-window 字段或 provider-specific model tables。

回滚策略：

- 若 context window resolution 行为不稳定，可以回退到不消费 resolved context window snapshot，仅保留现有 reactive compaction/recovery 路径；
- route 和 integration 的新增 context-window fields 都应是 optional，因此回滚不需要迁移用户已有 agent definitions。

## Open Questions

- token estimation hint 是否应绑定 tokenizer 实现对象、枚举名称，还是保持更弱的 advisory contract？
- provider hints 是否只暴露 context-window 数值字段，还是同时暴露 profile source/confidence 供 hooks 做更细粒度决策？
