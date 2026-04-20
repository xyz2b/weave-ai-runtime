## ADDED Requirements

### Requirement: Claude 兼容的 runtime hook phases
runtime SHALL 支持与 Claude Code 兼容的 runtime hook phase 名称与契约，覆盖 session、prompt、tool、stop、elicitation、compact、notification 与 subagent lifecycle events。

#### Scenario: 在 Claude 兼容 phase 中执行 hook
- **WHEN** 某个 hook 被注册到 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop`、`SubagentStop` 或 `SessionEnd` 等 Claude 兼容事件上
- **THEN** runtime SHALL 在对应 runtime phase 中，按照该事件定义的 hook payload contract 调用该 hook

### Requirement: hooks 可以影响 runtime flow
runtime SHALL 允许 hooks 在对应 phase 允许的前提下追加 context、更新 tool input、阻止 continuation、发出通知或提供 elicitation results。

#### Scenario: pre-tool hook 修改输入
- **WHEN** 某个 `PreToolUse` hook 返回了更新后的 tool input
- **THEN** runtime SHALL 使用更新后的输入执行该 tool call，而不是原始输入

### Requirement: host lifecycle hooks
runtime SHALL 提供用于 startup 和 shutdown 集成的 host lifecycle hooks，使嵌入式 host 能在不修改 turn engine 的前提下接入自定义逻辑。

#### Scenario: CLI host 注册启动逻辑
- **WHEN** 某个 CLI 或 UI host 注册了 startup lifecycle hook
- **THEN** runtime SHALL 在 host 开始处理 interactive session 之前，于 runtime startup 阶段调用该 host hook
