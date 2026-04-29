# background-job-control-plane Specification

## Purpose
TBD - created by archiving change add-runtime-task-list-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Runtime owns a dedicated background-job control plane
The runtime SHALL provide a dedicated background-job control plane for runtime execution records such as background agents, shell runs, teammate projections, and similar long-lived work, and SHALL keep that control plane separate from task-list semantics.

#### Scenario: runtime records a background execution
- **WHEN** the runtime starts a background-capable execution such as a background agent run or shell task
- **THEN** the runtime SHALL create or update a background-job record in the background-job control plane
- **AND** SHALL NOT require a task-list entry to exist for that execution to be tracked

#### Scenario: background job lifecycle changes
- **WHEN** a background execution transitions among pending, running, completed, failed, or stopped terminal states
- **THEN** the runtime SHALL update the corresponding background-job record
- **AND** SHALL keep that lifecycle independent from any task-list entry status

### Requirement: Built-in job tools operate on background-job records
The runtime SHALL expose explicit job control tools for model-visible inspection and stopping of background executions.

#### Scenario: agent lists background jobs
- **WHEN** an agent invokes `job_list`
- **THEN** the runtime SHALL return the visible background-job records for the current execution scope
- **AND** SHALL NOT return task-list entries as though they were jobs

#### Scenario: agent inspects a background job
- **WHEN** an agent invokes `job_get` for a specific job identifier
- **THEN** the runtime SHALL return the current background-job record for that identifier
- **AND** SHALL surface job lifecycle metadata rather than task-list planning fields

#### Scenario: agent stops a running background job
- **WHEN** an agent invokes `job_stop` for a running background job
- **THEN** the runtime SHALL attempt to stop that background execution
- **AND** SHALL NOT mutate any task-list entry unless a separate explicit task-list operation is issued

#### Scenario: agent inspects a missing background job
- **WHEN** an agent invokes `job_get` for a job identifier that is not visible in the current execution scope
- **THEN** the runtime SHALL return a structured tool-visible `not_found` error
- **AND** SHALL NOT fabricate a placeholder job record

#### Scenario: agent stops a missing background job
- **WHEN** an agent invokes `job_stop` for a job identifier that is not visible in the current execution scope
- **THEN** the runtime SHALL return a structured tool-visible `not_found` error
- **AND** SHALL NOT mutate any task-list entry or unrelated job record

#### Scenario: agent stops a non-running background job
- **WHEN** an agent invokes `job_stop` for a background job whose lifecycle state is already terminal or otherwise not stoppable
- **THEN** the runtime SHALL return a structured tool-visible `not_running` error
- **AND** SHALL preserve the existing terminal job state

### Requirement: Background-job control does not rename task-list semantics
The runtime SHALL preserve the conceptual split that task lists are for planning while jobs are for execution control.

#### Scenario: host or agent consumes both surfaces
- **WHEN** a host or agent interacts with both the task-list and background-job control planes
- **THEN** the runtime SHALL make each surface observable through distinct identifiers and contracts
- **AND** SHALL NOT require callers to infer from context whether a `task` identifier is actually a background job

#### Scenario: runtime assigns job identifiers
- **WHEN** the runtime creates or exposes a background-job record
- **THEN** it SHALL expose a job identifier in the background-job namespace for that record
- **AND** SHALL NOT require the identifier to match any task-list entry identifier

