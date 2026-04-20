## ADDED Requirements

### Requirement: 参考实现兼容的 agent 定义
runtime SHALL 支持与参考实现兼容的 agent 定义语义，包括 tools、disallowed tools、skills、model selection、effort、permission mode、max turns、background execution、memory scope 与 isolation。

#### Scenario: 注册自定义 agent 定义
- **WHEN** 用户使用参考实现兼容字段定义一个 agent
- **THEN** runtime SHALL 在不引入新 agent 定义格式的前提下注册该 agent

### Requirement: 内置 main-router agent
runtime SHALL 内置一个主线程 `main-router` agent，由它承担 runtime routing 决策。

#### Scenario: 主线程执行 routing
- **WHEN** 主线程收到一个请求，该请求可能需要直接回答、通过 tool 处理、通过 skill 处理，或委派给 subagent
- **THEN** `main-router` agent SHALL 成为负责做出 routing 决策的 runtime 实体

### Requirement: subagent 执行复用共享 turn engine
runtime SHALL 使用与主线程相同的 turn engine 执行 subagents，并同时应用 agent 级 capability filtering 与 execution options。

#### Scenario: 启动后台 subagent
- **WHEN** runtime 启动一个后台或被委派的 subagent
- **THEN** runtime SHALL 使用共享 turn engine 执行该 subagent，并 SHALL 应用该 subagent 解析后的 tools、skills、permissions 与 execution limits
