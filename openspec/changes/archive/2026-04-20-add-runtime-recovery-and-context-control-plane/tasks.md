## 1. Recovery Contracts

- [x] 1.1 在 `src/runtime/contracts.py` 或 `src/runtime/turn_engine/` 新增 provider-neutral failure classification 模型，统一表示 `context_limit`、`output_limit`、`media_limit`、`provider_overload`、`auth_error`、`internal_error` 等分类
- [x] 1.2 新增 `RecoveryState` dataclass，显式承载 retry counters、prior compaction attempts、active failure class 与 pending override snapshot
- [x] 1.3 新增 `RecoveryDecision` dataclass，覆盖 `halt`、`continue_same_turn`、`rebuild_request`、`compact_and_retry`、`retry_with_override` 的 action、reason、metadata 与 injected messages
- [x] 1.4 新增 `StopPhaseOutcome` dataclass，替代 stop 阶段只靠 `continue_execution: bool` 的表达
- [x] 1.5 新增通用 `RequestOverrideState` 及其 serialize / coerce helper，覆盖 model、effort、model_route、invocation_mode、max_output_tokens 等字段
- [x] 1.6 为现有 `SkillRequestOverrideState` 提供兼容 adapter，使旧 skill 输出仍能映射到新的 `RequestOverrideState`
- [x] 1.7 定义 resumable continuation metadata contract，区分 turn-local recovery state 与允许跨 blocked / waiting resume 恢复的 override / continuation 字段

## 2. Recovery Policy And Override Lifecycle

- [x] 2.1 从 `src/runtime/turn_engine/engine.py` 提取 attempt outcome normalization helper，把 provider stop reason / error / abort 转成标准化 recovery input
- [x] 2.2 实现 `RecoveryPolicy` 骨架接口，使 `RECOVERY_DECISION` 不再直接依赖 `engine.py` 的本地 if/else 分支
- [x] 2.3 实现 context-limit / output-limit / media-limit / non-retryable provider failure 的基线决策矩阵
- [x] 2.4 实现 interrupted / aborted / max-turns / tool executor unavailable 的 halt-class 决策矩阵
- [x] 2.5 实现 failure precedence 规则，确保 stop-hook block / continue 不能重写 failure-class terminal
- [x] 2.6 实现 `RequestOverrideState` 的 precedence 规则，固定 runtime baseline < skill < stop-phase < recovery 的字段级 merge
- [x] 2.7 实现 override 的 one-shot consumption 规则，使 override 在下一次 request 成功发出后默认清空
- [x] 2.8 实现 resumable override snapshot 规则，仅在 terminal metadata 显式标记时允许 blocked / waiting resume 继续使用 override
- [x] 2.9 将 recovery action、failure class、override source 与 retry counters 接入 `TurnTransition` / `TurnTerminal` metadata

## 3. Context Control Plane Foundations

- [x] 3.1 新增 `PreparedContext` dataclass，承载 active messages、prompt context、private context updates、generation、effects 与 sidecar restart 标记
- [x] 3.2 新增 `ContextPreparationEffect` 模型，明确 projection、compaction、spillover、budget decision、sidecar restart 等 effect kind
- [x] 3.3 新增 `ContextControlPlane` 接口与默认实现骨架，支持 ordered pass pipeline
- [x] 3.4 新增 `ContextBudgetRequest`、`BudgetCandidate`、`ProviderBudgetHints`、`BudgetPlan`、`BudgetDecision` 与 `ContextBudgetHookFailureMode` 模型
- [x] 3.5 将 `ContextBudgetHook` 落成 `Protocol`，兼容 sync / async 实现，并限制为 candidate-local downgrade 决策
- [x] 3.6 实现 control-plane config resolution，解析 runtime default、agent config、session / turn override 的 precedence 并生成 turn-scoped snapshot
- [x] 3.7 让 `ContextControlPlane` 在 turn 开始时固定 resolved config snapshot，避免 mid-turn 动态改整套 control-plane config

## 4. Budget Pass, Projection, And Compaction

- [x] 4.1 实现 `ToolResultBudgetPass` 的 candidate collector，从当前 transcript / replay candidates 中提取 tool-result payload、summary、size/token hints 与 metadata
- [x] 4.2 实现 budget-hook invocation adapter，把 `ContextBudgetRequest` 发给用户实现的 `ContextBudgetHook`
- [x] 4.3 实现 budget plan validation，覆盖 unknown candidate、duplicate decision、illegal action、invalid summary / externalize request
- [x] 4.4 实现 budget-hook error / timeout fallback，支持 `pass_through` 与 `fail_prepare` 两种 failure mode
- [x] 4.5 实现 projection invariants checker，显式保护 system/developer prompt、latest user turn、tool pairing、continuation markers、attachment / artifact handles
- [x] 4.6 实现 `ContextProjectionPass` 的最小版本，支持 non-destructive active-view reduction 且不破坏 projection invariants
- [x] 4.7 将现有 `CompactionManager` 包装为 `MaterialCompactionPass`，统一接入 `ContextControlPlane`
- [x] 4.8 将 compaction boundary / continuation / summary metadata 写入 `PreparedContext.effects` 与 `PromptContextEnvelope`
- [x] 4.9 实现 prompt-envelope build step，使 override、projection、compaction、spillover metadata 在一个入口合并到 request build
- [x] 4.10 基于 effect diff 实现 `context_generation` bump / reuse 规则，只有 active view 或 request-shaping envelope 变化时才更新 generation

## 5. Spillover Artifact Store And Replay

