## ADDED Requirements

### Requirement: Built-in runtime pack includes dedicated task orchestration tools
The runtime SHALL include first-party task orchestration tools in the built-in runtime pack for claim, release, next-task assignment, and dependency-edge maintenance.

#### Scenario: runtime boots with task orchestration tools available
- **WHEN** the runtime starts with the built-in runtime pack enabled
- **THEN** the built-in tool catalog SHALL include `task_claim`, `task_release`, `task_assign_next`, `task_block`, and `task_unblock` or equivalent first-party task orchestration tools
- **AND** those tools SHALL participate in normal tool-pool resolution rather than requiring a special built-in agent mode

#### Scenario: built-in claim tools advance status by default
- **WHEN** a caller invokes built-in `task_claim` or `task_assign_next` for unresolved work
- **THEN** the runtime SHALL claim the task through the task orchestration control plane
- **AND** SHALL advance that task to `in_progress` by default unless an explicit runtime-owned override disables state advancement

#### Scenario: generic task update does not bypass orchestration semantics
- **WHEN** a caller invokes the built-in `task_update` tool
- **THEN** the runtime SHALL reserve orchestration-critical mutations such as dependency-edge maintenance and claim-style assignment for the dedicated orchestration tools
- **AND** SHALL reject raw orchestration-field updates that would bypass those dedicated operations

#### Scenario: owner mutation migrates to claim and release tools
- **WHEN** a caller needs to assign or clear task ownership through the built-in runtime pack
- **THEN** the runtime SHALL require that caller to use `task_claim` or `task_release` rather than direct owner mutation through `task_update`
- **AND** SHALL keep dependency-edge mutation on `task_block` and `task_unblock` rather than `task_update`
