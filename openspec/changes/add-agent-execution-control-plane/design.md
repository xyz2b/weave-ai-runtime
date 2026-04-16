## Context

当前 runtime 在 agent 方向上最正确的地方，是没有为 subagent 单独发明另一套 conversation engine。`AgentRuntime` 最终仍然把 agent 执行落到共享 `TurnEngine`。这条方向应当保留。

真正不足的地方不是“没有 agent”，而是 agent execution control plane 还太薄：

- 入口对象过于简化，只能传 prompt 与少量 metadata
- model selection 仍停留在单一全局 `model_client` 下的 model 名称透传，不能表达 provider route，也不能在 runtime 内按 agent 选择不同的 `BASE_URL / KEY / MODEL`
- `ModelRequest` / `ModelClient` contract 过薄，缺少一等的 route identity、provider identity、resolved capability profile 与 invocation mode
- turn 主路径实际上是 stream-only，`complete()` 还没有真实执行落点，无法承接 buffered / non-stream provider path
- kernel 对 host 有显式 binding，但对 provider 还没有对称的 assembly boundary，provider control plane 仍被迫外置
- conformance harness 还抓不到 route identity、resolved capabilities 与 provider path 回归
- child run 缺少 sidechain record
- fork 缺少 cache-aware context builder
- capability trimming 还没有形成稳定的多层 contract

这个 change 的目标是把这些差异显式化，但不引入第二套执行引擎。

## Goals / Non-Goals

**Goals**

- 保持所有 agent 执行最终复用共享 `TurnEngine`
- 把 spawn path 与真正执行解耦：入口负责路由，执行服务负责组装 execution spec 并运行
- 支持按 agent 选择不同 model/provider route
- 让 runtime 自己拥有 provider control plane，而不是继续依赖外部单体 `model_client`
- 让 route identity、provider identity、resolved capabilities 与 invocation mode 成为正式 contract
- 为 child run 增加 sidechain transcript / run record
- 为 fork 增加稳定的上下文构造契约
- 把 capability trimming 收敛成明确的 layered policy

**Non-Goals**

- 不实现 provider SDK fallback / retry 细节
- 不把 secrets 直接暴露到 agent frontmatter
- 不在本 change 中引入独立 swarm engine

## Decisions

### 1. 引入统一的 `AgentExecutionSpec` 与 `AgentExecutionService`

所有 agent 执行路径，包括：

- `agent` tool 委派
- background agent
- forked skill agent context
- 未来 teammate / mailbox worker

都应先收敛为一个一等的 `AgentExecutionSpec`，再进入统一的 `AgentExecutionService.run(spec)`。

建议 `AgentExecutionSpec` 最少携带：

- `run_id`
- `parent_run_id`
- `session_id`
- `turn_id`
- `agent_name`
- `spawn_mode`
- `query_source`
- `prompt_messages`
- `base_system_prompt`
- `cwd`
- `parent_policy_state`
- `requested_model_route`
- `requested_model`
- `background`
- `metadata`

字段级 contract 建议固定为：

- `run_id`
  - child execution 的稳定主键
  - 在 dispatch 阶段生成，随后贯穿 request metadata、child run record、host notification 与 tracing
  - 同一个 child run 内不得重新生成新的 `run_id`
- `parent_run_id`
  - 指向直接父 execution；root turn 为空
  - 只能表达直接父子关系，不承担跨层祖先链编码
- `session_id`
  - 继承自当前 session
  - 所有 child run record 必须复用父 session，而不是隐式新开 session
- `turn_id`
  - 表示当前 child execution 自己的 turn identity
  - 允许在 dispatch 时为空，并由 execution service 在真正进入 `TurnEngine` 前补齐
- `agent_name`
  - 指向解析后的 child agent definition
  - 一旦进入 execution service 不应再被 prompt 或 route 覆写
- `spawn_mode`
  - 显式区分 `sync`、`background`、`fork`、`teammate`
  - 用于 layered policy、run record 和 host observability，不能只靠 metadata 推断
