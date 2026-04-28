# Layered Memory Runtime V2

本文档说明 memory v2 的分层模型、hybrid policy、声明式配置面，以及 host diagnostics 中可以看到的关键信息。

## 分层模型

memory v2 将记忆拆成四层：

- `LongTermMemory`
  - 共享 durable memory，落在 `.weavert/memory/documents/`
  - 主要承载 `preferences/`、`conventions/`、`topics/` 和 `shared/`
- `AgentNamespaceMemory`
  - agent 私有 durable memory，落在 `.weavert/memory/agents/<agent>/documents/`
  - 不越出当前 `user/project/local` boundary
- `SessionMemory`
  - 当前 session 的 continuity artifacts，落在 `.weavert/memory/sessions/<session>/`
  - 主要包括 `session-summary.md`、`open-threads.md`、`metadata.json`
- `ConsolidationMemory`
  - 跨 session 的慢速后台整合层
  - 工作状态落在 `.weavert/memory/consolidations/`
  - 产生的 durable outputs 最终 merge 回 `LongTermMemory`

## Hybrid Policy

memory v2 的 retrieval 和 extraction 都走“先确定性、再增强”的路径。

### Retrieval

- manifest/header prefilter
- deterministic lexical shortlist
- optional embedding shortlist
- optional LLM rerank
- per-layer materialization

当前 diagnostics 会记录：

- `applied_filters`
- `boosts`
- `decays`
- `selected_doc_ids`
- `budget_decisions`
- `config`

其中 `config` 会暴露当前生效的 memory config source、warnings 和关键 knobs。

### Extraction

- 主线程规则抽取 obvious facts
- 后台 synthesis 处理高价值 topic/preference/agent note
- close session 后触发 consolidation backlog 检查

对 `do_not_persist` 或被 config 禁止的事实，runtime 会在 write receipts 和 diagnostics 中保留拒绝原因，而不是静默丢弃。

## 声明式配置面

项目级配置文件放在：

- `.weavert/memory/config.yaml`
- `.weavert/memory/config.yml`

也可以通过 `RuntimeConfig.memory_config` 以声明式 mapping 注入。

示例：

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

### 当前支持的配置能力

- retrieval
  - `max_results`
  - `embedding_enabled`
  - `llm_rerank`
  - `prefer_tags`
  - `suppress_tags`
- extraction
  - `never_capture`
  - safe routing overrides
- session memory
  - summary refresh thresholds
- consolidation
  - background 开关
  - min closed sessions
  - min hours since last run
  - backlog threshold

### 安全边界

以下内容仍由 runtime 固定控制，不允许被配置突破：

- scope boundary safety
- guarded memory roots
- secret/privacy baseline
- provenance recording
- rollback-safe consolidation writes

不安全或无效的配置不会让 runtime 崩溃。它们会被忽略，并在 diagnostics 中以 warnings 暴露。

## Consolidation Runtime

`ConsolidationMemory` 的 canonical artifacts：

- `consolidations/checkpoints/<run-id>.json`
- `consolidations/staging/<run-id>.json`
- `consolidations/logs/<run-id>.md`
- `manifests/consolidation-manifest.json`

`consolidation-manifest.json` 负责：

- 记录 backlog
- 记录 `last_successful_run_at`
- 记录 `active_lock`
- 保留最近 runs 的 checkpoint/log 引用

运行时序：

1. session close 更新 `session-manifest.json`
2. runtime 刷新 consolidation backlog
3. 满足 cadence 后生成 run lock
4. 写 staging/checkpoint/log
5. merge proposals 回 shared long-term memory
6. success 后写 `last_consolidated_at`
7. refresh manifests 并清 lock

如果 consolidation merge 中断：

- 共享 durable documents 会从 snapshot 恢复
- `active_lock` 会被清理
- run 会在 manifest/checkpoint/log 中标记为 `failed`

## Host Diagnostics

host 侧现在可以从 memory diagnostics 中看到：

- retrieval trace
- write receipts
- background extraction task id
- config source 与 warnings

在 session metadata 中还可以看到：

- `background_memory_tasks`
- `background_memory_consolidation_tasks`
- `durable_memory_deltas`
- `last_consolidated_at`

这些信息用于回答：

- 为什么某条 memory 被召回
- 为什么某条 fact 被写入或被拒绝
- consolidation 是否已经跑过
- 当前 backlog 还有多少 closed sessions 未整合
