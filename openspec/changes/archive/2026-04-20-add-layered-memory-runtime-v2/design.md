## Context

memory v1 已经把参考实现风格的基础语义落地为 runtime control plane：

- `MEMORY.md` entrypoint
- `user/project/local` scope resolution
- pre-turn relevant retrieval
- post-turn durable extraction
- memory path guard rails

但它仍然只有一个中心化 `MemoryManager`。参考实现的更成熟之处不在于“使用了文件型 memory”，而在于它把记忆拆成不同时间尺度和不同作用范围的运行时层次。对于 framework 而言，v2 不应机械复刻参考实现的每一步内部算法，而应保留参考实现风格的外部心智模型，同时把内部实现升级为 layered architecture 与 mixed policy。

## Goals / Non-Goals

**Goals:**

- 明确 `LongTermMemory`、`SessionMemory`、`ConsolidationMemory`、`AgentNamespaceMemory` 四个服务边界。
- 保留参考实现风格的外部语义：文件型 memory、scope boundary、turn 前召回、turn 后抽取、后台整理。
- 把检索与抽取升级为混合式 policy，而不是“全规则”或“每轮都强制 side-query”。
- 把 `SessionMemory` 与 compaction 从语义上拆开，避免长会话控制面与会话记忆混淆。
- 提供声明式 user-config surface，让用户可调策略但不会破坏 runtime invariants。

**Non-Goals:**

- 不要求 v2 在内部逐步 1:1 复制参考实现的 side-query 与 extractor 调度细节。
- 不把 v2 直接设计成用户可执行任意 Python/JS memory hooks 的平台。
- 不要求第一版必须引入外部向量数据库；embedding 可由默认 provider 或后续可选组件提供。
- 不让 compaction manager 兼任 session memory manager。

## Compatibility Stance

v2 的兼容策略是：

- **继承参考实现的接口语义和用户心智模型**
  - `MEMORY.md`
  - `user/project/local`
  - pre-turn recall
  - post-turn background extraction
  - agent-aware memory behavior
- **不强制继承参考实现的唯一内部算法**
  - 不要求每次 retrieval 都必须经过 side-query
  - 不要求 extraction 完全依赖 LLM agent
  - 允许 deterministic shortlist、embedding shortlist 与可选 rerank 共存

这意味着 v2 更像“reference-compatible layered runtime”，而不是“参考实现内部实现的 literal port”。

## Architecture

```text
                            MEMORY V2 RUNTIME
┌──────────────────────────────────────────────────────────────────────┐
│                              Turn Engine                             │
│  pre-turn assemble context                         post-turn hooks   │
└───────────────┬───────────────────────────────────────────┬──────────┘
                │                                           │
                ▼                                           ▼
      ┌───────────────────┐                    ┌──────────────────────┐
      │   Retrieval Pipe   │                    │   Extraction Pipe    │
      │ manifest/header    │                    │ obvious fact rules   │
      │ lexical/embedding  │                    │ background synthesis │
      │ optional rerank    │                    │ persistence routing  │
      └─────────┬─────────┘                    └──────────┬───────────┘
                │                                         │
     ┌──────────┼──────────┬───────────────┬──────────────┘
     ▼          ▼          ▼               ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌─────────────────────┐
│LongTerm  │ │Session   │ │AgentNamespace│ │ConsolidationMemory  │
│Memory    │ │Memory    │ │Memory        │ │(slow background)    │
└──────────┘ └──────────┘ └──────────────┘ └─────────────────────┘
```

## Canonical Artifact Layout

为避免 v2 在实现阶段出现“先有服务、后补目录约定”的漂移，先定义一版 canonical artifact layout。这里的 layout 是逻辑契约，不要求第一阶段把所有文件都实现完，但目录归属和命名风格应尽量保持稳定。

```text
<boundary>/.runtime/memory/
  MEMORY.md
  manifests/
    long-term-manifest.json
    agent-manifest.json
    session-manifest.json
    consolidation-manifest.json

  documents/
    shared/
      <slug>.md
    preferences/
      <slug>.md
    conventions/
      <slug>.md
    topics/
      <slug>.md

  agents/
    <agent-name>/
      namespace-manifest.json
      documents/
        workflows/
          <slug>.md
        heuristics/
          <slug>.md
        durable-notes/
          <slug>.md

  sessions/
    <session-id>/
      session-summary.md
      open-threads.md
      metadata.json
      checkpoints/
        <checkpoint-id>.json

  consolidations/
    checkpoints/
      <run-id>.json
    logs/
      <run-id>.md
    staging/
      <run-id>.json
```

layout 约束：

- `MEMORY.md` 继续作为人类可读入口和顶层 instructions 入口。
- `manifests/` 只存便宜元数据和索引，不存正文。
- `documents/` 只存 shared long-term durable memory。
- `agents/` 只存 namespace-scoped durable agent memory。
- `sessions/` 只存当前或历史 session continuity artifacts。
- `consolidations/` 只存 slow background synthesis 的工作状态和审计日志。

## Artifact Contract

v2 中的 memory artifact 默认是 markdown 正文 + sidecar metadata，或纯 metadata 文件：

- 正文 artifacts：`.md`
- 索引 / sidecar / checkpoint：`.json`

推荐正文 artifact frontmatter：

```yaml
---
memory_kind: preference
scope: project
namespace: shared
agent_namespace: null
retention: durable_until_superseded
source_pathway: rule
source_message_ids:
  - msg_123
last_confirmed_at: 2026-04-17T04:00:00Z
tags:
  - testing
  - workflow
---
```

推荐 metadata 字段：