- `query_source`
  - 用于区分 `agent_tool`、`skill_fork`、`background_agent` 等入口来源
  - 应进入 request metadata 与 child run record，便于回放和调试
- `prompt_messages`
  - child agent 真正消费的消息输入
  - fork path 允许通过专门 context builder 生成；其他路径可以只携带单个 user prompt
- `base_system_prompt`
  - child agent 进入 `TurnEngine` 前的基础 system prompt
  - 允许 parent/system shaping 叠加，但 execution service 需要给出最终单一来源
- `cwd`
  - child 执行实际使用的工作目录
  - 必须先于工具调度与隔离准备阶段确定
- `parent_policy_state`
  - 表示 parent ceiling 的直接输入
  - child execution 可以收窄，但不能突破该 ceiling 扩权
- `requested_model_route`
  - execution-time route hint
  - 优先级高于 agent-level `model_route`
- `requested_model`
  - execution-time model override
  - 只允许覆盖已解析 route 的默认模型名，不允许改变 provider ownership
- `background`
  - 表示该次 child run 是否以异步后台模式运行
  - 不应与 `spawn_mode` 冲突；如两者同时出现，以显式 `spawn_mode` 为准
- `metadata`
  - 保留非核心扩展位
  - 不得承载已经拥有一等字段的核心 contract，例如 route identity、spawn mode、run linkage

对应 `AgentRunRecord` 建议固定为：

- `run_id`、`parent_run_id`、`session_id`、`parent_turn_id`、`agent_name`、`spawn_mode`
  - 作为 child run linkage 的最小索引集
- `resolved_model_route`
  - 记录最终 route resolution 结果，而不是原始请求 hint
- `request_metadata`
  - 记录本次执行真正送往 provider / turn runtime 的结构化上下文
- `terminal_metadata`
  - 记录 stop reason、usage、error、abort reason 与 provider terminal details
- `messages`
  - 记录 child 内部消息历史；主 transcript 不必完整复制这些消息
- `status`
  - 至少区分 `running`、`completed`、`failed`、`denied`
  - background child 至少要有一次初始 `running` 持久化，再写终态

写入规则建议固定为：

- sync child 至少写一次终态 `AgentRunRecord`
- background child 至少写两次：启动时 `running`，结束时 terminal status
- denied child 也必须写 run record，不能因为未进入模型调用就丢失 observability
- child run record 的完整消息历史进入 sidechain；主 transcript 只保留 continuation 必需消息与 tool results

Why:

- 这样可以保留“共享 turn engine”的统一性，同时补足 Claude 风格的“上下文塑形”
- 把差异显式放进 spec，比继续在 metadata 里隐式拼装更稳定
- 后续 teammate / mailbox 也能直接复用这一层，而不是重新发明执行入口

Alternatives considered:

- 继续沿用当前偏薄的 `AgentInvocation`，靠 metadata 扩展。拒绝，因为核心 contract 会继续漂移到非结构化 dict 中。
- 为 fork / background / teammate 分别定义不同 runner。拒绝，因为这会破坏统一执行器设计。

### 2. 保留“单一执行内核，多种 spawn mode”，但把 dispatch 与 execution 分开

runtime 需要区分两层职责：

- `AgentDispatcher`
  - 判断是 sync、background、fork、teammate 还是 future remote worker
  - 计算 parent/child linkage、spawn mode 与 route hint
  - 生成 `AgentExecutionSpec`
- `AgentExecutionService`
  - 解析 agent definition
  - 解析 layered policy
  - 解析 model route
  - 构造 child run context
  - 调用共享 `TurnEngine`
  - 记录 sidechain transcript / terminal metadata

Why:

- Claude Code 的可取之处不是 spawn branch 数量，而是 branch 之后仍会归一到共享执行器
- 让 dispatch 只负责路由，可以避免执行逻辑继续分散在工具入口、技能入口和后台逻辑里

Alternatives considered:

- 让 `AgentRuntime.invoke()` 继续同时承担 dispatch 和 execution。拒绝，因为随着 route、fork、transcript 增长，这个入口会继续膨胀。

