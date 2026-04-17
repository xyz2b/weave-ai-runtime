## Delivery Strategy

memory v2 不建议一次性全量落地。推荐按三期交付：

- **Phase 1 / MVP**: 先落 `LongTermMemory + AgentNamespaceMemory + SessionMemory`，并把 retrieval / extraction 跑通为“确定性可用”的最小闭环。
- **Phase 2 / Hybrid Upgrade**: 在 MVP 稳定后补 optional embedding、optional LLM rerank、后台 extraction worker 与 ownership/provenance 完整语义。
- **Phase 3 / Slow Consolidation**: 最后补 `ConsolidationMemory`、cadence/locks/checkpoints、完整 config surface 与 observability。

交付原则：

- 先把层次边界做稳，再补更聪明的策略。
- 先把 deterministic path 做稳，再补模型增强路径。
- 先让 memory runtime 在单 session 和 delegated execution 下正确，再扩到跨 session consolidation。

## Phase 1 / MVP

### Goal

交付一个可运行的 layered memory MVP，具备：

- durable shared long-term memory
- agent namespace memory
- session continuity memory
- deterministic retrieval
- deterministic obvious-fact extraction

本阶段明确不包含：

- embedding shortlist
- LLM rerank
- background synthesis worker
- consolidation worker

### 1. Foundations and Contracts

- [x] 1.1 将现有 `MemoryManager` 重构为 `LongTermMemory` 基础层，保留 `MEMORY.md`、scope resolution 与 path guard 语义
- [x] 1.2 固化 canonical artifact layout，并在 runtime 中建立 `documents/`、`agents/`、`sessions/` 三类路径 contract
- [x] 1.3 固化 manifest envelope、memory artifact frontmatter 与 required/optional field vocabulary
- [x] 1.4 为 memory v2 基础路径增加 schema/validation helpers，确保坏条目降级而不是直接拖垮 retrieval

### 2. Deterministic Long-Term Retrieval

- [x] 2.1 实现 `long-term-manifest.json` 与 `agent-manifest.json` 的生成和刷新
- [x] 2.2 实现 manifest/header prefilter 与 deterministic lexical shortlist
- [x] 2.3 实现 retrieval scoring 的 `hard_filter + boost + decay` 最小可用路径
- [x] 2.4 实现 per-layer budgeted materialization，优先支持 `agent namespace + shared long-term + session summary`
- [x] 2.5 为 retrieval trace 增加最小 debug payload，至少暴露 applied filters、selected doc ids 和 budget decisions

### 3. Agent Namespace Memory

- [x] 3.1 实现 `agents/<agent-name>/` namespace resolution，确保 namespace 运行在 `user/project/local` 边界之内
- [x] 3.2 将 delegated execution policy 与 namespace-aware retrieval precedence 接通
- [x] 3.3 实现 agent namespace durable writes 和 namespace manifest refresh
- [x] 3.4 为 policy ceiling、cross-namespace fallback 和 dedupe 增加测试

### 4. Session Memory

- [x] 4.1 实现 `session-summary.md`、`open-threads.md`、`metadata.json` 的 artifact lifecycle
- [x] 4.2 实现 session summary refresh triggers 的 MVP 版本
  - token/character growth threshold
  - turn threshold
  - tool call threshold
- [x] 4.3 将 `SessionMemory` 注入 turn preparation，并与 compaction summary 明确区分
- [x] 4.4 实现 open threads 的 `thread-key` 生成和 `upsert_by_thread_key` 行为
- [x] 4.5 为 resume / blocked / compaction-after-refresh 等场景增加 integration tests

### 5. Deterministic Extraction MVP

- [x] 5.1 落地一版最小 fact taxonomy classifier，至少覆盖：
  - `preference`
  - `project_convention`
  - `workflow_command`
  - `agent_workflow`
  - `session_continuity`
  - `session_thread`
  - `transient_task`
  - `sensitive_value`
- [x] 5.2 实现 obvious-fact rules，并按 taxonomy 路由到 shared / agent / session targets
- [x] 5.3 对 `transient_task`、`sensitive_value`、明显噪音类实现 `do_not_persist`
- [x] 5.4 将 `memory_update_owned`、manifest refresh 与 durable write receipts 打通
- [x] 5.5 为 routing matrix 的核心路径增加 tests，确保分类决定能稳定落到目标层

### Phase 1 Exit Criteria

- [x] 1.E1 `main-router` 在同一 session 内能稳定消费 `SessionMemory`
- [x] 1.E2 delegated agent 能稳定消费并写入自身 namespace memory，且不越过 parent ceiling
- [x] 1.E3 durable long-term memory 的 deterministic retrieval 在无 embedding / 无 rerank 下可工作
- [x] 1.E4 obvious-fact extraction 能正确区分 shared / agent / session / do-not-persist 四类目标
- [x] 1.E5 compaction 发生后，session continuity 仍由 `SessionMemory` 保持，而不是错误依赖 compaction summary

## Phase 2 / Hybrid Upgrade

### Goal

在 Phase 1 的 deterministic 基础上，增加混合式增强能力：