- `memory_kind`
- `scope`
- `namespace`
- `agent_namespace`
- `retention`
- `source_pathway`
- `source_message_ids`
- `created_at`
- `last_confirmed_at`
- `supersedes`
- `tags`
- `confidence`

这样做的目的：

- markdown 仍然适合人读、diff 和手工审阅
- manifest 和 rerank 不必每次读取正文
- conflict/merge/consolidation 可以在 metadata 层完成大部分判断

## Manifest Schemas

manifest 的目标不是替代正文，而是给 runtime 一层便宜、稳定、可解释的索引视图。pre-turn retrieval、background consolidation、staleness control 和 audit trace 都优先消费 manifest，而不是每次扫描所有 markdown 正文。

### Common Manifest Envelope

所有 manifest 建议共享一层 envelope：

```json
{
  "schema_version": "memory.v2",
  "manifest_kind": "long_term",
  "boundary_scope": "project",
  "generated_at": "2026-04-17T04:30:00Z",
  "stats": {
    "entry_count": 42,
    "stale_entry_count": 3
  },
  "entries": []
}
```

公共字段用途：

- `schema_version`: manifest 升级和兼容判断
- `manifest_kind`: 区分 long-term / agent / session / consolidation
- `boundary_scope`: 当前 manifest 所属 `user/project/local`
- `generated_at`: 索引刷新时间
- `stats`: 便于 observability 和调试
- `entries`: 候选索引记录

### `long-term-manifest.json`

用途：

- 给 shared durable memory 做 prefilter
- 支持 lexical shortlist、embedding shortlist 和 stale decay
- 避免每轮都读取 `documents/*` 正文

建议 entry 结构：

```json
{
  "doc_id": "ltm_pref_pytest_q",
  "path": "documents/preferences/use-pytest-q.md",
  "title": "Use pytest -q",
  "memory_kind": "preference",
  "namespace": "shared",
  "scope": "project",
  "agent_namespace": null,
  "tags": ["testing", "workflow"],
  "summary": "Prefer pytest -q for concise unit test runs.",
  "token_estimate": 96,
  "source_pathway": "rule",
  "source_message_ids": ["msg_123"],
  "created_at": "2026-04-17T04:00:00Z",
  "last_confirmed_at": "2026-04-17T04:00:00Z",
  "retention": "durable_until_superseded",
  "stale_after": "2026-05-17T04:00:00Z",
  "conflict_key": "preference.testing.pytest_command",
  "embedding_ref": "emb:7f9c",
  "contested": false
}
```

关键字段：

- `summary`: 供 prefilter / rerank 使用的便宜摘要，不等于全文
- `token_estimate`: materialization budget 计算
- `conflict_key`: 合并和覆盖判断
- `embedding_ref`: 可选 embedding 索引引用
- `contested`: 表示该 memory 目前有冲突，不应被无条件优先召回

### `agent-manifest.json`

用途：

- 暴露当前 boundary 下有哪些 agent namespace
- 为 active agent namespace retrieval 提供入口
- 支持 namespace precedence 和 delegated policy ceiling 校验

建议结构：

```json
{
  "schema_version": "memory.v2",
  "manifest_kind": "agent",
  "boundary_scope": "project",
  "generated_at": "2026-04-17T04:30:00Z",
  "namespaces": [
    {
      "agent_name": "main-router",
      "path": "agents/main-router/",
      "entry_count": 8,
      "last_updated_at": "2026-04-17T04:10:00Z",
      "conflict_keys": [
        "agent_workflow.main-router.python-tests"
      ]
    }
  ]
}
```

对应 `agents/<agent-name>/namespace-manifest.json` 的 entry 建议结构：

```json
{
  "doc_id": "agent_main_router_pytest_heuristic",
  "path": "agents/main-router/documents/heuristics/pytest-heuristic.md",
  "title": "Pytest Heuristic",
  "memory_kind": "agent_workflow",
  "namespace": "agent:main-router",
  "tags": ["testing", "heuristic"],
  "summary": "When verifying small code changes, start with pytest -q before broader checks.",
  "token_estimate": 82,
  "last_confirmed_at": "2026-04-17T04:10:00Z",
  "retention": "durable_reviewable",
  "conflict_key": "agent_workflow.main-router.python-tests"
}
```

### `session-manifest.json`

用途：

- 告诉 runtime 当前 boundary 下哪些 session artifacts 仍可用
- 快速判断某个 session 是否存在 summary、open threads 或 checkpoints
- 帮助 consolidation worker 枚举 closed sessions backlog

建议结构：

```json
{
  "schema_version": "memory.v2",
  "manifest_kind": "session",
  "boundary_scope": "project",
  "generated_at": "2026-04-17T04:30:00Z",
  "sessions": [
    {
      "session_id": "session-abc",
      "status": "active",
      "path": "sessions/session-abc/",
      "has_summary": true,
      "has_open_threads": true,
      "checkpoint_count": 2,
      "last_updated_at": "2026-04-17T04:22:00Z",
      "last_compaction_at": "2026-04-17T04:18:00Z",
      "ready_for_consolidation": false
    }
  ]
}
```

### `consolidation-manifest.json`

用途：

- 跟踪 consolidation cadence
- 记录 backlog、最近一次成功 run、失败/锁状态
- 为后台 worker 决定是否应该发起下一次 consolidation

建议结构：

