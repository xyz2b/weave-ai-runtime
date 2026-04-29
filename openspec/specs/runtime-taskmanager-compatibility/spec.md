# runtime-taskmanager-compatibility Specification

## Purpose
TBD - created by archiving change retire-runtime-context-and-taskmanager-compat. Update Purpose after archive.
## Requirements
### Requirement: TaskManager SHALL remain only as a legacy facade over shared job and task-list services
The runtime SHALL treat any retained `TaskManager` surface as a legacy facade over `JobService` and `TaskListService` rather than as an independent authoritative control plane.

#### Scenario: legacy caller uses TaskManager
- **WHEN** a legacy caller interacts with a retained `TaskManager` compatibility surface
- **THEN** the runtime SHALL resolve that interaction against the shared authoritative job and task-list services
- **AND** SHALL preserve those shared services as the source of truth for lifecycle, visibility, and mutation semantics

### Requirement: Runtime-owned primary paths SHALL NOT depend on TaskManager materialization
The runtime SHALL ensure that runtime-owned primary paths do not require `TaskManager` to be materialized or consulted as part of normal control-plane execution.

#### Scenario: runtime-owned path executes background or planning logic
- **WHEN** a runtime-owned primary path performs background-job or task-list related work
- **THEN** that path SHALL use the shared job and task-list control planes directly
- **AND** SHALL NOT depend on `TaskManager` materialization as an authoritative intermediate surface

### Requirement: TaskManager compatibility adapters SHALL be explicitly whitelisted
The runtime SHALL publish an explicit finite whitelist of the compatibility-only adapters that may still materialize `TaskManager` during the migration.

#### Scenario: caller inspects TaskManager compatibility metadata
- **WHEN** a caller or conformance test inspects compatibility metadata for `TaskManager`
- **THEN** the runtime SHALL identify the finite set of explicit legacy adapters that may still materialize `TaskManager`
- **AND** SHALL identify `JobService` and `TaskListService` as the authoritative control planes behind those adapters

