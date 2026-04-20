## Context

当前 runtime 已经具备显式 turn phase、attempt-final / turn-final 分离、streaming tool orchestration 和 session-level terminal projection，但恢复与上下文准备仍只有骨架，没有真正闭合成 runtime 自己拥有的控制面。

当前主要缺口有 5 类：

1. `TurnRecoveryAction` 已定义 `rebuild_request`、`compact_and_retry`、`retry_with_override`，但运行路径基本仍停留在 `halt` 或 `continue_same_turn`。
2. `CompactionManager` 目前只覆盖 material summary compaction，没有统一承载 budget hook integration、context projection 和 active context rebuild。
3. sidecar supervisor 只在 applied compaction 时显式 restart，budget hook 驱动的 rewrite、projection change 或 recovery rebuild 还不会触发 deterministic invalidation。
4. stop phase / hook outcome 仍以布尔式 continue/block 为主，不足以表达“继续当前 turn”“阻塞 session”“携带 injected messages 或 request override”这几种不同语义。
5. `ToolResultSummary` 已存在，但 tool result 仍直接以内联 payload 回填 continuation history，runtime 还没有正式接管 hook-driven tool-result budget decisions 与 spillover。

这意味着：

- prompt-too-long、output-limit、media-limit 等恢复路径还没有 provider-neutral policy surface
- non-destructive context reduction 仍缺少正式语义，只能依赖 transcript rewrite 或完全不做
- tool result 体积会继续向 prompt 直接泄漏
- stale sidecar 结果在复杂 continuation 下仍可能参与后续 request shaping

这次设计的目标不是重写 `SessionController -> TurnEngine -> StreamingToolOrchestrator`，而是在现有状态机之上补齐两个正式控制面：

- `RecoveryPolicy`
- `ContextControlPlane`

## Goals / Non-Goals

**Goals:**

- 让 `RECOVERY_DECISION` phase 由结构化 `RecoveryPolicy` 驱动，而不是继续堆叠 ad-hoc branch logic。
- 让 `COMPACT_OR_REBUILD` phase 由结构化 `ContextControlPlane` 驱动，统一处理 active context preparation，并通过可插拔 budget hook 承载业务特定预算决策。
- 区分 transcript truth、active context view 与 spillover artifacts，使 non-destructive context reduction 不再强依赖 transcript rewrite。
- 将 request override 从 skill-only 语义泛化为 runtime-wide control surface，供 recovery 与 stop-phase 共同使用。
- 让 sidecar invalidation 与 request shaping 绑定到统一的 `context_generation` 语义，而不是只绑定 material compaction。
- 保持 ordered tool-result replay 和 lifecycle semantics，但允许结果在 budget hook 判定需要降载时摘要化或 externalize。
- 为后续 reactive compact、context collapse、route fallback 和 richer stop hooks 提供稳定边界。

**Non-Goals:**

- 不在本 change 中逐项复刻 Claude Code 的所有 compaction 算法，如 snip、microcompact、contextCollapse 等完整产品逻辑。
- 不在本 change 中引入新的 host UI 渲染协议，只增加 host-visible metadata / transition contract。
- 不要求 provider adapter 在第一阶段实现完整 retry/fallback 产品策略，只要求暴露足够的标准化 failure classification。
- 不重做 transcript store 的整体持久化模型，只在需要时为 spillover artifact 增加最小补充接口。
- 不在本 change 中内建统一的 budget 计算公式；不同业务如何计算 token、字节数、工具结果权重或风险阈值，统一交给接入方实现的 `ContextBudgetHook`。

## Decisions

### 1. 引入 `RecoveryPolicy`，并将 `RECOVERY_DECISION` phase 的裁决职责从 `engine.py` 分支逻辑中抽离

`TurnEngine` 将继续拥有 phase 驱动权，但恢复裁决本身将由独立模块完成：

```text
RecoveryPolicy.evaluate(
  attempt: AttemptFinished,
  stop_outcome: StopPhaseOutcome | None,
  recovery_state: RecoveryState,
  context_state: PreparedContext,
  tool_outcomes: Sequence[ToolOutcome],
) -> RecoveryDecision
```

