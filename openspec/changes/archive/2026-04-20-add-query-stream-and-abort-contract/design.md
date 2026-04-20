## Context

参考实现的 `query()` 既是 conversation loop，也是 host 与 provider 之间的事件桥。它不仅返回最终消息，还会产出 request start、raw stream event、assistant message、tombstone 和 terminal reason，并把 abort signal 贯穿到模型流调用。当前 Python runtime 的 `ModelRequest` 和 `ModelStreamEvent` 过于简化，`TurnEngine.run_turn()` 也只在流结束后返回聚合结果，因此 host 无法消费真实 stream，中断也只能停止工具而不能停止模型。

这个 change 以新的结构化消息协议为前提，负责补齐“query runtime 的流式与中断骨架”。

## Goals / Non-Goals

**Goals:**

- 定义比当前更接近参考实现的模型流协议和 turn stream 协议。
- 让模型请求携带 abort handle，并让 turn engine 能可靠终止慢流。
- 让 host 可以消费统一的 turn event stream，而不是自己拼装 provider 事件。
- 在 partial output、fallback 和 interrupt 场景下明确 discard/repair 规则。

**Non-Goals:**

- 本 change 不负责 assembled runtime wiring、agent/skill handler 注入或 host adapter 实现细节。
- 本 change 不追求一次性复刻参考实现的所有产品遥测和 feature gate。
- 本 change 不处理 transcript 长期持久化格式，那由消息协议 change 负责。

## Decisions

### 1. 区分 provider raw stream contract 与 host-facing turn stream contract

provider adapter 负责把底层 SDK 事件转换为统一 raw stream event；turn engine 再基于这些 raw event 构造 assistant blocks、tool use state 和 host-facing turn events。

Why:

- 参考实现里 `provider-adapter.ts` 和 `query.ts` 也是分层的：一个处理 provider raw stream，一个处理 turn loop。
- 这样可以让 provider 适配和 host 消费都保持稳定边界。

Alternatives considered:

- 让 host 直接消费 provider raw event。拒绝，因为 host 会重新承担 block assembly 和 continuation 决策。

### 2. `run_turn_stream()` 成为 turn engine 的主接口，`run_turn()` 退化为聚合包装

新增 async generator 接口，产出：

- request start
- stream event
- finalized assistant/user/system message
- terminal metadata

`run_turn()` 继续保留，内部消费 `run_turn_stream()`，方便现有调用和测试平滑迁移。

Why:

- 参考实现的 host 实际上消费的是 `query()` yield 出来的统一事件流。
- 先把 stream 作为一等接口，后续 session/host assembly 才能真正接起来。

Alternatives considered:

- 保持 `run_turn()` 为主接口，只在内部记录 event。拒绝，因为 host 无法无损观察 turn 过程。

### 3. 为 `ModelRequest` 增加 abort signal 和 terminal metadata contract

`ModelRequest` 增加 request-scoped abort handle、query source 和 runtime metadata；terminal result 增加 `stop_reason`、`usage`、`request_id`、`ttft_ms` 等字段。

Why:

- 当前 interrupt 只能影响 tool scheduler，不能终止模型流。
- host 和 golden tests 需要稳定观测 turn terminal 状态。

Alternatives considered:

- 只在 provider adapter 层偷偷持有 abort controller。拒绝，因为 turn engine 和 tests 都需要显式 contract。

### 4. 中断和 partial output 采用“不提交未完成 block”的规则

如果 interrupt/fallback 发生在消息尚未完成时，未闭合的 block 不进入 continuation history；必要时产出显式 discard/tombstone event 供 host 清理渲染状态。

Why:

- 参考实现明确避免把半截 thinking/tool input 留在下一轮上下文中。
- 在没有更复杂 transcript surgery 的前提下，“未完成即不提交”是最稳妥的最小规则。

Alternatives considered:

- 直接把 partial text/tool input 拼成最终 message。拒绝，因为这会污染下一轮 request，并制造非法 tool/result pairing。

## Risks / Trade-offs

- [事件模型复杂化] `TurnEngine` 的接口和测试夹具都会变复杂。 → Mitigation: 保留 `run_turn()` 聚合包装，逐步迁移上层调用。
- [provider 适配成本上升] 需要实现 block-level event adapter。 → Mitigation: 先定义统一 raw event 协议，第一版 fake provider 与真实 provider 共用同一接口。
- [中断边界更严格] 丢弃 partial block 可能改变当前测试结果。 → Mitigation: 在 golden suite 中明确记录 interrupt/fallback 后的预期 terminal 行为。

## Migration Plan

1. 扩展 `ModelRequest`、`ModelStreamEvent` 与 turn terminal 数据模型。
2. 在 turn engine 中新增 `run_turn_stream()` 和 assistant block accumulator。
3. 将 interrupt 信号贯穿到 model request。
4. 为 partial output 添加 discard/tombstone 规则。
5. 保留 `run_turn()` 包装接口，直到 session/host assembly 完成迁移。

Rollback strategy:

- 如果新的 stream contract 暂时无法被上层完全消费，可继续通过 `run_turn()` 聚合包装提供兼容入口，但 abort signal 和 terminal metadata contract 应保留。

## Open Questions

- 第一版 host-facing turn event 是否需要显式 tombstone 类型，还是只用 discard metadata 即可？
- provider adapter 是否要在这一 change 中同时承担 request retry/fallback，还是只定义单次请求的流式 contract？
