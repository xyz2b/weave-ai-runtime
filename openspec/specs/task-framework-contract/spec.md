# task-framework-contract Specification

## Purpose
TBD - created by archiving change harden-runtime-task-framework-contract. Update Purpose after archive.
## Requirements
### Requirement: Public task mutation contracts SHALL align across runtime surfaces
The runtime SHALL expose the same supported raw task mutation set across built-in task tools, host task APIs, and task-list service validation, and SHALL reserve ownership and dependency changes for dedicated orchestration operations rather than generic patch updates.

#### Scenario: task update exposes only supported mutable fields
- **WHEN** a caller uses the public `task_update` surface through a built-in tool or host bridge API
- **THEN** the runtime SHALL allow raw patch mutation only for `status`, `subject`, `description`, `active_form`, and `metadata`
- **AND** SHALL NOT expose `owner`, `blocks`, or `blocked_by` as supported raw update fields

#### Scenario: orchestration fields require dedicated task operations
- **WHEN** a caller needs to change task ownership or dependency edges
- **THEN** the runtime SHALL require dedicated operations such as claim, release, assign-next, block, or unblock
- **AND** SHALL return a structured validation error if the caller attempts to perform those mutations through a generic task update path

### Requirement: Exact task lookup SHALL remain archival-aware
The runtime SHALL treat exact task-id lookup as record retrieval rather than active-work filtering, even when archived tasks are hidden from default list or watch views.

#### Scenario: exact lookup returns archived task by id
- **WHEN** a caller invokes built-in `task_get` or host `get_task(...)` for an archived task identifier
- **THEN** the runtime SHALL return that archived task snapshot even if default task-list views hide archived tasks
- **AND** SHALL preserve the canonical archival metadata on the returned record

### Requirement: Task archival metadata SHALL use a canonical public shape
The runtime SHALL expose archival state through stable public task fields `is_archived`, `archived_at`, and `archived_by` across tool, host, and service-derived task snapshots.

#### Scenario: archived task snapshot carries archival markers
- **WHEN** a caller receives an archived task through exact lookup or an archived-visible task-list snapshot
- **THEN** the runtime SHALL set `is_archived` to `true`
- **AND** SHALL include `archived_at` and `archived_by` values or `null` where that archival actor is unavailable

#### Scenario: active task snapshot carries non-archived markers
- **WHEN** a caller receives a non-archived task snapshot
- **THEN** the runtime SHALL set `is_archived` to `false`
- **AND** SHALL set `archived_at` and `archived_by` to `null`

### Requirement: Task retirement SHALL be explicit and visibility-aware
The runtime SHALL provide a task-retirement lifecycle that distinguishes archival from deletion, SHALL keep archival orthogonal to planning status, and SHALL hide archived tasks from default active-work views unless the caller opts in.

#### Scenario: completed task can be archived without changing planning status
- **WHEN** a caller archives a completed task
- **THEN** the runtime SHALL preserve that task's work status as `completed`
- **AND** SHALL mark the task as archived through explicit retirement metadata rather than by changing the task status enum

#### Scenario: archived tasks are hidden from default task views
- **WHEN** a caller requests a task-list snapshot without an explicit archived-visibility override
- **THEN** the runtime SHALL exclude archived tasks from the returned task collection and derived readiness summaries
- **AND** SHALL allow the caller to include archived tasks by opting in through an explicit archived-visibility flag

#### Scenario: archived task can be restored or deleted through dedicated retirement operations
- **WHEN** a caller performs unarchive or delete on an archived task
- **THEN** unarchive SHALL restore the task to the visible completed state
- **AND** delete SHALL permanently remove the task record and clean any dangling dependency references from surviving tasks in the same list

### Requirement: Archived tasks SHALL be immutable outside retirement operations
The runtime SHALL reject normal task mutation and orchestration operations against archived tasks, and SHALL expose stable lifecycle error codes for invalid retirement transitions.

#### Scenario: archived task rejects ordinary task mutations
- **WHEN** a caller attempts `task_update`, `task_claim`, `task_release`, `task_assign_next`, `task_block`, or `task_unblock` against an archived task
- **THEN** the runtime SHALL reject that request with structured code `archived_task_immutable`
- **AND** SHALL leave the archived task unchanged

#### Scenario: invalid archive transition returns canonical lifecycle error
- **WHEN** a caller attempts to archive a task whose work status is not `completed`
- **THEN** the runtime SHALL reject that request with structured code `archive_requires_completed`
- **AND** SHALL leave the task unchanged

#### Scenario: repeated archive returns canonical lifecycle error
- **WHEN** a caller attempts to archive an already archived task
- **THEN** the runtime SHALL reject that request with structured code `already_archived`
- **AND** SHALL leave the archived task unchanged

#### Scenario: unarchive requires archived state
- **WHEN** a caller attempts to unarchive a task that is not currently archived
- **THEN** the runtime SHALL reject that request with structured code `not_archived`
- **AND** SHALL leave the task unchanged

#### Scenario: delete requires archived state
- **WHEN** a caller attempts to delete a task that is not currently archived
- **THEN** the runtime SHALL reject that request with structured code `delete_requires_archived`
- **AND** SHALL leave the task unchanged

### Requirement: Active-work projections SHALL suppress hidden archived dependency references
The runtime SHALL keep default active-work snapshots self-contained when archived tasks are hidden, and SHALL preserve full dependency data only when archived visibility is explicitly requested or exact task lookup is used.

#### Scenario: active-work task list suppresses archived dependency ids
- **WHEN** a caller requests a default task-list snapshot without archived visibility
- **THEN** the runtime SHALL omit `blocks` and `blocked_by` references that target archived tasks from the visible task payloads
- **AND** SHALL keep readiness summaries unaffected by those hidden archived references

#### Scenario: archived-visible projection preserves archived dependency ids
- **WHEN** a caller requests archived visibility explicitly or performs an exact task lookup
- **THEN** the runtime SHALL preserve dependency references to archived tasks in the returned task payloads
- **AND** SHALL NOT apply the active-work edge suppression used by default list views

### Requirement: Default task-list persistence SHALL be crash-safe and single-writer
The bundled file-backed task-list store SHALL persist snapshot updates through crash-safe replacement semantics and SHALL document a single-runtime-writer boundary for the default implementation.

#### Scenario: snapshot updates replace persisted state atomically
- **WHEN** the default file-backed store saves a task-list snapshot
- **THEN** it SHALL write the new snapshot through an atomic replacement flow rather than mutating the live snapshot file in place
- **AND** SHALL leave either the previous complete snapshot or the new complete snapshot recoverable after an interrupted write

#### Scenario: multi-process mutation is not implied by the default store
- **WHEN** multiple runtime processes target the same default file-backed task-list root
- **THEN** the runtime SHALL NOT claim cross-process writer safety or merge behavior for that default store
- **AND** SHALL require embedders that need multi-writer semantics to supply a custom task-list store

