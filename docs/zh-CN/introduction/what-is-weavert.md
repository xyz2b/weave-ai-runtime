# WeaveRT 是什么？

WeaveRT 是一个可组合的 AI 运行时框架，用于构建 Agent 系统。
它提供稳定的运行时内核，以及一组清晰的扩展边界，覆盖工具、智能体、技能、宿主、权限、记忆、工作流包和场景包。

## 适合谁？

- 正在判断 WeaveRT 是什么，以及它是否适合自己产品或工作流的仓库访问者。

## 前置条件

- 无。这个层级设计成在读完根目录 `../../../README.zh-CN.md` 后就能直接阅读。

WeaveRT 是什么：

- 一个可以嵌入 CLI、SDK、worker 或应用壳层的运行时模型
- 一个用于组合 Agent 能力、同时不隐藏系统所有权的框架
- 一条从小型项目内工作流扩展到更完整产品形态集成的路径

WeaveRT 不是什么：

- 不是一个硬编码的单体助手应用
- 不是一个只在某个 shell 里可用的单 prompt demo
- 不是一个要求你自己重写 turn 编排的框架

最核心的心智模型很简单：

```text
你的应用或宿主
  -> RuntimeConfig
  -> RuntimeAssembly
  -> Session
  -> Turn Engine
  -> Tools / Skills / Agents / Memory / Hooks / Permissions
```

先从 starter 开始。
再理解定义这些边界的 concepts。
只有在需要时再进入 guides、examples 和 architecture。

下一步阅读：

- `use-cases.md`
- `../getting-started/quickstart.md`
- `../concepts/runtime-model.md`

## 下一步

- 读 `use-cases.md`，把框架映射到真实产品形态
- 读 `design-principles.md`，理解这个运行时背后的架构取向
- 当你想跑通最小项目路径时，进入 `../getting-started/quickstart.md`

## 另见

- `../../../README.zh-CN.md`
- `../README.md`
- `../getting-started/quickstart.md`
- `../concepts/runtime-model.md`
