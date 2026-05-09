# 扩展控制面

## 适合谁？

已经不再只是添加 tools、agents 或 skills，而是需要通过 hosts、permissions、elicitation、hooks、context contributors 或动态 capability refresh 来塑造 runtime 行为的用户。

## 前置条件

- 一个可运行的 runtime baseline
- 熟悉 `RuntimeConfig` 与 `RuntimeAssembly`
- 你确实需要在不重写 turn engine 的前提下改变 runtime 行为

## 第一个区分：事件 Hook 与 context contributor

这两类扩展很容易混淆，但它们解决的问题不同。

- Hook bus registrations
  - 对某个 runtime phase 做出反应，如 `PreToolUse`、`Stop` 或 `SessionEnd`
  - 返回 hook effects
- Context contributors
  - 在 request assembly 之前贡献 prompt、private 或 diagnostics 数据
  - 它们是 package-owned sidecars，不是 HookBus 事件

一个实用的经验法则是：

- 当你是在响应生命周期阶段时，用 hooks
- 当你是在模型调用前塑造请求上下文时，用 context contributors

## 选择合适的 control-plane seam

### Host

当你的产品需要这些能力时，用 host：

- 生命周期所有权
- approval UX
- elicitation UX
- turn-event rendering
- app-local commands 或 app shell 行为

### Permissions

当某个 tool、shell action 或 delegated workflow 应保持显式受控，而不是静默执行时，走 permission path。

### Elicitation

当 runtime 需要的是结构化的人类输入，而不是简单的 yes/no approval 时，用 elicitation。

### Hooks

当稳定生命周期阶段是正确注入点时，用 hooks，例如改写 tool input、阻止操作、调整 model request 或观察 stop 行为。

### Context contributors

当 package-owned 逻辑应添加下面这些内容时，用 context contributors：

- prompt-visible fragments
- runtime-private fragments
- diagnostics

### Tool refresh

当可见能力池应在请求时根据环境或 session 条件动态刷新，而不是固定整个 runtime 生命周期时，使用 `tool_refresh_callback`。

## 最小 host-binding 集成

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_hosts_reference import SdkHostRuntime

runtime = assemble_runtime(RuntimeConfig.for_ordinary_workflow(Path.cwd()))
host = SdkHostRuntime(name="sdk")
bound = runtime.bind_host(host)
```

优先使用这些分组后的 bound surfaces：

- `bound.prompts`
- `bound.sessions`
- `bound.hooks`
- `bound.inspection`
- `bound.work`

## Permissions 与 elicitation posture

一个简单的心智模型是：

- runtime 决定何时需要 permission 或 elicitation
- host 可以拥有这种交互的展示方式
- 决策记录应保持显式且可检查

尽量把这些关注点与 prompt logic 分开。

## Context contributor 规则

Context contributors 应保留通道边界：

- prompt contributions 用于模型可见上下文
- private contributions 用于 runtime-only state
- diagnostics contributions 用于 inspection 与调试

不要把 prompt-safe 与 runtime-private 状态混在同一个无差别 payload 中。

## Tool refresh 指南

当可见工具集依赖于变化中的环境或 session 条件时，再使用 `tool_refresh_callback`。
如果固定项目本地工具集已经足够，就不要拿它代替普通静态 discovery。

## 预期结果

你能通过稳定 control-plane seams 扩展 runtime 行为，同时继续让 session 与 turn orchestration 由 runtime 拥有。

## 下一步

- 如果你需要生命周期注入，读 `register-hooks.md`
- 如果你需要 host 生命周期与 approvals，读 `bind-a-host.md`
- 如果你需要 observability 与 validation，读 `testing-and-observability.md`

## 另见

- `bind-a-host.md`
- `register-hooks.md`
- `../concepts/hosts-permissions-memory.md`
- `../deep-dives/weavert-control-plane-extension-guide.md`
