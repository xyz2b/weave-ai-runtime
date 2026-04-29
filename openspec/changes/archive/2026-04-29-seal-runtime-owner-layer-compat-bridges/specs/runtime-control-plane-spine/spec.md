## MODIFIED Requirements

### Requirement: Execution plane consumes control-plane services through a stable runtime contract
The runtime SHALL provide `SessionController`, `TurnEngine`, `ToolRuntime`, `AgentRuntime`, `SkillRuntime`, and other runtime-owned execution helpers with a stable runtime-level contract for consuming control-plane services. Package-owned control-plane extensions SHALL be consumed through canonical capability lookup, lifecycle registries, or shared job and task-list services rather than package-specific top-level service slots.

#### Scenario: Turn execution needs runtime control services
- **WHEN** a turn, tool call, agent delegation, skill execution, or runtime-owned workflow helper requires access to permissions, hooks, elicitation, memory, compaction, tasks, jobs, transcript services, or package-owned control-plane behavior
- **THEN** the execution path SHALL access those capabilities through the shared runtime control-plane contract rather than per-call callback injection
- **AND** SHALL treat retained package-specific top-level projections as compatibility wrappers rather than canonical owner-layer lookup paths

## ADDED Requirements

### Requirement: Control-plane compatibility projections SHALL remain bounded
The runtime SHALL keep any retained package-specific control-plane projections explicitly bounded to compatibility use, with canonical runtime services remaining authoritative for runtime-owned primary paths.

#### Scenario: runtime-owned job or task logic uses canonical services
- **WHEN** runtime-owned code needs authoritative background-job or task-list state
- **THEN** it SHALL use the shared job or task-list control-plane services as the source of truth
- **AND** SHALL NOT widen `TaskManager` or another retained compatibility projection into the primary control-plane abstraction

#### Scenario: assembled control plane publishes wrapper status
- **WHEN** the runtime assembles its shared control-plane graph with first-party package contributions
- **THEN** it SHALL publish which top-level control-plane projections remain compatibility-only
- **AND** SHALL identify the canonical lookup paths that runtime-owned code is expected to use instead
