## Why

当前 runtime 已经支持 named `model_route`、统一 compaction manager 和 `context_limit` 后的 compact-and-retry，但“已知 context window”还没有成为 route 或模型接入层的一部分。若继续让最终用户在 runtime 顶层手工维护大而散的模型 context window 表，或把 context window 直接写到 agent 配置里，业务组件就会和 provider/model 细节耦合，且在接入大量不同模型时难以维护。

现在需要把 context window 元数据与最小恢复分类提示收口到模型接入层和 route/profile contract 中，让 framework 只负责统一消费已知 context window 信息并在信息未知时提供 reactive fallback。这样 agent 仍然只选择 route，而不需要承担 provider-specific context window 知识。

## What Changes

- 引入 integration-owned model context window profile contract，使 provider/model 接入逻辑可以注册已知 `max_input_tokens`、reserved output headroom、token estimation hints，以及面向恢复路径的最小分类提示，其中至少覆盖 `context_limit`，可选覆盖 `output_limit`。
- 扩展 named `model_route` contract，使 route 除了 provider binding、default model 与 normalized capabilities 外，还能持有 context window profile ownership、route-level override/narrowing 与 unknown-window fallback policy。
- 让 runtime 在 turn preparation 中优先从 resolved route/model context window metadata 派生 proactive compaction policy；当当前模型没有已知 context window 信息时，runtime SHALL 降级为 reactive-only compaction，而不是要求用户显式补齐全量配置才能运行。
- 保持 agent / component 侧通过 `model_route` 或等价语义 profile 选择模型，不新增 agent-level context-window 字段，也不要求业务层直接维护 provider/model context window 细节。
- 框架默认随附 first-party OpenAI provider integration，并提供可直接使用或覆盖的 OpenAI named route / context window profile 基线；第三方或私有 provider 仍按同一 contract 扩展。
- 将现有上下文载荷控制 vocabulary 从 `budget` 统一调整为 `context window` 语义，例如将 `ContextBudgetHook`、`ContextBudgetRequest`、`ProviderBudgetHints` 分别演进为 `ContextWindowHook`、`ContextWindowRequest`、`ProviderContextWindowHints`，并继续把紧邻的 `BudgetCandidate`、`BudgetDecision`、`BudgetPlan`、failure mode、config keys、diagnostics 与 effect kind 一并迁移到 context-window 命名；旧名字通过兼容别名降低迁移成本。
- 为 request shaping hook 与 observability surface 增加稳定的 provider/model context window hints，便于不同模型接入包与上层策略共享统一上下文窗口语义。

## Capabilities

### New Capabilities
- `model-context-window-profiles`: 定义模型接入层注册 context window 档案、route 解析 context window ownership、以及 unknown-window reactive fallback 的统一 contract。

### Modified Capabilities
- `agent-system`: 扩展 named model route 语义，使 route 在 provider/default model/capabilities 之外还能解析 context window profile ownership 与 route-level context window policy。
- `builtin-runtime-pack`: 随附 first-party OpenAI provider integration、默认 named routes，以及对应的 context window profile 基线与最小恢复分类提示。
- `runtime-compaction-manager`: 扩展 compaction trigger contract，使 runtime 可基于 resolved route/model context window metadata 执行 proactive compaction，并在 context window 信息未知时稳定退化到 reactive recovery。

## Impact

- Affected code: `src/runtime/runtime_kernel/config.py`, `src/runtime/agent_execution_service.py`, `src/runtime/turn_engine/`, `src/runtime/compaction/`, provider/model adapter wiring, bundled provider definitions, and runtime configuration examples.
- Affected APIs/contracts: `ModelRouteBinding`, provider/model integration registration surfaces, compaction policy derivation, context-window hook vocabulary, context-window plan/decision metadata, provider context-window hints, bundled OpenAI provider definitions, and route-owned request metadata.
- Affected systems: named model routes, context preparation, compaction/recovery policy, built-in runtime packs, and extension points for integrating many heterogeneous models.
