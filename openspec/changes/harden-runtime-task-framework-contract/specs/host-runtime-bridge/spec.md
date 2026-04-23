## ADDED Requirements

### Requirement: Bound host runtime SHALL expose task mutation APIs
The runtime SHALL expose runtime-owned task mutation methods on the bound host bridge so hosts can drive the shared task plane directly without invoking agent tools or private services.

#### Scenario: host mutates task state through the bound bridge
- **WHEN** a bound host creates, updates, claims, releases, assigns, blocks, unblocks, archives, unarchives, or deletes a task through the host bridge
- **THEN** the runtime SHALL resolve the same task-list scope rules used by the tool path
- **AND** SHALL return the same canonical task snapshot shape or structured validation error categories used by the corresponding built-in task tools

### Requirement: Host exact task lookup SHALL be archival-aware
The runtime SHALL let bound hosts retrieve archived tasks by exact identifier even when archived tasks are hidden from default host task-list projections.

#### Scenario: host get task returns archived record by id
- **WHEN** a bound host invokes `get_task(...)` for an archived task identifier
- **THEN** the runtime SHALL return that archived task snapshot even if default host task-list queries hide archived tasks
- **AND** SHALL include canonical archival fields `is_archived`, `archived_at`, and `archived_by` in the returned payload

### Requirement: Host task queries SHALL support archived visibility control
The runtime SHALL let bound hosts query and watch task lists with explicit archived-visibility control, while default host task projections remain focused on active work.

#### Scenario: host task list queries hide archived tasks by default
- **WHEN** a bound host requests a task-list snapshot or registers a task-list watch without an archived-visibility override
- **THEN** the runtime SHALL emit snapshots that exclude archived task entries by default
- **AND** SHALL keep readiness summaries limited to non-archived tasks

#### Scenario: host can opt into archived task visibility
- **WHEN** a bound host requests archived visibility explicitly for task-list queries or watches
- **THEN** the runtime SHALL include archived task entries in the emitted snapshot
- **AND** SHALL preserve archival markers needed for the host to render retirement state

#### Scenario: default host task projections suppress hidden archived dependency ids
- **WHEN** a bound host receives a default task-list snapshot without archived visibility
- **THEN** the runtime SHALL suppress dependency references that target hidden archived tasks from the visible task payloads
- **AND** SHALL keep the host-facing default snapshot self-contained without references to hidden archived task ids
