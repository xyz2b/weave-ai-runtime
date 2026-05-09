# 宿主、权限与记忆

这些都属于 control-plane 关注点。
它们影响的是 runtime 如何运行，而不只是某个 agent 说什么。

## 适合谁？

- 已经理解落地页定位、现在需要核心运行时词汇的使用者。

## 前置条件

- 先读 `../introduction/what-is-weavert.md`
- 如果你想把术语和可运行路径对应起来，快速浏览 `../getting-started/quickstart.md`

## Hosts

Host 是面向产品的一层，拥有生命周期与 UX。
典型 host 包括 CLI shell、SDK wrapper、web backend 或 app shell。

Host 通常负责：

- startup 与 shutdown
- approvals 与 elicitation
- notifications 与 turn-event rendering
- 应用特定的本地命令或展示逻辑

绑定 host 后，推荐使用分组后的 bound surfaces，而不是平铺接口：

- `bound.prompts`
- `bound.sessions`
- `bound.hooks`
- `bound.inspection`
- `bound.work`

## Permissions 与 elicitation

Permissions 让高风险动作保持显式。
尤其适用于：

- write tools
- shell commands
- network access
- delegated agents 或长时间运行的工作

Host 可以参与审批决策，但 runtime 仍拥有“请求了什么、在何时请求”这一控制面语义。

Elicitation 与之相邻：当 runtime 需要更多人工输入时，host 往往负责提问、渲染上下文并把答案传回。

## Prompt-safe 上下文与 runtime-private 状态

这是 WeaveRT 里最重要的设计规则之一。

- prompt-visible context 应只包含对模型安全的 memory、attachments 和 session hints
- runtime-private state 应把 permissions、diagnostics、route metadata 和执行策略隔离在 prompt 外

即便模型不应看到这些私有状态，tools、hosts 和 runtime services 仍可能需要访问它们。

## Memory 是分层的，而不是一个 prompt 字段

WeaveRT 将持久工件与 prompt 可见上下文分开。
更高层的 memory model 在 `memory-model.md` 中，这里只给出简要总结：

- long-term memory
  - 共享的持久记忆，如偏好、约定和主题
- agent namespace memory
  - 限定在单个 agent namespace 下的持久笔记
- session memory
  - 单个 session 的连续性工件
- consolidation memory
  - 更慢的后台聚合与合并工作

## 为什么这种分离重要

需要记住的几个区分：

- transcript truth 不等于当前投影出的 prompt context
- runtime-private state 不应泄漏到 prompt-visible context
- durable memory、child runs、tasks 与 jobs 应保持可检查

## 什么时候应从简单项目转向 host binding

如果你只需要本地 tools、agents 或 skills，就继续沿 starter 与 ordinary workflow 路径走。
只有在需要下面这些能力时，再进入 host binding：

- approval UX
- 更长生命周期的 sessions
- turn-event rendering
- 应用特定本地命令
- 产品拥有的 durable state 展示

## 下一步

- 当你需要生命周期、审批或展示所有权时，进入 `../guides/bind-a-host.md`
- 当你需要 hooks、permissions、elicitation 或 tool refresh seam 时，进入 `../guides/extend-the-control-plane.md`
- 当问题更具体地落在 memory 行为上时，读 `memory-model.md`

## 另见

- `memory-model.md`
- `../guides/bind-a-host.md`
- `../guides/extend-the-control-plane.md`
- `../guides/register-hooks.md`
- `../guides/testing-and-observability.md`
- `../architecture/persistence-and-state.md`
- `../reference/memory-configuration.md`
- `../deep-dives/layered-memory-weavert-v2.md`
