# 记忆模型

WeaveRT 把记忆视为一个分层运行时系统，而不是一个巨大的 prompt blob。

## 适合谁？

- 已经理解落地页定位、现在需要核心运行时词汇的使用者。

## 前置条件

- 先读 `../introduction/what-is-weavert.md`
- 如果你想把术语和可运行路径对应起来，快速浏览 `../getting-started/quickstart.md`

## 四层模型

### 长期记忆

用于存放应超出单个 session 存活期的共享持久事实。
典型例子包括：

- preferences
- conventions
- topics
- shared reference notes

典型持久根目录：

- `.weavert/memory/documents/`

### Agent namespace 记忆

限定到单个 agent namespace 的持久记忆。
当某个 agent 需要自己的持久笔记，但又不希望越过当前用户、项目或本地边界时使用它。

典型持久根目录：

- `.weavert/memory/agents/<agent>/documents/`

### Session 记忆

单个 session 的连续性工件。
Runtime 可以在这里保存：

- session summaries
- open threads
- session metadata

典型持久根目录：

- `.weavert/memory/sessions/<session>/`

### Consolidation 记忆

一种更慢的后台记忆工作，用于把有价值的 session 结果合并回更长期的记忆。
它不只是另一个 prompt-time 层，而是长期维护层。

典型持久根目录：

- `.weavert/memory/consolidations/`

## Retrieval 是混合式的

记忆检索遵循 “deterministic first, enhanced second” 的姿态。
典型流程是：

1. manifest 或 header 预筛选
2. 确定性的词法 shortlist
3. 可选的 embedding shortlist
4. 可选的 LLM rerank
5. 按层把结果 materialize 到 turn context

这样既保持了可检查性，也允许在配置后获得更强的排序能力。

## Extraction 也是分层的

记忆写入同样采用混合路径：

- 明显事实可以在主线程捕获
- 更高价值的综合可以在更慢的后台工作中完成
- consolidation 之后还能把多个已结束 session 的结果再合并

如果某条事实不应被存储，runtime 应在 diagnostics 或 receipts 中保留拒绝原因，而不是静默丢弃。

## 为什么这种设计重要

这个分层模型保护了几个关键边界：

- prompt-visible context 不等于整个 durable memory 系统
- session continuity 不应被视为 shared long-term memory 的同义词
- 后台 consolidation 不应在没有 diagnostics 的情况下悄悄重写 runtime truth
- memory policy 应能被配置，而不会破坏安全边界

## 普通用户通常最先需要什么

多数使用者一开始不需要替换整个 memory 子系统。
他们通常先需要理解：

- durable artifacts 存在哪里
- 某条事实属于哪一层
- retrieval 与 extraction 是如何组织的
- 如何通过配置而不是自定义代码来调优行为

## 下一步

- 使用 `../reference/memory-configuration.md` 来配置或检查分层 memory policy
- 当你需要更广义的 durable-state 所有权地图时，读 `../architecture/persistence-and-state.md`

## 另见

- `hosts-permissions-memory.md`
- `../reference/memory-configuration.md`
- `../architecture/persistence-and-state.md`
- `../deep-dives/layered-memory-weavert-v2.md`