### 3. 用 named model route 和 provider binding，而不是把 transport 细节塞进 `model`

当前 `agent.model` 只适合表达 provider-native 的模型名，不适合承载：

- provider identity
- base URL
- credential source
- capability profile
- invocation mode

这个 change 引入 runtime-level named model routes。

建议：

- `AgentDefinition` 新增可选 `model_route`
- 第一版不为 `SkillDefinition` 新增 `model_route`
- `RuntimeConfig` 新增 `model_routes`、`provider_bindings` 与 `model_router`
- route profile 至少包含：
  - `provider`
  - `base_url`
  - `credential_ref`
  - `default_model`
  - `capabilities`
  - `supported_invocation_modes`
  - `metadata`
- `ModelRequest` 扩展为显式携带：
  - `resolved_model_route`
  - `provider`
  - `resolved_capabilities`
  - `invocation_mode`
- `ModelClient` / provider adapter 需要显式声明：
  - 自身支持的 normalized capabilities
  - 支持的 invocation modes，例如 `stream`、`buffered_completion`
- `runtime_kernel` 需要像装配 host 一样装配 provider graph，而不是只接受一个外部拼好的 `model_client`

解析优先级建议为：

1. execution spec 显式 route override
2. agent definition 的 `model_route`
3. inherited route hint
4. runtime default route

而 `model` 字段仍保留 Claude 兼容语义，只用于覆盖 route 的默认模型名，不承担 transport 配置。

补充约束：

- `model_route` 决定 provider route ownership；`model` 只决定最终使用的模型名，二者职责不能混淆
- 当同时出现 `requested_model_route` 与 `model_route` 时，以 execution-time override 为准
- 当 route 已经解析完成后，`model` 只能覆盖该 route 的 `default_model`，不能把请求重新路由到另一 provider
- fork/background child 默认继承 parent route hint；只有显式允许 override 的入口才能切换 route
- 如果 child 请求的 route 超出 parent policy 或 runtime-global route policy，runtime 应拒绝或回退到父级允许范围，而不是静默扩权
- forked skill 第一版继续通过其 delegated agent 解析 route，不单独引入 skill-level route ownership；这样 route precedence 只需围绕 execution spec 与 agent definition 建模

建议将这套 precedence 固定成独立 contract，而不是散落在调用方约定里。

`main-router` 与 `ModelRoute` 的关系需要明确区分：

- `main-router` 是内置的主线程 agent，职责是决定这轮对话走“直接回答 / 调 tool / 调 skill / 委派 subagent”中的哪条执行路径
- `ModelRoute` 是 provider / model transport 控制面，职责是决定某个 agent 最终走哪条 provider binding、哪个 `base_url`、哪套 credentials、哪个默认 model 与哪些 normalized capabilities
- 二者不是同一层概念：`main-router` 可以像其他 agent 一样绑定某个 `model_route`，但它本身不是 route resolver
- `main-router` 作为 root agent 解析出的 route，可以成为 child execution 的 inherited route hint；但 child 是否继承、切换或被拒绝，仍由统一的 route precedence 与 policy contract 决定
- 如果 `main-router` 未显式声明 `model_route`，则它与其他 agent 一样回退到 runtime default route，而不是拥有单独的隐式 transport 特权

最小 capability taxonomy 建议固定为：

- `tool_calls`
- `streaming`
- `buffered_completion`
- `vision`
- `reasoning_effort`
- `json_mode`

约束建议：

- route profile、provider adapter 与 `ModelRequest` 都应使用同一组 normalized capability keys
- runtime policy 与 capability filter 只能消费这组规范化 key，不能依赖 provider 私有能力名
- provider 私有能力可以保留在 route metadata 中，但不得替代 normalized capability contract
- 当 route 与 adapter 声明不一致时，以运行时可验证的交集能力作为 `resolved_capabilities`

Why:

