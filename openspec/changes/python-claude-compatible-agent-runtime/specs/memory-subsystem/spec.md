## ADDED Requirements

### Requirement: 默认 Claude 风格 memory provider
runtime SHALL 提供一个默认文件型 memory 子系统，遵循 Claude Code 兼容的目录解析与 prompt 注入行为。

#### Scenario: 使用默认 memory 启动 session
- **WHEN** 某个 session 在启用默认 memory provider 的情况下启动
- **THEN** runtime SHALL 解析 memory 目录、加载 `MEMORY.md` 或等价入口内容，并将 memory instructions 注入 session prompt context

### Requirement: relevant memory retrieval
runtime SHALL 在 turn 执行前检索 relevant memories，并将其提供给 turn engine。

#### Scenario: 在 prompt 之前筛选相关 memories
- **WHEN** 用户提交一个 prompt
- **THEN** runtime SHALL 评估当前可用的已存储 memories，并在模型执行前把判定为相关的 memories 注入 turn context

### Requirement: turn 后 memory 提取
runtime SHALL 支持在主线程 session 中使用默认 memory provider 自动执行 post-turn memory extraction。

#### Scenario: 主线程 turn 结束但未直接写 memory
- **WHEN** 主线程 agent 完成一个 turn，且尚未直接写入相关的 memory update
- **THEN** runtime SHALL 执行配置好的 post-turn extraction flow，并通过默认 provider 持久化提取出的 memory updates

### Requirement: agent memory scopes
runtime SHALL 支持与 Claude Code 风格一致的 agent-specific memory scopes，包括 user、project 与 local memory 行为。

#### Scenario: agent 使用 project scope memory
- **WHEN** 某个 agent definition 声明了 project-scoped memory 配置
- **THEN** runtime SHALL 在 project-scoped memory 边界内加载并持久化该 agent 的 memory，而不是落到 user-wide 边界
