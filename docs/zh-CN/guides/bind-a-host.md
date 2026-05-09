# 绑定 Host

## 适合谁？

需要把 WeaveRT 嵌入 CLI、SDK、服务或 app shell，并拥有生命周期控制与 runtime event 所有权的用户。

## 前置条件

- 一个可运行的 runtime baseline
- 如果你要使用 reference host types，请安装 `packages/framework-packs/integrations/hosts-reference`
- 你确实需要自己拥有 approvals、notifications 或 turn-event rendering

## 什么时候你真的需要 host

如果你只需要 one-shot 或 headless workflow execution，就继续使用普通 `RuntimeAssembly` helpers。
只有在需要以下能力时，才绑定 host：

- approval UX
- elicitation
- 更长生命周期的 session control
- turn-event rendering
- 应用拥有的本地命令或 shell 行为

## 最小绑定示例

```python
from pathlib import Path

from weavert import RuntimeConfig, assemble_runtime
from weavert_hosts_reference import SdkHostRuntime

runtime = assemble_runtime(RuntimeConfig.for_ordinary_workflow(Path.cwd()))
host = SdkHostRuntime(name="sdk")
bound = runtime.bind_host(host)
```

对于更长生命周期的集成，应把 bound runtime 当作 host 拥有的生命周期表面，并显式 shutdown。

## 推荐的分组表面

绑定后，优先使用分组表面，而不是兼容风格的平铺 helpers：

- `bound.prompts`
- `bound.sessions`
- `bound.hooks`
- `bound.inspection`
- `bound.work`

## 生命周期所有权

一个有用的心智模型是：

- host 负责 startup、ready、shutdown、approvals 和 presentation
- session 仍负责 transcript continuity
- turn engine 仍负责一次执行循环

运行时不应迫使你在 app shell 里重建这些层。

## 常见 host 关注点

合理的 host 职责包括：

- permission prompts
- notifications 与 progress rendering
- 把 runtime events 映射到应用特定 UI 或日志
- 不应消耗 model turn 的本地命令

## 预期结果

你的 host 拥有生命周期、审批与事件呈现，而 runtime 继续拥有 session 与 turn 的编排。

## 下一步

用 `python3 -B -m examples.hosts.minimal_host_bound_demo` 验证这个 seam。

## 另见

- `../concepts/hosts-permissions-memory.md`
- `extend-the-control-plane.md`
- `register-hooks.md`
- `testing-and-observability.md`
- `../deep-dives/weavert-control-plane-extension-guide.md`
