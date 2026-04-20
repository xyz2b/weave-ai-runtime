## Why

当前 Python runtime 只能在简化的 fake model 场景下完成 `model -> tool -> model` 循环，因为 assistant 的 tool use 与 tool result 在回喂前已经被压平成普通字符串。只要接入更接近 Claude Code 的真实 query path，这种扁平化就会破坏 continuation、transcript 恢复和 tool/result 配对修复，因此必须先补齐消息协议骨架。

## What Changes

- 将 API-bound turn history 从 `content: str` 升级为结构化 content blocks，至少保留 `text`、`tool_use`、`tool_result` 以及预留的 thinking block 类型。
- 将当前 “assistant metadata + JSON 字符串 tool message” 的 continuation 形式替换为 Claude 风格的 assistant `tool_use` block 和 user `tool_result` block。
- 在 provider 调用前新增 message normalization 与 tool/result pairing repair 层，负责合并连续消息、规范化 tool payload 和修复断裂的 tool/result 结构。
- 升级 transcript 持久化格式，使其无损保存 block 结构，并为现有扁平 transcript 提供兼容读取路径。
- 调整 turn engine 的下一轮回喂逻辑，确保模型看到的是结构化的前一轮 assistant/user 语义，而不是调试用字符串。

## Capabilities

### New Capabilities

- `query-message-protocol`: Claude 风格的结构化消息协议、tool/result 配对修复与 transcript 无损持久化。

### Modified Capabilities

- 无。

## Impact

- 影响 `src/claude_agent_runtime/contracts.py`、`src/claude_agent_runtime/session_runtime/transcript.py`、`src/claude_agent_runtime/turn_engine/engine.py` 与所有依赖 `RuntimeMessage.content` 的路径。
- 需要新增 message normalization / pairing repair 模块，并定义新的 content block 数据模型。
- 会改变 turn engine 中 tool result 的内部表示方式，以及后续 stream/assembly/change 的接口假设。
