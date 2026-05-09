# Memory 配置参考

这页汇总分层 memory system 周围稳定的配置与 diagnostics 词汇。

## 适合谁？

- 已理解整体工作流、现在需要稳定查询页的读者。

## 前置条件

- 先读对应的 guide 或 concept 页面
- 把这页当成 reference sheet，而不是第一站教程

## 配置入口

项目本地配置文件：

- `.weavert/memory/config.yaml`
- `.weavert/memory/config.yml`

程序化入口：

- `RuntimeConfig.memory_config`

## 示例

```yaml
memory:
  retrieval:
    max_results: 5
    prefer_tags: [testing, workflow]
    suppress_tags: [scratch]
    embedding_enabled: true
    llm_rerank: auto

  extraction:
    never_capture:
      - transient_task
      - secret
    routing:
      preference: long_term.preferences
      project_convention: long_term.conventions
      agent_workflow: agent_namespace
      session_thread: session

  session_memory:
    refresh:
      token_growth_threshold: 4000
      tool_call_threshold: 8
      turn_threshold: 6

  consolidation:
    enable_background: true
    min_closed_sessions: 4
    min_hours_since_last_run: 12
    backlog_threshold: 4
```

## 支持的 retrieval 字段

- `max_results`
- `embedding_enabled`
- `llm_rerank`
- `prefer_tags`
- `suppress_tags`

## 支持的 extraction 字段

- `never_capture`
- 安全的 routing overrides

## 支持的 session-memory 字段

- summary refresh thresholds，例如 token、tool-call 与 turn thresholds

## 支持的 consolidation 字段

- 启用或禁用后台 consolidation
- 最少 closed sessions 数量
- 自上次运行以来的最少小时数
- backlog threshold

## 安全边界

即便配置变化，runtime 仍应保持这些边界：

- scope-boundary safety
- guarded memory roots
- secret 与 privacy baselines
- provenance recording
- rollback-safe consolidation writes

无效或不安全的配置应以 warnings 形式被忽略，而不是直接让 runtime 崩溃。

## Consolidation artifacts

典型 consolidation artifacts 包括：

- `consolidations/checkpoints/<run-id>.json`
- `consolidations/staging/<run-id>.json`
- `consolidations/logs/<run-id>.md`
- `manifests/consolidation-manifest.json`

常见 manifest 关注点包括 backlog、active locks、上次成功运行，以及最近 checkpoint 或 log 的引用。

## Diagnostics 词汇

有用的 retrieval diagnostics 可能包括：

- `applied_filters`
- `boosts`
- `decays`
- `selected_doc_ids`
- `budget_decisions`
- `config`

对 host 或 session 可见的 diagnostics 可能包括：

- retrieval trace
- write receipts
- background extraction task ids
- config source 与 warnings
- `background_memory_tasks`
- `background_memory_consolidation_tasks`
- `durable_memory_deltas`
- `last_consolidated_at`

## 这能帮助回答的问题

- 为什么某段记忆被召回？
- 为什么某条事实被写入或被拒绝？
- consolidation 正在运行、被阻塞，还是仍有 backlog？
- 当前还有多少 closed-session backlog？

## 下一步

- 如果你需要这套配置背后的层级模型，回到 `../concepts/memory-model.md`
- 如果下一步是验证 retrieval、writes 或 consolidation 行为，进入 `../guides/testing-and-observability.md`
- 如果你需要更广泛的 durable-state 所有权说明，读 `../architecture/persistence-and-state.md`

## 另见

- `../concepts/memory-model.md`
- `../architecture/persistence-and-state.md`
- `workflow-observability.md`
- `../deep-dives/layered-memory-weavert-v2.md`