推荐的输出模型：

```text
RecoveryDecision
  - action:
      halt
      continue_same_turn
      rebuild_request
      compact_and_retry
      retry_with_override
  - reason: TurnTransitionReason | recovery-specific reason
  - injected_messages: tuple[RuntimeMessage, ...]
  - request_override: RequestOverrideState | None
  - metadata: Mapping[str, Any]
```

Why:

- 当前 `TurnRecoveryAction` 已存在，但没有成为实际控制面；独立 policy 才能真正落地枚举。
- `RecoveryDecision` 需要同时消费 attempt outcome、stop outcome、context pressure 和 retry state，继续散在 `engine.py` 里会很快失控。
- 把裁决抽成纯策略对象后，更容易做 golden tests 和 provider-specific classification tests。

Alternatives considered:

- 继续把 recovery 分支内联在 `engine.py`。拒绝，因为 phase 增长后可读性和可验证性都会继续下降。
- 让 provider adapter 直接决定 retry / halt。拒绝，因为 recovery 是 runtime continuation policy，不是 provider 语义。

### 2. 先标准化 provider / model outcome，再让 recovery policy 做统一裁决

恢复策略不应直接依赖 provider 的裸 `stop_reason` 或错误字符串。`ModelTerminalMetadata.metadata` 需要补一层 provider-neutral classification，例如：

```text
failure_class:
  none
  context_limit
  media_limit
  output_limit
  provider_overload
  auth_error
  tool_schema_error
  internal_error

retryable: bool
provider_error_code: str | None
```

`_terminal_reason_from_attempt()` 仍负责 turn-final projection，但 `RecoveryPolicy` 优先读标准化 classification，再决定 action。

Why:

- 当前未知 stop reason 会退化成 `INCOMPLETE`，这不足以支持结构化恢复。
- provider-neutral classification 让 recovery tests 可以脱离具体 provider 字符串。

Alternatives considered:

- 只保留 `stop_reason` 并在 recovery 内做字符串匹配。拒绝，因为 provider drift 会持续污染 runtime。

### 3. 将 skill-only override 泛化为 runtime-wide `RequestOverrideState`

当前 runtime 只有 `SkillRequestOverrideState`，但 recovery 也需要对下一次 request 施加结构化 override。建议引入更通用的状态对象：

```text
RequestOverrideState
  - requested_model: str | None
  - requested_effort: Any | None
  - requested_model_route: str | None
  - invocation_mode_override: ModelInvocationMode | None
  - max_output_tokens_override: int | None
  - source: str | None
```

该状态由 `RuntimePrivateContext.extensions` 持有，并提供 deterministic merge 语义：

- skill override 可以写入
- recovery override 可以写入
- stop-phase hook 也可以写入
- `BUILD_REQUEST` phase 统一消费并在 request 发出后按规则清理

Why:

- `retry_with_override` 如果没有正式 override state，就只能退回临时局部变量。
- skill 与 recovery 不应各自维护一套 request override 机制。

Alternatives considered:

- 在 `TurnLoopState` 单独维护 recovery-only override。拒绝，因为 skill 与 stop hooks 也需要共享这条控制面。

### 4. 引入 `ContextControlPlane`，统一构造 Active Context View，并将 budget 计算委托给 hook

`COMPACT_OR_REBUILD` 不应只等同于 `CompactionManager`。建议新增：

```text
ContextControlPlane.prepare(
  transcript_messages: Sequence[RuntimeMessage],
  private_context: RuntimePrivateContext,
  prompt_context: PromptContextEnvelope,
  prior_prepared: PreparedContext | None,
) -> PreparedContext
```

`ContextControlPlane` 通过构造时注入的 `ContextBudgetHook` 获取预算决策，而不是在 runtime 内硬编码 budget 公式：

```text
ContextBudgetHook.plan(
  request: ContextBudgetRequest,
) -> BudgetPlan | None
```

推荐按现有代码风格落成 `Protocol`，接受 sync / async 实现，并只暴露只读视图：

