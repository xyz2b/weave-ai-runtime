# WeaveRT 系统架构

> 文档说明：这个文件仍然是系统架构的 deep-dive 参考。普通阅读路径请先从 `docs/zh-CN/architecture/overview.md` 和 `docs/zh-CN/architecture/request-lifecycle.md` 开始。

## 对应主文档

- 架构概览 -> `docs/zh-CN/architecture/overview.md`
- 请求生命周期 -> `docs/zh-CN/architecture/request-lifecycle.md`
- Package system -> `docs/zh-CN/architecture/package-system.md`
- Persistence and state -> `docs/zh-CN/architecture/persistence-and-state.md`

## 1. 目的

这篇 deep dive 主要回答：

- runtime 负责什么
- 每个大层拥有哪个主要关注点
- 一次请求如何跨越 session 与 turn 边界
- tools、skills、agents、memory 与 control-plane surfaces 如何拼在一起
- 哪些地方适合扩展，哪些地方开始进入 kernel edits

## 2. 系统定位

WeaveRT 的定位不是单个预设助手，而是一套可嵌入、可组合、保留所有权边界的运行时。

## 3. 核心架构原则

### 3.1 Ingress 先于 turn execution

- 不是每个输入都会变成新的 model turn
- replay、acknowledgements 与 private updates 可能对 session 可见，但不一定接纳一个 turn
- transcript continuity 需要只有一个权威

### 3.2 Prompt-visible context 与 runtime-private context 分离

- prompt-visible context
- runtime-private state
- diagnostics / control-plane state

模型可见上下文有不同的安全与正确性要求；host 或 control-plane 私有状态不应变成 prompt 文本。

### 3.3 Transcript truth 与 active context projection 分离

- compacted 或 retrieved context 不等于 transcript truth
- prompt construction 可以变化，但 durable history 不应被悄悄改写

### 3.4 Attempt-final 不等于 turn-final

这一区分支撑：

- tool continuation
- recovery handling
- stop / resume logic
- child execution follow-up

### 3.5 生命周期所有者必须显式

Host、session、turn engine 与 delegated execution 都必须保留清晰边界。

## 4. 分层所有权视图

### 4.1 App 或 host 层

- UX 与 rendering
- 本地 shell 或 UI 行为
- 部署级 provider / store 选择
- approval 与 elicitation 展示
- audit sinks 与 deployment policy

### 4.2 Assembly 层

- `RuntimeConfig`
- distribution choice
- package admission 与 selection
- discovery sources
- model routes
- store bindings
- host binding inputs

### 4.3 Session 层

- ingress normalization
- transcript continuity
- private updates 与 replay handling
- 决定输入是否真正接纳一个新 turn

### 4.4 Turn-execution 层

- active context assembly
- model request / response processing
- tool orchestration
- skill execution
- agent delegation
- recovery 与 continuation
- terminal turn result production

### 4.5 横切 control-plane 层

- hooks
- permissions
- elicitation
- memory
- compaction
- host bridge mediation
- job / task-facing services

## 5. 请求流转台账

需要长期记住的是：

- host event 可以影响 session，而不一定变成新的 turn
- active context 是投影视图，而不是完整 transcript 或 private state bag
- 即使 provider 支持 tool calls，tool continuation 仍由 runtime 拥有
- recovery 属于 runtime control plane，而不属于某个 model transport

## 6. 执行能力层

### 6.1 Tool runtime

- 文件或工作区操作
- API 或服务调用
- 可复用的结构化能力

### 6.2 Skill runtime

- inline workflow guidance
- 可复用的 review / verification 过程
- delegated forked subflows

### 6.3 Agent runtime

- 具名 workers，如 reviewer 或 planner
- 受限 delegated roles
- prompt identity + policy choices

## 7. Invocation visibility 与 capability resolution

可见能力由多层共同决定：

- discovered definitions
- package contributions
- path activation
- host 或 policy narrowing
- request-time capability refresh

## 8. Memory runtime 边界

- memory policy 由 runtime 拥有
- retrieval 与 extraction posture 应可配置
- 某个 turn 的 memory selection 属于 active context assembly
- memory 不会取代 transcript truth
- compaction 与 memory 有关，但仍是独立边界

## 9. Host bridge 与交互控制面

Host bridge 主要承担：

- permissions
- elicitation
- notifications
- turn events
- host-owned lifecycle presentation

## 10. Team 与 delegated orchestration

团队与委派层需要让下列问题保持可观察：

- 事件观测
- 进度渲染
- 协作 UX
- team state
- delegation semantics
- child-run control flow

## 11. 状态与持久化权威

Transcript、child runs、jobs、task lists 与 memory artifacts 都应有显式权威所有者，不因 app 壳层而被模糊。

## 12. 扩展 seams

普通扩展入口包括：

- 本地 tools、agents、skills
- package manifests 与 package contributions
- model routes
- memory policy
- 稳定公开 hooks
- host binding
- request-time context contributors

## 13. 大多数集成方一开始不要碰什么

- `SessionController`
- `TurnEngine`
- core runtime-private state handling
- kernel-owned first-party assembly tables

## 14. 相关文档

- `docs/zh-CN/architecture/overview.md`
- `docs/zh-CN/architecture/request-lifecycle.md`
- `docs/zh-CN/architecture/persistence-and-state.md`
- `docs/zh-CN/deep-dives/weavert-integration-guide.md`
- `docs/zh-CN/deep-dives/weavert-control-plane-extension-guide.md`
- `docs/zh-CN/deep-dives/layered-memory-weavert-v2.md`