```json
{
  "schema_version": "memory.v2",
  "manifest_kind": "consolidation",
  "boundary_scope": "project",
  "generated_at": "2026-04-17T04:30:00Z",
  "last_successful_run_at": "2026-04-16T18:00:00Z",
  "active_lock": null,
  "backlog": {
    "closed_session_count": 6,
    "pending_session_ids": ["session-a", "session-b", "session-c"]
  },
  "recent_runs": [
    {
      "run_id": "cons-20260416-1800",
      "status": "success",
      "checkpoint_path": "consolidations/checkpoints/cons-20260416-1800.json",
      "log_path": "consolidations/logs/cons-20260416-1800.md"
    }
  ]
}
```

manifest 刷新策略建议：

- `long-term-manifest.json`: durable write 或 merge 后刷新
- `agent-manifest.json`: agent namespace write 后刷新
- `session-manifest.json`: session summary / open thread / checkpoint 更新后刷新
- `consolidation-manifest.json`: consolidation run lifecycle 事件后刷新

### Manifest Field Requirements

为了避免 v2 实现阶段出现每种 manifest 自己发明字段的情况，建议先固定一套 required / optional vocabulary。

#### Common Envelope Fields

所有 manifest envelope 必须包含：

- `schema_version`
- `manifest_kind`
- `boundary_scope`
- `generated_at`

以下字段可选但推荐：

- `stats`
- `warnings`
- `generation_trace`

#### Common Entry Fields

凡是表示“可检索 memory entry”的记录，建议区分：

必填字段：

- `doc_id`
- `path`
- `title`
- `memory_kind`
- `namespace`
- `token_estimate`
- `retention`

条件必填字段：

- `scope`: shared long-term entries 必填
- `agent_namespace`: agent namespace entries 必填
- `summary`: 允许进入 retrieval shortlist 的 entries 必填
- `last_confirmed_at`: durable entries 必填
- `conflict_key`: 需要 merge/overwrite policy 的 entries 必填

可选增强字段：

- `tags`
- `source_pathway`
- `source_message_ids`
- `created_at`
- `stale_after`
- `embedding_ref`
- `contested`
- `confidence`

#### Session Index Fields

`session-manifest.json` 中每个 session record 必须包含：

- `session_id`
- `status`
- `path`
- `last_updated_at`

推荐字段：

- `has_summary`
- `has_open_threads`
- `checkpoint_count`
- `last_compaction_at`
- `ready_for_consolidation`

#### Consolidation Index Fields

`consolidation-manifest.json` 必须包含：

- `last_successful_run_at`
- `backlog`

如果 runtime 允许后台 consolidation 并发控制，还应包含：

- `active_lock`
- `recent_runs`

### Manifest Validation Rules

manifest 层建议有一套独立校验规则：

- `path` 必须落在当前 boundary 的 canonical layout 内
- `namespace=shared` 时，`agent_namespace` 必须为 `null`
- `namespace=agent:<name>` 时，`agent_namespace` 必须和路径中的 agent 目录一致
- `retention=drop` 的条目不得进入 durable manifests
- `token_estimate` 必须是正整数
- `contested=true` 的条目不得被 budget allocator 无条件优先
- `ready_for_consolidation=true` 的 session 不得仍标记为 `active`

manifest validation 失败时：

- 不应直接让 retrieval 崩溃
- 应降级忽略坏条目并写入 audit / warning
- 严重错误时才中断对应 background worker

## Service Boundaries

### 1. `LongTermMemory`

`LongTermMemory` 是 durable shared memory layer。它负责：

- 解析 `user/project/local` 边界
- 维护 `MEMORY.md` entrypoint
- 管理 shared/topic/preference/convention 类 durable documents
- 提供长期 memory 的 provider boundary、path resolution、dedupe 与 provenance

它不负责：

- 会话内滚动摘要
- 跨 session 慢速 consolidation orchestration
- agent-specific namespace policy

建议 artifact layout：

```text
<boundary>/.runtime/memory/
  MEMORY.md
  manifests/
    long-term-manifest.json
  documents/
    shared/
      <slug>.md
    preferences/
      <slug>.md
    conventions/
      <slug>.md
    topics/
      <slug>.md
```

`LongTermMemory` 拥有的 canonical paths：

- `MEMORY.md`
- `manifests/long-term-manifest.json`
- `documents/shared/`
- `documents/preferences/`
- `documents/conventions/`
- `documents/topics/`

### 2. `AgentNamespaceMemory`

`AgentNamespaceMemory` 不是新的顶层 scope，而是作用在 `LongTermMemory` 之上的 namespace overlay。它负责：

- 为 agent 提供独立 durable working memory
- 在同一 `user/project/local` boundary 内隔离不同 agent 的长期工作上下文
- 规定 namespace-aware retrieval order 与 write routing
- 在 delegation 时遵守 parent policy ceiling

它不负责：

- 覆盖或替代 shared long-term memory
- 决定跨 session consolidation

建议 artifact layout：

```text
<boundary>/.runtime/memory/
  manifests/
    agent-manifest.json
  agents/
    <agent-name>/
      namespace-manifest.json
      documents/
        workflows/
          <slug>.md
        heuristics/
          <slug>.md
        durable-notes/
          <slug>.md
```

`AgentNamespaceMemory` 拥有的 canonical paths：

- `manifests/agent-manifest.json`
- `agents/<agent-name>/namespace-manifest.json`
- `agents/<agent-name>/documents/workflows/`
- `agents/<agent-name>/documents/heuristics/`
- `agents/<agent-name>/documents/durable-notes/`

建议 retrieval precedence：

1. active agent namespace
2. scope-shared durable memory
3. topic/preference/convention memory
4. optional session summary overlays

### 3. `SessionMemory`

`SessionMemory` 是 current-session continuity layer。它负责：

