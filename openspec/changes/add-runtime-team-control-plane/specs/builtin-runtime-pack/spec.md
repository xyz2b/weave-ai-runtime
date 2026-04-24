## MODIFIED Requirements

### Requirement: 内置 tool pack
runtime SHALL 默认随附一个内置 tool pack，其中包括 `read`、`edit`、`write`、`glob`、`grep`、`bash`、`web_fetch`、`web_search`、`agent`、`skill`、`task_create`、`task_get`、`task_update`、`task_claim`、`task_release`、`task_assign_next`、`task_block`、`task_unblock`、`task_list`、`task_delete`、`task_archive`、`task_unarchive`、`job_get`、`job_list`、`job_stop`、`team_create`、`team_spawn`、`team_send`、`team_delete`、`ask_user` 与 `sleep`。

#### Scenario: 无自定义 tools 时启动 runtime
- **WHEN** runtime 在没有用户自定义 tools 的情况下启动
- **THEN** 内置 tool pack SHALL 仍然被注册，并根据 tool-pool resolution 规则可供 runtime 使用

## ADDED Requirements

### Requirement: Built-in `team_*` tools SHALL operate on the runtime-owned team control plane
The runtime SHALL make built-in `team_create`, `team_spawn`, `team_send`, and `team_delete` resolve against the runtime-owned team control plane rather than against host-local UI state or ad hoc caller metadata.

#### Scenario: lead agent creates and uses a team through built-in tools
- **WHEN** a lead agent invokes built-in `team_create` and later `team_spawn`
- **THEN** the runtime SHALL create or reuse runtime-owned team state and teammate membership under the shared team control-plane contract
- **AND** SHALL return structured tool results that identify the created team or teammate member

#### Scenario: built-in team tools resolve against the caller's active team binding
- **WHEN** a caller invokes built-in `team_spawn`, `team_send`, or `team_delete`
- **THEN** the runtime SHALL resolve the target team from the caller's active team binding and runtime-private context
- **AND** SHALL NOT require or accept a caller-supplied `team_id` for those built-in tool contracts

#### Scenario: built-in team creation is idempotent per leader session
- **WHEN** a lead agent that already owns an active team invokes built-in `team_create` again
- **THEN** the runtime SHALL return the existing active team for that leader
- **AND** SHALL report through the structured tool result that the team was reused rather than newly created

#### Scenario: team spawn requires a unique name and agent selector
- **WHEN** a lead agent invokes built-in `team_spawn`
- **THEN** the tool contract SHALL require a unique teammate `name` and an `agent` selector
- **AND** MAY allow teammate-level execution defaults such as `cwd`, `model`, `model_route`, `permission_mode`, `isolation`, or `max_turns`
- **AND** SHALL return a structured result containing the stable runtime-owned teammate identity

#### Scenario: teammate cannot invoke leader-only lifecycle tools
- **WHEN** a caller operating as a teammate invokes built-in `team_create`, `team_spawn`, or `team_delete`
- **THEN** the runtime SHALL reject that built-in tool call as outside the teammate's lifecycle authority
- **AND** SHALL preserve the existing team state unchanged

#### Scenario: team send supports direct and broadcast routing
- **WHEN** a caller invokes built-in `team_send` with a direct recipient or broadcast target
- **THEN** the runtime SHALL route that request through the structured team message bus
- **AND** SHALL NOT require the caller to know whether the final recipient path resolves to leader ingress, teammate execution, or a host-facing side-channel

#### Scenario: public team send uses a frozen v1 addressing contract
- **WHEN** a caller invokes built-in `team_send`
- **THEN** the tool contract SHALL require `to` and `message`
- **AND** SHALL reserve `to="leader"` for the leader, `to="*"` for broadcast, and any other `to` value for teammate-name resolution inside the caller's active team
- **AND** SHALL reject public cross-team addressing in v1
