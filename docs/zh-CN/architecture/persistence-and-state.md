# 持久化与状态

WeaveRT 会维护多种 durable state。
把它们区分开，能让调试和产品集成都更容易。

## 适合谁？

- 正在评估 runtime 在底层如何被组装、执行和持久化的读者。

## 前置条件

- 先读 `../concepts/runtime-model.md`
- 在把这层当作更深的架构层之前，先用相关 concept 页面补足词汇

## 常见 durable artifacts

- transcripts
- child runs
- task lists 与 jobs
- memory artifacts
- workflow reports 与 host 可观察 diagnostics

## 典型根目录

项目本地 durable state 通常位于 `.weavert/` 下。
某些 app samples 会把这部分 runtime-owned state 放到更高层的本地根目录，例如 `.local/examples/.../.weavert/`。

常见例子包括：

- `.weavert/transcripts/`
- `.weavert/child_runs/`
- `.weavert/task_lists/`
- `.weavert/jobs/`
- `.weavert/memory/`

Memory 相关子树常见包括：

- `.weavert/memory/documents/`
- `.weavert/memory/agents/<agent>/documents/`
- `.weavert/memory/sessions/<session>/`
- `.weavert/memory/consolidations/`

## 所有权比目录名更重要

一个实用视角是：

- session 拥有 transcript continuity
- delegated execution surfaces 拥有 child-run records
- memory services 拥有 memory artifacts
- host 可以展示或镜像状态，但不应悄悄替代 runtime 权威

## 不要假设持久化一定自动存在

最容易犯的错误之一，就是假设 transcript 与 child-run 默认总会持久化。
实际情况里，持久化取决于已配置的 stores 与 assembly posture。

请显式问这些问题：

- 当前是否配置了 transcript store？
- 当前是否配置了 child-run store？
- 当前样例使用的是可变 app workspace，还是普通 project root？

Memory 也是同理：retrieval、extraction 与 consolidation posture 取决于活跃配置和服务，而不是某个硬编码全局默认值。

## Memory 与 consolidation runtime

Memory persistence 不只是存储 documents。
它还包括更慢的 consolidation 工作，用于在多个已关闭 sessions 之间 checkpoint、stage 和 merge 结果。

典型 consolidation artifacts 包括：

- `consolidations/checkpoints/<run-id>.json`
- `consolidations/staging/<run-id>.json`
- `consolidations/logs/<run-id>.md`
- `manifests/consolidation-manifest.json`

这些工件有助于解释 backlog、active locks，以及某次后台 merge 成功还是失败。

## Diagnostics 与 observability

当持久化问题涉及 memory 时，有用的信号可能包括：

- retrieval traces
- write receipts
- background memory task ids
- config-source warnings
- `last_consolidated_at`
- durable memory deltas

## 重要区分

- durable transcript truth 不等于当前投影的 prompt context
- runtime-private control-plane state 应与模型可见上下文分离
- app-level 的可变工作区可以包裹 runtime-owned state，但不应遮蔽它

## 为什么用户关心

这种分离能帮助你判断故障来自：

- route setup
- prompt projection
- tool execution
- durable-state ownership
- host-specific wiring

## 下一步

- 当下一步任务是调整 memory retrieval 或写入行为时，进入 `../reference/memory-configuration.md`
- 如果持久化问题其实是 host-owned lifecycle 与 shutdown，读 `../guides/bind-a-host.md`
- 当你需要验证命令与可观测性表面时，进入 `../guides/testing-and-observability.md`

## 另见

- `../concepts/hosts-permissions-memory.md`
- `../concepts/memory-model.md`
- `../reference/memory-configuration.md`
- `../deep-dives/layered-memory-weavert-v2.md`
- `../../../examples/apps/code_assistant/README.zh-CN.md`
- `../deep-dives/current-system-architecture.md`