- 维护当前 session 的滚动摘要
- 跟踪最近完成的任务、局部约束、近期决策与未完成线程
- 以独立 artifact 存储与更新，而不是把这些信息埋进 compaction summary
- 在 turn 前把会话摘要作为单独 memory fragment 注入

它不负责：

- durable cross-session preference storage
- transcript compaction
- topic-level slow synthesis

`SessionMemory` 与 compaction 的关系：

- compaction 负责 **context pressure management**
- session memory 负责 **session continuity memory**

两者都可能产生 summary，但语义完全不同，不能互相替代。

建议 artifact layout：

```text
<boundary>/.runtime/memory/
  sessions/
    <session-id>/
      session-summary.md
      open-threads.md
      metadata.json
      checkpoints/
        <checkpoint-id>.json
```

`SessionMemory` 拥有的 canonical paths：

- `sessions/<session-id>/session-summary.md`
- `sessions/<session-id>/open-threads.md`
- `sessions/<session-id>/metadata.json`
- `sessions/<session-id>/checkpoints/`

### Session Artifact Templates

`SessionMemory` 最核心的两个可读 artifacts 是：

- `session-summary.md`
- `open-threads.md`

它们都不是 transcript 替身，而是给 runtime 和模型提供“继续这场会话”所需的压缩视图。

#### `session-summary.md`

用途：

- turn 前注入当前 session 的稳定连续性信息
- 在 resume 后快速恢复上下文
- 在 compaction 发生后保留“我们正在做什么”的视图

推荐模板：

```md
# Session Summary

## Current Objective
- 当前这场会话要解决的主目标

## Current State
- 已完成的关键里程碑
- 当前代码/设计/调查进行到哪

## Key Decisions
- 已经做出的决定
- 明确拒绝的方案

## Active Constraints
- 当前必须遵守的约束
- 用户在本 session 中强调的局部偏好

## Important Recent Outcomes
- 最近值得延续的 tool / agent / verification 结果

## Likely Next Steps
- 如果下一轮继续，最可能的推进路径

## Provenance
- session_id: ...
- updated_at: ...
- source_turn_ids:
  - ...
```

填写规则建议：

- 保持面向“下一轮继续工作”而不是面向“完整历史归档”
- 不记录所有细节，只保留 continuity-critical 信息
- 单个 summary 应受 token/character 预算约束

生成规则建议：

- 来源窗口应优先覆盖自上次 summary refresh 以来的新 turns，而不是每次重扫全量 transcript
- 必须优先纳入：
  - 当前主目标
  - 已确认的关键决策
  - 仍然生效的约束
  - 最近会影响下一步的 tool / verification 结果
- 不应纳入：
  - 低价值逐轮日志
  - 可从 transcript 轻易恢复的细枝末节
  - secrets / tokens / credentials
  - 仍未确认且噪音较大的推测

刷新策略建议：

- 新内容不足以改变 continuity view 时允许跳过刷新
- compaction 后允许刷新，但不得简单复制 compaction summary
- refresh 产物应覆盖旧 summary，而不是无界追加

#### `open-threads.md`

用途：

- 专门记录未闭合的线程
- 避免 summary 被 pending items 塞满
- 为 resume / user re-entry / subagent follow-up 提供清晰接点

推荐模板：

```md
# Open Threads

## Thread: <thread-key>
- Status: blocked | pending | waiting_user | ready
- Owner: main-router | verification | <agent-name>
- Summary: 这条线程当前卡在什么地方
- Next Action: 下一步应该做什么
- Unblock Condition: 什么条件满足后可以继续
- Related Artifacts:
  - sessions/<session-id>/checkpoints/<checkpoint-id>.json
  - documents/topics/<slug>.md

## Thread: <thread-key-2>
- Status: ...
- Owner: ...
- Summary: ...
- Next Action: ...
- Unblock Condition: ...
```

填写规则建议：

- 一条 thread 必须有稳定 `thread-key`
- `Summary` 只写线程本身，不复述整个 session
- 用户明确回答或 blocker 解决后，应及时移除或标记 closed

生成规则建议：

- 只有满足以下任一条件的事项才进入 open threads：
  - 明确 blocked
  - 等待用户输入
  - 等待后台 agent / verification 结果
  - 本轮结束时仍有明确 next action
- 已闭合事项应在下次 refresh 时移除，或迁移到 session summary 的 recent outcomes
- `thread-key` 建议由稳定语义键生成，而不是使用临时消息 id

推荐 `thread-key` 组成：

- `thread_kind`
- `target_subject`
- `owner`

示例：

- `verification:pytest-suite:verification`
- `user_input:memory-routing:main-router`
- `blocker:test-fixture-mismatch:main-router`

禁止项：

- 不得把整个 todo list 原封不动塞进 open threads
- 不得把已经 durable 化的长期偏好或项目约定重复写进 open threads
- 不得把没有 next action 的泛泛担忧写成线程

#### `metadata.json`

`metadata.json` 主要服务于 runtime，不直接注入模型。建议字段：

```json
{
  "session_id": "session-abc",
  "status": "active",
  "created_at": "2026-04-17T03:00:00Z",
  "updated_at": "2026-04-17T04:22:00Z",
  "summary_version": 3,
  "open_thread_count": 2,
  "last_compaction_at": "2026-04-17T04:18:00Z",
  "last_summary_refresh_at": "2026-04-17T04:22:00Z"
}
```

### Session Artifact Validation Rules

为保证 session artifacts 对 retrieval 和 resume 真有帮助，建议固定以下校验规则：

