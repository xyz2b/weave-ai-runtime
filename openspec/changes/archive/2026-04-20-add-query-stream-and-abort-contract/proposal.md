## Why

在消息协议对齐之后，runtime 仍然缺少参考实现风格的流式 query contract。当前模型接口只有粗粒度 event，host 看不到请求生命周期或 block 级增量，中断也无法终止正在进行的模型流，因此还不能构成真实可交互的 query runtime。

## What Changes

- 扩展模型请求与流式事件 contract，引入 abort-capable request、request lifecycle metadata、block-level raw streaming event、terminal stop metadata。
- 将 turn engine 拆分为 async streaming 主接口和结果聚合包装接口，使 host 可以像参考实现一样消费 turn event stream。
- 在 turn engine 中加入 assistant block accumulator，按 block 生命周期生成结构化 assistant messages，而不是只在最后拼接文本。
- 定义中断、stream fallback 和 partial output 的丢弃/修复规则，避免半截消息继续污染下一轮上下文。
- 向上层暴露 request id、stop reason、usage、TTFT 等 turn terminal 信息，为 host 和后续 golden tests 提供稳定观测点。

## Capabilities

### New Capabilities

- `query-turn-stream`: 参考实现风格的 turn stream、abort contract、terminal metadata 和 partial-output 处理语义。

### Modified Capabilities

- 无。

## Impact

- 影响 `src/runtime/turn_engine/models.py`、`src/runtime/turn_engine/engine.py` 以及未来的 provider adapter 实现。
- 需要引入新的 turn event 类型，并让 session/host 层改为消费 event stream 而非仅消费最终 messages。
- 会为后续 runtime assembly 和 golden verification 提供统一的 turn execution observability contract。
