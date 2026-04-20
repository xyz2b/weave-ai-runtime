## Context

参考实现的 query runtime 不是围绕普通字符串消息递归，而是围绕 assistant `tool_use` block、user `tool_result` block 和发送前的 `normalizeMessagesForAPI()` / `ensureToolResultPairing()` 运转。当前 Python runtime 只有 `RuntimeMessage(content: str)`，tool result 在 turn 内被编码成 JSON 文本并塞回消息列表，这使第二轮 request 丢失 `tool_use_id` 和 block 结构，也让 transcript 恢复无法做结构修复。

这个 change 需要先把“消息协议骨架”立起来，后续的流式事件、abort、runtime assembly 和 golden tests 都基于这里定义的 contract。

## Goals / Non-Goals

**Goals:**

- 定义 provider-agnostic 的结构化 content block 模型，覆盖 query runtime continuation 需要的最小参考实现语义。
- 让 assistant tool use 与 user tool result 以稳定的 ID 关联形式跨 turn 保留。
- 在 transcript 持久化与恢复中无损保存 block 结构，并提供最小 legacy 兼容。
- 在 provider 调用前增加标准化和 pairing repair 层，为后续 stream/runtime 装配提供稳定输入。

**Non-Goals:**

- 本 change 不实现 provider 级流式事件拆分和 abort 信号，那是后续 stream contract change 的职责。
- 本 change 不追求一次性覆盖参考实现的所有 block 类型、UI message 类型或产品专用 metadata。
- 本 change 不处理 host adapter、permission UI 或 assembled runtime wiring。

## Decisions

### 1. 引入 provider-agnostic 的 block 模型，而不是继续复用 `content: str`

新增一组 Python 数据模型，例如：

- `TextBlock`
- `ToolUseBlock`
- `ToolResultBlock`
- `ThinkingBlock` / `RedactedThinkingBlock` 预留位

并让 API-bound `RuntimeMessage` 持有 `tuple[ContentBlock, ...]`。

Why:

- 参考实现风格 continuation 依赖 block 结构和 `tool_use_id`，这些信息不能稳定地放在字符串或 metadata 中。
- transcript、repair、golden fixture 都需要可序列化、可比较的稳定数据模型。

Alternatives considered:

- 继续用 `content: str` + `metadata.tool_calls`。拒绝，因为模型 continuation 看不到真正的 block 语义。
- 直接依赖某个 provider SDK 的 block 类型。拒绝，因为 runtime 需要保持 provider-agnostic。

### 2. 将 tool execution 输出建模为 user `tool_result` 消息，而不是 `MessageRole.TOOL`

保留 host-local 或调试路径上的 `TOOL` 角色空间，但 query runtime 的 continuation 路径必须把工具执行结果编码成 user message 中的 `tool_result` blocks。

Why:

- 参考实现的 continuation 语义就是 “assistant 发起 tool_use，user 返回 tool_result”。
- 只有这种表示法才能和 provider 发送前的 normalize/pairing 逻辑一致。

Alternatives considered:

- 继续把工具结果作为独立 `TOOL` role 回喂。拒绝，因为这不是参考实现风格 tool protocol，无法直接配对。

### 3. 新增单独的 message normalizer，而不是把 repair 逻辑散落在 turn engine

新增独立模块负责：

- 合并连续 user/assistant messages
- 规范化 tool 名称和 tool input
- 修复 `tool_use` / `tool_result` 配对
- 过滤不允许进入 provider 的 host-local message

Why:

- 参考实现把这部分视为 query runtime 的正式边界，而不是临时补丁。
- transcript 恢复、manual compact、stream fallback 等路径都需要复用同一套 repair 逻辑。

Alternatives considered:

- 只在 `TurnEngine.run_turn()` 中做局部修补。拒绝，因为恢复、resume 和未来 host 路径会重复造轮子。

### 4. transcript 采用无损 block 持久化，并对旧格式做 best-effort 兼容读取

新的 transcript entry 直接保存结构化 blocks。读取时若遇到旧格式的纯字符串消息，则将其映射成单一 `TextBlock`，但不再假装能从旧字符串恢复 `tool_use` / `tool_result` 关系。

Why:

- 一旦进入结构化协议，最重要的是不再继续丢信息。
- 兼容读取可以降低切换成本，但不能牺牲新协议的正确性。

Alternatives considered:

- 全量迁移旧 transcript。拒绝，因为当前没有足够信息安全地还原历史 tool pair。

## Risks / Trade-offs

- [协议改动面广] 会触及 contracts、transcript、turn engine 和测试夹具。 → Mitigation: 将 host-local message 与 API-bound message 的边界显式化，先只迁移最小 continuation 路径。
- [兼容复杂度] 旧 transcript 无法完全恢复结构化 tool pair。 → Mitigation: legacy 读取只承诺保留文本，不承诺伪造 tool/result 关系。
- [后续 change 依赖该模型] 如果 block 模型命名不稳，后续 stream/assembly 又会返工。 → Mitigation: 先定义 provider-agnostic 最小集合，不提前绑定 UI 或单一 provider 字段。

## Migration Plan

1. 引入新的 content block 数据模型和序列化格式。
2. 更新 transcript store 的写入路径，同时保留 legacy 读取兼容。
3. 在 turn engine 中把 assistant tool use 和 user tool result 改成结构化 continuation。
4. 在 provider 调用入口前接入 normalizer + pairing repair。
5. 后续 stream/assembly changes 改为消费结构化消息协议。

Rollback strategy:

- 若 block 协议引入不可接受回归，可临时回退到旧 transcript 写入路径，但必须保留新增 normalizer 模块接口，以免后续 change 再次耦合字符串协议。

## Open Questions

- 第一版是否需要把 `thinking` blocks 暴露到 transcript，还是只保留类型预留位？
- host-local 的 `MessageRole.TOOL` 是否保留给 UI/诊断用途，还是彻底从 query path 中移除？