- 这能满足“不同 agent 走不同 BASE_URL / KEY / MODEL”的需求
- 避免把 secrets 暴露到 agent frontmatter
- route 是 runtime control plane 能力，不应退化成字符串拼接约定
- provider graph 进入 kernel 之后，runtime 才真正拥有 provider control plane，而不是继续依赖外部“大一统 model client”
- route identity 与 capability profile 结构化之后，后续 provider-agnostic policy 才有稳定落点

Alternatives considered:

- 继续只保留一个全局 `model_client`，让外部自己从 `request.model` 猜 route。拒绝，因为这不是稳定 contract。
- 把 `base_url` / `api_key` 直接写进 agent frontmatter。拒绝，因为这会把 secrets 与 repo 内容耦合。

最小配置样例建议如下：

```yaml
runtime:
  default_model_route: openai_default
  provider_bindings:
    - name: openai-prod
      provider: openai
      base_url: https://api.openai.com/v1
      credential_ref: env:OPENAI_API_KEY
    - name: local-gateway
      provider: openai_compatible
      base_url: https://llm-gateway.internal/v1
      credential_ref: secret:gateway_api_key

  model_routes:
    - name: openai_default
      provider_binding: openai-prod
      default_model: gpt-5
      capabilities:
        streaming: true
        buffered_completion: true
        tool_calls: true

    - name: reviewer_route
      provider_binding: local-gateway
      default_model: reviewer-large
      capabilities:
        streaming: false
        buffered_completion: true
        tool_calls: true

agents:
  - name: main-router
    model_route: openai_default
  - name: reviewer
    model_route: reviewer_route
    model: reviewer-large
```

样例约束：

- provider binding 持有 provider identity、credential source 与 base URL
- model route 持有 route-level default model 与 normalized capabilities
- agent 只引用 route name，不直接持有 secret 或 transport 配置
- 同一 session 内不同 agent 可以解析到不同 route / provider binding
- `main-router` 只是这些 agent 中的一个内置 root agent；它可以绑定 `openai_default`，但该 route 仍是 runtime-level control plane 对象，而不是 `main-router` 自身的一部分

### 4. `TurnEngine` 必须同时支持 streaming 与 buffered completion path

当前 turn 主路径只真正消费 `stream()`；这会把 provider contract 锁死在 streaming-only 假设上。

建议：

- `ModelClient` 保留 `stream()` 与 `complete()` 两类入口，但 runtime 需要根据 route / adapter capabilities 选择真实执行路径
- 当 route 或 adapter 不支持 streaming 时，`TurnEngine` 应走 buffered completion path
- buffered path 仍然需要回到统一的 message / tool call normalization，不能为 non-stream provider 另造一套上层消息协议
- 第一版范围直接包含“完整响应后 tool call normalization”，不再拆出 text-only buffered 过渡阶段

buffered / non-stream turn 语义建议固定为：

- `TurnEngine` 在 request 发出前先根据 `resolved_capabilities` 与 adapter declaration 选择 `invocation_mode`
- 当 `invocation_mode=buffered_completion` 时，adapter 返回完整响应后，runtime 仍需归一成与 streaming path 相同的 assistant message、tool call 与 terminal metadata 结构
- 如果 provider 只能在完整响应后给出可解析 tool call，tool call normalization 也应发生在 buffered path 内部，而不是把这类 provider 排除在 agent runtime 之外
- `request_id`、`usage`、`stop_reason`、`error`、`abort_reason` 等 terminal fields 在 streaming 与 buffered path 下应保持同一语义
- capability trimming 与 tool policy 发生在 provider 调用之前，不因 buffered path 而放松约束
- 上层 `SessionController`、`ToolScheduler` 与 transcript contract 不应感知 provider 是 streaming 还是 buffered

Why:

- 这样 provider contract 才能覆盖只支持完整响应返回的 adapter
- 也能承接“完整响应后才可解析 tool call”的 provider
- 保持上层 turn / tool runtime 继续面向统一消息协议，而不是感知 provider transport 差异

Alternatives considered:

