# agent-system Specification

## Purpose
TBD - created by archiving change add-agent-execution-control-plane. Update Purpose after archive.
## Requirements
### Requirement: agent execution uses a unified execution service
runtime SHALL 将 subagent、background agent、forked skill agent context 与未来的 teammate worker 执行统一收敛到共享的 agent execution service，而不是为不同 spawn path 建立独立执行框架。

#### Scenario: model-generated `agent` tool delegates to a child agent
- **WHEN** 主线程 turn 中触发内置 `agent` tool 并请求执行一个 child agent
- **THEN** runtime SHALL 先构造结构化的 agent execution spec
- **AND** SHALL 通过共享的 agent execution service 执行该 child
- **AND** SHALL 在 child 执行内部继续复用共享 `TurnEngine`

#### Scenario: execution spec fields remain stable across a child run
- **WHEN** runtime 已为某次 child agent execution 构造 `AgentExecutionSpec`
- **THEN** runtime SHALL 为该 child run 分配稳定的 `run_id`
- **AND** SHALL 在 provider request metadata、child run record 与相关 observability surface 中复用同一个 `run_id`
- **AND** SHALL NOT 将 route identity、spawn mode 或 run linkage 仅隐藏在非结构化 metadata 中

#### Scenario: explicit spawn mode override wins over inherited background defaults
- **WHEN** 某次 child agent execution 显式指定 `spawn_mode`
- **AND** agent definition 或 legacy invocation flags 同时声明了冲突的 background 默认值
- **THEN** runtime SHALL 以显式 `spawn_mode` 作为 dispatch 判定的唯一来源
- **AND** SHALL 让 `AgentExecutionSpec.background` 与最终 `spawn_mode` 保持一致
- **AND** SHALL NOT 因遗留 boolean 标记而把 sync child 错误升级为 background execution

### Requirement: agents may select different named model routes
runtime SHALL 支持 agent 通过命名 route 选择不同的 provider profile、base URL、credential reference 与默认模型，而不是只依赖单一全局 model client 配置。

#### Scenario: two agents in the same session use different routes
- **WHEN** 同一个 session 中两个不同 agent 分别绑定不同的 named model routes
- **THEN** runtime SHALL 为各自 provider request 解析并使用对应的 route
- **AND** SHALL 将 resolved route identity、provider identity 与 resolved capabilities 写入结构化 request fields 或等价的 execution metadata

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

### Requirement: model adapter contract exposes structured route and capability metadata
runtime SHALL 为 provider-agnostic execution 暴露结构化的 model adapter contract，而不是只依赖宽泛 metadata 与单一 `model` 字符串。

#### Scenario: a request is dispatched through a resolved model route
- **WHEN** runtime 已为某次 agent execution 解析出最终 route
- **THEN** runtime SHALL 将 route identity、provider identity、resolved capability profile 与 invocation mode 作为结构化 contract 传给下游 model adapter
- **AND** SHALL NOT 只要求下游从自由形态 metadata 中猜测这些字段

### Requirement: normalized capability taxonomy is shared across routes and adapters
runtime SHALL 为 route capability filtering 定义一组稳定的 normalized capability keys，而不是让各 provider 各自暴露不可比较的能力名。

#### Scenario: runtime filters capabilities for a resolved route
- **WHEN** runtime 需要根据 resolved route 对 child execution 做 capability trimming
- **THEN** runtime SHALL 使用统一的 normalized capability keys 解析 route、adapter 与 request 上的能力声明
- **AND** SHALL 以规范化后的 `resolved_capabilities` 作为 policy filtering 的输入
- **AND** SHALL NOT 直接依赖 provider 私有 capability 名称执行核心 policy 判断

### Requirement: turn execution supports streaming and buffered provider paths
runtime SHALL 支持 streaming 与 buffered / non-stream completion 两类 provider path，包括只能在完整响应后产出可解析 tool call 的 provider，而不是把 turn execution 固定在 streaming-only 假设上。

#### Scenario: a provider route does not support streaming
- **WHEN** 某个 resolved route 或 provider adapter 不支持 streaming，但支持完整 completion
- **THEN** runtime SHALL 走 buffered / non-stream completion path 完成该次 turn
- **AND** SHALL 仍然将结果归一到共享的 message / tool-call runtime contract

#### Scenario: a buffered provider returns tool-call-capable output only after full completion
- **WHEN** 某个 provider 只能在完整响应返回后给出可解析 tool call
- **THEN** runtime SHALL 在 buffered / non-stream path 内完成 tool-call normalization
- **AND** SHALL 将其归一到与 streaming path 相同的 assistant message、tool result continuation 与 terminal metadata contract

### Requirement: runtime owns an explicit provider assembly boundary
runtime SHALL 在 kernel 中显式装配 provider graph / route graph，而不是继续依赖外部注入一个“大一统”的 model client。

#### Scenario: runtime boots with multiple provider bindings
- **WHEN** runtime 配置了多个 provider bindings 与多个 named routes
- **THEN** kernel SHALL 显式装配这些 provider bindings 与 route resolution graph
- **AND** SHALL 允许不同 agent 通过 route 解析到不同 provider binding

