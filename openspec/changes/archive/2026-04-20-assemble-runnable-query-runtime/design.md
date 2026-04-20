## Context

当前 Python runtime 里已经存在 `TurnEngine`、`AgentRuntime`、`SkillExecutor`、`SessionController` 等零件，但它们没有被一个正式 assembly 层组装成可运行系统。`build_runtime_kernel()` 只产出 registries 与 config 容器，`assemble_host_runtime()` 只绑定空 host；与此同时，builtin `agent` / `skill` tools 需要 `context.agent_runner` / `context.skill_runner`，而这两个 handler 目前没有正式 wiring。参考实现的 REPL 路径会先构造完整的 `ToolUseContext`、system prompt、tool/agent definitions，再调用统一的 `query()`。这个 change 的目标是把 Python runtime 也提升到“正式装配”的层次，而不是继续依赖测试手工拼对象。

## Goals / Non-Goals

**Goals:**

- 提供一层正式的 runtime assembly，把 kernel、turn engine、agent runtime、skill executor、session controller 和 host surface 组装为可运行栈。
- 让模型生成的 builtin `agent` / `skill` tool 调用走正式 runtime path。
- 让 host 通过统一的 session/turn interface 消费 stream，而不是自己重写 orchestration。
- 扩展 `ToolContext` 到足够承载 query runtime 所需 turn-scoped 状态。

**Non-Goals:**

- 本 change 不追求 REPL、Ink 或 SDK 的完整产品级 UI 复刻。
- 本 change 不负责完善 memory、hooks、MCP、plugin 等后续子系统。
- 本 change 不要求移除所有 direct-route 兼容路径，只要求它们不再是主路径成功的前提。

## Decisions

### 1. 引入独立的 runtime assembly 层，而不是继续把实例拼装散落在测试和 host 中

新增一个正式 assembly 对象，负责创建：

- `TurnEngine`
- `AgentRuntime`
- `SkillExecutor`
- `SessionController` factory
- host-facing runtime handle

Why:

- kernel 负责 definitions 和 configuration，assembly 才负责可运行实例生命周期。
- 这样可以让 interactive 和 headless host 共享完全相同的 runtime core。

Alternatives considered:

- 继续让每个 host 或测试自己拼 runtime。拒绝，因为这会重复 wiring 并掩盖真实运行缺口。

### 2. handler wiring 统一在 assembly 中完成

`agent_runner`、`skill_runner`、`permission_handler`、`ask_user_handler` 必须由 assembly 统一注入到 `TurnEngine`，而不是靠调用方手工传入。

Why:

- builtin `agent` / `skill` tools 是 runtime pack 的正式能力，不能依赖测试夹具才能工作。
- 统一 wiring 可以避免 `AgentRuntime`、`SkillExecutor` 和 `TurnEngine` 之间出现不一致上下文。

Alternatives considered:

- 在 builtin tools 内部直接 new 运行时对象。拒绝，因为会引入隐藏依赖和循环装配。

### 3. `ToolContext` 向参考实现风格的 `ToolUseContext` 收敛，但只做 query runtime 最小集

扩展 `ToolContext` 至少包含：

- 当前 turn messages
- request abort handle
- notifications sink
- tool refresh callback
- turn/session metadata

Why:

- 真实工具执行需要看到 turn 上下文，而不仅是 cwd 和 registries。
- 后续 hooks、host adapters 和 mid-turn tool refresh 也需要复用这一上下文层。

Alternatives considered:

- 只在个别工具里加额外参数。拒绝，因为会把 query runtime 状态散落到具体工具实现中。

### 4. `SessionController` 以 turn stream 为主驱动接口

`SessionController` 不再只收集最终 messages，而是驱动 turn stream、append transcript、处理 queued commands 和 interrupt/resume 状态。

Why:

- 上一 change 已经把 stream contract 提升为一等接口，session 层必须顺着这个接口工作。
- 这样 host 才能用统一方式处理 interactive 与 headless execution。

Alternatives considered:

- session 层继续只调用 `run_turn()` 聚合接口。拒绝，因为 host 看不到真实 turn progress。

## Risks / Trade-offs

- [装配层引入更多对象关系] `TurnEngine`、`AgentRuntime` 和 `SkillExecutor` 之间存在循环依赖风险。 → Mitigation: 使用显式 factory/wiring 阶段，避免运行时懒创建互相引用。
- [ToolContext 变宽] 新增上下文字段会提高工具接口复杂度。 → Mitigation: 只引入 query runtime 必需字段，其余能力通过可选回调扩展。
- [host surface 过早抽象] 太早做大一统 host API 可能返工。 → Mitigation: 先定义最小 interactive/headless 共用 surface，再逐步扩展。

## Migration Plan

1. 新增 runtime assembly 层和可运行 runtime handle。
2. 将 `TurnEngine`、`AgentRuntime`、`SkillExecutor` 和 `SessionController` 的构造迁移到 assembly。
3. 统一注入 agent/skill/permission/ask-user handlers。
4. 扩展 `ToolContext`，并让 session 层基于 turn stream 驱动执行。
5. 调整 `assemble_host_runtime()` 与最小 host adapter 以消费 assembled runtime。

Rollback strategy:

- 如果 assembly 接口需要调整，可暂时保留旧的 kernel-only path 供测试使用，但 builtin `agent` / `skill` tool 的主路径 wiring 不应回退到“未配置 runner”的状态。

## Open Questions

- minimal host-facing runtime handle 是直接暴露 `create_session()`，还是暴露更高层的 `prompt()` / `stream()` convenience API？
- direct-route `/agent` `/skill` helpers 在第一版 assembly 完成后是否保留为 public debug surface？
