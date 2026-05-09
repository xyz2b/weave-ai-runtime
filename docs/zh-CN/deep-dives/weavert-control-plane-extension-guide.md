# WeaveRT 控制面与 Hook 集成

> 文档说明：这是 control-plane extension 的 deep-dive 参考。普通路径请先读 `docs/zh-CN/guides/extend-the-control-plane.md`、`docs/zh-CN/guides/bind-a-host.md` 与 `docs/zh-CN/guides/register-hooks.md`。

## 对应主文档

- Host binding -> `docs/zh-CN/guides/bind-a-host.md`
- Control-plane overview -> `docs/zh-CN/guides/extend-the-control-plane.md`
- Hook authoring -> `docs/zh-CN/guides/register-hooks.md`
- Concept boundary -> `docs/zh-CN/concepts/hosts-permissions-memory.md`

## 1. 先分清两类“像 Hook 的表面”

### 1.1 Event hooks

- event-driven
- phase-based
- payload-oriented
- 通过 hook effects 消费

典型 phases：

- `PreToolUse`
- `PostToolUse`
- `PreModelRequest`
- `Stop`
- `Elicitation`

### 1.2 Context contributors

- `PackageContribution.context_contributors`
- `RuntimeServices.context_contributor_execution_plan()`

它不是 event bus，而是在 request assembly 期间执行，可贡献 prompt、private 或 diagnostics 数据。

经验法则：

- 响应 runtime phases 时用 hooks
- 在 model call 之前塑造 request context 时用 contributors

## 2. Host 是正式的 control-plane 边界

Host 负责：

- 生命周期展示
- approvals 与 elicitation UX
- notifications 与 turn-event rendering
- app-local shell 或 UI 行为

Runtime 继续拥有：

- session 与 turn control flow
- permission evaluation triggers
- elicitation triggers
- tool / skill / agent orchestration

推荐通过 `bind_host(...)` 后的分组表面访问：

- `bound.prompts`
- `bound.sessions`
- `bound.hooks`
- `bound.inspection`
- `bound.work`

## 3. Permission 与 elicitation 边界

### 3.1 Permission

适用于：

- 工具或 workflow 必须显式受控
- host 或部署策略必须保持可见
- side effects 应可审计

Runtime 决定何时需要 permission，host 决定如何展示，决策记录必须显式保留。

### 3.2 Elicitation

当 runtime 需要结构化人工输入时，不应把它假装成 prompt-only 约定。
Host 可以改变提问界面，但回答必须仍属于正式 runtime control flow。

## 4. HookBus 契约

### 4.1 公开 phases 显式存在

对外依赖时优先承诺稳定 phases。

### 4.2 Registration source 决定所有权

常见来源：

- runtime config
- bound host
- session API
- turn API
- skill hooks

### 4.3 Stop 与 recovery 属于正式 control flow

- approval gates
- continue-after-failure flows
- controlled resume behavior

### 4.4 External handlers 不是默认安全表面

对普通集成，`callback` 仍是最安全的默认值。

## 5. Skill hooks 与 agent hooks

- skill hooks 是成熟的 definition-level hook 路径
- agent-owned hooks 不是普通推荐 v1 surface
- 默认 assembly 会拒绝 agent-owned hooks
- 兼容模式可以容忍历史形状，但不是前进方向

## 6. Context-contributor 通道边界

- prompt-visible context
- runtime-private context
- diagnostics

Prompt-safe context 面向模型；private context 只留给 runtime；diagnostics 用于解释行为，不应变成 prompt 输入。

## 7. Job、work 与 refresh 边界

### 7.1 Job plane

- `RuntimeServices.job_service`
- bound-host work surfaces
- `job_get`、`job_list`、`job_stop`

### 7.2 Tool refresh

只有当 request-time capability pool 会变化时，才使用 dynamic refresh；普通场景优先静态 discovery 与 package composition。

## 8. Package-owned control-plane 契约

Packages 可以拥有：

- context contributors
- invocation providers
- capability lookup
- host-facet lookup
- 通用 host extension events

## 9. 稳定性建议

### 9.1 更安全的依赖对象

- `HostRuntime` / `BoundHostRuntime`
- 稳定公开 hook phases
- skill hooks
- context contributors
- permission 与 elicitation services
- job service 与 bound work surfaces

### 9.2 需要更谨慎依赖

- advanced hook phases
- external hook handlers
- compatibility adapter collection surfaces
- `TaskManager` 这类 compatibility-only facades

### 9.3 不应当作主要公开契约

- agent-owned hooks
- internal-only phases
- core runtime objects 上的 package-specific ad hoc fields

## 10. 面向集成者的推荐分层

优先顺序通常是：

1. host binding
2. permission / elicitation
3. stable hooks
4. context contributors
5. package-level control-plane seams

## 11. 相关文档

- `docs/zh-CN/guides/extend-the-control-plane.md`
- `docs/zh-CN/guides/bind-a-host.md`
- `docs/zh-CN/guides/register-hooks.md`
- `docs/zh-CN/reference/hook-registration.md`
- `docs/zh-CN/deep-dives/weavert-hook-configuration-platform.md`
- `docs/zh-CN/deep-dives/weavert-integration-guide.md`
- `docs/zh-CN/deep-dives/current-system-architecture.md`