#### Scenario: agents resolve routes from named provider-backed configuration
- **WHEN** 两个 agent 在同一 runtime 中分别引用不同的 named routes
- **THEN** runtime SHALL 从 provider-backed route configuration 中解析出各自的 provider binding、default model 与 normalized capabilities
- **AND** SHALL NOT 要求 agent 直接持有 secret、base URL 或 provider transport 配置

### Requirement: child agent runs produce sidechain records
runtime SHALL 为 delegated、forked 或 background child agent runs 保留独立于主线程 transcript 的 sidechain run record。

#### Scenario: background child agent completes
- **WHEN** runtime 启动一个 background child agent 并完成执行
- **THEN** runtime SHALL 保留该 child run 的 `run_id`、parent linkage、status、terminal metadata 与 child messages
- **AND** SHALL 不要求主线程 transcript 承载该 child 的完整内部消息历史

#### Scenario: child sidechain records stay outside the main transcript store contract
- **WHEN** runtime 为 delegated、forked、background、denied 或 early-failed child run 写入 sidechain observability 记录
- **THEN** runtime SHALL 将这些 child run records 写入独立于主 transcript continuation contract 的 sidechain store 或等价独立接口
- **AND** SHALL NOT 要求主 transcript store 承担 child status index 或 sidechain lifecycle 更新语义

#### Scenario: denied or early-failed child runs still produce records
- **WHEN** 某个 child agent 在真正进入模型调用前被拒绝，或在执行早期失败
- **THEN** runtime SHALL 仍然保留该 child run 的 `run_id`、linkage、status 与 terminal metadata
- **AND** SHALL NOT 因为该 child 未产出完整消息历史而跳过 sidechain run record

#### Scenario: background child terminal status is not upgraded to completed
- **WHEN** 某个 background child 最终进入 `denied`、`failed` 或其他非 `completed` 终态
- **THEN** runtime SHALL 在 host-visible task state、notification 与 sidechain record 中保留该真实终态
- **AND** SHALL NOT 仅因为该 child 运行在后台就将其统一标记为 `completed`

#### Scenario: fork hooks observe denied and early-failed child terminal states
- **WHEN** 某个 forked child 绑定了 `SubagentStop` hooks
- **AND** 该 child 在真正进入模型调用前被拒绝，或在执行早期失败
- **THEN** runtime SHALL 仍然分发对应的 terminal hook payload
- **AND** SHALL 让 hook handler 观察到与 sidechain record 一致的 child terminal status

### Requirement: fork execution preserves a shared prefix contract
runtime SHALL 为 forked child execution 提供稳定的共享前缀构造契约，使多个 child runs 只在 worker-specific directive tail 处发生差异。

#### Scenario: spawning multiple forked workers from the same parent context
- **WHEN** runtime 从同一个父上下文派生多个 forked child workers
- **THEN** runtime SHALL 使用共享的 prefix message history 构造这些 child requests
- **AND** SHALL 将 worker-specific directive 限制在 tail 差异部分

### Requirement: capability trimming is layered
runtime SHALL 以分层 capability trimming 约束 child agent execution，至少覆盖 runtime-global restrictions、spawn-mode restrictions、parent policy ceiling、agent frontmatter restrictions 与 route capability filtering。

#### Scenario: child requests broader capabilities than the parent policy allows
- **WHEN** 某个 child agent 请求的 tools、permissions 或 execution mode 超过 parent policy ceiling 或 route capability 允许范围
- **THEN** runtime SHALL 对该 child execution 进行裁剪或拒绝
- **AND** SHALL NOT 允许 child agent 通过自身 frontmatter 扩大父级未授予的能力

### Requirement: 参考实现兼容的 agent 定义
runtime SHALL 支持与参考实现兼容的 agent 定义语义，包括 tools、disallowed tools、skills、model selection、effort、permission mode、max turns、background execution、memory scope 与 isolation。

#### Scenario: 注册自定义 agent 定义
- **WHEN** 用户使用参考实现兼容字段定义一个 agent
- **THEN** runtime SHALL 在不引入新 agent 定义格式的前提下注册该 agent

### Requirement: 内置 main-router agent
runtime SHALL 内置一个主线程 `main-router` agent，由它承担 runtime routing 决策。

#### Scenario: 主线程执行 routing
- **WHEN** 主线程收到一个请求，该请求可能需要直接回答、通过 tool 处理、通过 skill 处理，或委派给 subagent
- **THEN** `main-router` agent SHALL 成为负责做出 routing 决策的 runtime 实体

### Requirement: subagent 执行复用共享 turn engine
runtime SHALL 使用与主线程相同的 turn engine 执行 subagents，并同时应用 agent 级 capability filtering 与 execution options。

#### Scenario: 启动后台 subagent
- **WHEN** runtime 启动一个后台或被委派的 subagent
- **THEN** runtime SHALL 使用共享 turn engine 执行该 subagent，并 SHALL 应用该 subagent 解析后的 tools、skills、permissions 与 execution limits

