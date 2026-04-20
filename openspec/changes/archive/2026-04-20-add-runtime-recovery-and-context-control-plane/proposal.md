## Why

当前 runtime 已经具备显式的 turn 状态机、attempt-final / turn-final 分离和 streaming tool orchestration，但 `COMPACT_OR_REBUILD` 与 `RECOVERY_DECISION` 仍然只完成了骨架。恢复路径、tool-result 增长控制、active context 投影、sidecar 失效重跑以及 stop-phase continuation 语义还没有被收敛为正式控制面，长会话和复杂 provider 行为仍会退回到分散判断与简化摘要压缩。

现在需要在不推翻 `SessionController -> TurnEngine -> StreamingToolOrchestrator` 分层的前提下，把“恢复”和“上下文整形”补成 runtime 自己拥有的可观察 contract，这样后续 prompt-too-long、output-limit、tool-result spillover、hook-driven continuation 和 resume-safe context reduction 才能继续演进而不把主循环重新打散。

## What Changes

- 引入 turn-scoped `RecoveryPolicy`，把 provider/model outcome 分类、恢复状态、request override 和 terminal precedence 收敛成统一决策面，而不是散落在 `engine.py` 的局部分支里。
- 引入 `ContextControlPlane`，在每次 provider request 前统一构造 active context view，覆盖 budget hook 调用、tool-result spillover control、context projection、material compaction、prompt envelope build 和 sidecar invalidation。
- 区分 transcript truth 与 active context view，让 non-destructive context projection 不再依赖 transcript rewrite，同时保留 material compaction 的 resume-safe continuation 语义。
- 把 skill-only request override 泛化为 runtime 通用 request override，使 recovery 能显式驱动 model/route/output-cap 的 retry，而不是只支持 skill 注入。
- 将 stop phase / hook outcome 升级为结构化 continuation contract，允许 hooks 产出 continue, block, request override, injected messages 等效果，再由 recovery policy 统一裁决。
- 为 tool-result budget 引入可插拔 `ContextBudgetHook`，由接入方决定如何计算预算以及何时 inline、summarize 或 externalize，runtime 只负责调用 hook 并执行其决策。
- 明确 `ContextBudgetHook` 的结构化输入、允许返回的 candidate-local 决策以及 error / timeout fallback 语义，避免 runtime 重新内建业务特定预算逻辑。
- 保持 ordered tool-result replay 语义，但允许 tool results 在 budget hook 判定需要降载时被摘要化或 externalize，并通过稳定 artifact/reference metadata 回填 continuation history。
- 为 memory / hook sidecar 增加 generation-aware invalidation 语义，使 compaction、projection、budget hook 驱动的 rewrite 或 recovery 重建后的 stale sidecar 结果不会继续污染下一次 request。

## Supplementary Closure

为避免实现阶段再次退回 ad-hoc 分支，这次 proposal 额外把下面 8 个闭合项写成正式 contract：

- 明确 turn-local state 与 session-resumable metadata 的边界，避免 turn 内恢复逻辑在 resume 后丢失或错误复用。
- 明确 `RecoveryPolicy` 的决策矩阵，覆盖 interrupted、max-turns、tool infra unavailable、provider failure、stop continuation 等非 happy-path 分支。
- 明确 `RequestOverrideState` 的 source precedence、字段级 merge 语义和 one-shot consumption 生命周期。
- 明确 `ContextProjectionPass` 的不变量，禁止破坏 system/developer prompt、最新 user turn、tool pairing、continuation markers 和 attachment/artifact handles。
- 明确 spillover artifact 的 manifest、retention、missing-artifact fallback 和 resume-safe replay 语义。
- 明确多个 hooks 同时返回结构化效果时的聚合顺序、冲突裁决和 stop disposition precedence。
- 明确最小 control-plane observability schema，使 host / transcript / diagnostics 能稳定看到 context generation、effect summary、policy tag、recovery reason 和 override source。
- 明确 control-plane config 的注入点与 precedence，覆盖 runtime default、agent override 和 session/turn override 的解析顺序。

## Capabilities

### New Capabilities

- `runtime-recovery-control-plane`: 定义 turn-scoped recovery policy、failure classification、recovery state、request override 与 terminal precedence contract。
- `runtime-context-control-plane`: 定义 active context view preparation，包括 budget hook contract / fallback、tool-result spillover control、context projection、material compaction、prompt build 与 sidecar invalidation。

### Modified Capabilities

- `runtime-main-loop-state-machine`: 扩展 main loop，使 `COMPACT_OR_REBUILD` 和 `RECOVERY_DECISION` phase 显式委托给 context control plane 和 recovery policy。
- `runtime-compaction-manager`: 将 compaction manager 收敛为 broader context pipeline 中的 material compaction stage，并明确与 projection / spillover 的职责边界。
- `streaming-tool-orchestration`: 保持 ordered replay 和 lifecycle 语义，同时允许被 budget hook 决策降载的 tool results 使用摘要或 artifact reference 回填。
- `runtime-hook-bus`: 扩展 stop-phase hook effects，使其能够返回结构化 continuation outcome，而不只是布尔式 continue/block 信号。

## Impact

- 影响 `src/runtime/turn_engine/`、`src/runtime/session_runtime/`、`src/runtime/compaction/`、`src/runtime/tool_runtime.py`、`src/runtime/tool_orchestration.py`、`src/runtime/hooks/` 与 `src/runtime/contracts.py` 的主循环与上下文边界。
- 影响 turn-scoped metadata、session-resumable continuation metadata、request shaping、compaction continuation、tool-result replay metadata 与 sidecar restart semantics。
- 影响 child-run / session status projection，因为新的 recovery 和 terminal metadata 会成为外围状态投影的 authoritative 输入。
- 为后续 provider fallback、reactive compact、context collapse、long-session spillover、resume-safe continuation 和 AI-driven implementation 留出稳定的实现边界。
