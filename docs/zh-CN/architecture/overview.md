# 架构概览

这页只回答一个问题：WeaveRT 的主要层有哪些，以及每层拥有些什么？

```text
你的应用 / 宿主
  -> RuntimeConfig
  -> RuntimeAssembly
  -> SessionController
  -> TurnEngine
  -> Tools / Skills / Agents / Memory / Hooks / Permissions
```

## 适合谁？

- 正在评估 runtime 在底层如何被组装、执行和持久化的读者。

## 前置条件

- 先读 `../concepts/runtime-model.md`
- 在把这层当作更深的架构层之前，先用 concepts 页面补齐词汇

## 两个平面：控制面与执行面

理解这套架构的一个有用方式，是分开看两个平面：

- control plane
  - hooks
  - permissions
  - elicitation
  - memory
  - compaction
  - host bridge
  - task 与 job surfaces
- execution plane
  - model invocation
  - tool orchestration
  - skill execution
  - agent delegation
  - teammate orchestration

重点不是把它们完全隔离，而是让所有权保持明显。

## 第 1 层：应用或宿主

你的产品拥有用户体验、审批、本地命令和应用特定呈现。
它不需要重实现 runtime loop。

## 第 2 层：Assembly

`RuntimeConfig` 描述期望的 runtime posture。
`RuntimeAssembly` 暴露组装完成后的 prompts、sessions、binding 和 inspection 表面。

这也是 package 与 distribution posture 可见的地方：

- `weavert-core`
- `weavert-default`
- `weavert-full`
- 显式 package manifests 与 requested packages

## 第 3 层：Session

Sessions 负责规范 ingress、维护 transcript continuity，并决定输入是否应被接纳为一个 turn。
它是 “发生了某件事” 和 “应该执行一个 turn” 之间的边界。

## 第 4 层：Turn engine

Turn engine 拥有一次执行循环：

- model request 与 response handling
- tool orchestration
- skill execution
- agent delegation
- terminal result production

## 第 5 层：横切运行时服务

Hooks、permissions、elicitation、memory、compaction 和 host bridges 都会从侧面塑造执行过程，但不会取代 turn engine 本身。

## 到处都会出现的原则

阅读更深架构页时，请始终记住这些规则：

- ingress 先于 turn execution
- prompt-visible context 与 runtime-private state 分离
- transcript truth 与 active context projection 分离
- attempt-final 与 turn-final 分离
- 生命周期所有权保持显式

## 大多数集成方一开始不该做什么

不要把 `TurnEngine` 当成普通 SDK 入口。
大多数用户应停留在 `RuntimeConfig`、`RuntimeAssembly`、本地 definitions、package selection 与 bound-host 这一层。

## 下一步

- 读 `request-lifecycle.md`，追踪一条输入如何经过 ingress、turn execution 和 terminal persistence
- 如果你的问题其实是 package 所有权或激活，读 `package-system.md`
- 如果问题具体落在持久工件边界上，读 `persistence-and-state.md`

## 另见

- `request-lifecycle.md`
- `package-system.md`
- `persistence-and-state.md`
- `../deep-dives/current-system-architecture.md`
