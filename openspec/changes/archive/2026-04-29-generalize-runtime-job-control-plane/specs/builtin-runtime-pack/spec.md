## MODIFIED Requirements

### Requirement: 内置 tool pack
runtime SHALL 默认随附一个内置 tool pack，其中包括 `read`、`edit`、`write`、`glob`、`grep`、`bash`、`web_fetch`、`web_search`、`agent`、`skill`、`task_create`、`task_get`、`task_update`、`task_claim`、`task_release`、`task_assign_next`、`task_block`、`task_unblock`、`task_list`、`job_get`、`job_list`、`job_stop`、`ask_user` 与 `sleep`。

#### Scenario: 无自定义 tools 时启动 runtime
- **WHEN** runtime 在没有用户自定义 tools 的情况下启动
- **THEN** 内置 tool pack SHALL 仍然被注册，并根据 tool-pool resolution 规则可供 runtime 使用

## ADDED Requirements

### Requirement: Built-in `job_*` tools SHALL reflect the shared job control plane
runtime SHALL make built-in `job_get`, `job_list`, and `job_stop` operate on the shared job control plane rather than on an executor-private or `TaskManager`-shaped internal registry contract.

#### Scenario: agent inspects background work through built-in job tools
- **WHEN** an agent invokes a built-in `job_*` tool
- **THEN** runtime SHALL resolve that operation against the shared job control plane
- **AND** SHALL return generic job control information such as lifecycle state, executor kind, visibility metadata, result or error envelope, and sidecar linkage summary where applicable

#### Scenario: built-in job stop targets a visible running job
- **WHEN** an agent invokes `job_stop` for a visible running job
- **THEN** runtime SHALL route the stop request through the shared job executor contract
- **AND** SHALL NOT require the caller to know whether the underlying work is implemented as an `asyncio` task, subprocess, thread, or custom executor

