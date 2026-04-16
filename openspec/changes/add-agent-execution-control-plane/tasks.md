## 0. Scope Locks and Rollout Gates

- [x] 0.1 记录 buffered completion 范围决议：第一版直接支持完整响应后的 tool-call normalization，不采用 text-only 过渡阶段
- [ ] 0.2 锁定 sidechain transcript 的落点：明确采用独立 child-run store 还是 transcript store 扩展索引
- [ ] 0.3 锁定 `model_route` 的暴露面：明确第一版只开放给 `AgentDefinition`，还是同步开放给 `SkillDefinition`
- [x] 0.4 将 buffered-path 决议与 route-policy requirement 回写到 `proposal.md`、`design.md`、`spec.md` 与 `tasks.md`，避免后续 implementation slice 在范围上漂移

## 1. Execution Contract Foundations

- [ ] 1.0 Land Slice A (`agent_runtime.py`, execution models module, protocol fixtures) so structured child-run contract exists before dispatch and provider routing change
- [ ] 1.1 新增 `AgentExecutionSpec`、`SpawnMode`、`AgentRunRecord` 与 parent-child linkage models
- [ ] 1.2 固定 `run_id`、`parent_run_id`、`session_id`、`turn_id`、`query_source`、`requested_model_route`、`requested_model` 与 `metadata` 的字段语义、继承规则与稳定性约束
- [ ] 1.3 固定 `AgentRunRecord` 的最小索引集、terminal status 集合，以及 sync/background/denied child 的最小写入要求
- [ ] 1.4 增加最小 contract tests，证明 core execution contract 不会回落到非结构化 metadata

## 2. Dispatcher / Execution Split

- [ ] 2.0 Land Slice B (`agent_runtime.py`, dispatcher/service modules, compat shims) so dispatch and execution are separated before route-aware behavior lands
- [ ] 2.1 从 `AgentRuntime.invoke()` 中抽出 `AgentDispatcher`，统一负责 sync、background、fork 与 future teammate 的入口判定、linkage 计算与 execution spec 构造
- [ ] 2.2 引入 `AgentExecutionService.run(spec)`，统一负责 agent resolution、layered policy resolution、isolation preparation、shared `TurnEngine` 调用与 run-record lifecycle
- [ ] 2.3 让 builtin `agent` tool、background agent 与 forked skill path 全部走 `AgentDispatcher -> AgentExecutionService`
- [ ] 2.4 保留现有 `/agent`、`/skill`、`/tool` compat route，但将其收敛为 dispatcher 前的兼容 shim，而不是并行的执行引擎

## 3. Provider Control Plane Foundations

- [ ] 3.0 Land Slice C (`definitions.py`, `runtime_kernel/config.py`, `runtime_kernel/kernel.py`, provider-route fixtures) so runtime owns provider graph before request contract expands
- [ ] 3.1 扩展 definition schema，引入 agent-level `model_route`，并按 0.3 的结论决定 skill definition 是否同步支持
- [ ] 3.2 扩展 `RuntimeConfig`，新增 `provider_bindings`、`model_routes` 与 `default_model_route`
- [ ] 3.3 新增 `ProviderBinding`、`ModelRouteDefinition`、`ResolvedModelRoute` 与 `ModelRouter`
- [ ] 3.4 在 runtime kernel 中显式装配 provider graph / route graph，而不是继续只注入单一全局 `model_client`
- [ ] 3.5 增加最小 `ProviderBinding` / `ModelRoute` 配置样例与 kernel assembly 测试夹具

## 4. Route Resolution and Policy Contract

- [ ] 4.0 Land Slice D (route resolver plus execution-service integration) so route ownership and precedence are fixed before model adapter changes
- [ ] 4.1 固定 route precedence：execution spec route override > agent `model_route` > inherited route hint > runtime default route
- [ ] 4.2 固定 `model_route` 与 `model` 的职责分工：`model_route` 决定 provider ownership，`model` 仅覆盖已解析 route 的默认模型名
- [ ] 4.3 明确并实现 route ownership 约束，禁止 `model` 覆盖把请求重路由到另一 provider
- [ ] 4.4 明确 `main-router` 与其他 agent 使用同一 route precedence contract；其已解析 route 只作为 child execution 的 inherited route hint，而不是隐式 transport 特权
- [ ] 4.5 增加 route-policy enforcement：当 child 请求 route 超出 parent policy 或 runtime-global route policy 时，runtime 必须拒绝或收窄，而不是静默扩权

## 5. Model Adapter Contract and Normalized Capabilities

