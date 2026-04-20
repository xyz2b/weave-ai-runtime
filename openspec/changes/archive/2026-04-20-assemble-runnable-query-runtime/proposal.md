## Why

即使消息协议和 stream contract 都补齐，runtime 仍然不会自动变成可运行系统。当前 kernel 只装 registry，不装 `TurnEngine`、`AgentRuntime`、`SkillExecutor`、`SessionController` 和 handler wiring；因此模型真正发出 `agent` 或 `skill` tool call 时，builtin tool 仍会因为缺少 runner 而失败。

## What Changes

- 在 runtime kernel 之上新增正式的 runtime assembly 层，负责构造 `TurnEngine`、`AgentRuntime`、`SkillExecutor`、session factory、transcript store 和 host-facing runtime handle。
- 通过 assembly 统一注入 `agent_runner`、`skill_runner`、`permission_handler` 和 `ask_user_handler`，让模型生成的 builtin `agent` / `skill` tool path 真正可执行。
- 扩展 `ToolContext`，加入 turn-scoped messages、abort handle、notifications、tool refresh callback 等 query runtime 所需上下文。
- 让 `SessionController` 和 host adapter 消费 turn stream，而不是各自重写 orchestration。
- 将当前基于 `/tool`、`/skill`、`/agent` 字符串的 direct-route 路径降级为调试/兼容旁路，而不是主线程 routing 的主要证明。

## Capabilities

### New Capabilities

- `query-runtime-assembly`: 可运行的 query runtime 装配层，包括 handler wiring、session execution surface 和 host-independent runtime stack。

### Modified Capabilities

- 无。

## Impact

- 影响 `src/claude_agent_runtime/runtime_kernel/*`、`src/claude_agent_runtime/turn_engine/engine.py`、`src/claude_agent_runtime/agent_runtime.py`、`src/claude_agent_runtime/skill_runtime.py` 与 `src/claude_agent_runtime/session_runtime/controller.py`。
- 需要新增正式的 runtime assembly 数据结构和 host-facing session/run surface。
- 会改变 builtin `agent` / `skill` tools 的真实执行路径，并为后续最小 interactive/headless host 提供统一入口。
