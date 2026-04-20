## Why

当前 runtime 在 agent/tool 的执行骨架上已经成立，但和参考实现相比，模型对可委派 agent 的认知、`agent` tool 的调用表达力、child agent 的可观测性，以及 route-aware / buffered tool execution 的行为完整度仍有明显缺口。现在收口这些行为差距，可以让现有实现从“架构正确”提升到“产品行为可用且可预期”。

## What Changes

- 在主线程 prompt 组装中显式暴露可用 agent catalog，并强化 `main-router` 的 routing 指令，使模型能更稳定地在直答、tool、skill 和 subagent 之间做选择。
- 扩充内置 `agent` tool 的输入 contract 和返回 payload，支持更完整的 child execution shaping，包括 `spawn_mode`、`cwd`、`model`、`model_route` 等显式控制面。
- 为 sync、background、fork、denied 和 early-failed child agent runs 补齐稳定的 run record、child message history 和 host-visible lifecycle。
- 将 agent-level `model_route` / `model` 从 metadata 字段提升为真实执行行为，使不同 agent 能稳定选择不同 route，并把 resolved route 写入 child run metadata。
- 在 `TurnEngine` 中补齐 buffered / non-stream completion path，使只能在完整响应后产出 tool call 的 provider 也能走统一的 tool-call continuation contract。

## Capabilities

### New Capabilities
- `agent-delegation`: 暴露 agent catalog 给模型，强化 router prompt，并扩展 `agent` tool 的 delegation contract。
- `child-run-observability`: 为 child agent execution 提供稳定的 run identity、terminal metadata、message history 和 lifecycle 观测面。
- `route-aware-tool-execution`: 让 agent route selection 和 buffered/non-stream tool execution 成为正式 runtime 行为。

### Modified Capabilities
- None.

## Impact

- Affected code: `src/runtime/contracts.py`, `src/runtime/turn_engine/composer.py`, `src/runtime/turn_engine/engine.py`, `src/runtime/turn_engine/models.py`, `src/runtime/builtins/agents.py`, `src/runtime/builtins/tools.py`, `src/runtime/builtins/tool_impls.py`, `src/runtime/agent_runtime.py`, `src/runtime/agent_dispatcher.py`, `src/runtime/agent_execution.py`, `src/runtime/agent_execution_service.py`, `src/runtime/runtime_kernel/config.py`, `src/runtime/runtime_kernel/kernel.py`.
- Affected tests: `tests/test_agent_skill_runtime.py`, `tests/test_streaming_tool_runtime.py`, and new coverage for child-run persistence and route-aware model execution.
- Runtime behavior: child agent selection, delegation payload shape, child run observability, model route resolution, and tool execution mode selection.
