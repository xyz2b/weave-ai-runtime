## 背景

`cc-src` 和 `docs/cc` 已经提供了足够多的架构材料，可用于抽取一个可复用的 AI Agent Runtime，但项目目前还没有一个正式的变更提案来约束这项工作。该 runtime 将使用 Python 实现，同时保持 Claude Code 面向用户的 tool、agent、skill、memory 与 hook 定义模型，以便用户几乎无需转换即可复用自己的定义。

## 变更内容

- 引入一个基于 Python 的 agent runtime 内核，采用显式的 bootstrap、registry、session control 和 turn execution 分层，而不是以 REPL 为中心组织实现。
- 保持与 Claude Code 兼容的 `Tool`、`Agent`、`Skill` 与 hook event 定义语义，并用 Python 原生抽象重新实现 runtime。
- 增加一个显式的内置主线程 `main-router` agent，负责 runtime routing：直接回答、直接调 tool、调用 skill、委派 subagent。
- 定义一个默认 memory 子系统，沿用 Claude Code 的文件型 memory 流程，包括检索、prompt 注入、agent memory scope 与 turn 结束后的提取。
- 定义一个 hook 系统，既包含 Claude Code 兼容的 runtime hook phase，也包含用于嵌入 CLI、TUI、SDK 或 channel 启动逻辑的 host lifecycle hook。
- 提供一组参考 Claude Code 抽取出来的内置 agents、tools 与 skills，作为 runtime 默认内置包的一部分。

## Capabilities

### New Capabilities

- `runtime-kernel`：Python runtime 的 bootstrap、registry 初始化、session controller 与 turn engine 分层。
- `tool-system`：Claude Code 兼容的 tool 定义、tool pool 解析与 tool 执行编排。
- `agent-system`：Claude Code 兼容的 agent 定义、显式 `main-router` 与 subagent 执行语义。
- `skill-system`：Claude Code 兼容的 `SKILL.md` 加载、激活与执行行为。
- `memory-subsystem`：默认 Claude 风格的 memory 加载、检索、提取与 agent memory scope。
- `hook-system`：Claude Code 兼容的 runtime hook phase，以及用于启动和关闭集成的 host lifecycle hook。
- `builtin-runtime-pack`：runtime 默认随附的一组内置 agents、tools 和 skills。

### Modified Capabilities

- 无。

## 影响范围

- 新增 runtime kernel、tools、agents、skills、memory、hooks 与 built-ins 的 OpenSpec capability specs。
- 影响未来 Python 包的目录布局，包括 bootstrap、registries、session control、turn execution、memory 与 host adapters。
- 确立用户自定义 tool、agent 与 skill 定义的兼容性要求。
- 明确后续实现必须提供的内置 runtime surface。
