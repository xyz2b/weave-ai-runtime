# task-list-control-plane Specification

## Purpose
TBD - created by archiving change add-runtime-task-list-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Runtime owns a dedicated task-list control plane
The runtime SHALL provide a dedicated task-list control plane for model-facing work planning, and SHALL keep it separate from the internal background-job/task registry used for agent execution, memory work, or teammate projections.

#### Scenario: model-facing task tools update a task list
- **WHEN** an agent invokes `task_create`, `task_get`, `task_update`, or `task_list`
- **THEN** the runtime SHALL route that operation through the task-list control plane
- **AND** SHALL NOT treat the operation as a mutation of the internal background-job registry

#### Scenario: background execution projections do not create planning tasks implicitly
- **WHEN** a background agent run, memory job, or teammate projection changes status
- **THEN** the runtime SHALL update the internal background-job/task registry as needed
- **AND** SHALL NOT implicitly create or mutate task-list entries unless an explicit task-list operation or configured projection policy requests it

### Requirement: Task lists are persistent and scope-resolved
The runtime SHALL resolve a task-list identity for each execution context and SHALL persist task-list state independently of transcript-only recovery.

#### Scenario: session without explicit override resolves a default task list
- **WHEN** a session executes without an explicit task-list override
- **THEN** the runtime SHALL resolve a default task-list identifier from session or team context
- **AND** SHALL use that identifier consistently across subsequent task-list operations in the same scope

#### Scenario: delegated child execution inherits task-list scope
- **WHEN** a delegated or child execution does not provide an explicit task-list override
- **THEN** the runtime SHALL inherit the parent execution's resolved task-list identifier
- **AND** SHALL allow child task-list operations to observe and mutate the same persisted list

#### Scenario: runtime restarts after task-list updates
- **WHEN** the runtime restarts after a task list has been created or updated
- **THEN** the runtime SHALL be able to reconstruct that task list from persistent storage
- **AND** SHALL NOT require transcript scanning as the authoritative recovery path

### Requirement: Task entries support v2 planning semantics
The task-list control plane SHALL support task entries with planning-oriented fields including `subject`, `description`, `active_form`, `status`, `owner`, `blocks`, `blocked_by`, and metadata.

#### Scenario: creating a task initializes planning fields
- **WHEN** an agent creates a new task-list entry
- **THEN** the runtime SHALL persist a task with a stable task identifier
- **AND** SHALL initialize it with `pending` status unless an explicit policy allows another initial state
- **AND** SHALL preserve any supplied `subject`, `description`, `active_form`, dependency, owner, or metadata fields

#### Scenario: updating task status and ownership
- **WHEN** an agent updates a task-list entry
- **THEN** the runtime SHALL allow status transitions among `pending`, `in_progress`, and `completed`
- **AND** SHALL allow owner, dependency, and metadata mutations under the task-list service contract

#### Scenario: runtime enables strict single in-progress enforcement
- **WHEN** the runtime route or execution policy is configured to enforce at most one `in_progress` task per task list
- **THEN** a task update that would create more than one `in_progress` task in the same list SHALL be rejected
- **AND** SHALL return a structured tool-visible error or validation failure rather than silently rewriting another task

#### Scenario: strict single in-progress enforcement is disabled
- **WHEN** the runtime route or execution policy does not enable strict single-`in_progress` validation
- **THEN** the task-list control plane MAY allow more than one `in_progress` task in the same list
- **AND** SHALL leave sequencing discipline to prompt policy, reminder sidecars, or higher-level orchestration

### Requirement: Built-in task tools expose a snapshot-oriented task contract
The runtime SHALL make built-in `task_create`, `task_get`, `task_update`, and `task_list` behave as task-list operations with explicit list resolution, persisted task snapshots, and structured validation errors.

#### Scenario: agent creates a task through the built-in task surface
- **WHEN** an agent invokes `task_create` with a valid `subject` and any optional supported task fields
- **THEN** the runtime SHALL create a persisted task-list entry in the resolved task list
- **AND** SHALL return the resolved `task_list_id` plus the created task snapshot including its stable task identifier

#### Scenario: agent lists tasks for the resolved list
- **WHEN** an agent invokes `task_list`
- **THEN** the runtime SHALL return the resolved `task_list_id`
- **AND** SHALL return the current persisted task snapshots for that list rather than a transcript-derived reconstruction

#### Scenario: agent gets a missing task
- **WHEN** an agent invokes `task_get` for a task identifier that does not exist in the resolved task list
- **THEN** the runtime SHALL return a structured tool-visible `not_found` error
- **AND** SHALL NOT fabricate an empty task placeholder

#### Scenario: agent updates a task through a partial patch
- **WHEN** an agent invokes `task_update` with a valid `task_id` and one or more supported mutable fields
- **THEN** the runtime SHALL apply only the provided field mutations
- **AND** SHALL return the updated persisted task snapshot for that task

#### Scenario: agent sends an empty or unsupported update patch
- **WHEN** an agent invokes `task_update` without any supported mutable fields
- **THEN** the runtime SHALL return a structured tool-visible `invalid_request` error
- **AND** SHALL NOT treat the request as a no-op success

#### Scenario: built-in task update does not overload deletion
- **WHEN** an agent invokes `task_update`
- **THEN** the runtime SHALL interpret it as an update-only operation
- **AND** SHALL NOT expose task deletion through an implicit delete flag in the built-in task-tool contract

### Requirement: Task discipline is injected through a host-agnostic sidecar
The runtime SHALL be able to inject hidden task-discipline reminders through request-assembly context contribution, without requiring any built-in task UI.

#### Scenario: task tools are available and task-list maintenance becomes stale
- **WHEN** the current execution has access to the task-list tools
- **AND** the runtime determines that task-list maintenance has been stale for the configured threshold
- **THEN** the runtime SHALL inject a hidden reminder fragment into model-visible context
- **AND** SHALL include enough current task-list state to remind the model what work remains

#### Scenario: host provides no task UI
- **WHEN** the bound host does not implement any task-list panel or renderer
- **THEN** task-list tools and hidden reminder injection SHALL still operate through the runtime
- **AND** SHALL NOT depend on host rendering to preserve task-discipline behavior

### Requirement: User-defined agents can opt into task lists through normal tool-pool resolution
The runtime SHALL allow built-in and user-defined agents to participate in the task-list workflow by resolving the task-list tools through the normal tool-pool contract.

#### Scenario: custom agent includes task tools
- **WHEN** a user-defined agent includes the task-list tools in its allowed tool set
- **THEN** the runtime SHALL make those tools available to that agent under the same task-list control-plane semantics as built-in agents
- **AND** SHALL NOT require a special built-in agent type to activate task-list behavior

#### Scenario: agent excludes task tools
- **WHEN** an agent's resolved tool pool excludes the task-list tools
- **THEN** the runtime SHALL NOT force task-list operations or task-discipline reminders on that agent
- **AND** SHALL continue executing the agent under its remaining resolved tool pool

