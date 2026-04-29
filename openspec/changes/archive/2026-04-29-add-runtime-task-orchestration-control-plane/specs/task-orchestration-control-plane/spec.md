## ADDED Requirements

### Requirement: Runtime derives task readiness from the persisted task graph
The runtime SHALL derive task orchestration readiness from the resolved task-list snapshot rather than requiring callers to infer availability from raw status and dependency fields alone.

#### Scenario: pending task with no unresolved blockers is available
- **WHEN** a task is `pending`, has no owner, and every task in its `blocked_by` set is already `completed`
- **THEN** the runtime SHALL classify that task as available in the orchestration view
- **AND** SHALL include that task identifier in the list-level `available_task_ids` summary or equivalent derived readiness projection

#### Scenario: unresolved blocker keeps task blocked
- **WHEN** a task is not completed and at least one task in its `blocked_by` set remains unresolved
- **THEN** the runtime SHALL classify that task as blocked rather than available
- **AND** SHALL expose the unresolved blocker identifiers in the derived orchestration view for that task

### Requirement: Claim and next-task assignment are atomic blocker-aware operations
The task orchestration control plane SHALL provide atomic `claim`, `release`, and `assign_next` operations that validate blockers and ownership under the same task-list mutation boundary.

#### Scenario: blocked task cannot be claimed
- **WHEN** a caller attempts to claim a task that still has unresolved blockers
- **THEN** the runtime SHALL reject the claim with a structured `blocked` error or equivalent validation result
- **AND** SHALL NOT mutate ownership or status for that task

#### Scenario: repeated claim by the same owner is idempotent
- **WHEN** the current owner of an unresolved task repeats a claim request for that same task
- **THEN** the runtime SHALL treat that request as an idempotent success or equivalent stable claim result
- **AND** SHALL NOT report an ownership conflict for the same owner

#### Scenario: default claim advances unresolved task to in-progress
- **WHEN** a caller uses the default public claim path for an unresolved task
- **THEN** the runtime SHALL assign the requested owner and advance that task to `in_progress`
- **AND** SHALL only skip automatic state advancement when an explicit runtime-owned override disables that behavior

#### Scenario: release clears owner and returns unresolved task to pending
- **WHEN** a caller releases a claimed task that is not yet completed
- **THEN** the runtime SHALL clear the task owner
- **AND** SHALL return that task to `pending` rather than leaving it in `in_progress`

#### Scenario: assign-next claims the first available task
- **WHEN** a caller invokes `assign_next` for a task list that has at least one available task
- **THEN** the runtime SHALL atomically select one available task and assign it to the requested owner
- **AND** SHALL return that claimed task snapshot rather than requiring the caller to race a separate list-and-claim sequence

#### Scenario: assign-next returns no task when nothing is available
- **WHEN** a caller invokes `assign_next` for a task list that has no available tasks
- **THEN** the runtime SHALL return an empty or null assignment result rather than fabricating a task
- **AND** SHALL leave the task list unchanged

#### Scenario: owner-busy policy rejects parallel open-task assignment
- **WHEN** owner-busy enforcement is enabled and the requested owner already holds another unresolved task in the same list
- **THEN** `claim` or `assign_next` SHALL reject the new assignment with a structured `owner_busy` error or equivalent result
- **AND** SHALL leave the task list unchanged

### Requirement: Dependency maintenance preserves a validated bidirectional graph
The task orchestration control plane SHALL mutate task dependency edges only through dedicated operations that keep `blocks` and `blocked_by` consistent and reject invalid graphs.

#### Scenario: adding a dependency updates both directions
- **WHEN** the runtime adds a dependency where task A blocks task B
- **THEN** it SHALL record task B in task A's `blocks` set
- **AND** SHALL record task A in task B's `blocked_by` set within the same persisted mutation

#### Scenario: dependency cycle is rejected
- **WHEN** a requested dependency would create a cycle in the task graph
- **THEN** the runtime SHALL reject the mutation with a structured `dependency_cycle` error or equivalent validation result
- **AND** SHALL NOT persist a partial forward or reverse edge

#### Scenario: deleting a task cleans dangling dependency edges
- **WHEN** the runtime deletes or otherwise removes a task from a persisted task list
- **THEN** it SHALL remove that task identifier from any remaining `blocks` or `blocked_by` sets in the same list
- **AND** SHALL NOT leave dangling dependency references in the surviving task graph

### Requirement: Task orchestration views are queryable as stable snapshots
The runtime SHALL expose a stable orchestration view that includes per-task readiness classification and list-level readiness summaries for model, host, and runtime consumption.

#### Scenario: orchestration view returns per-task readiness metadata
- **WHEN** a caller requests a task-list orchestration view
- **THEN** the runtime SHALL return each task together with derived readiness state such as available, blocked, in progress, claimed, or completed
- **AND** SHALL include unresolved blocker identifiers or equivalent readiness diagnostics for blocked tasks

#### Scenario: orchestration view returns list-level readiness summary
- **WHEN** a caller requests a task-list orchestration view
- **THEN** the runtime SHALL return stable list-level readiness summaries such as available and blocked task identifiers
- **AND** SHALL allow the caller to consume that readiness snapshot without recomputing blockers from raw task edges alone
