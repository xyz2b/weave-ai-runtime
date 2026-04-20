## Context

当前 Python runtime 的测试主要通过 fake model 批次断言“有没有第二次请求”和“最后文本是否匹配”。这种覆盖不足以证明它实现了参考实现的 query runtime contract，因为真正关键的是：

- 第二轮 request 是否带了正确的 `tool_result.tool_use_id`
- interrupt 是否能终止 in-flight stream
- transcript 恢复后是否仍然维持合法 pairing
- model-generated `agent` / `skill` tool 是否走 assembled runtime 主路径参考实现的 query runtime 本身就依赖大量消息结构与恢复逻辑，因此这里需要一个单独的 conformance change，用更接近协议层的 golden fixtures 锁住边界。

## Goals / Non-Goals

**Goals:**

- 建立 request-level 和 turn-event-level 的 golden fixture harness。
- 为结构化消息协议、stream interrupt、transcript resume 和 runtime assembly 提供回归保护。
- 用 assembled runtime 路径验证 model-generated builtin orchestration tools，而不是只测 direct-route 旁路。

**Non-Goals:**

- 本 change 不引入新的 runtime 能力，只验证前面三个 change 的 contract。
- 本 change 不追求 UI snapshot 或产品级渲染测试。
- 本 change 不覆盖所有参考实现的 feature gate，只覆盖当前四步拆分后的主骨架。

## Decisions

### 1. 用协议级 golden 而不是最终文本 snapshot 作为主要护栏

golden fixture 主要断言：

- provider request messages
- stream event sequence
- transcript round-trip shape
- assembled runtime handler invocation

Why:

- query runtime 的风险点在协议边界，不在最后展示给用户的一句文本。
- 最终文本 snapshot 对 message pairing、interrupt、resume 等问题几乎没有识别力。

Alternatives considered:

- 继续以最终文本输出为主断言。拒绝，因为无法发现协议退化。

### 2. 将 conformance harness 分成 request、stream、resume、assembly 四层

测试基座分为：

- provider request capture
- turn event capture
- transcript fixture helpers
- assembled runtime integration fixture

Why:

- 这四类问题的失败模式不同，混成一种 fixture 会让测试既脆弱又难排查。
- 分层 fixture 可以直接映射这四个 proposal 的交付边界。

Alternatives considered:

- 只做一个大一体的 end-to-end fixture。拒绝，因为出错时很难定位是在协议、stream 还是 assembly。

### 3. 已知错误模式直接固化为负例回归

至少固化以下回归：

- tool result 被压平成字符串
- `agent_runner` / `skill_runner` 未 wiring
- interrupt 不会终止 slow stream
- transcript resume 后出现 orphaned tool_result

Why:

- 这些都是已经在现有仓库里出现过或已通过探索明确识别的真实风险。
- 把它们变成负例比抽象“应该可用”更有价值。

Alternatives considered:

- 只写 happy path。拒绝，因为当前最需要的是防止再次退化。

## Risks / Trade-offs

- [fixture 易脆] request/event golden 容易因字段调整频繁更新。 → Mitigation: golden 只锁结构语义和关键字段，不锁无关时间戳或随机 ID。
- [集成测试更慢] assembled runtime 路径测试比当前 fake batch 更重。 → Mitigation: 保持分层，单元与集成分开跑。
- [验证面扩大] 需要 runtime 暴露更多可观测信息。 → Mitigation: 只要求 request/event/transcript 所需的最小观测点。

## Migration Plan

1. 构建 protocol capture fixture 和 transcript fixture helpers。
2. 增加 tool roundtrip 与 pairing repair golden tests。
3. 增加 interrupt / partial discard / resume regression tests。
4. 增加 assembled runtime agent/skill orchestration 与 host event consumption tests。
5. 将已识别的当前失败模式固化为负例回归。

Rollback strategy:

- 若 golden 格式需要调整，应优先保留语义断言并更新 fixture helper，而不是删掉整类 conformance tests。

## Open Questions

- golden fixture 是以 JSON 文件保存，还是以内联断言 helper 方式维护更合适？
- host event consumption tests 第一版是否只覆盖 headless host，还是同时覆盖最小 interactive host？