```text
ContextBudgetRequest
  - turn_id: str
  - attempt_index: int
  - candidates: tuple[BudgetCandidate, ...]
  - transcript_messages: tuple[RuntimeMessage, ...]
  - prompt_context: PromptContextEnvelope
  - private_context: RuntimePrivateContextView
  - provider_hints: ProviderBudgetHints | None
  - prior_plan: BudgetPlan | None
```

```text
BudgetCandidate
  - candidate_id: str
  - tool_use_id: str
  - tool_name: str
  - message_index: int
  - block_index: int
  - is_error: bool
  - content: Any
  - tool_result_summary: ToolResultSummary | None
  - estimated_token_count: int | None
  - serialized_size_bytes: int | None
  - metadata: Mapping[str, Any]

ProviderBudgetHints
  - provider_name: str | None
  - model_name: str | None
  - requested_model_route: str | None
  - invocation_mode: Any | None
  - max_input_tokens: int | None
  - reserved_output_tokens: int | None
  - remaining_input_tokens: int | None
  - extensions: Mapping[str, Any]
```

推荐的决策模型：

```text
BudgetPlan
  - decisions: tuple[BudgetDecision, ...]
  - policy_tag: str | None
  - metadata: Mapping[str, Any]
  - diagnostics: tuple[str, ...]

BudgetDecision
  - candidate_id: str
  - action: inline | summarize | externalize
  - summary_text: str | None
  - reason: str | None
  - artifact_metadata: Mapping[str, Any] | None
```

若未注册 `ContextBudgetHook` 或 hook 返回 `None`，第一阶段默认采用 pass-through 行为，不在 runtime 内自行推导业务预算。

Runtime 对 hook 的 authority 应做硬边界约束：

- hook 只能对已有 `BudgetCandidate.candidate_id` 返回 candidate-local 决策
- hook 不能新增、删除、重排 `tool_result` slot，也不能直接修改 transcript
- hook 返回未知 `candidate_id`、重复决策或非法 action 时，runtime 只忽略非法项并记录 diagnostics
- `summarize` 必须能由 `summary_text` 或现有 `ToolResultSummary` 产出稳定回放内容，否则该项回退为 no-op
- `externalize` 只有在 artifact store 可用时才生效，否则该项回退为 no-op

建议增加显式 failure mode：

```text
ContextBudgetHookFailureMode
  - pass_through
  - fail_prepare
```

默认使用 `pass_through`：

- hook 抛错、超时或返回不可解析 plan 时，runtime 记录 `context_budget_hook_error` diagnostics
- `pass_through` 下保持候选结果原样 inline，继续后续 projection / compaction
- `fail_prepare` 下把该错误提升为结构化 context-preparation failure，再交给 `RecoveryPolicy`

推荐的输出模型：

```text
PreparedContext
  - active_messages: tuple[RuntimeMessage, ...]
  - prompt_context: PromptContextEnvelope
  - private_context_updates: Mapping[str, Any]
  - pressure: ContextPressureLike
  - generation: int
  - effects: tuple[ContextPreparationEffect, ...]
  - requires_sidecar_restart: bool
```

第一阶段建议固定 4 个 pass：

1. `ToolResultBudgetPass`
2. `ContextProjectionPass`
3. `MaterialCompactionPass`
4. `PromptEnvelopeBuild`

其中：

- `ToolResultBudgetPass` 负责收集 tool-result candidates、调用 `ContextBudgetHook`，并执行 hook 返回的 inline / summarize / externalize 决策
- `ContextProjectionPass` 负责 non-destructive active view reduction
- `MaterialCompactionPass` 复用现有 `CompactionManager`
- `PromptEnvelopeBuild` 负责把 active view 和控制面产物组装成 request input

执行顺序上，`ToolResultBudgetPass` 需要先于 projection / compaction：

1. 先收集 replay candidates 并调用 `ContextBudgetHook`
2. 再基于 hook 结果生成新的 active replay payload / spillover refs
3. 若 active view 仍超过后续压力阈值，再进入 projection 与 material compaction

这样 runtime 不负责“怎么算预算”，但仍负责“何时消费 budget decision”。

Why:

