## ADDED Requirements

### Requirement: Hosts can query and watch runtime-owned task orchestration views
The runtime SHALL expose host-facing query and watch surfaces for task orchestration views without requiring hosts to compute dependency readiness or claimability from raw task snapshots themselves.

#### Scenario: host queries derived task orchestration view
- **WHEN** a bound host queries task state for a session or resolved task list
- **THEN** the runtime SHALL be able to return a task orchestration view that includes derived readiness information such as available or blocked tasks
- **AND** SHALL expose list-level readiness summaries without requiring the host to reimplement blocker resolution

#### Scenario: host orchestration snapshot includes minimum readiness fields
- **WHEN** the runtime returns a host-facing task orchestration snapshot
- **THEN** that snapshot SHALL include list-level readiness summaries such as `available_task_ids` and `blocked_task_ids` or equivalent fields
- **AND** SHALL include per-task readiness state plus unresolved blocker identifiers for blocked tasks

#### Scenario: host watches task orchestration updates
- **WHEN** a bound host registers to observe task orchestration updates
- **THEN** the runtime SHALL provide full current orchestration snapshots or equivalent stable watch payloads on relevant task-list mutations
- **AND** SHALL keep orchestration persistence and validation under runtime ownership rather than shifting scheduler responsibility to the host
