# Runtime Contract Appendix

本文档补充 `align-runtime-ingress-context-lifecycle-boundaries` 变更后的开发者约定，重点说明 ingress 协议、prompt/private 双 carrier、sidecar 贡献语义、host-scope lifecycle ordering，以及兼容层收敛 gate。

## Ingress Protocol

session ingress 是所有 inbound session event 的唯一准入面。调用方和 session control 需要遵守以下约束：

- 所有 inbound event 先进入 `SessionIngressProcessor`
- ingress 只能通过 `SessionIngressResult` 暴露结果
- `normalized_messages` 负责 transcript-visible message
- `replay_outputs` 负责 host-visible replay，不得隐式等价为 transcript append
- `prompt_updates` 只允许出现在 `admit_turn`
- `private_updates` 承载 runtime-private state，供 session/runtime/tool execution 消费

`IngressAdmission.kind` 的稳定 taxonomy：

- `admit_turn`
- `local_only`
- `transcript_only`
- `replay_only`
- `reject`

session 层只执行 ingress 归一化之后的结果，不再根据原始 inbound payload 重新推断 role、visibility、source 或 turn admission。

## Prompt And Private Carriers

prompt-visible 与 runtime-private state 必须分通道传递：

- `PromptContextEnvelope`
  - memory、hooks、compaction、attachments、session hints
  - 允许进入 `ContextAssembler`
  - 允许出现在 request fixtures 与 prompt-facing turn context
- `RuntimePrivateContext`
  - permission、policy、run linkage、route、invocation mode、diagnostics、private extensions
  - 允许进入 tool/agent/skill/runtime execution
  - 允许出现在 request metadata、host diagnostics、tool context
  - 不允许通过 prompt 直接泄露

`runtime_context` 仍然作为兼容桥接 surface 存在，但只用于：

- 接受 legacy caller 输入
- 为 legacy sidecar/harness 提供只读或 clone 后的 compat snapshot
- 作为 `PromptContextEnvelope` / `RuntimePrivateContext` 的单向适配来源

新的 authoritative state 不得继续依赖共享 `runtime_context` mutation。

## Sidecar Contribution Semantics

sidecar 必须通过统一 contract 贡献上下文：

- `prompt_fragments`
- `private_updates`
- `diagnostics`

合并顺序固定为：

1. session/base context
2. ingress updates
3. sidecar contributions
4. request-scoped explicit overrides

约束：

- prompt-facing hint 只能进入 `PromptContextEnvelope`
- private execution state 只能进入 `RuntimePrivateContext`
- diagnostics 只能走 private/non-prompt channel
- legacy sidecar 若仍写 `runtime_context`，runtime 只读取 clone 差异并投影到 private/diagnostics；这些 mutation 不再成为共享 authoritative state

## Host-Scope Lifecycle Ordering

host lifecycle owner 是 `BoundHostRuntime`，session lifecycle owner 是 `SessionController`。

稳定顺序：

1. `BoundHostRuntime.__aenter__()` 或显式 `startup()` + `ready()`
2. 在 active host scope 下创建或复用 session
3. session close 只做 session-scoped cleanup
4. host scope 结束时先关闭 managed sessions
5. session cleanup 完成后再执行 `host.shutdown()`

one-shot helper 的 contract：

- `run_prompt()` 保证 helper-owned session close
- `stream_prompt()` 保证 normal、interrupt、error 下都 close helper-owned session
- helper 不隐式拥有 outer host shutdown

## Compat-Shim Removal Gate

当前允许保留的 legacy `runtime_context` 路径：

- 外部调用仍可向 `TurnEngine` / `RuntimeAssembly` / invocation resolution 传入 `runtime_context`
- sidecar service 仍可接收 clone 后的 compat `runtime_context`
- compaction policy fallback 仍可读取 `legacy_runtime_context`

必须清零的 authoritative write：

- sidecar 结果不得再通过共享 `runtime_context` 成为 turn 内 authoritative private state
- execution policy、permission context、run linkage、route、invocation mode、diagnostics 不得依赖共享 `runtime_context` 的后续原地更新
- 新增 prompt-visible 字段不得先写入 `runtime_context` 再等待 assembler 过滤

默认 gate：

- 新代码必须优先写 `PromptContextEnvelope` / `RuntimePrivateContext`
- `runtime_context` compat 仅允许单向 bridge
- 任何新增 legacy write 都应视为 rollout blocker

## Conformance Matrix

推进默认启用或进一步删除 compat shim 前，至少需要通过以下 harness：

- `tests/test_session_ingress.py`
- `tests/test_session_runtime.py`
- `tests/test_query_turn_stream.py`
- `tests/test_query_runtime_protocol_golden.py`
- `tests/test_invocation_catalog.py`
- `tests/test_runtime_control_plane.py`
- `tests/test_interactive_control_plane.py`

rollout 结论：

- request fixtures 必须同时暴露 prompt/private carriers
- host/test 可观察 private state，但 prompt 不得泄露 private 字段
- invocation resolution 必须能从 carrier 读取 policy/path context，不再强依赖原始 `runtime_context`
- host-scope shutdown ordering 必须稳定为 `managed sessions -> session cleanup -> host shutdown`

只有在上述 matrix 持续通过、且未再发现新的 shared `runtime_context` authoritative write 之后，才应继续推进 compat shim 的进一步删除或默认启用切换。