- 当前 `CompactionManager` 太窄，不能承载完整的 context shaping。
- 不同业务的 budget 计算方式不同，runtime 需要稳定的调用边界，而不是统一的内建公式。
- Claude Code 的关键不是某个具体 compaction 算法，而是“所有上下文整理都走同一个主循环 join point”。

Alternatives considered:

- 继续把 compaction manager 扩成“大一统 context manager”。拒绝，因为 material compaction 与 non-destructive projection 的语义不同，混在一个 strategy 体系里会混淆 transcript rewrite 边界。
- 复用通用 `HookBus` 做 budget 计算。拒绝，因为 budget 决策要求单一 owner、强类型输入输出和 deterministic merge，不适合 fan-out hook effects。

### 5. 明确区分 `Transcript Truth`、`Active Context View` 和 `Spillover Artifacts`

当前 runtime 在语义上还把“模型看到什么”和“transcript 持久化什么”混得过近。新的边界应当是：

```text
Transcript Truth
  完整会话事实与 material compaction 后的持久化状态

Active Context View
  下一次 provider request 实际看到的消息视图

Spillover Artifacts
  被 budget hook / runtime decision 标记移出 active view、但可被追踪或恢复的 payload
```

这意味着：

- non-destructive `ContextProjectionPass` 不改 transcript
- `MaterialCompactionPass` 可以改 transcript，并产生 boundary/continuation metadata
- `ToolResultBudgetPass` 根据 hook 决策 externalize 的结果进入 spillover artifact store，而 continuation history 中只保留摘要或 reference

实现上建议优先扩展 transcript service，而不是引入新的 memory 子系统：

```text
TranscriptArtifactStore
  - persist_artifact(kind, payload, metadata) -> artifact_ref
  - load_artifact(artifact_ref) -> payload
```

Why:

- large tool results 属于会话连续性，不属于长期记忆。
- 如果 projection 和 material compaction 都继续直接改 transcript，后续 collapse / snip / spillover 很快会互相污染。

Alternatives considered:

- 把 spillover payload 放入 memory manager。拒绝，因为它不符合 memory 的语义边界。
- 让 non-destructive projection 也直接 rewrite transcript。拒绝，因为 resume-safe semantics 会变得不可解释。

### 6. sidecar 失效语义统一绑定到 `context_generation`

当前 sidecar supervisor 只在 applied compaction 时显式 restart，这不足以覆盖 budget hook 驱动的 rewrite、projection rebuild 或 request override。新的规则是：

- 任何改变 `Active Context View` 或 request-shaping envelope 的 pass 都会 bump `context_generation`
- budget hook 的决策集合若改变了任一 replay payload、summary 文本或 artifact ref，也视为 active context change
- sidecar result 必须带 generation
- join 时 generation 不匹配的 sidecar result 必须丢弃
- 若下一次 request 仍需要 sidecar，则按新 generation restart

Why:

- stale sidecar 结果是否可用，取决于 request-shaping input 是否变了，而不是“是否发生了 compaction”。
- generation-aware invalidation 能把 sidecar 生命周期和 main loop state machine 对齐。

Alternatives considered:

- 继续只在 material compaction 后 restart。拒绝，因为 projection/budget-hook-driven rewrite/recovery 重建同样会让 sidecar 失效。

### 7. 将 stop phase / hook outcome 升级为结构化 `StopPhaseOutcome`

当前 `HookDispatchResult.continue_execution: bool` 无法区分：

- 允许 turn 终止
- 继续当前 turn
- 阻塞 session 等待后续输入
- 终止但带失败优先级

建议新增：

```text
StopPhaseOutcome
  - disposition:
      allow_terminal
      continue_same_turn
      block_session
      halt_failure
  - injected_messages: tuple[RuntimeMessage, ...]
  - additional_context: tuple[str, ...]
  - request_override: RequestOverrideState | None
  - matched_hooks: tuple[str, ...]
  - notifications: tuple[str, ...]
```

`HookBus` 仍负责 dispatch，但 stop-phase 的最终裁决交给 `RecoveryPolicy`。

Why:

- 布尔式 `continue_execution` 过于粗糙，无法支持 Claude Code 风格的 stop-hook continuation。
- stop hook 应该表达结构化意图，而不是直接改写 terminal precedence。

