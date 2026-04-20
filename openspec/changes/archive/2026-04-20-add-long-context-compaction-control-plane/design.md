## Context

参考实现的 compaction 不是附属 feature，而是主循环的一部分。它决定在上下文压力下如何继续会话、如何保留摘要与边界、以及 transcript 在压缩后的 resume 行为。当前 runtime 对这部分几乎没有显式建模，因此长会话仍然缺少稳定语义。

与 memory 不同，compaction 的核心不是“存什么”，而是“在 turn 继续之前，runtime 如何安全地改变上下文并保持 continuation contract”。

## Goals / Non-Goals

**Goals:**

- 引入统一的 `CompactionManager` 与策略边界，把 long-context control plane 直接纳入 runtime 主流程。
- 在 provider request 前根据上下文压力或策略要求执行 compaction，而不是依赖散落的 truncation helper。
- 让 compaction 返回结构化结果，包含 compacted context、summary 与 boundary metadata。
- 保证 compaction 之后的 transcript、resume 与 continuation 语义可验证。

**Non-Goals:**

- 不要求第一版逐项复刻参考实现的每个 compaction 算法细节。
- 不在本变更中实现 memory retrieval/extraction。
- 不把 compaction 简化成单纯的 token 裁剪工具函数。

## Decisions

### 1. 使用 `CompactionManager` 作为统一入口

runtime 将新增 `CompactionManager`，由它决定何时执行 compaction、采用何种策略、以及如何返回 continuation metadata。

Why:

- 参考实现的 compaction 是主循环的一部分，不应散落在多个 request-prep helper 中。
- manager 能把策略选择、结果建模与 transcript integration 收敛成一个稳定 contract。

Alternatives considered:

- 继续在 request preparation 中内联截断逻辑。拒绝，因为这无法表达 boundary semantics 与 resume-safe continuation。

### 2. compaction 结果必须是结构化 continuation artifact

compaction 不直接“修改 prompt 完事”，而是产出 `CompactionResult`，至少包含：

- compacted messages 或 fragments
- summary / carry-forward context
- boundary metadata
- continuation directives

Why:

- 只有结构化结果才能安全接入 transcript、resume 与 future compact hooks。
- 这与参考实现的 long-context control plane 更一致。

### 3. 先对齐 orchestration contract，再逐步加细策略

第一版会提供 ordered strategy interface，但优先锁定：

- 何时触发 compaction
- compaction 前后的边界
- 如何恢复 continuation

Why:

- 对 framework 而言，先把控制面契约做稳比提前复制具体算法更重要。

Alternatives considered:

- 先直接复制复杂 compaction 算法。拒绝，因为在 orchestration contract 还不稳定时会放大实现噪声。

### 4. transcript 与 session resume 必须消费 compaction metadata

session 与 transcript flow 不能把 compaction 当成未跟踪 prompt mutation，而必须保存与消费 compaction metadata。

Why:

- 否则 resume 后的上下文与当时 provider 看到的上下文会脱节。
- 这正是 long-context control plane 最核心的 runtime 语义。

## Risks / Trade-offs

- **[语义复杂]** compaction 牵涉 turn preparation、session persistence 与 resume。 → Mitigation: 把 boundary/summary/continuation 明确建模成结果对象。
- **[算法与 contract 分离]** 第一版可能先有 contract、后补细算法。 → Mitigation: 通过 fixtures 与 transcript tests 锁定外部语义。
- **[触发策略不稳定]** 上下文压力判断若设计不清，会导致 compaction 触发不可预测。 → Mitigation: 明确 ordered strategy interface 与 deterministic tests。

## Migration Plan

1. 新增 `CompactionManager`、compaction models 与 ordered strategy interface。
2. 将 compaction manager 接入 provider request 之前的 turn preparation。
3. 让 transcript/session flow 持久化 compaction boundary 与 summary metadata。
4. 将 compaction continuation 行为接入 resume path 与 background execution。
5. 增加 long-session、boundary、resume-safe continuation 与 strategy orchestration 的测试。

Rollback strategy:

- 若统一 compaction boundary 暂时不成立，可回退到 no-op manager，同时保留 structured result contract，避免再次退化成 scattered truncation helpers。

## Open Questions

- 第一版是否需要区分 proactive compaction 与 reactive compaction，还是先通过单一 ordered strategy interface 建立 contract？
- `PreCompact` / `PostCompact` hook phases 是否在本阶段直接接入，还是在 interactive hook bus 稳定后补充？