- `session-summary.md` 必须包含 `Current Objective` 和 `Current State`
- `open-threads.md` 中每条 thread 必须至少有 `Status`、`Owner`、`Summary`、`Next Action`
- `metadata.json.summary_version` 必须与最近一次 summary refresh 单调递增
- `open_thread_count` 应与 `open-threads.md` 中 active threads 数一致
- `last_summary_refresh_at` 不得早于 `updated_at`

校验失败处理建议：

- summary 缺失核心段落时，runtime 可回退到最近 checkpoint 或触发一次 forced refresh
- open threads 结构错误时，runtime 应忽略坏线程并记录 warning，而不是整份文件报废
- metadata 与 markdown 不一致时，以 markdown 为准重建 metadata

更新触发建议：

- token 或字符增长阈值
- tool call 数阈值
- turn 数阈值
- session 状态从 blocked/active 进入 stable window
- compaction 发生后可触发 session memory refresh，但 compaction 不是 session memory 本身

### 4. `ConsolidationMemory`

`ConsolidationMemory` 是 slow background synthesis layer。它负责：

- 在多个 session 结束后回顾 session summaries 与 durable memory changes
- 将重复、零散或低层事实整合为 topic memory / preference memory / project convention
- 控制 consolidation cadence、locks、merge policy 与 conflict resolution
- 为长期 memory 生成更高层抽象，而不是每轮即时写入

它不负责：

- 当前 turn 的即时召回
- 当前 session 的滚动 continuity
- 单 agent namespace 的短期工作草稿

建议 artifact layout：

```text
<boundary>/.runtime/memory/
  consolidations/
    checkpoints/
      <run-id>.json
    logs/
      <run-id>.md
    staging/
      <run-id>.json
```

`ConsolidationMemory` 拥有的 canonical paths：

- `consolidations/checkpoints/`
- `consolidations/logs/`
- `consolidations/staging/`

它产生的 durable outputs 会被提交回：

- `documents/topics/`
- `documents/preferences/`
- `documents/conventions/`

触发建议：

- 距上次 consolidation 时间足够久
- 已关闭 session 数达到阈值
- backlog 的 session summaries 超过阈值
- 当前 host/turn 没有高优先级实时工作

## Lifecycle Orchestration

### Session Start

session 启动时：

1. 解析 active scope boundary
2. 解析 active agent namespace
3. 加载 `LongTermMemory` entrypoint 与 shared manifests
4. 尝试加载 `SessionMemory` artifact
5. 注册 background extraction / session summary / consolidation workers 所需的 runtime handles

### Pre-Turn Retrieval

pre-turn retrieval 不再是“读取所有长期记忆然后直接拼 prompt”，而是统一走 retrieval pipeline：

1. resolve memory sources
   - active agent namespace
   - shared long-term memory
   - topic/preference/convention pools
   - session summary
2. manifest/header prefilter
3. lexical shortlist
4. optional embedding shortlist
5. optional LLM rerank
6. token budget allocation
7. render structured fragments with provenance

### Post-Turn Extraction

turn 成功结束后：

1. 规则层先抽 obvious facts
2. 对需要高层归纳的内容生成 extraction job
3. 后台受限 agent 处理高价值 synthesis
4. 根据 routing policy 决定写入：
   - `SessionMemory`
   - `AgentNamespaceMemory`
   - `LongTermMemory`
5. 满足 consolidation 条件时，由 `ConsolidationMemory` 异步消费 closed-session outputs

## Retrieval Policy

### Design Principle

retrieval policy 目标不是“永远最聪明”，而是：

- 先用确定性手段把 candidate pool 收窄
- 让模型只参与高价值的最后判断
- 在没有 embedding 或 LLM rerank 时也能稳定降级
- 为调试与 observability 保留 explainable scoring path

### Retrieval Stages

#### 1. Manifest/Header Prefilter

预筛只使用便宜元数据：

- title
- tags
- scope
- namespace
- document kind
- recency
- source/provenance
- path/module/workspace affinity

预筛的目标是先排除明显无关项，而不是直接做最终排序。

#### 2. Lexical Shortlist

lexical shortlist 使用确定性信号：

- query term overlap
- entity/file/module overlap
- normalized keyword scoring
- recency boost
- scope/namespace boost
- explicit tag boost

这一步必须可解释，并能在没有 embedding provider 时独立工作。

#### 3. Optional Embedding Shortlist

当 runtime 配置了 embedding support 时，可以对 lexical shortlist 或 manifest candidates 追加 semantic shortlist。

embedding 在 v2 中是：

- 可选能力，不是硬依赖
- 用于补 lexical 对隐式语义召回的短板
- 不应强迫引入外部 vector database

#### 4. Optional LLM Rerank

LLM rerank 不是默认硬路径，而是满足以下条件时的增强项：

- candidate 数量超过 deterministic confidence threshold
- query 语义明显模糊
- 当前 model/provider 可用，且 latency budget 允许
- host policy 未禁用额外模型调用

这与参考实现的区别在于：参考实现倾向于把模型判相关放在 retrieval 主路径；v2 则把它放在最后一跳。

#### 5. Budgeted Materialization

最终回注时必须遵守 token/character budget。materialization policy 应支持：

- per-layer budget
- per-kind budget
- session summary 与 durable memories 分开预算
- provenance rendering

### Retrieval Quality Controls

为避免 noise，v2 应内建：

- minimum score threshold
- dedupe across layers
- namespace precedence
- stale memory decay
- contradiction marker support

### Retrieval Scoring Policy Table

为了让 retrieval 可测试、可解释、可配置，建议把 scoring policy 分成四类信号：

