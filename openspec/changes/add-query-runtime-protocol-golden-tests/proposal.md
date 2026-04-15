## Why

协议、stream 和 assembly 逐步补齐之后，如果测试仍然只断言“发了几轮 request”或“最后输出了什么字符串”，runtime 很快会再次偏离 Claude Code 的 query contract。当前测试对 request payload、pairing repair、interrupt、resume 和 model-generated agent/skill path 几乎没有保护，因此需要单独的 conformance/golden change 来锁定这些边界。

## What Changes

- 引入协议级 fixture/golden harness，能够捕获 provider requests、turn events、transcript 状态和 assembled runtime 调用路径。
- 增加围绕 `tool_use` / `tool_result` continuation 的 request-level golden tests，而不是只验证最终文本输出。
- 增加 interrupt、partial discard、transcript resume、pairing repair 的回归测试。
- 增加 assembled runtime 下 model-generated `agent` / `skill` tool call 以及 host event consumption 的集成测试。
- 将当前已识别的错误模式固化为负例回归，例如扁平化 tool result、缺失 runner wiring 和中断不能终止模型流。

## Capabilities

### New Capabilities

- `query-runtime-conformance`: query runtime 协议级 golden fixtures、回归用例与 assembled runtime 集成验证。

### Modified Capabilities

- 无。

## Impact

- 主要影响 `tests/` 下的 fixture harness、集成测试和协议 golden cases。
- 会要求 runtime 对外暴露足够稳定的 request/event/transcript 观测点，以便进行协议级断言。
- 为后续实现 change 提供回归护栏，降低 message protocol、stream contract 和 assembly wiring 再次退化的风险。
