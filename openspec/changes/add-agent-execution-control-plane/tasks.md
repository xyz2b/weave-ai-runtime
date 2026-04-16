- [ ] 1. 定义统一的 agent execution contract
- [ ] 1.1 新增 `AgentExecutionSpec`、`SpawnMode`、`AgentRunRecord` 与 parent-child linkage models
- [ ] 1.2 明确 sync、background、fork 与 future teammate 的统一 execution entry
- [ ] 1.3 明确 `AgentExecutionSpec` / `AgentRunRecord` 的字段来源、继承规则、稳定性约束与写入时机

- [ ] 2. 重构 agent dispatch 与 execution 边界
- [ ] 2.1 引入 `AgentExecutionService`，让 `agent` tool、background agent 与 forked skill 统一走该入口
- [ ] 2.2 将现有 `AgentRuntime.invoke()` 的 dispatch 逻辑与真正执行逻辑拆开

- [ ] 3. 引入按 agent 选择的 model route / provider route
- [ ] 3.1 扩展 agent definition 与 runtime config，支持 named `model_route` 与 provider assembly boundary
- [ ] 3.2 引入 `ModelRouter` 与结构化 route resolution contract，明确 route precedence、`model_route`/`model` 分工，并覆盖 provider、base URL、credential ref、default model、resolved capabilities 与 invocation mode
- [ ] 3.3 扩展 `ModelRequest` / `ModelClient` contract，显式承载 route identity、provider identity、resolved capabilities 与 supported invocation modes
- [ ] 3.4 定义并落地 normalized capability taxonomy，供 route filtering、adapter declaration 与 request metadata 共享
- [ ] 3.5 让 `TurnEngine` 同时支持 streaming 与 buffered / non-stream completion path
- [ ] 3.6 将 route resolution 写入 provider request metadata 与 child run metadata
- [ ] 3.7 增加最小 `ProviderBinding` / `ModelRoute` 配置样例与对应测试夹具

- [ ] 4. 增加 sidechain transcript / run record
- [ ] 4.1 为 subagent、forked skill agent run 与 background agent 持久化 child run record
- [ ] 4.2 记录 `run_id`、`parent_run_id`、`spawn_mode`、resolved route、terminal metadata 与 child messages
- [ ] 4.3 保持主 transcript 只承载 continuation 必需的消息与 tool results

- [ ] 5. 增加 fork context builder
- [ ] 5.1 实现 shared-prefix + directive-tail 的 fork context shaping contract
- [ ] 5.2 为 future prompt cache reuse 增加稳定的 message construction 测试夹具

- [ ] 6. 扩展 layered capability trimming
- [ ] 6.1 增加 runtime-global deny layer、spawn-mode deny layer 与 route capability filter
- [ ] 6.2 保证 child agent 不能突破 parent policy ceiling 扩权

- [ ] 7. 补充 conformance tests
- [ ] 7.1 增加不同 agent 在同一 session 中选择不同 model routes 的 request-level tests
- [ ] 7.2 增加 route precedence、`model_route`/`model` override 与 route ownership 的 request-level regression tests
- [ ] 7.3 增加 route identity、resolved capabilities 与 provider metadata 的 request-level regression tests
- [ ] 7.4 增加 buffered / non-stream completion path tests，包括完整响应后 tool-call normalization
- [ ] 7.5 增加 provider assembly / router selection regression tests
- [ ] 7.6 增加 background / fork / delegated child run 的 sidechain transcript tests
- [ ] 7.7 增加 denied / early-failed child run 仍然写 sidechain record 的 regression tests
- [ ] 7.8 增加 layered capability trimming 与 fork context shaping regression tests