- `hard_filter`
- `boost`
- `decay`
- `rerank_trigger`

这些信号不要求都映射成一个统一数值模型，但必须有稳定 vocabulary，便于测试、日志和用户配置。

推荐 v2 默认 scoring policy：

| Policy Type | Signal | Default Effect | Why It Exists |
|---|---|---|---|
| `hard_filter` | scope mismatch | exclude | 防止跨 boundary 污染 |
| `hard_filter` | namespace mismatch under strict namespace mode | exclude | 防止错误召回其他 agent namespace |
| `hard_filter` | `retention=drop` | exclude | 明确不可持久条目不得参与 durable retrieval |
| `hard_filter` | invalid manifest entry | exclude + warn | 坏索引不应拖垮整轮 retrieval |
| `hard_filter` | secret/sensitive classification | exclude + redact | 防止敏感值回注模型 |
| `hard_filter` | contested entry with policy=`block_contested` | exclude | 冲突条目不能默认参与召回 |
| `boost` | exact conflict-key or entity match | high | 提高显式相关性 |
| `boost` | active agent namespace hit | high | agent working memory 应优先于 shared memory |
| `boost` | explicit preferred tag hit | medium | 让项目配置能表达偏好主题 |
| `boost` | recent confirmation | medium | 新鲜 memory 优先 |
| `boost` | same workspace/module/path affinity | medium | 增强局部上下文命中 |
| `boost` | `memory_kind` matches inferred query intent | medium | 比如 testing query 命中 conventions/workflows |
| `boost` | session continuity artifact | medium | 长会话下优先保证连贯性 |
| `decay` | stale beyond threshold | medium | 旧条目逐步降权 |
| `decay` | superseded artifact | high | 已被更新的旧条目不应继续抢位 |
| `decay` | weak lexical overlap | low | 降低噪音候选 |
| `decay` | low-confidence inferred memory | medium | 推断型 memory 不应压过显式事实 |
| `decay` | cross-namespace retrieval fallback | low | 非当前 agent namespace 的内容应被抑制 |
| `rerank_trigger` | candidate count exceeds shortlist threshold | run optional rerank | 候选太多时需要更强区分 |
| `rerank_trigger` | top scores too close | run optional rerank | 规则信号无法稳定决策 |
| `rerank_trigger` | lexical and embedding results diverge | run optional rerank | 两种召回意见冲突 |
| `rerank_trigger` | query is semantically vague | run optional rerank | 模糊问题更适合语义判断 |
| `rerank_trigger` | host/model budget unavailable | skip rerank | rerank 是增强项而不是依赖项 |

### Retrieval Decision Pipeline

建议把 scoring 的应用顺序固定为：

1. `hard_filter`
2. base shortlist scoring
3. `boost`
4. `decay`
5. confidence threshold cut
6. optional rerank
7. budgeted materialization

这样做的原因：

- filter 永远优先于加分
- decay 不会“复活”已经被排除的条目
- rerank 只发生在 deterministic shortlist 之后

### Retrieval Trace Contract

每次 retrieval 建议输出一份 decision trace，用于调试和审计。最小字段：

```json
{
  "query_id": "turn-123",
  "applied_filters": ["scope_mismatch", "retention_drop"],
  "boosts": ["active_agent_namespace", "recent_confirmation"],
  "decays": ["stale_beyond_threshold"],
  "rerank_triggered": true,
  "selected_doc_ids": ["ltm_pref_pytest_q", "agent_main_router_pytest_heuristic"]
}
```

trace 不要求暴露给最终用户，但应进入 debug logs 或 host-visible diagnostics。

## Extraction Policy

### Design Principle

extraction policy 不应在“全规则”和“全 agent”之间二选一。v2 采用两阶段抽取：

- 规则层负责 obvious facts
- 后台受限 agent 负责高价值 synthesis

这样既保留确定性，也保留语义抽象能力。

### Extraction Classes

#### 1. Obvious Facts

规则层直接处理：

- user preference
- stable project convention
- explicit workflow command
- long-lived environment fact
- clear identity/preference statement

这类内容适合立即落入 `LongTermMemory` 或 `AgentNamespaceMemory`。

#### 2. Session Continuity Facts

规则层或轻量 summarizer 处理：

- 当前 session 的 recent decisions
- unfinished threads
- recent tool outcomes that matter for the next few turns

这类内容默认写入 `SessionMemory`，而不是 durable long-term memory。

#### 3. High-Level Synthesis

后台受限 agent 处理：

- repeated preferences inferred across sessions
- emerging project conventions
- topic memory distilled from multiple turns or sessions
- multi-message intent or strategy patterns

这类内容通常进入 `ConsolidationMemory` 或 `LongTermMemory/topics`。

### Extraction Fact Taxonomy

为避免“同一条事实今天是 preference，明天又成 convention”的漂移，v2 应定义一套稳定的 fact taxonomy。taxonomy 的用途是：

- 统一 extraction classification
- 驱动 routing matrix
- 决定 retention 和 merge policy
- 给 user-config surface 提供稳定 selector

推荐 fact taxonomy：