Alternatives considered:

- 继续沿用布尔式 continue/block，并在 `engine.py` 做更多特判。拒绝，因为这只会让 stop/recovery 更纠缠。

### 8. 保持 ordered replay，但允许 tool-result slot 使用摘要或 artifact reference

`StreamingToolOrchestrator` 的 replay contract 不变：仍按原始 `tool_use` 顺序回填 `tool_result` slot。变化点在于 slot payload 允许是：

- full result
- summarized result
- stable artifact reference

建议 `tool_result` metadata 增加：

```text
tool_results[*].spillover = {
  externalized: bool,
  artifact_ref: str | null,
  summarized: bool,
  decision_reason: str | null,
  policy_tag: str | null
}
```

Why:

- ordered replay 是 continuation 正确性的基础，不能因为 budget decision 破坏 slot 顺序。
- 摘要化 / externalize 应属于 slot payload 变化，而不是 replay model 变化。

Alternatives considered:

- 预算超限时直接跳过该 `tool_result`。拒绝，因为这会破坏 pairing 与 ordered replay。

### 9. 明确 turn-local state 与 session-resumable metadata 的边界

控制面补齐后，必须明确哪些状态只在当前 turn / attempt 内有效，哪些状态需要跨 session resume 恢复。

建议划分为两类：

```text
Turn-local only
  - RecoveryState.retry_counters
  - pending StopPhaseOutcome
  - PreparedContext.active_messages
  - in-flight context_generation
  - sidecar handles / task refs
  - pending RequestOverrideState after successful request emission

Session-resumable metadata
  - compaction_boundary / compaction_continuation
  - spillover artifact manifest refs
  - blocked / waiting continuation hints
  - observability metadata needed for diagnostics
  - explicit resume_request_override (only when terminal metadata marks it resumable)
```

恢复规则：

- runtime 不持久化 opaque active view snapshot
- session resume 时总是从 transcript truth + resumable metadata 重新构建 `PreparedContext`
- 新 user turn 默认清空上一 turn 的 `RecoveryState`
- `RequestOverrideState` 默认是 one-shot turn-local state；只有 terminal metadata 显式标记 resumable 时，才允许跨 resume 恢复

Why:

- 当前 session 层只显式同步 compaction continuation，控制面补齐后如果不定义边界，resume 会变成半隐式行为。
- 将 active view 直接持久化会让 projection / spillover / compaction 的边界重新混乱。

### 10. 明确 `RecoveryPolicy` 的基线决策矩阵

`RecoveryPolicy` 不只需要“能决策”，还需要一个 bounded decision matrix，避免实现方在每种 terminal 上重新发明分支。

第一阶段建议至少固定以下基线：

```text
context_limit + reducible + not yet compacted
  -> compact_and_retry

output_limit + retry budget remaining + override available
  -> retry_with_override

stop_outcome.continue_same_turn + non-failure attempt
  -> continue_same_turn

stop_outcome.block_session + non-failure attempt
  -> halt with blocked/waiting-class terminal

interrupted / abort / max_turns / tool executor unavailable
  -> halt

non-retryable provider failure
  -> halt
```

该矩阵必须是：

- failure-class first
- bounded by explicit retry counters
- observable in transition metadata
- testable without provider-specific string matching

### 11. 明确 `RequestOverrideState` 的 merge precedence 与生命周期

共享 override state 需要更具体的 contract，否则实现时会重新退回局部变量。

第一阶段建议：

```text
baseline request config
  < skill override
  < stop-phase override
  < recovery override
```

字段级规则：

- `None` 表示 no-op，不表示显式清空
- higher-precedence non-null field wins
- merge 是 field-wise，不是 whole-object replace

生命周期规则：

- override 在下一次 `BUILD_REQUEST` 消费后默认清空
- 若 request 未真正发出，则 override 保持 pending
- 只有 terminal metadata 显式携带 `resume_request_override` 时，override 才允许跨 blocked / waiting resume 保留

Why:

- 当前 skill override 只是 last-writer field merge，无法覆盖 recovery 和 stop hooks 共享写入的场景。
- one-shot consumption 可以避免 override 在后续 unrelated attempts 泄漏。

### 12. 为 `ContextProjectionPass` 定义硬不变量

projection pass 不能只说“non-destructive”，还必须有不能破坏的最低语义边界。

第一阶段建议至少保证：

- 保留全部 system / developer prompt
- 保留最新 user turn 的完整用户输入
- 不打断 `tool_use -> tool_result` pairing
- 不删除 compaction continuation / boundary markers
- 不删除 blocked / waiting continuation 所需的 resume cues
- 不删除 attachment handles、artifact refs 或它们的稳定替代引用

允许变化的只有：

- older assistant / tool payload 的 active-view inclusion 形式
- summary / reference 形式的 replay payload
- projection fragment 的组织方式

Why:

- 如果这些不变量不写死，projection 很容易退化成“按长度裁剪消息”，直接破坏 continuation correctness。

### 13. 明确 spillover artifact lifecycle 与 missing-artifact fallback

artifact store 不只是 `persist/load` 两个接口，还需要生命周期 contract。

第一阶段建议：

```text
ArtifactManifestEntry
  - artifact_ref
  - producing_turn_id
  - kind
  - digest
  - created_at
  - metadata
  - retention_class
```

生命周期规则：

- transcript 或 session metadata 仍引用该 `artifact_ref` 时不得 GC
- 恢复或 replay 时若 artifact 缺失，runtime 不能静默跳过 slot
- 缺失时必须保留 replay slot，并回退为 degraded placeholder / summary plus diagnostics
- retention policy 由 control-plane config 注入，而不是硬编码在 runtime

Why:

- 没有 retention 和 missing-ref fallback，resume-safe spillover 只是名义成立。

### 14. 明确 hook aggregation 的顺序与冲突裁决

当前 hook bus 仍以布尔聚合为主。结构化 stop outcome 上线后，必须定义多 hook 的 deterministic aggregation。

建议：

- hook registration order 成为稳定聚合顺序
- `additional_context` / `notifications` 按顺序 append
- `updated_input` 继续 last-writer-wins
- stop disposition precedence 固定为：

```text
halt_failure
  > block_session
  > continue_same_turn
  > allow_terminal
```

- 多个 hook 的 request override 先按 registration order merge，再交由 runtime-wide override precedence 与 recovery override 合并
- matched hook owners 必须按稳定顺序暴露给 observability metadata

Why:

- 如果 stop-phase 没有 deterministic aggregation，结构化 hook effect 只会把原来的 bool 特判换一种形式重演。

### 15. 明确最小 control-plane observability schema

控制面分层后，排障不能再依赖“看最终 transcript 猜发生了什么”。

第一阶段建议 host-visible metadata 至少包含：

```text
context_preparation
  - context_generation
  - effect_kinds[]
  - projection_kind
  - compaction_applied
  - spillover_refs[]
  - budget_policy_tag
  - diagnostics[]

recovery
  - recovery_action
  - recovery_reason
  - failure_class
  - terminal_reason
  - override_sources[]

hooks
  - stop_disposition
  - matched_hook_owners[]
```

这些字段不要求都成为独立事件，但必须能通过 turn event metadata 或 equivalent diagnostics 稳定获取。

### 16. 明确 control-plane config 的注入点与 precedence

控制面不止有 request override，还会新增 budget hook、projection policy、compaction strategy chain、artifact retention policy 和 recovery config。

建议固定 precedence：

```text
runtime default
  < agent config
  < session / turn override
```

执行语义：

- turn 开始时解析出 resolved control-plane config snapshot
- 该 snapshot 在当前 turn 内保持稳定
- recovery 可以写 request override，但不回写整套 control-plane config

第一阶段至少需要可配置：

- `RecoveryPolicyConfig`
- `ContextBudgetHook` 与 failure mode / timeout
- projection policy
- material compaction strategy chain
- spillover retention policy
- hook aggregation policy

## Risks / Trade-offs