- 继续把 `complete()` 保留为协议占位。拒绝，因为这会让 non-stream provider 永远没有正式落点。
- 先做 buffered text-only completion，再把 tool call normalization 延后到下一版。拒绝，因为这会让 tool-capable non-stream provider 仍然没有正式执行落点，也会把 invocation-mode contract 人为拆成两个阶段。

### 5. 为 child agent run 建立 sidechain transcript / run record

主线程 transcript 不应承担所有 child run 的完整记录。runtime 应增加 child run 级别的 sidechain record，至少保留：

- `run_id`
- `parent_run_id`
- `session_id`
- `parent_turn_id`
- `agent_name`
- `spawn_mode`
- `query_source`
- `resolved_model_route`
- `status`
- `request metadata`
- `terminal metadata`
- `messages`

主线程继续只接收对当前 continuation 必要的 `tool_result` / summary，而 child run 的完整消息历史与终态进入 sidechain record。

sidechain transcript 的落点固定为独立 child-run store，而不是 transcript store 扩展索引：

- 现有 `TranscriptStore` contract 只围绕主 session message append/load/replace 建模，不承担 child-run record 的索引与状态更新语义
- child run record 需要稳定表达 `running` 到 terminal status 更新、denied/early-failed 最小记录，以及 host/test 可枚举的独立观测面
- 因此第一版引入独立的 child-run store 或等价 sidechain service 接口，主 transcript contract 继续只服务 continuation 历史，不为 sidechain 引入额外写入语义

Why:

- 这样后台 agent、forked skill 与 future teammate 才有统一的观测面
- 主线程 transcript 可以保持稳定，不必为 child internals 膨胀
- sidechain record 能让 host、tests 与 future mailbox 都消费同一种 child run 契约

Alternatives considered:

- 把 child run 完整消息直接塞回主 transcript。拒绝，因为这会污染主 continuation 历史。
- 完全不记录 child run，只保留最终消息。拒绝，因为这会让 agent runtime 缺少可调试性与可验证性。

### 6. fork 使用专门的 `ForkContextBuilder`

fork 不应只是“复制父 prompt 再改一句话”。runtime 应定义一个明确的 `ForkContextBuilder`，负责：

- 生成所有 child 共享的 prefix
- 为 shared prefix 中的 tool uses 生成 continuation-safe 占位结构
- 只让 worker-specific directive 出现在 tail 部分

第一版不必强绑定某个 provider 的 cache 实现，但必须把“共享前缀 + 最后 directive 分叉”收敛成稳定 contract。

Why:

- 这能保留 Claude fork 设计里真正有价值的部分：prompt cache 复用
- 独立 builder 也比在 `AgentRuntime` 里 ad-hoc 拼 message 更容易测试

Alternatives considered:

- 继续让 fork 直接复制全部上下文。拒绝，因为这会让 cache-aware fork 无法成为正式能力。

### 7. capability trimming 使用 layered policy，而不是单层 allowlist

当前 runtime 已经有 parent ceiling 与 frontmatter allow/disallow，但还需要继续收敛成显式分层：

1. runtime-global denied tools / skills
2. spawn-mode specific denied set
   - 例如 background agent、fork worker、future teammate 的额外限制
3. parent effective policy ceiling
4. agent frontmatter `tools` / `disallowedTools` / `skills`
5. provider/model capability filter
   - 比如当前 route 不支持 tools、streaming 或某类 executor tier

任何 child agent 都不应突破上层 ceiling 扩权。

Why:

- Claude 的可取之处在于 capability trimming 是 runtime contract，不是 prompt 约定
- route capability 进入这一层后，provider routing 才会真正影响 agent execution，而不只是影响 transport

Alternatives considered:

- 继续只靠 parent ceiling 与 agent allow/disallow。拒绝，因为这无法表达 background/route/global 三类限制。

### 8. teammate / mailbox 未来也应包在同一个执行器之上

本 change 不实现完整 teammate mailbox，但要把扩展方向固定下来：

- mailbox / identity / permissions bridge 属于 agent orchestration 外层
- 真正执行 child run 时仍然进入 `AgentExecutionService.run(spec)`