| Fact Type | Definition | Typical Source | Default Target | Retention | Persist? |
|---|---|---|---|---|---|
| `preference` | 用户或团队明确表达的偏好 | user prompt, confirmed assistant recap | `LongTermMemory/preferences` | `durable_until_superseded` | yes |
| `project_convention` | 项目稳定约定、标准流程、 repo 规则 | user/tool/verification confirmation | `LongTermMemory/conventions` | `durable_until_revoked` | yes |
| `workflow_command` | 可复用的固定命令或操作步骤 | tool result, user instruction | `LongTermMemory/conventions` | `durable_until_revoked` | yes |
| `topic_memory` | 经多轮或多 session 提炼出的高层主题知识 | consolidation, background synthesis | `LongTermMemory/topics` | `durable_until_superseded` | yes |
| `agent_workflow` | 某 agent 可复用的工作习惯或启发式 | agent result, verification pattern | `AgentNamespaceMemory` | `durable_reviewable` | yes |
| `agent_note` | 某 agent 的持久工作笔记，但未上升为 shared knowledge | agent synthesis | `AgentNamespaceMemory` | `durable_reviewable` | yes |
| `session_continuity` | 当前 session 的状态压缩、近期决策和局部约束 | session summarizer | `SessionMemory/session-summary.md` | `session_lifetime` | yes |
| `session_thread` | 当前 session 未闭合的 blocker、待确认事项、待续步骤 | session thread tracker | `SessionMemory/open-threads.md` | `session_lifetime` | yes |
| `transient_task` | 一次性任务状态或短期操作意图 | turn-local planning | `do_not_persist` | `drop` | no |
| `ephemeral_observation` | 低价值临时观察、日志片段、瞬时输出 | tool output noise | `do_not_persist` | `drop` | no |
| `sensitive_value` | secret、token、credential、敏感个人信息 | any source | `do_not_persist` | `drop` | no |
| `contested_fact` | 存在冲突、需后续确认的 memory candidate | conflicting extraction paths | `staging_or_contested_state` | `review_required` | guarded |

### Taxonomy Classification Rules

推荐分类优先级：

1. `sensitive_value`
2. `transient_task`
3. `session_thread`
4. `session_continuity`
5. `agent_workflow` / `agent_note`
6. `project_convention` / `workflow_command`
7. `preference`
8. `topic_memory`
9. `contested_fact`

分类原则：

- 显式用户陈述优先落到 `preference` 或 `project_convention`
- 当前会话仍未闭合的事项优先落到 `session_thread`
- 只对当前 agent 有复用价值的知识优先落到 `agent_workflow` 或 `agent_note`
- 需要跨 session 才能稳健确认的高层归纳优先落到 `topic_memory`
- 无法安全持久化的内容必须先命中 `sensitive_value` / `transient_task`

### Taxonomy to Config Mapping

user-config surface 后续应优先允许用户按 taxonomy selector 配置，而不是按自由文本乱配。例如：

- `always_capture: [preference, project_convention]`
- `never_capture: [transient_task, sensitive_value]`
- `routing_override.agent_workflow: agent_namespace`

这样可以让配置和 runtime 内部分类保持一致。

### Taxonomy Validation Rules

为减少错分带来的后续污染，建议固定以下校验：

- `sensitive_value` 和 `transient_task` 不得写入 durable manifests
- `session_thread` 不得直接写入 `LongTermMemory`
- `topic_memory` 不得由单条低置信度 rule extraction 直接生成
- `agent_workflow` 写入时必须带 `agent_namespace`
- `project_convention` 和 `workflow_command` 必须有 `conflict_key`
- `contested_fact` 不得在无审查/无确认的情况下覆盖稳定 durable memory

### Non-Extractable Classes

默认不抽取：

- transient task state
- ephemeral error logs
- one-off operational noise
- secrets / credentials / unsafe personal data
- stale scratch decisions with no future reuse value

### Ownership and Routing

extraction routing policy 应回答两个问题：

1. 记到哪一层？
2. 属于 shared 还是 agent namespace？

建议把 routing matrix 固定成至少五列：

- `fact_type`
- `default_target_layer`
- `namespace`
- `retention`
- `merge_policy`

推荐 v2 默认路由矩阵：

| Fact Type | Typical Signal | Default Target Layer | Namespace | Retention | Merge Policy |
|---|---|---|---|---|---|
| explicit preference | “我偏好…”, “always…”, “never…” | `LongTermMemory/preferences` | `shared` | `durable_until_superseded` | `overwrite_on_newer_confirmation` |
| stable project convention | “项目使用…”, “repo 约定…” | `LongTermMemory/conventions` | `shared` | `durable_until_revoked` | `merge_with_provenance` |
| reusable workflow command | 固定命令、测试/构建工作流 | `LongTermMemory/conventions` | `shared` | `durable_until_revoked` | `merge_with_last_confirmed_at` |
| agent-specific working habit | 某 agent 的工作偏好或启发式 | `AgentNamespaceMemory` | `agent:<name>` | `durable_until_superseded` | `overwrite_inside_namespace` |
| agent durable note | 某 agent 反复复用的操作诀窍 | `AgentNamespaceMemory` | `agent:<name>` | `durable_reviewable` | `append_with_dedupe` |
| current thread continuity | 本 session 的近期决策和上下文 | `SessionMemory` | `session` | `session_lifetime` | `replace_summary_window` |
| unresolved blocker / open thread | 当前未解决问题、待续任务 | `SessionMemory/open-threads` | `session` | `session_lifetime` | `upsert_by_thread_key` |
| repeated multi-session pattern | 多 session 重复出现的主题或偏好 | `ConsolidationMemory -> LongTermMemory/topics` | `shared` | `durable_until_superseded` | `synthesize_then_merge` |
| emerging preference inferred indirectly | 多轮/多 session 推断出的偏好 | `ConsolidationMemory -> LongTermMemory/preferences` | `shared` | `durable_until_superseded` | `require_multi_source_confirmation` |
| transient task state | “今天先…”, 一次性临时状态 | `do_not_persist` | `none` | `drop` | `no_write` |
| secret / sensitive value | token、password、credential | `do_not_persist` | `none` | `drop` | `redact_and_block` |

