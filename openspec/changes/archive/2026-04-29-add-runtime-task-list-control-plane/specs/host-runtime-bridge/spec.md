## ADDED Requirements

### Requirement: Host bridge exposes optional task-list query and watch surfaces
The runtime SHALL expose host-facing task-list query and observation surfaces through the runtime bridge or bound runtime API, without requiring hosts to take ownership of task orchestration.

#### Scenario: host queries task-list state for a session
- **WHEN** a bound host requests the task-list state associated with a session or resolved task-list identifier
- **THEN** the runtime SHALL return the current persisted task-list snapshot through the bridge surface
- **AND** SHALL NOT require the host to reconstruct task state from transcript messages or notifications

#### Scenario: host observes task-list changes
- **WHEN** a bound host subscribes to task-list updates for a resolved task-list identifier
- **THEN** the runtime SHALL provide a callback-based watch registration on the bound runtime surface
- **AND** SHALL emit the current full task-list snapshot when the subscription is established
- **AND** SHALL emit subsequent full snapshots after committed task-list changes for that identifier
- **AND** SHALL keep task orchestration, validation, and persistence under runtime ownership

#### Scenario: host does not consume task-list projections
- **WHEN** a bound host never queries or subscribes to task-list state
- **THEN** the runtime SHALL continue to execute task-list tools and hidden reminder sidecars normally
- **AND** SHALL NOT require host participation for task-list correctness

#### Scenario: host prefers polling over callbacks
- **WHEN** a bound host chooses not to register a task-list watch callback
- **THEN** the runtime SHALL still make the latest task-list snapshot available through query APIs
- **AND** SHALL NOT require event-stream transport support for first-version task-list projection

### Requirement: Host bridge exposes separate background-job query surfaces
The runtime SHALL expose host-facing background-job query surfaces separately from task-list surfaces so hosts can build execution monitors without conflating them with planning state.

#### Scenario: host queries background-job state
- **WHEN** a bound host requests the visible background jobs for a session, scope, or specific job identifier
- **THEN** the runtime SHALL return background-job snapshots through explicit job-oriented bridge surfaces
- **AND** SHALL NOT require the host to read task-list state to discover background execution lifecycle

#### Scenario: host consumes both task lists and jobs
- **WHEN** a bound host renders both planning state and execution state
- **THEN** the runtime SHALL let the host consume task-list and background-job data through distinct bridge contracts
- **AND** SHALL keep task-list identifiers and job identifiers distinct in those projections
