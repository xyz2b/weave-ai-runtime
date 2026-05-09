# 适用场景

WeaveRT 面向这样一类团队：他们需要的已经不止是一条助手 prompt，但又不想直接走到一套完全自定义的编排栈。

## 适合谁？

- 正在判断 WeaveRT 是什么，以及它是否适合自己产品或工作流的仓库访问者。

## 前置条件

- 无。这个层级设计成在读完根目录 `../../../README.zh-CN.md` 后就能直接阅读。

常见适配场景：

- Coding assistant
  - 工作区检查、编辑循环、验证、review 和审批
  - 参见 `../guides/use-scenario-packs.md` 和 `../../../examples/apps/code_assistant/README.zh-CN.md`
- Chat 或 research assistant
  - 检索、网页、记忆和多步响应流程
  - 参见 `../../../packages/product-kits/chat/README.zh-CN.md`
- Local assistant
  - 宿主拥有的权限、shell 或 OS 操作，以及持久 session 状态
  - 参见 `../../../packages/product-kits/local-assistant/README.zh-CN.md`
- 嵌入到应用或服务中的 runtime
  - 把 runtime 绑定到你自己的 host、routes、stores 和 control plane
  - 参见 `../guides/bind-a-host.md`

适合选择 WeaveRT 的理由：

- 你需要显式保留 session 和 turn 的所有权
- 你希望工具、智能体和技能保持为彼此独立的扩展类型
- 你想组合 first-party 或应用本地 package，同时不失去对 host 的控制
- 你想让同一套运行时模型既适用于离线测试，也适用于 live provider 运行

不太适合的情况：

- 你只需要单个固定 prompt，也不需要运行时生命周期
- 你不需要持久状态、权限或宿主集成
- 你想要的是托管产品，而不是可嵌入框架

下一步阅读：

- `design-principles.md`
- `../concepts/packages-and-scenario-packs.md`
- `../../../examples/README.zh-CN.md`

## 下一步

- 如果上述场景之一正是你想构建的内容，继续看 `../getting-started/quickstart.md`
- 如果你在评估运行时模型背后的取舍，读 `design-principles.md`
- 如果你已经明确需要 product-profile 路线，直接跳到 `../guides/use-scenario-packs.md`

## 另见

- `what-is-weavert.md`
- `design-principles.md`
- `../getting-started/quickstart.md`
- `../guides/use-scenario-packs.md`