- optional embedding shortlist
- optional LLM rerank
- background restricted extraction worker
- 完整 provenance / ownership / conflict policy

### 6. Hybrid Retrieval Enhancements

- [x] 6.1 增加 optional embedding shortlist provider interface
- [x] 6.2 增加 lexical 与 embedding divergence detection
- [x] 6.3 实现 optional LLM rerank orchestration 和 trigger policy
- [x] 6.4 为 contested entries、stale decay、confidence threshold 增加更细粒度 scoring controls
- [x] 6.5 为 rerank skip / rerank success / rerank budget denied 三类路径增加 tests

### 7. Background Extraction Worker

- [x] 7.1 实现后台受限 extraction worker，专门处理高价值 synthesis
- [x] 7.2 把 `topic_memory`、multi-turn preference inference、agent durable note synthesis 接到 worker
- [x] 7.3 增加 extraction job queue、coalescing、de-dup 和 trailing-run merge
- [x] 7.4 实现 provenance、confidence、conflict_key 和 merge-safe durable writes
- [x] 7.5 增加“主线程 turn 完成后异步抽取”的 integration tests

### 8. Ownership, Conflict, and Audit

- [ ] 8.1 实现 contested fact staging 和 guarded overwrite 规则
- [ ] 8.2 实现 retention / merge policy vocabulary 在 runtime 中的最小执行器
- [ ] 8.3 暴露 extraction provenance、retrieval decision trace 和 write receipts 到 host diagnostics
- [ ] 8.4 为 contested overwrite、superseded artifact、audit trace consistency 增加 tests

### Phase 2 Exit Criteria

- [x] 2.E1 runtime 在配置 embedding/rerank 时可增强召回，不配置时仍保持稳定降级
- [x] 2.E2 高价值 synthesis 不再依赖主线程同步完成
- [ ] 2.E3 contested / superseded / stale 条目在 retrieval 和 extraction 中都有稳定行为
- [ ] 2.E4 host 能看到足够的 diagnostics 来解释“为什么写入/为什么召回”

## Phase 3 / Slow Consolidation

### Goal

补齐跨 session 慢整合层：

- `ConsolidationMemory`
- cadence / locks / checkpoints
- topic/preference/convention synthesis
- 完整 user config surface 和 rollout-safe observability

### 9. Consolidation Runtime

- [ ] 9.1 实现 `consolidation-manifest.json`、run checkpoints、logs 和 staging artifacts
- [ ] 9.2 实现 consolidation cadence policy
  - min closed sessions
  - min hours since last run
  - backlog threshold
- [ ] 9.3 实现 consolidation lock，避免并发 background runs
- [ ] 9.4 从 closed-session summaries 与 durable memory deltas 生成 topic/preference/convention proposals
- [ ] 9.5 将 consolidation outputs merge 回 `LongTermMemory`

### 10. Full Config Surface

- [ ] 10.1 固化声明式 memory config schema，覆盖 retrieval/extraction/session/consolidation knobs
- [ ] 10.2 把 taxonomy selector、routing override、preferred tags、never-capture categories 接到 config surface
- [ ] 10.3 为 invalid config、unsafe override 和 partial config fallback 增加 tests

### 11. Operational Hardening

- [ ] 11.1 增加 multi-session end-to-end tests，覆盖 session close -> consolidation backlog -> durable topic write
- [ ] 11.2 增加 rollback-safe behavior，确保 consolidation 中断不会破坏已有 durable memory
- [ ] 11.3 补充中文文档，解释 layered model、hybrid policy、config surface 与 host diagnostics
- [ ] 11.4 对 Phase 1/2 功能做回归验证，确保 consolidation 引入后不回退单 session correctness

### Phase 3 Exit Criteria

- [ ] 3.E1 多 session 结束后能稳定产出 topic/preference/convention consolidations
- [ ] 3.E2 consolidation 失败、重试、锁冲突都不会破坏已有 durable memory
- [ ] 3.E3 user-config surface 足以控制常见策略，而不需要任意可执行 hooks
- [ ] 3.E4 整套 memory v2 在单 session、delegated agent、long session、multi-session 四类场景下均有稳定 contract

## Dependency Notes

- `SessionMemory` 可以在没有 background worker 的情况下先以 deterministic summarizer 交付。
- `AgentNamespaceMemory` 必须早于 hybrid rerank 落地，否则 retrieval precedence 无法稳定。
- `ConsolidationMemory` 必须晚于 fact taxonomy、routing matrix 和 provenance，否则输出不可控。
- config surface 应在核心 runtime 行为稳定后接入，避免把未定型内部语义过早暴露成兼容承诺。

## Suggested Implementation Order

推荐的实际落地顺序：

1. Path/layout/schema helpers
2. `LongTermMemory` refactor
3. `AgentNamespaceMemory`
4. `SessionMemory`
5. deterministic extraction + routing
6. deterministic retrieval trace + budgets
7. optional embedding / rerank
8. background extraction worker
9. `ConsolidationMemory`
10. config surface + docs + full regression
