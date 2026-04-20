## Why

当前 runtime 已经不是简单的 ReAct loop，而是 `SessionController` 命令循环叠加 `TurnEngine` 流式迭代循环的两层执行骨架；其正确的规范表面应当是 async generator 驱动的事件流，而不是只返回最终消息的 helper。但主循环状态仍然分散在 `SessionState.metadata`、`TurnEngine` 的局部变量和 session 级后处理里，导致 continuation 原因、预算/恢复路径、memory sidecar 和 stop-phase 语义都还是隐式约定，后续继续叠加 memory、compaction、hooks 和多 provider 行为会越来越脆弱。

现在需要在不推翻现有分层的前提下，把 Runtime 主循环提升为一个显式、可观察、可恢复的流式状态机 contract，先把控制面边界做稳，再继续扩展功能。

## What Changes

- 引入显式的 Runtime 主循环状态机 contract，覆盖 turn preparation、sidecar 预取、compaction、模型流式输出、tool replay、stop handling、budget/recovery 和 continuation transition。
- 明确 `run_turn_stream()` / `stream_until_idle()` 所代表的 async generator event stream 是 Runtime 主循环的 canonical surface，聚合 helper 只能建立在这条流之上。
- 保留当前 `SessionController -> TurnEngine -> StreamingToolOrchestrator` 的分层，不复制 Claude Code 那种巨型单文件 `query.ts` 实现。
- 为每轮 continuation 增加结构化 transition reason 和 phase metadata，使 host、tests 和后续控制面逻辑能够解释“为什么继续、为什么阻塞、为什么恢复、为什么结束”。
- 定义 pre-turn sidecar 和 post-turn effects 的统一边界，让 memory retrieval、hook context、compaction artifacts、session persistence 和 background extraction 不再通过隐式时序耦合。
- 收紧 host-facing terminal contract：`TERMINAL` 只保留 turn-final 语义，旧的 `TERMINAL(stop_reason=tool_use)` 等 attempt-final 消费方必须迁移到 `ATTEMPT_FINISHED` 或等价 attempt metadata。
- 补齐 runtime 级 budget / recovery 设计；第一阶段只统一 `max_tokens` / 输出预算、tool-result 增长和 reactive compaction 三类恢复入口，provider retry/fallback 等更深策略后置。
- 将 `PreCompact` / `PostCompact` 等已声明但尚未真正接入主循环的 phase 纳入统一状态机设计。
- 明确由 runtime 统一接管 turn-scoped 的上下文装配、工具编排、记忆 sidecar、预算、恢复和状态转移，而不是把这些决策散落给 provider、host 或单个工具子系统。

## Compatibility / Scope Guardrails

- 这是一个显式的兼容性迁移 change：所有依赖 host-facing `TERMINAL(stop_reason=tool_use)` 作为“继续执行”信号的 host、client、adapter 和 tests，都必须在同一批迁移到 `ATTEMPT_FINISHED` 或等价 attempt-level contract。
- 兼容过渡期允许镜像旧字段，但这些字段只能作为辅助调试信息，不能继续作为 authoritative 判断条件。
- 第一阶段不试图一次性收敛所有 provider recovery 策略；provider retry/fallback 保持 deferred decision，只要求先把最关键的 budget/recovery join point 与 continuation contract 稳定下来。

## Capabilities

### New Capabilities
- `runtime-main-loop-state-machine`: 定义 Runtime 主循环的 async-generator canonical surface，以及显式状态、phase、transition reason、sidecar orchestration、stop handling 和 recovery contract。

### Modified Capabilities

## Impact

- 影响 `src/claude_agent_runtime/turn_engine/`、`src/claude_agent_runtime/session_runtime/`、`src/claude_agent_runtime/runtime_services/`、`src/claude_agent_runtime/tool_executors.py`、`src/claude_agent_runtime/tool_orchestration.py`、`src/claude_agent_runtime/memory/` 与 `src/claude_agent_runtime/compaction/` 的主循环边界。
- 影响 host 可观察事件、terminal metadata、turn-level diagnostics 和 runtime conformance tests。
- 影响所有仍把 `TERMINAL(stop_reason=tool_use)` 视为 attempt-final signal 的现有消费方，它们必须切换到新的 attempt-level event/metadata。
- 为后续 memory、compaction、hook、route fallback、budget guard 和 long-running session 行为提供统一延展点。
