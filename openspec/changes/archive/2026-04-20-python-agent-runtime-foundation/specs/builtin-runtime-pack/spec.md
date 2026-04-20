## ADDED Requirements

### Requirement: 内置 tool pack
runtime SHALL 默认随附一个内置 tool pack，其中包括 `read`、`edit`、`write`、`glob`、`grep`、`bash`、`web_fetch`、`web_search`、`agent`、`skill`、`task_create`、`task_get`、`task_update`、`task_list`、`task_stop`、`ask_user` 与 `sleep`。

#### Scenario: 无自定义 tools 时启动 runtime
- **WHEN** runtime 在没有用户自定义 tools 的情况下启动
- **THEN** 内置 tool pack SHALL 仍然被注册，并根据 tool-pool resolution 规则可供 runtime 使用

### Requirement: 内置 agent pack
runtime SHALL 随附内置 agents：`main-router`、`general-purpose`、`explore`、`plan` 和 `verification`。

#### Scenario: 无自定义 agents 时启动 runtime
- **WHEN** runtime 在没有用户自定义 agents 的情况下启动
- **THEN** 内置 agent pack SHALL 仍然被注册，并可用于主线程和委派执行

### Requirement: 内置 skill pack
runtime SHALL 随附内置 skills：`verify`、`debug`、`stuck`、`batch`、`simplify` 和 `remember`。

#### Scenario: 无自定义 skills 时启动 runtime
- **WHEN** runtime 在没有用户自定义 skills 的情况下启动
- **THEN** 内置 skill pack SHALL 仍然被注册，并根据 skill discovery 与 activation 规则在 session 中可用

### Requirement: 内置 pack 仍然可配置
runtime SHALL 允许 host 或应用扩展或选择性禁用内置 runtime packs，而不需要改变 built-in definition format。

#### Scenario: host 禁用某个 built-in
- **WHEN** 某个 host 配置禁用了某个内置 runtime 定义
- **THEN** runtime SHALL 应用该启用状态覆盖，同时保持其余 built-ins 的定义契约不变