补充路由规则：

- `SessionMemory` 永远不直接提升为 `LongTermMemory`；必须经过下一轮确认或 consolidation。
- `AgentNamespaceMemory` 默认不向 shared durable memory 外溢；除非 consolidation 或 explicit promotion 发生。
- `ConsolidationMemory` 不直接暴露给 pre-turn retrieval；它先产出 durable outputs，再由 `LongTermMemory` 消费。
- 对于 `do_not_persist` 类，runtime 应记录拒绝原因到 audit trace，而不是静默丢弃。

### Retention Classes

为避免每类 memory 都重新发明生命周期，建议固定 retention vocabulary：

- `session_lifetime`
- `durable_reviewable`
- `durable_until_superseded`
- `durable_until_revoked`
- `drop`

### Merge Policy Vocabulary

建议固定 merge policy vocabulary：

- `append_with_dedupe`
- `overwrite_on_newer_confirmation`
- `overwrite_inside_namespace`
- `merge_with_provenance`
- `merge_with_last_confirmed_at`
- `replace_summary_window`
- `upsert_by_thread_key`
- `synthesize_then_merge`
- `require_multi_source_confirmation`
- `no_write`

### Provenance and Conflict Policy

所有 extraction outputs 都应带：

- source message ids
- source roles
- extraction pathway
  - `rule`
  - `background_extractor`
  - `consolidation`
- timestamp
- scope
- namespace

冲突处理建议：

- 明确更新型 preference 以后写覆盖先写
- project convention 合并时保留 provenance 和 last-confirmed timestamp
- 高冲突内容先标记为 contested，不直接覆盖

## User-Config Surface

### Configuration Principles

user-config surface 需要满足：

- 可调 policy，但不破坏 runtime invariants
- 优先声明式配置，而不是任意可执行脚本
- 平台层安全边界不可被覆盖

### Non-Configurable Invariants

以下内容由 runtime 固定控制：

- scope boundary safety
- guarded memory roots
- secret/privacy redaction baseline
- provenance recording
- replay-safe write phases

### Configurable Retrieval Surface

允许用户声明：

- retrieval limits
- per-layer budget
- 是否启用 embedding
- 是否启用 LLM rerank
- tag boosts / suppressions
- namespace precedence overrides within safe bounds
- stale decay policy

### Configurable Extraction Surface

允许用户声明：

- always-capture categories
- never-capture categories
- explicit phrase hints
- preferred routing targets
- consolidation cadence
- session summary refresh thresholds

### Future Extension Surface

v2 不直接开放任意可执行 extractor/reranker，但为后续保留：

- pluggable embedding provider
- pluggable rerank provider
- reviewed hook phases for advanced enterprise customization

### Example Configuration

```yaml
memory:
  retrieval:
    max_results: 5
    per_layer_budget:
      session: 1200
      agent_namespace: 1600
      shared_long_term: 2400
    lexical_enabled: true
    embedding_enabled: true
    llm_rerank: auto
    prefer_tags: [testing, workflow, preferences]
    suppress_tags: [temporary, scratch]
    stale_decay_days: 30

  extraction:
    obvious_fact_rules: default
    background_synthesis: enabled
    always_capture:
      - preference
      - project_convention
    never_capture:
      - transient_task
      - secret
      - scratch_status
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
    min_closed_sessions: 4
    min_hours_since_last_run: 12
    enable_background: true
```

## Alternatives Considered

### 1. 继续保持 v1 单层 memory manager

拒绝，因为这会继续把 session continuity、cross-session synthesis 与 agent-specific durable memory 混在一起，最终让 compaction 或 ad hoc rules 被迫承担错误职责。

### 2. 完全复制参考实现的 side-query 与 extractor orchestration

拒绝，因为 framework 需要：

- 更强的可解释性
- 更稳定的降级路径
- 更低的 provider 耦合
- 更可控的成本与延迟

### 3. 完全规则化 memory system

拒绝，因为纯规则无法覆盖隐式语义召回与高质量跨 session synthesis。

### 4. 完全 LLM-centric memory system

拒绝，因为纯模型路径会把每次 retrieval/extraction 都变成高成本黑盒行为，不适合 runtime framework。

## Risks / Trade-offs

- **[层次增多]** 四层 memory runtime 比 v1 更复杂。  
  Mitigation: 明确每层只负责单一时间尺度与单一写入目标。

- **[配置面扩大]** user-config surface 如果设计过宽，会把 memory runtime 变成策略泥团。  
  Mitigation: 固定 invariants，只开放声明式 knobs。

- **[双路径冲突]** obvious fact rules 与 background synthesis 可能重复写入。  
  Mitigation: 用 provenance、dedupe、routing precedence 与 conflict policy 统一收敛。

- **[embedding optionality]** 没有 embedding 时召回质量会下降。  
  Mitigation: lexical shortlist 必须可用，LLM rerank 为增强项而不是依赖项。

## Migration Plan

1. 先把 v1 `MemoryManager` 重构为 v2 `LongTermMemory` 基础层。
2. 增加 `AgentNamespaceMemory`，但保持 `user/project/local` 外部语义不变。
3. 引入独立 `SessionMemory` artifacts 与 refresh orchestration。
4. 将 current retrieval 流程替换为 staged mixed policy pipeline。
5. 将 current extraction 流程替换为 rules + background synthesis pipeline。
6. 引入 `ConsolidationMemory` worker、locks、checkpoints 与 topic memory output。
7. 最后补 user-config surface、observability 和 end-to-end tests。
