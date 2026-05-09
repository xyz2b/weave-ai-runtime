# WeaveRT 集成指南

> 文档说明：这是集成层的 deep-dive 参考。主路径请先读 `docs/zh-CN/getting-started/quickstart.md`，再按需进入 host binding、OpenAI integration 与 architecture 文档。

## 对应主文档

- First run -> `docs/zh-CN/getting-started/quickstart.md`
- Official starter path -> `docs/zh-CN/getting-started/starter-scaffolds.md`
- Host binding -> `docs/zh-CN/guides/bind-a-host.md`
- OpenAI live route -> `docs/zh-CN/guides/integrate-openai.md`
- Architecture overview -> `docs/zh-CN/architecture/overview.md`

这篇文档重点回答：

- 调用方应先集成哪个 runtime surface
- `RuntimeConfig`、`RuntimeAssembly`、`BoundHostRuntime` 与 `DefinitionSourcePaths` 如何分责
- “package boundary” 在 runtime 语义上是什么意思
- 哪些生命周期与策略关注点仍由 app 拥有

## 1. 一句话心智模型

四个最重要的集成表面仍是：

- `RuntimeConfig`
- `RuntimeAssembly`
- `BoundHostRuntime`
- `DefinitionSourcePaths`

## 2. 稳定集成表面

### 2.1 `RuntimeConfig`

它负责：

- distribution selection
- working directory
- discovery sources
- built-in selection 与 replacement
- package admission 与 package requests
- host binding inputs
- model client 与 model routes
- transcript / child-run stores
- memory config

通常的选择方式：

- 需要快速获得已知 assembly posture 时，用 preset
- 已经有强定制 routing、stores 或 package policy 时，再手动构造

### 2.2 `RuntimeAssembly`

它负责：

- one-shot prompt helpers
- streaming prompt helpers
- session creation
- invocation visibility 与 diagnostics
- assembly-level inspection 与 metadata access

### 2.3 `BoundHostRuntime`

适合：

- CLI shells
- SDK-owned interactive sessions
- web / desktop UI shells
- 需要 approvals、elicitation、notifications 与 turn-event rendering 的场景

### 2.4 `DefinitionSourcePaths`

默认文件型发现规则：

- `tools/*.py`
- `agents/*.md`
- `skills/**/SKILL.md`

## 3. Distribution 与 package 边界

- distribution 只决定默认组装哪些 first-party packages
- 外部 packages 通过 `extra_package_manifests` 进入候选集合
- admitted packages 只有在真正进入 resolved graph 后才会 active
- scenario packs 仍是普通 packages，不是特殊 kernel mode

需要分开看：

- distribution
- scenario pack
- app-owned wiring

## 4. Package boundary 意味着 protocol attachment

真正的 package boundary 体现在：

- manifest admission 与 dependency ordering
- `PackageContribution`
- invocation providers
- context contributors
- capability lookup
- host-facet lookup
- lifecycle participation

不要再依赖：

- patch kernel-owned first-party tables
- 给 `RuntimeServices` 添加 package-specific ad hoc fields
- 为某个 package family 扩展 mandatory host contracts

## 5. 不同角色应从哪里接入

- business caller：先从 `RuntimeAssembly` 开始
- host integrator：先从 `bind_host(...)` 开始
- capability author：先从 `.weavert/` discovery 与 guides 开始
- 只有 runtime maintainers 才应从 `SessionController` 或 `TurnEngine` 开始

## 6. 三种集成姿态

### 6.1 Embeddable runtime

适合：

- prompt execution
- session reuse
- offline / headless workflows
- 最小 control-plane customization

主表面：`RuntimeAssembly`

### 6.2 Host-bound runtime

适合：

- 显式生命周期所有权
- approval 与 elicitation UX
- notifications 与 turn events
- host-local shell 或 UI 行为

主表面：`BoundHostRuntime`

### 6.3 Capability-extending runtime

适合：

- 本地 tools、agents 或 skills
- package-level reusable capability groups
- custom invocation providers
- scenario-pack 或 shared-package composition

主表面：

- `DefinitionSourcePaths`
- package manifests 与 package contributions

## 7. 集成方应牢记的 request-flow 边界

- 不是每个输入都会变成一个 turn
- active context 只是投影，不是完整 runtime-private state bag
- 一次 model attempt 结束，不等于 turn 已终态
- recovery、tool continuation、permissions 与 host mediation 仍属于 runtime-owned control flow

## 8. 值得保留在平台层的扩展点

### 8.1 Model routes

适合：

- 不同 workflows 需要不同 providers 或策略
- 你想做 route-level request shaping
- 你希望 provider-specific 行为与应用 prompts 隔离

### 8.2 Memory policy

适合：

- retrieval 与 extraction 的取舍需要可配置
- 不同部署需要不同 persistence 或 compaction posture
- memory 应保持为 runtime service，而不是 prompt 约定

### 8.3 Provider-only invocation packages

当你只想扩展 provider route，而不是扩展整个 host/app 层时使用。

### 8.4 Request-time context contributors

适用于：

- prompt-visible fragments
- runtime-private fragments
- diagnostics

### 8.5 Runtime-owned team mode

团队协作能力应继续作为 runtime-owned capability surface 存在，而不是被某个 app 私有壳层吞掉。

## 9. 集成出问题时该看什么

- assembly posture
- capability visibility
- host binding
- runtime flow

## 10. 简短集成检查表

1. 先确认你在用哪种 preset 或手动 `RuntimeConfig(...)`
2. 检查 discovery roots 与 package requests
3. 区分 admitted packages 与 active packages
4. 需要 UX / approvals 时再绑定 host
5. 需要 live route 时先做 preflight

## 11. 相关文档

- `docs/zh-CN/architecture/overview.md`
- `docs/zh-CN/architecture/request-lifecycle.md`
- `docs/zh-CN/guides/bind-a-host.md`
- `docs/zh-CN/guides/integrate-openai.md`
- `docs/zh-CN/deep-dives/weavert-definition-authoring-guide.md`
- `docs/zh-CN/deep-dives/weavert-control-plane-extension-guide.md`
- `docs/zh-CN/deep-dives/current-system-architecture.md`
- `docs/zh-CN/deep-dives/layered-memory-weavert-v2.md`
