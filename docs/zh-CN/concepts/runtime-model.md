# 运行时模型

理解 WeaveRT 最有用的方式，是把它看成一个分层运行时，而不是一个单独的 assistant 对象。

```text
你的应用 / 宿主
  -> RuntimeConfig
  -> RuntimeAssembly
  -> SessionController
  -> TurnEngine
  -> Tools / Skills / Agents / Memory / Hooks / Permissions
```

## 适合谁？

- 已经理解落地页定位、现在需要核心运行时词汇的使用者。

## 前置条件

- 先读 `../introduction/what-is-weavert.md`
- 如果你想把术语和可运行路径对应起来，快速浏览 `../getting-started/quickstart.md`

## 面向用户的四个运行时表面

大多数使用者应主要从四个稳定入口思考：

- `RuntimeConfig`
  - 声明 runtime 应如何组装
- `RuntimeAssembly`
  - 暴露 one-shot helpers、sessions、binding 和 inspection
- `BoundHostRuntime`
  - 增加 host 拥有的生命周期与分组后的 bound surfaces
- `DefinitionSourcePaths`
  - 控制本地 tools、agents 和 skills 的发现方式

## 核心对象

### `RuntimeConfig`

声明 assembly posture，例如：

- 工作目录和 discovery sources
- distribution 与 package 选择
- model client 与 routes
- stores 与 memory 配置
- host 相关集成设置

### `RuntimeAssembly`

已组装好的 runtime 表面。
它暴露 helper entrypoints、session 创建、host binding、inspection 和 invocation visibility。

### Session

Session 负责 transcript 连续性与 ingress 处理。
输入会先被标准化，之后才可能进入一个 turn。

### Turn engine

一个 turn 负责一次执行循环：model 调用、tool 编排、skill 执行、agent 委派，以及终态结果生成。

## 五条值得记住的架构规则

### 1. Ingress 发生在 turn 执行之前

输入不会直接跳进 turn engine。
Session ingress 会先决定哪些内容应该进入 transcript，可见历史中保留什么，什么保持私有，以及是否真的要运行一个 turn。

### 2. Prompt 可见上下文不等于运行时私有状态

模型可见上下文应只包含对模型安全的 memory、hooks、attachments 或 session hints。
运行时私有状态应把 permissions、diagnostics、route metadata 和执行策略状态隔离在 prompt 之外。

### 3. Transcript truth 不等于当前 active context

持久 transcript 是历史记录。
Active context 是 runtime 为某一次 turn 构建的投影视图。
把两者分开，才能在不重写历史的前提下做 context projection、compaction 和恢复。

### 4. Attempt-final 与 turn-final 是两个不同时间点

一次 model attempt 可以结束，但整个 turn 还没完成。
这个区分使 tool continuation、recovery policy 和更丰富的 terminal metadata 更容易成立。

### 5. 所有权要保持明显

- host 负责产品 UX 与审批
- session 负责连续性
- turn engine 负责一次执行循环
- tools、skills 和 delegated agents 负责各自的执行边界

## Helper 的所有权语义

使用 helper surfaces 时，session 所有权很重要：

- `run_prompt()` 和 `stream_prompt()` 为这次调用拥有 session 生命周期
- `run_prompt_report()` 和 `stream_prompt_report()` 同样拥有 session 生命周期，并补全 report 表面
- `run_prompt_report_in_session()` 和 `stream_prompt_report_in_session()` 只是在调用者拥有的 session 内包装当前 turn

这也是为什么：headless 验证通常最适合 report helper，而更长生命周期的 shell 或 app 更适合 bound host 或显式 session。

## 普通用户应扩展哪里

先通过这些路径扩展 runtime：

- `.weavert/tools/*.py`
- `.weavert/agents/*.md`
- `.weavert/skills/**/SKILL.md`
- `RuntimeConfig` presets 与 package selection

普通用户不应一上来就修改 turn 编排内部。

## 下一步

- 读 `tools-agents-skills.md`，理解普通扩展 seam
- 当你需要 control-plane 与 state 边界时，读 `hosts-permissions-memory.md`
- 如果你需要实现导向的层级地图，进入 `../architecture/overview.md`

## 另见

- `tools-agents-skills.md`
- `hosts-permissions-memory.md`
- `../architecture/overview.md`
- `../reference/runtime-config.md`