- [ ] 5.0 Land Slice E (`turn_engine/models.py`, adapter declarations, request fixtures) so structured provider metadata exists before buffered execution lands
- [ ] 5.1 扩展 `ModelRequest`，显式携带 resolved route identity、provider identity、resolved capabilities 与 invocation mode
- [ ] 5.2 扩展 `ModelClient` / provider adapter contract，要求显式声明 normalized capabilities 与 supported invocation modes
- [ ] 5.3 固定最小 normalized capability taxonomy：`tool_calls`、`streaming`、`buffered_completion`、`vision`、`reasoning_effort`、`json_mode`
- [ ] 5.4 将运行时 `resolved_capabilities` 固定为 route profile 与 adapter declaration 的可验证交集，而不是依赖 provider 私有 capability 名称
- [ ] 5.5 将 resolved route / provider / capability metadata 写入 provider request metadata 与 child run metadata

## 6. TurnEngine Invocation-Mode Selection and Buffered Path

- [ ] 6.0 Land Slice F (`turn_engine/engine.py`, invocation selector, normalization helpers) so transport choice stays internal to `TurnEngine`
- [ ] 6.1 在 `TurnEngine` 内增加 invocation-mode selector，根据 resolved route 与 adapter capabilities 在 `stream` 与 `buffered_completion` 之间选择真实执行路径
- [ ] 6.2 实现 buffered completion path 下的 assistant text / terminal metadata normalization，且不改变上层 session / transcript / tool runtime contract
- [ ] 6.3 补齐完整响应后的 buffered tool-call normalization，并与 streaming path 归一到同一 assistant message / tool result continuation contract
- [ ] 6.4 统一 streaming 与 buffered path 下的 `request_id`、`usage`、`stop_reason`、`error` 与 `abort_reason` 语义
- [ ] 6.5 增加 invocation-mode selection / downgrade observability，便于 host 与 conformance harness 观察实际 provider path

## 7. Sidechain Run Record and Transcript Boundaries

- [ ] 7.0 Land Slice G (child run store plus host-visible observability) so run recording exists before fork and policy hardening depend on it
- [ ] 7.1 按 0.2 的结论实现 child run record store 或 transcript-side index，并固定读写接口
- [ ] 7.2 为 sync delegated child 持久化终态 `AgentRunRecord`
- [ ] 7.3 为 background child 持久化初始 `running` 记录与终态更新
- [ ] 7.4 为 denied / early-failed child 持久化最小 sidechain record，即使没有真正进入模型调用
- [ ] 7.5 保持 child 的完整消息历史与 terminal metadata 进入 sidechain，而主 transcript 只保留 continuation 必需消息与 tool results

## 8. Fork Context Builder

- [ ] 8.0 Land Slice H (`skill_runtime.py`, execution-service fork integration, fork builder module) after shared execution and sidechain recording are stable
- [ ] 8.1 引入 `ForkContextBuilder`，固定 shared-prefix + directive-tail 的 fork context shaping contract
- [ ] 8.2 让 forked child 通过 execution spec 继承 route hint、policy ceiling 与 linkage，而不是继续靠 ad-hoc metadata 塑形
- [ ] 8.3 增加稳定的 fork message construction fixtures，覆盖 prompt-cache-oriented shared prefix 与 continuation-safe tail 差异

## 9. Layered Capability Trimming

- [ ] 9.0 Land Slice I (policy layering integration) after route capabilities and fork shaping are formalized
- [ ] 9.1 增加 runtime-global deny layer 与 spawn-mode-specific deny layer
- [ ] 9.2 保持 parent execution policy ceiling 作为 child execution 的不可突破上界
- [ ] 9.3 将 agent frontmatter restrictions 与 route capability filter 收敛到同一 layered policy contract
- [ ] 9.4 对超出父级 ceiling、route capability 或 spawn-mode policy 的 child requests 执行裁剪或拒绝
- [ ] 9.5 增加 background / fork / route-specific capability narrowing 的 regression coverage

## 10. Conformance Matrix and Final Rollout Gate

- [ ] 10.0 建立最小 request-level conformance matrix，并将其作为移除剩余 single-client 假设前的 rollout gate
- [ ] 10.1 增加同一 session 内不同 agent 选择不同 named routes 的 request-level tests
- [ ] 10.2 增加 route precedence、`model_route` / `model` override、`main-router` parity 与 route ownership 的 regression tests
- [ ] 10.3 增加 provider assembly / kernel router selection regression tests
- [ ] 10.4 增加 resolved route identity、provider identity、resolved capabilities 与 invocation mode metadata propagation tests
- [ ] 10.5 增加 buffered / non-stream completion path 与 buffered tool-call normalization tests
- [ ] 10.6 增加 delegated、background、forked、denied 与 early-failed child run 的 sidechain transcript tests
- [ ] 10.7 增加 layered capability trimming、inherited-route policy 与 fork context shaping regression tests
- [ ] 10.8 以 conformance matrix 为最终 gate，确认多 route、多 provider、双 invocation-mode 与 child-run observability 行为都被锁定后再推进默认启用
