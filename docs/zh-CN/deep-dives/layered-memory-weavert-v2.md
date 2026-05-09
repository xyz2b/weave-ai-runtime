# WeaveRT 分层 Memory Runtime

> 文档说明：这是 memory 细节的 deep-dive 参考。主路径请先读 `docs/zh-CN/concepts/memory-model.md`；配置与诊断查询见 `docs/zh-CN/reference/memory-configuration.md`；更大的持久化边界见 `docs/zh-CN/architecture/persistence-and-state.md`。

## 对应主文档

- Memory concepts -> `docs/zh-CN/concepts/memory-model.md`
- Memory configuration quick reference -> `docs/zh-CN/reference/memory-configuration.md`
- Persistence boundary -> `docs/zh-CN/architecture/persistence-and-state.md`

## 1. 层级模型

核心区分：

- session continuity 不等于 shared long-term memory
- consolidation 不只是另一个 prompt-time retrieval layer

## 2. Hybrid policy

### 2.1 Retrieval

典型策略仍是 deterministic first、enhanced second：先做清晰、可检查的筛选，再叠加 embedding 或 rerank。

### 2.2 Extraction

- 明显事实可在主线程捕获
- 高价值综合可放到后台
- consolidation 可把多个 session 的有用结果合并回共享 durable memory

## 3. 声明式配置表面

配置来源：

- `.weavert/memory/config.yaml`
- `.weavert/memory/config.yml`
- `RuntimeConfig.memory_config`

主要配置块：

- retrieval
- extraction
- session memory
- consolidation

## 4. 安全边界

- scope-boundary safety
- guarded memory roots
- secret 与 privacy baselines
- provenance recording
- rollback-safe consolidation writes

## 5. Consolidation 所有权

Consolidation 负责：

- 观察 closed-session backlog
- stage 与 checkpoint merge work
- 把有用提案合并回共享 durable memory
- 保留足够日志与 manifests 以支持恢复和检查

典型工件：

- checkpoints
- staging records
- run logs
- 一个跟踪 backlog、locks 与 recent run state 的 consolidation manifest

Consolidation 可以更新共享 durable memory，但必须通过显式 manifests、logs 与 rollback-safe writes 完成，不能悄悄重写 transcript truth。

## 6. Diagnostics 词汇

常见 retrieval diagnostics：

- `applied_filters`
- `boosts`
- `decays`
- `selected_doc_ids`
- `budget_decisions`
- `config`

常见 memory 诊断：

- write receipts
- rejection reasons
- background extraction task ids
- config source 与 warnings
- consolidation backlog 或 last-run state

这些词汇主要帮助回答：

- 为什么某个 memory fragment 被召回？
- 为什么某条事实被写入或被拒绝？
- consolidation 是否运行、被阻塞，还是仍有 backlog？

## 7. 相关文档

- `docs/zh-CN/concepts/memory-model.md`
- `docs/zh-CN/reference/memory-configuration.md`
- `docs/zh-CN/architecture/persistence-and-state.md`
- `docs/zh-CN/deep-dives/current-system-architecture.md`
