## MODIFIED Requirements

### Requirement: 内置 tool pack
runtime SHALL 默认随附一个内置 tool pack，其中包括 `read`、`edit`、`write`、`glob`、`grep`、`bash`、`web_fetch`、`web_search`、`agent`、`skill`、`task_create`、`task_get`、`task_update`、`task_claim`、`task_release`、`task_assign_next`、`task_block`、`task_unblock`、`task_archive`、`task_unarchive`、`task_delete`、`task_list`、`job_get`、`job_list`、`job_stop`、`ask_user` 与 `sleep`。

#### Scenario: 无自定义 tools 时启动 runtime
- **WHEN** runtime 在没有用户自定义 tools 的情况下启动
- **THEN** 内置 tool pack SHALL 仍然被注册，并根据 tool-pool resolution 规则可供 runtime 使用

## ADDED Requirements

### Requirement: Built-in task tools SHALL expose only supported task mutations
The built-in task tool surface SHALL keep raw task updates narrow, SHALL expose ownership and dependency changes only through dedicated orchestration tools, and SHALL expose retirement through dedicated archival or deletion tools.

#### Scenario: built-in task update excludes orchestration fields
- **WHEN** an agent invokes built-in `task_update`
- **THEN** the runtime SHALL accept only supported non-orchestration mutable fields on that tool surface
- **AND** SHALL direct ownership and dependency changes to `task_claim`, `task_release`, `task_assign_next`, `task_block`, or `task_unblock`

#### Scenario: built-in task retirement uses dedicated tools
- **WHEN** an agent needs to retire task records from the shared task plane
- **THEN** the runtime SHALL expose dedicated built-in task retirement operations for archive, unarchive, and delete
- **AND** SHALL NOT overload `task_update` as the public retirement path

#### Scenario: built-in task retirement surfaces canonical lifecycle errors
- **WHEN** an agent invokes a built-in task retirement or mutation operation that violates archived-task lifecycle rules
- **THEN** the runtime SHALL return structured tool-visible error codes from the canonical retirement set such as `archive_requires_completed`, `delete_requires_archived`, `already_archived`, `not_archived`, or `archived_task_immutable`
- **AND** SHALL NOT collapse those retirement failures into an unqualified generic success or no-op result

### Requirement: Built-in exact task lookup SHALL be archival-aware
The built-in `task_get` surface SHALL retrieve archived tasks by exact identifier even when default list views hide archived tasks.

#### Scenario: built-in task get returns archived task by id
- **WHEN** an agent invokes built-in `task_get` for an archived task identifier
- **THEN** the runtime SHALL return that archived task snapshot
- **AND** SHALL include canonical archival fields `is_archived`, `archived_at`, and `archived_by` in the returned payload

### Requirement: Built-in task listing SHALL support archived-visibility control
The built-in `task_list` surface SHALL default to active task visibility and SHALL allow callers to request archived task visibility explicitly.

#### Scenario: built-in task list hides archived tasks by default
- **WHEN** an agent invokes built-in `task_list` without an archived-visibility override
- **THEN** the runtime SHALL return only non-archived task entries in the default list payload
- **AND** SHALL exclude archived entries from readiness summaries such as available and blocked task identifiers

#### Scenario: built-in task list can include archived tasks explicitly
- **WHEN** an agent invokes built-in `task_list` with an explicit archived-visibility override
- **THEN** the runtime SHALL include archived task entries in the returned snapshot
- **AND** SHALL preserve each task's archival markers in that payload

#### Scenario: built-in default task list suppresses hidden archived dependency ids
- **WHEN** an agent invokes built-in `task_list` without archived visibility
- **THEN** the runtime SHALL suppress `blocks` and `blocked_by` references that target archived tasks from the visible task entries
- **AND** SHALL keep the default list payload self-contained without references to hidden archived task ids
