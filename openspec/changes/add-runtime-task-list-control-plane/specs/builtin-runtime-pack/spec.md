## MODIFIED Requirements

### Requirement: 内置 tool pack
runtime SHALL 默认随附一个内置 tool pack，其中包括 `read`、`edit`、`write`、`glob`、`grep`、`bash`、`web_fetch`、`web_search`、`agent`、`skill`、`task_create`、`task_get`、`task_update`、`task_list`、`job_get`、`job_list`、`job_stop`、`ask_user` 与 `sleep`。

#### Scenario: 无自定义 tools 时启动 runtime
- **WHEN** runtime 在没有用户自定义 tools 的情况下启动
- **THEN** 内置 tool pack SHALL 仍然被注册，并根据 tool-pool resolution 规则可供 runtime 使用

#### Scenario: built-in task tools target task-list semantics only
- **WHEN** runtime 解析内置的 `task_create`、`task_get`、`task_update` 与 `task_list`
- **THEN** 这些 tools SHALL 只暴露 model-facing task-list 语义
- **AND** SHALL NOT 作为 background-job 控制或查询入口

#### Scenario: built-in job tools target background execution control
- **WHEN** runtime 解析内置的 `job_get`、`job_list` 与 `job_stop`
- **THEN** 这些 tools SHALL 暴露 background execution record 的查询与停止语义
- **AND** SHALL NOT 直接创建、更新或删除 task-list entries