- [x] 5.1 在 `src/runtime/session_runtime/transcript.py` 或相邻模块新增 transcript artifact store interface，支持 persist / load spillover payload
- [x] 5.2 为 file-backed transcript store 增加 spillover artifact persistence 实现，定义 companion manifest 或等价落盘格式
- [x] 5.3 为 in-memory transcript store 增加 spillover artifact store 实现，支撑单测和集成测试
- [x] 5.4 新增 `ArtifactManifestEntry` 或等价 manifest metadata，至少记录 `artifact_ref`、producing turn、kind、digest、created_at、retention class
- [x] 5.5 实现“被 transcript 或 session metadata 引用时不得 GC”的最小 retention 规则
- [x] 5.6 扩展 `tool_result` metadata，使 replay slot 能携带 `externalized`、`summarized`、`artifact_ref`、decision reason 与 `policy_tag`
- [x] 5.7 更新 `src/runtime/tool_orchestration.py`，使 summarized / externalized 结果仍按原始 `tool_use` 顺序回填
- [x] 5.8 更新 `src/runtime/tool_runtime.py` 与相关 lifecycle 代码，保证 replay slot payload 可使用 full / summary / artifact-ref 三种形式
- [x] 5.9 实现 missing artifact / unresolved spillover ref 的 degraded placeholder + diagnostics fallback，禁止静默丢失 replay slot
- [x] 5.10 打通 resume 路径，使 session 恢复后可重新解析 spillover refs、compaction continuation 与其他 resumable context metadata

## 6. Hooks, Main Loop, And Session Integration

- [x] 6.1 在 `src/runtime/turn_engine/engine.py` 中把 `COMPACT_OR_REBUILD` 改为显式调用 `ContextControlPlane.prepare(...)`
- [x] 6.2 在 `src/runtime/turn_engine/engine.py` 中把 `RECOVERY_DECISION` 改为显式调用 `RecoveryPolicy.evaluate(...)`
- [x] 6.3 用共享 `RequestOverrideState` 替换当前 skill-only override flow，使 `BUILD_REQUEST`、tool outcome、stop hooks 和 recovery 共用一套 override surface
- [x] 6.4 升级 `src/runtime/hooks/bus.py` 的 effect aggregation，使 `additional_context` / `notifications` 按 registration order 稳定聚合
- [x] 6.5 在 `src/runtime/hooks/bus.py` 中实现 stop disposition precedence，固定 `halt_failure > block_session > continue_same_turn > allow_terminal`
- [x] 6.6 将 stop-hook 聚合结果投影为 `StopPhaseOutcome`，并把 hook-level override 先在 hook 侧聚合，再交给 runtime-wide override merge
- [x] 6.7 将 sidecar supervisor 的重启 / 丢弃规则绑定到 `context_generation`，覆盖 projection、budget rewrite、compaction 与 recovery rebuild
- [x] 6.8 更新 `src/runtime/session_runtime/controller.py`，把 compaction continuation、spillover refs、resumable override snapshot 等写入 session metadata
- [x] 6.9 更新 session resume 入口，使恢复时从 transcript truth + session-resumable metadata 重建 prepared context，而不是恢复 opaque active view
- [x] 6.10 为 host-visible turn events 定义 canonical control-plane metadata schema，至少包含 context generation、effect kinds、recovery action、failure class、policy tag、matched hook owners 与 override sources
- [x] 6.11 更新 child-run projection 与 `TurnResult` 汇总逻辑，使 recovery / stop / context effects 成为 status 与 diagnostics 的 authoritative 输入

## 7. Verification

- [x] 7.1 增加 recovery classification tests，验证 provider-neutral failure classification 不依赖 provider-specific string matching
- [x] 7.2 增加 recovery policy matrix tests，覆盖 context-limit、output-limit、media-limit、interrupted、max-turns、tool infra unavailable 与 non-retryable failure
- [x] 7.3 增加 override precedence tests，验证 skill / stop / recovery 的字段级 merge 与 one-shot consumption
- [x] 7.4 增加 resumable override / recovery boundary tests，验证新 user turn 不继承旧 recovery state，blocked / waiting resume 仅恢复显式 metadata
- [x] 7.5 增加 `ContextBudgetHook` request-shape tests，验证 candidates、provider hints、prior plan 与 private-context view 都被正确提供
- [x] 7.6 增加 budget plan validation tests，覆盖 unknown candidate、duplicate decision、illegal action、invalid summary / externalize 请求
- [x] 7.7 增加 budget-hook failure mode tests，覆盖 timeout / exception 下的 `pass_through` 与 `fail_prepare`
- [x] 7.8 增加 projection invariant tests，验证 latest user turn、tool pairing、continuation markers、attachments / artifact handles 不被破坏
- [x] 7.9 增加 `context_generation` tests，验证 projection、spillover rewrite、compaction 与 request rebuild 下的 bump / reuse 规则
- [x] 7.10 增加 material compaction integration tests，验证 compaction result 被正确转成 prepared-context effects 与 prompt envelope metadata
- [x] 7.11 增加 artifact manifest / retention tests，验证被引用 artifact 不会过早清理
- [x] 7.12 增加 ordered replay tests，验证 summarized / externalized tool result 仍保持原始 slot 顺序
- [x] 7.13 增加 missing-artifact fallback tests，验证 degraded placeholder + diagnostics 不会丢失 replay slot
- [x] 7.14 增加 stop-hook aggregation tests，验证 registration-order aggregation、disposition precedence 与 hook-level override merge
- [x] 7.15 增加 session integration tests，验证 session metadata 持久化与 resume 后 prepared-context rebuild 正常
- [x] 7.16 增加 child-run / session status projection tests，验证 blocked / interrupted / failure-class outcome 不被错误归类
- [x] 7.17 增加 observability schema tests，验证 host-visible metadata 稳定包含 context generation、effect summary、recovery reason、policy tag 与 override sources
