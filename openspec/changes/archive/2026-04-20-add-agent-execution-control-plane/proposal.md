## Context

当前 runtime 在 agent 体系上已经具备一个正确的骨架：

- 主线程与 subagent 共享同一个 `TurnEngine`
- `main-router` 是显式 agent
- `agent` / `skill` 通过 assembled runtime 主路径执行
- policy ceiling 已经开始承担 capability trimming，而不是只依赖 prompt

但这套实现距离参考实现想表达的 agent runtime 还有几个明显缺口：

- agent execution 入口仍然偏薄，缺少一等的 execution spec，很多差异仍靠零散 metadata 塑形
- runtime 仍把所有 agent 绑定到单一全局 `model_client`，`agent.model` 也只是简单字符串透传，缺少一层正式的 route resolution contract，无法在 runtime 内按 agent 选择不同的 `BASE_URL / KEY / MODEL`
- model adapter contract 仍然过薄：`ModelRequest` 没有一等的 route identity、provider identity 与 resolved capability profile，`ModelClient` 也没有声明 normalized capabilities，难以承接 provider-agnostic runtime
- turn 主路径目前实际上是 stream-only，`complete()` 没有真实执行落点；如果 provider 只能提供非流式 completion，或者只能在完整响应后才能产出可解析 tool call，当前 contract 还无法表达正式的 buffered / non-stream provider path，也无法在同一 turn contract 内完成 tool-call normalization
- kernel 对 host 已经有显式 binding，但对 provider 还没有对称的 assembly boundary；如果不引入 runtime-owned provider graph，就会继续把 route resolution 压回外部“大一统 model client”
- 现有 conformance harness 还抓不到 route identity、resolved capabilities 与 provider path 的回归，后续即使 route/capability 丢失，现有 golden/test 也未必会报警
- subagent 缺少 sidechain transcript / run record，后台 agent 也只有 task + notification，没有 child run 级元数据沉淀
- fork 还没有 cache-aware 的上下文构造契约，难以表达“共享请求前缀，只在最后 directive 分叉”的执行语义

这个 change 的目标不是推翻现有 `TurnEngine` 路径，而是在它之上补齐 agent execution control plane。

## What Changes

- 引入统一的 `AgentExecutionSpec` / `AgentExecutionService`，让所有 agent spawn path 都先归一到同一个执行入口
- 引入 named model route / provider route contract，使 agent 能按 route 选择 provider profile、base URL、credential ref 与默认 model，而不是继续依赖单一全局 model client
- 扩展 `ModelRequest` / `ModelClient` contract，把 route identity、provider、resolved capabilities 与 execution mode 变成结构化字段；adapter 需要显式暴露 normalized capabilities，而不是只靠宽泛 metadata 暗传
- 让 `TurnEngine` 真正支持 `stream` 与 buffered / non-stream completion 两类 provider path；buffered path 第一版即支持完整响应后的 tool-call normalization，而不是让 `complete()` 继续停留在死接口状态
- 在 `runtime_kernel` 中增加与 `HostBinding` 对称的 provider assembly boundary，例如 `ModelRoute` / `ProviderBinding` / `ModelRouter` 组装入口，让 runtime 自己拥有 provider control plane
- 为 subagent、forked skill 与 background agent 增加 sidechain run record / transcript contract，保留 parent-child linkage、terminal metadata 与 child message history；第一版采用独立 child-run store，而不是把主 transcript store 扩展成 sidechain 索引
- 增加 fork context builder，定义共享前缀与 worker-specific directive 的构造边界，为 prompt cache 复用预留稳定契约
- 将 capability trimming 扩展成显式的分层策略，而不是只保留当前的 parent ceiling + frontmatter allow/disallow
- 补充 provider / route conformance harness，覆盖 route selection、route metadata、resolved capabilities、invocation-mode selection、buffered completion path、完整响应后的 tool-call normalization 与 capability trimming 回归
- `model_route` 第一版只开放给 `AgentDefinition`；skill 继续通过委派 agent 或 execution-time route hint 间接选择 route，避免 route ownership 在 agent/skill 两套 definition 上分叉

## Goals

- 保留“共享 turn engine”这条已经正确的主线，不为不同 agent 另起一套执行框架
- 让 agent 差异通过 execution spec 的上下文塑形表达出来，而不是散落在 ad-hoc metadata 中
- 让不同 agent 在同一 session 中能够稳定选择不同 provider route
- 让 runtime 自己拥有 provider control plane，而不是继续依赖外部注入一个“大而全”的单体 `model_client`
- 让 route identity、provider identity、resolved capabilities 与 buffered/non-stream invocation path 成为正式 runtime contract
- 支持 tool-capable buffered providers，而不让 provider transport 差异泄漏到 session / tool runtime 上层
- 为后续 teammate / mailbox / swarm 能力提供统一执行基座，而不是先造独立 orchestration engine

## Non-Goals

- 本 change 不实现具体 provider SDK 适配细节
- 本 change 不实现完整 teammate mailbox 系统
- 本 change 不把明文 API key / secret 写进 agent frontmatter
- 本 change 不替换现有 session / turn / tool runtime 分层

## Impact

- 影响 `agent_runtime`、`skill_runtime`、`runtime_kernel`、`turn_engine` 与 transcript/runtime metadata contract
- 需要扩展 agent definition / runtime config / model adapter contract 的模型路由能力
- 需要在 `runtime_kernel` 中引入 provider assembly surface，而不是继续只装配单一全局 `model_client`
- 需要补充 request-level conformance tests，覆盖 route selection、route metadata、resolved capabilities、invocation-mode selection、buffered completion path、完整响应后的 tool-call normalization 与 capability trimming 回归
