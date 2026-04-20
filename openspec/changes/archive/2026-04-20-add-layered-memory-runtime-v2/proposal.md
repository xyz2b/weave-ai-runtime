## Why

当前 memory 子系统已经完成 v1：`MEMORY.md` 入口、`user/project/local` scopes、pre-turn retrieval、post-turn extraction 与 path guard 都已具备。但它仍然是单层 durable memory control plane，而不是参考实现那种按时间尺度和作用范围拆开的 layered memory runtime。

当前缺口主要有四类：

- 缺少独立 `SessionMemory`，长会话连续性主要依赖 compaction summary 近似承担。
- 缺少跨 session 的慢速 `ConsolidationMemory`，没有 topic-level durable synthesis。
- 缺少真正的 `AgentNamespaceMemory`，agent 目前只有 scope ceiling，没有独立持久工作记忆。
- 检索与抽取策略仍是轻量规则实现，尚未形成“确定性 shortlist + 可选模型参与”的混合式 policy。

memory v2 的目标不是推翻参考实现兼容语义，而是在保留参考实现风格外部心智模型的前提下，把内部实现升级成更适合 runtime framework 的 layered architecture。

## What Changes

- 新增 layered memory runtime 设计，明确 `LongTermMemory`、`SessionMemory`、`ConsolidationMemory`、`AgentNamespaceMemory` 四个服务边界。
- 将 memory retrieval 设计为混合式策略：manifest/header 预筛、lexical/embedding shortlist、可选 LLM rerank、预算控制与 provenance 保留。
- 将 memory extraction 设计为混合式策略：规则抽取 obvious facts，后台受限 agent 做高质量归纳和 consolidation。
- 增加声明式 user-config surface，让项目或用户可以调 retrieval/extraction policy，而不是一开始就开放任意可执行 hook。
- 明确 `SessionMemory` 与 compaction 的边界，避免把 long-context compaction 误当成会话记忆系统。

## Capabilities

### New Capabilities

- `layered-memory-runtime`: 定义 memory v2 的分层服务、混合式 policy 与配置表面。

### Modified Capabilities

- `runtime-memory-manager`: 从单层 reference-style memory manager 扩展为 layered memory runtime 的长期记忆基础层。

## Impact

- 影响 `src/runtime/memory/`、`src/runtime/session_runtime/`、`src/runtime/turn_engine/`、`src/runtime/tool_runtime/` 与 built-in memory skills 的语义边界。
- 会引入新的 memory artifact layout、background extraction/consolidation orchestration 与更清晰的 provenance/namespace model。
- 为后续多模型部署、成本控制、可解释性调试和跨 session 记忆演化提供更稳定的基础。
