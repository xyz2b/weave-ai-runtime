## MODIFIED Requirements

### Requirement: agents may select different named model routes
runtime SHALL 支持 agent 通过命名 route 选择不同的 provider profile、base URL、credential reference、默认模型与 route-owned context window policy，而不是只依赖单一全局 model client 配置或 agent-local context-window settings。

#### Scenario: two agents in the same session use different routes
- **WHEN** 同一个 session 中两个不同 agent 分别绑定不同的 named model routes
- **THEN** runtime SHALL 为各自 provider request 解析并使用对应的 route
- **AND** SHALL 将 resolved route identity、provider identity、resolved capabilities 与 resolved context-window ownership 或 fallback mode 写入结构化 request fields 或等价的 execution metadata

#### Scenario: route override and model override are resolved independently
- **WHEN** 某次 child agent execution 同时携带 route override、agent-level `model_route` 与显式 `model`
- **THEN** runtime SHALL 先按既定 precedence 解析最终 route ownership
- **AND** SHALL 仅允许 `model` 覆盖已解析 route 的默认模型名
- **AND** SHALL NOT 因 `model` 覆盖而把请求重路由到另一 provider

#### Scenario: route ownership remains agent-scoped in v1
- **WHEN** runtime 处理 forked skill 或其他 skill-driven child execution
- **THEN** runtime SHALL 通过 execution spec override、delegated agent `model_route` 或 inherited route hint 解析 route ownership
- **AND** SHALL NOT 要求或依赖 `SkillDefinition` 暴露独立的 `model_route` 字段

#### Scenario: route override outside parent or runtime route policy is rejected or narrowed
- **WHEN** 某次 child agent execution 请求的 route override 超出 parent policy ceiling 或 runtime-global route policy
- **THEN** runtime SHALL 在模型请求发出前拒绝该 override，或将其收窄到允许的 route ownership
- **AND** SHALL NOT 静默将 child execution 扩权到父 execution 未授予的 provider route

#### Scenario: `main-router` binds a named route like any other agent
- **WHEN** runtime 以 `main-router` 作为 root agent 启动一个 session
- **THEN** `main-router` SHALL 按与其他 agent 相同的 route precedence 解析其 `model_route`
- **AND** SHALL NOT 因为它承担主线程 routing 角色而获得单独的 transport resolution 语义
- **AND** 其已解析 route MAY 作为 child execution 的 inherited route hint，除非被显式 override 或被 policy 拒绝

#### Scenario: route-owned context window policy stays outside agent definitions
- **WHEN** runtime 为某个 agent 解析了同时携带 integration-owned context window profile 与 route-level context window policy 的 named route
- **THEN** runtime SHALL 从该 resolved route 派生 context window ownership、override 与 fallback policy
- **AND** SHALL NOT 要求 `AgentDefinition` 暴露 context-window、reserved-output 或 compaction-threshold 字段来完成该解析
