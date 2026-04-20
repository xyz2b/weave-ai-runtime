## Why

当前 runtime 已经形成 `RuntimeAssembly -> SessionController -> TurnEngine` 的主骨架，但仍缺少三个关键边界：session ingress 仍然是事件直通、runtime 私有控制面状态会泄露到模型可见 prompt、host/session/runtime 的生命周期 owner 仍然交叉。随着 interactive/headless host、agent execution 和更多控制面能力继续叠加，这些边界不先补齐，后续复杂度会持续堆积在 `SessionController` 和 `TurnEngine` 里。

## What Changes

- 引入独立的 session ingress 能力，在 turn 执行前统一完成 inbound event 归一化、附加上下文注入、是否进入 query 的判定和 ingress 结果投影，并把 ingress 结果固定为正式协议对象。
- 将模型可见 prompt context 与 runtime 私有 execution context 分离，采用强类型 envelope 承载两类上下文，避免权限、policy、diagnostics、host/runtime metadata 被直接拼入 system prompt，同时保留它们在 runtime 和 tool execution 中的可用性。
- 重新定义 host、runtime assembly、session controller 的 lifecycle ownership，明确 startup/shutdown、session start/end 和 convenience helper 的责任边界，并让 `BoundHostRuntime` 成为显式 host scope owner。
- 扩展 runtime contract 和 conformance coverage，使 ingress 结果、context 边界和 lifecycle 事件可以被测试和 host surface 稳定消费。
- 收紧若干 public-ish runtime surface 的语义边界：`TurnContext` 变成 prompt-safe carrier，`ToolContext` 与 `ModelRequest` 显式承载 non-prompt private context，而 `run_prompt()` / `stream_prompt()` 明确只保证 helper-owned session close，不隐式拥有 host shutdown。

## Capabilities

### New Capabilities
- `runtime-session-ingress`: 定义 session 级输入归一化、上下文注入和 turn admission contract。
- `runtime-prompt-context-boundaries`: 定义 prompt-visible context 与 runtime-private context 的分离和装配边界。
- `runtime-lifecycle-ownership`: 定义 host/runtime/session 生命周期 owner、关闭语义和 helper contract。

### Modified Capabilities
- None. This change adds new capability contracts while tightening the semantics of existing runtime surfaces through those contracts.

## Impact

- Affected code: `src/runtime/session_runtime/`, `src/runtime/turn_engine/`, `src/runtime/runtime_kernel/`, `src/runtime/runtime_services/`, `src/runtime/hosts/`, `src/runtime/tool_runtime.py`
- Affected contracts: `TurnContext`, `ToolContext`, `ModelRequest`, session ingress/result model, prompt/private context carriers, runtime helper surfaces, host lifecycle interfaces
- Affected systems: headless runtime, host bridge, memory/hooks/compaction sidecars, runtime protocol/conformance tests
- Public-ish surface migration notes: `TurnContext.metadata` no longer acts as the authoritative private metadata carrier, `ToolContext` and `ModelRequest` continue exposing runtime-private state only through non-prompt channels, and one-shot helpers guarantee session close but not outer host shutdown.
