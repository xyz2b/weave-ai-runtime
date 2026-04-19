## 0. Scope Locks And Migration Gates

- [x] 0.1 锁定 ingress 的正式协议面：`IngressAdmission`、`IngressReplayOutput`、`SessionIngressResult` 及 admission kind taxonomy 以 design/spec 为准
- [x] 0.2 锁定 prompt/private 双 carrier 决议：采用 `PromptContextEnvelope` + `RuntimePrivateContext` 的强外壳加弱扩展模式，而不是继续扩张单一 `runtime_context`
- [x] 0.3 锁定 lifecycle ownership matrix：`BoundHostRuntime` 拥有 host lifecycle，`SessionController` 拥有 session lifecycle，`RuntimeAssembly` one-shot helper 只保证 helper-owned session 完整关闭
- [x] 0.4 将 ingress、context boundary 与 lifecycle ownership 的关键决议回写到 `proposal.md`、`design.md` 与 capability specs，作为后续实现 slice 的 scope gate

## 1. Session Ingress Contract Foundations

- [x] 1.0 Land Slice A (`session_runtime/models.py`, new ingress module, protocol fixtures) so the ingress contract exists before controller wiring moves
- [x] 1.1 新增 `IngressAdmission`、`IngressReplayOutput` 与 `SessionIngressResult` 模型，并固定 `admit_turn`、`local_only`、`transcript_only`、`replay_only`、`reject` 的最小语义
- [x] 1.2 引入 `SessionIngressProcessor` 边界，统一接收 inbound event、session snapshot 与 runtime services，并输出结构化 ingress result
- [x] 1.3 固定 `normalized_messages`、`replay_outputs`、`prompt_updates`、`private_updates` 与 rejection/local-only outcome 的字段职责，禁止再靠布尔值或 loose metadata 传语义
- [x] 1.4 增加最小协议测试，证明 query-admitted、local-only 与 reject ingress 结果可以在不检查原始 payload 的情况下被区分和消费

## 2. SessionController Ingress Integration

- [x] 2.0 Land Slice B (`session_runtime/controller.py`, transcript/state fixtures) so every inbound session path goes through ingress before transcript mutation or turn execution
- [x] 2.1 将 `SessionController` 的用户输入、host 注入输入与 task/notification 输入统一改为先经过 `SessionIngressProcessor`
- [x] 2.2 在 admitted turn 上先持久化 ingress-normalized transcript messages，再发出首个 model request
- [x] 2.3 让 `local_only`、`transcript_only`、`replay_only` 与 `reject` outcome 在 session 层完成，不再把原始 inbound payload 直接落入 `TurnEngine`
- [x] 2.4 保持 ingress 定义的 role、visibility、source 语义，避免 `SessionController` 依据命令类型再次推断
- [x] 2.5 将 ingress 产出的 `prompt_updates` 与 `private_updates` 收敛到 turn 启动输入中，而不是重新摊平成原始 metadata bag
- [x] 2.6 增加 session regression tests，覆盖用户 prompt admission、local-only 控制输入、host-generated prompt 与 task notification 行为

## 3. Prompt And Private Carrier Foundations

- [x] 3.0 Land Slice C (`contracts.py`, `turn_engine/models.py`, `tool_runtime.py`, compat helpers) so dual context carriers exist before request assembly changes
- [x] 3.1 新增 `PromptContextEnvelope`，固定 memory、hooks、compaction、attachments、session hints 与 `extensions` 等 prompt-safe 字段
- [x] 3.2 新增 `RuntimePrivateContext`，固定 permission、policy、run linkage、route、invocation mode、diagnostics 与 `extensions` 等 private 字段
- [x] 3.3 让 `TurnContext` 变为 prompt-safe carrier，移除 authoritative private execution state
- [x] 3.4 扩展 `ModelRequest`，增加独立 private carrier 或等价 non-prompt metadata field，供 provider/runtime boundary 使用
- [x] 3.5 扩展 `ToolContext`，使 tools、agents 与 skills 直接拿到 `RuntimePrivateContext`，而不是依赖 prompt-facing metadata
- [x] 3.6 增加 compat adapters，将 legacy `runtime_context` 读取路径单向收敛到新 carriers，避免新代码继续扩散旧约定

## 4. TurnEngine Request Preparation Split

- [x] 4.0 Land Slice D (`turn_engine/engine.py`, `turn_engine/composer.py`, request fixtures) so prompt assembly and private execution state stop sharing one metadata bag
- [x] 4.1 将 `TurnEngine` 的 request-preparation 主路径从单一 `runtime_context` 改为显式消费 `PromptContextEnvelope` 与 `RuntimePrivateContext`
- [x] 4.2 收紧 `ContextAssembler` / composer，只允许消费 prompt-visible carrier，而不是直接遍历 runtime-private metadata
- [x] 4.3 将 permission、policy、route、run linkage 与 diagnostics 等控制面状态迁移到 `RuntimePrivateContext`
- [x] 4.4 保留 host/test observability：通过 `ModelRequest` 的 non-prompt metadata 暴露 private execution state，而不是通过 prompt 拼接泄露
- [x] 4.5 更新 serialization/sanitization helpers，把 prompt allowlist 变成正向 contract，而不是继续依赖隐藏少数字段的 blacklist 逻辑
- [x] 4.6 增加 request-level regression fixtures，证明 emitted prompt 不包含 private control-plane 字段，同时 private metadata 仍可被 host 和 tests 观察

