## Why

当前 runtime 的 tools 子系统已经具备重 `ToolContext`、共享 permission/hook control plane 和基础调度器，但核心执行模型仍然停留在“assistant message 完整结束后再批量执行 tools”。这和参考实现依赖的 streaming tool runtime 仍有明显偏差，尤其体现在工具契约、输入相关并发语义、sibling failure policy，以及 progress / capability refresh 的控制面打通上。

## What Changes

- 将现有偏静态的 tool definition 扩展为更完整的 runtime capability contract，引入 `ToolExecutionSemantics` 与 call-scoped resolved semantics snapshot，让调度、权限、UI 和自动分类共享同一份运行语义，而不是只依赖静态 traits。
- 引入 capability-aware 的 `StreamingToolExecutor` 体系，使 runtime 根据 provider 实际暴露的 tool-calling / stream 能力，在 `FullStreaming`、`Buffered` 和 `Batch` 三层执行模式间自动选择并在不足时自动降级。
- 为 tool orchestration 增加输入相关并发分类、原始 `tool_use` 顺序回放，以及 fatal sibling failure cascade 语义。
- 将 `ToolContext` 升级为显式 capability container，拆出 catalog、query、state、progress、notifications、refresh 和 memory access 等标准 capability，并避免 tools 直接依赖宽泛的 `runtime_services` / `metadata` 结构。
- 将工具调用生命周期显式建模为 `ToolCallEnvelope`、`ResolvedToolCall` 和 `ToolOutcome`，把最终输入冻结、resolved semantics、scheduler lane、ordered replay 和 terminal result 串成一条稳定主线。
- 打通 tool progress 和 capability refresh 到 host bridge 与 execution policy/control plane，避免它们停留在 tool-local callback 层。
- 补充针对 early start、ordered replay、fatal failure、progress 和 refresh 的 conformance tests，防止后续实现再次退化回 batch-only 行为。

## Capabilities

### New Capabilities

- `tool-runtime-capability-contract`: richer tool contract、显式 runtime capability context，以及 legacy tool compatibility adapter。
- `streaming-tool-orchestration`: capability-tiered `StreamingToolExecutor`、streamed `tool_use` early start、自动降级、输入相关并发 lane、ordered replay 和 sibling failure cascade。
- `tool-runtime-progress-and-refresh`: tool progress 事件与 capability refresh 经由 shared control plane 和 host bridge 生效。

### Modified Capabilities

- 无。

## Impact

- 主要影响 `src/runtime/definitions.py`、`src/runtime/tool_runtime.py`、`src/runtime/turn_engine/engine.py`、`src/runtime/turn_engine/models.py`、built-in tools，以及 host/control-plane wiring。
- 很可能新增 `src/runtime/tool_lifecycle.py`、`src/runtime/tool_resolution.py`、`src/runtime/tool_orchestration.py`、`src/runtime/tool_executors.py` 这类按 ownership 拆分的模块，并让 `tool_runtime.py` 退回兼容 facade。
- 会影响 `ToolDefinition`、`ToolContext`、tool discovery / builtin wiring 以及与 permission、host UI、classifier、memory 的交界面。
- 会引入新的 tool call lifecycle object model，并影响 tool execution pipeline、scheduler、permission flow 和 replay buffer 的边界。
- 会让 `TurnEngine`、`SessionController` 和 host adapter 通过 first-class turn events 消费 tool lifecycle，而不是只看 transcript/message 结果。
- 很可能引入新的 tool orchestration 模块和 capability selector，用来承接 tiered execution、automatic downgrade 与 ordered replay，而不是继续把批量调度内嵌在 `TurnEngine` 中。
- 会改变部分工具结果语义，尤其是 `bash` 这类 currently-successful-but-exit-code-nonzero 的边界。
- 需要新增 turn-level golden / conformance tests，覆盖 tool runtime 的时序与失败传播语义。