Why:

- 这能避免后续为了 multi-agent 再造一套独立 orchestration engine
- 也符合当前 runtime 已经建立起来的共享 turn engine 方向

## Architecture Sketch

```text
agent tool / skill fork / background / future teammate
                       │
                       ▼
                AgentDispatcher
         route spawn mode + build spec
                       │
                       ▼
               AgentExecutionSpec
        prompt_messages / policy / route / linkage
                       │
                       ▼
            AgentExecutionService.run()
   resolve agent -> resolve layered policy -> resolve model route
      -> build sidechain run -> shared TurnEngine -> persist record
```

## Data Model Notes

建议新增或扩展的核心对象：

- `AgentExecutionSpec`
- `AgentRunRecord`
- `SpawnMode`
- `ModelRouteDefinition`
- `ProviderBinding`
- `ResolvedModelRoute`
- `ModelRouter`

建议保留现有：

- `TurnEngine`
- `ExecutionPolicyState`
- `SessionController`

## Risks / Trade-offs

- **[控制面复杂度上升]** agent execution contract 会明显比当前更重。 → Mitigation: 保持 dispatch 与 execution 分层，不把复杂度重新塞回 tool entry。
- **[provider 抽象过早失真]** model route 如果定义过度，会与真实 provider adapter 脱节。 → Mitigation: 只要求最小 route profile，不提前承诺 retry/fallback 细节。
- **[provider graph 进入 kernel 后装配复杂度上升]** runtime 需要持有显式 provider assembly boundary。 → Mitigation: 保持 `ProviderBinding` / `ModelRouter` 最小化，只承担 route ownership、adapter selection 与 capability declaration。
- **[transcript 面扩张]** sidechain record 可能引入新的存储与 host 观察面。 → Mitigation: 主 transcript 与 sidechain transcript 分离，主路径只保留 continuation 必需信息。
- **[兼容性迁移]** 现有 `agent.model` 与单一 `model_client` 用户需要迁移路径。 → Mitigation: 保留 `model` 兼容语义，并允许 default route 承接旧配置。
- **[fork cache 价值依赖 provider]** 不同 provider 的缓存机制不同。 → Mitigation: 先把 shared-prefix contract 固定下来，不绑定某个 provider 专有实现。
- **[双路径执行增加协议复杂度]** stream 与 buffered path 都要落到同一消息协议。 → Mitigation: buffered path 只在 adapter 边界不同，进入 turn runtime 之前统一归一为同一种 message/tool call model。

## Migration Plan

1. 将已确认的 buffered-path 决议回写到 proposal / design / spec / tasks artifacts。
2. 先新增 `AgentExecutionSpec`、`SpawnMode` 与 `AgentRunRecord` contract。
3. 将 `agent` tool、background agent、forked skill 入口统一改为先生成 spec，再进入共享执行服务。
4. 在 runtime config 中引入 named model routes、`ProviderBinding` 与 `ModelRouter`，让 kernel 显式装配 provider graph。
5. 固定 route precedence、`model_route` / `model` 分工与 route-policy enforcement contract。
6. 扩展 `ModelRequest` / `ModelClient` contract，显式引入 route identity、resolved capabilities 与 invocation mode。
7. 让 `TurnEngine` 支持 stream 与 buffered completion 两类 provider path，并在 buffered path 内完成完整响应后的 tool-call normalization。
8. 把 route resolution 写回 request metadata / sidechain record，并增加 child run record store。
9. 引入 `ForkContextBuilder`，让 fork path 不再直接复制上下文。
10. 扩展 layered capability trimming 与 route capability filter。
11. 用 conformance matrix 锁定 sync/background/fork/route/provider-path/sidechain 行为后再推进默认启用。

## Open Questions

- provider binding 是否需要支持按 provider family 复用共享 credential/base URL 模板，还是第一版只支持 fully-resolved named routes？
- fork builder 第一版是否需要直接生成 provider-ready message history，还是只生成 provider-agnostic content blocks？