## 5. Sidecar Contribution Contract Migration

- [x] 5.0 Land Slice E (`runtime_services/__init__.py`, `memory/manager.py`, `hooks`, `compaction/manager.py`) so sidecars contribute through one dual-channel contract
- [x] 5.1 定义统一 sidecar contribution result：`prompt_fragments`、`private_updates` 与 `diagnostics`
- [x] 5.2 更新 memory retrieval 路径，使 model guidance 与 retrieval trace/diagnostics 分通道返回
- [x] 5.3 更新 hooks 与 host contribution 路径，使 private-only diagnostics/hints 不再通过 prompt-facing carrier 传播
- [x] 5.4 更新 compaction 和相关 control-plane service，使 prompt summary 与 private policy/runtime metadata 分离
- [x] 5.5 移除 sidecars 对共享 `runtime_context` 的原地 mutate；必要时仅保留单向 compat adapter
- [x] 5.6 增加 conformance tests，证明 sidecar 可以独立影响 prompt 与 private 通道，且不会引入 prompt 泄露

## 6. Lifecycle Ownership Split

- [x] 6.0 Land Slice F (`hosts/base.py`, `runtime_kernel/kernel.py`, `session_runtime/controller.py`) so host/session ownership is separated before helper behavior is tightened
- [x] 6.1 将 `host.startup()`、`host.ready()` 与 `host.shutdown()` 的 owner 从 `SessionController` 移出
- [x] 6.2 让 `SessionController` 的 `start()` / `close()` 只负责 session-scoped resource、session start/end semantics、transcript/memory artifact 与 cleanup
- [x] 6.3 使 session close 幂等，并保证 success、interrupt、error 下的 session-end cleanup 最多执行一次
- [x] 6.4 增加 regression tests，证明关闭 session 不会隐式关闭仍处于活动 scope 的 bound host

## 7. BoundHostRuntime Managed Scope And Helper Guarantees

- [x] 7.0 Land Slice G (`hosts/base.py`, `runtime_kernel/kernel.py`, host tests) so explicit host-scope lifecycle management exists before one-shot helpers rely on it
- [x] 7.1 为 `BoundHostRuntime` 增加 async context-manager 支持，`__aenter__()` 负责 `startup()` + `ready()`
- [x] 7.2 为 `BoundHostRuntime` 增加 managed-session registry，并固定 helper-owned / bound-owned session 的 register/deregister 语义
- [x] 7.3 实现 `__aexit__()` 的确定性关闭顺序：先关闭 managed sessions，完成 session cleanup，再执行 `host.shutdown()`
- [x] 7.4 更新 `RuntimeAssembly.run_prompt()`，保证 helper-owned session 在 success 路径下也会 `close()`
- [x] 7.5 更新 `RuntimeAssembly.stream_prompt()`，保证 helper-owned session 在 normal、interrupt 与 error 路径下都执行 `close()`
- [x] 7.6 增加 multi-session host reuse、managed-session shutdown ordering 与 one-shot helper close guarantee tests

## 8. Compatibility, Fixtures, And Documentation

- [ ] 8.0 Land Slice H (compat shims, fixtures, docs/comments) after ingress, carriers, and lifecycle owners are stable
- [ ] 8.1 审计 `agent_execution_service.py`、`skill_runtime.py`、`invocation_catalog.py`、`elicitation/service.py`、host bridge 等 `runtime_context` 旧调用点，并收敛到 ingress 或双 carrier contract
- [ ] 8.2 刷新 protocol fixtures、golden request fixtures 与 host bridge harnesses，反映 ingress outputs、prompt/private split 与 lifecycle ordering
- [ ] 8.3 补 developer-facing contract appendix 或等价文档，说明 ingress protocol、context carriers、sidecar contribution semantics 与 host-scope lifecycle ordering
- [ ] 8.4 定义 compat-shim removal gate：明确哪些 legacy `runtime_context` read/write 仍被允许、哪些 authoritative writes 必须归零、哪些 harness 必须通过
- [ ] 8.5 在 compat-shim removal gate 通过后，移除残余 shared `runtime_context` authoritative writes，并将 compat shim 收窄为最小只读桥接或直接删除
- [ ] 8.6 将刷新后的 conformance matrix 作为最终 rollout gate，确认 legacy `runtime_context` 假设已被清退后再推进默认启用或移除兼容层