- **[状态对象增多]** recovery state、prepared context、stop outcome、artifact refs 会增加模型复杂度。 → Mitigation: 让这些对象分别归属于 control plane 模块，而不是继续散在 `engine.py`。
- **[transcript 与 active view 分离后，调试成本会上升]** 同一轮里“存储事实”和“模型所见”不再完全相同。 → Mitigation: 在 turn event metadata 中暴露 `context_generation`、projection/compaction effects 和 artifact refs。
- **[hook 作者的语义预期会变化]** 旧 hook 可能只理解 continue/block。 → Mitigation: 提供兼容适配，将旧布尔式 effect 自动映射为新 `StopPhaseOutcome`。
- **[provider classification 可能不完整]** 第一阶段不同 provider 未必都能给出高质量 failure classification。 → Mitigation: 允许 unknown classification 默认 `halt`，并在 metadata 中保留原始 provider fields。
- **[spillover artifact store 需要额外持久化路径]** 会给 transcript service 增加少量接口。 → Mitigation: 第一阶段只支持本地 transcript companion store，不引入外部依赖。
- **[`ContextBudgetHook` 质量可能不稳定]** 业务自定义 hook 可能返回非法决策、超时或直接抛错。 → Mitigation: runtime 做严格 plan validation，并通过 `pass_through | fail_prepare` failure mode 控制退化路径。
- **[resume 边界定义不清会导致状态泄漏]** turn-local state 若被错误持久化，blocked / waiting / resumed turn 的行为会不可预测。 → Mitigation: 只持久化 resumable metadata，禁止持久化 opaque active view 与 in-flight loop state。
- **[projection invariants 若未固定会破坏 continuation correctness]** active-view reduction 容易退化成按长度删除消息。 → Mitigation: 将 latest-user、tool pairing、continuation marker、attachments/artifact refs 列为硬不变量。
- **[observability 不足会放大排障成本]** transcript truth 与 active view 分离后，单看 transcript 无法解释 runtime 的实际决策。 → Mitigation: 暴露最小 control-plane metadata schema。

## Migration Plan

1. 新增 `RecoveryPolicy`、`RecoveryDecision`、`RecoveryState` 与通用 `RequestOverrideState`，并明确决策矩阵、source precedence 与 one-shot lifecycle。
2. 新增 `ContextControlPlane` 与 `PreparedContext`，先以 no-op / pass-through pipeline 接入 `COMPACT_OR_REBUILD`，同时固定 projection invariants 与 config snapshot semantics。
3. 接入 `ContextBudgetHook`、request / decision models 与 `ToolResultBudgetPass`，实现 plan validation 与 failure fallback，再实现 transcript companion artifact store、artifact manifest 与 missing-ref fallback。
4. 将现有 `CompactionManager` 作为 `MaterialCompactionPass` 接入新的 context pipeline，保留现有 material compaction 语义，并让 session-resumable metadata 可恢复 `PreparedContext`。
5. 为 sidecar supervisor 加入 `context_generation` invalidation / restart 规则，并将 context-preparation / recovery effects 暴露为 canonical observability metadata。
6. 将 stop hook dispatch 结果适配到 `StopPhaseOutcome`，补齐 deterministic aggregation / precedence，再由 `RecoveryPolicy` 统一裁决 continue / block / halt。
7. 扩展 tests，覆盖 recovery action matrix、override precedence、projection invariants、spillover lifecycle、sidecar invalidation、observability schema 和 session / child-run status projection。

Rollback strategy:

- `ContextControlPlane` 可保留为 pass-through 实现，逐步启用单个 pass。
- `RecoveryPolicy` 可在 provider classification 缺失时退化为当前 `halt / continue_same_turn` 逻辑。
- spillover artifact store 可通过 feature flag 退回纯 inline tool results，而不回退新的 control-plane 边界。

## Open Questions

- spillover artifact store 应作为 transcript service 子接口实现，还是独立 session artifact service？
- `PromptContextEnvelope` 是否需要新增 `projection_fragments`，还是继续复用 `compaction_fragments` 但在 metadata 中区分来源？
- `HookBus.collect()` 是否应继续承担 pre-turn hook context sidecar 职责，还是在本 change 中直接拆出独立 `HookContextService`？
