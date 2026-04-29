# runtime-control-plane-spine Specification

## Purpose
TBD - created by archiving change introduce-runtime-control-plane-spine. Update Purpose after archive.
## Requirements
### Requirement: Kernel assembles an explicit control-plane service graph
The runtime SHALL assemble an explicit control-plane service graph before any session or turn execution begins, rather than wiring control logic solely through ad hoc callbacks.

#### Scenario: Building a runnable runtime
- **WHEN** the host or application assembles the runtime from configuration
- **THEN** the runtime SHALL construct shared control-plane service instances before creating any `SessionController` or turn-execution surface

### Requirement: Execution plane consumes control-plane services through a stable runtime contract
The runtime SHALL provide `SessionController`, `TurnEngine`, `ToolRuntime`, `AgentRuntime`, `SkillRuntime`, and other runtime-owned execution helpers with a stable runtime-level contract for consuming control-plane services. Package-owned control-plane extensions SHALL be consumed through canonical capability lookup, lifecycle registries, or shared job and task-list services rather than package-specific top-level service slots.

#### Scenario: Turn execution needs runtime control services
- **WHEN** a turn, tool call, agent delegation, skill execution, or runtime-owned workflow helper requires access to permissions, hooks, elicitation, memory, compaction, tasks, jobs, transcript services, or package-owned control-plane behavior
- **THEN** the execution path SHALL access those capabilities through the shared runtime control-plane contract rather than per-call callback injection
- **AND** SHALL treat retained package-specific top-level projections as compatibility wrappers rather than canonical owner-layer lookup paths

### Requirement: Control-plane and execution-plane responsibilities remain separated
The runtime SHALL keep control-plane concerns and execution-plane concerns in distinct layers, so that lifecycle, permissions, hooks, memory, and compaction do not become hidden responsibilities of the turn engine alone.

#### Scenario: Adding a new control-plane subsystem
- **WHEN** the runtime introduces a new cross-cutting subsystem such as hooks, permissions, elicitation, memory, or compaction
- **THEN** that subsystem SHALL be attached to the control-plane layer and consumed by execution components through the runtime contract instead of being embedded directly into a single execution class

### Requirement: Context assembly accepts control-plane contributions
The runtime SHALL provide a unified context-assembly boundary that can accept memory fragments, hook-provided context, compaction outputs, attachments, runtime metadata, and package-contributed context contributors before model requests are emitted.

#### Scenario: Preparing a model request
- **WHEN** the runtime prepares the context for a provider request
- **THEN** the runtime SHALL combine control-plane contributions through a dedicated context-assembly step instead of requiring each subsystem to mutate request text independently
- **AND** any package-contributed collect-style context participants SHALL run through the same runtime-owned staging contract

#### Scenario: Package-contributed context collector is absent
- **WHEN** the active runtime distribution does not include a package that would otherwise contribute a context collector for a given stage
- **THEN** the runtime SHALL continue to assemble the request through the same unified context-assembly boundary
- **AND** SHALL degrade by omitting only that optional package contribution rather than requiring a package-specific service slot to exist

### Requirement: Shared runtime control-plane services SHALL expose package-owned capabilities through one runtime contract
The runtime SHALL allow execution-plane surfaces to consume package-owned control-plane services through the shared runtime contract and capability-registry mechanism instead of requiring package-specific top-level service slots for each optional official package.

#### Scenario: Execution surface needs a package-owned control-plane service
- **WHEN** a session, turn, tool, agent, or skill execution path needs access to an optional package-owned control-plane service
- **THEN** it SHALL access that service through the shared runtime contract and capability-registry path
- **AND** the control-plane spine SHALL NOT require a new permanent top-level service slot solely because one official package contributes that service

### Requirement: Runtime-owned lifecycle phases SHALL admit package participants without transferring ownership
The runtime SHALL let package-contributed lifecycle participants run inside runtime-owned lifecycle phases while keeping host, session, and turn ownership in the core lifecycle managers.

#### Scenario: Package participates in session-close cleanup
- **WHEN** an official package registers a lifecycle participant for session-close behavior
- **THEN** the runtime SHALL invoke that participant within the runtime-owned session-close lifecycle
- **AND** the session controller SHALL remain the owner of session close semantics rather than delegating ownership to the package

### Requirement: Runtime-owned call paths SHALL prefer canonical package lookup over compatibility projections
The runtime SHALL require runtime-owned execution and control-plane call paths to resolve package-owned services and host-visible helpers through capability or host-facet lookup before relying on package-specific compatibility projections.

#### Scenario: runtime-owned surface needs a package-owned control-plane service
- **WHEN** a session, host wrapper, or runtime-owned helper path needs an optional package-owned control-plane service
- **THEN** that path SHALL resolve the service through the shared runtime capability contract
- **AND** it SHALL NOT require a package-specific top-level service slot to exist as the normative source of truth for that service

#### Scenario: runtime-owned surface needs a package-owned host-visible helper
- **WHEN** a runtime-owned helper path needs an optional package-owned host-visible operation
- **THEN** that path SHALL resolve the operation through the shared host-facet contract
- **AND** it SHALL treat any package-specific helper wrapper as a compatibility projection rather than as the canonical runtime-owned path

### Requirement: Compatibility projections SHALL remain non-authoritative
The runtime SHALL treat retained package-specific compatibility projections as migration aids rather than authoritative shared control-plane surfaces.

#### Scenario: compatibility projection is retained during boundary migration
- **WHEN** the runtime keeps a package-specific top-level projection for compatibility
- **THEN** the capability or host-facet registry SHALL remain the authoritative package-owned discovery surface
- **AND** new runtime-owned primary paths SHALL NOT be introduced that depend on the compatibility projection as the only supported lookup contract

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

### Requirement: Control-plane assembly publishes canonical core protocol inventory
The runtime SHALL publish a canonical inventory of stable core protocols as part of control-plane assembly, including the authoritative discovery or binding path for each protocol.

#### Scenario: assembled control plane is inspected for protocol guidance
- **WHEN** a caller or conformance test inspects the assembled control-plane metadata
- **THEN** the runtime SHALL identify the canonical control-plane and adjacent protocol surfaces for transcript persistence, jobs, task lists, permissions, elicitation, context contributors, invocation providers, and host binding
- **AND** SHALL distinguish those canonical protocol paths from compatibility-only helper surfaces

### Requirement: Shared control-plane authority SHALL live on structured context carriers and shared job/task services
The runtime SHALL keep authoritative shared context state on structured prompt/private carriers and authoritative execution-control state on shared job/task services rather than on raw `runtime_context` maps or `TaskManager` compatibility surfaces.

#### Scenario: control-plane path updates shared state
- **WHEN** a runtime-owned control-plane path updates shared private context or execution-control state
- **THEN** it SHALL update that state through the structured context carriers or shared job/task services
- **AND** SHALL NOT use raw `runtime_context` or `TaskManager` as an authoritative mutable control-plane contract

### Requirement: Execution plane SHALL consume package-owned privileged service families through canonical protocol bindings
The runtime SHALL require execution-plane and owner-layer components to consume package-owned privileged service families such as memory, compaction, and isolation through canonical runtime-owned protocol bindings rather than package-specific dedicated service slots.

#### Scenario: turn execution needs package-owned control-plane behavior
- **WHEN** turn preparation, session control, tool execution, or delegated execution requires memory-, compaction-, or isolation-owned behavior
- **THEN** the runtime SHALL resolve that behavior through canonical protocol bindings on the shared control-plane contract
- **AND** SHALL NOT require package-specific dedicated owner-layer fields to remain canonical integration surfaces

### Requirement: Control-plane metadata SHALL distinguish canonical protocol bindings from retained projections
The runtime SHALL publish metadata that distinguishes canonical protocol bindings from retained compatibility projections for package-owned privileged service families.

#### Scenario: embedder inspects assembled control-plane metadata
- **WHEN** an embedder or conformance test inspects the assembled control-plane metadata
- **THEN** the runtime SHALL identify the canonical protocol binding for each migrated privileged service family
- **AND** SHALL separately identify any retained dedicated service fields as compatibility-only projections

### Requirement: Runtime-owned primary paths SHALL remain independent of team-specific projections and wrappers
The runtime SHALL require runtime-owned team behavior to resolve through canonical team capability keys, host facets, lifecycle participants, and extension-event contracts rather than through package-specific projections or wrapper methods on owner-layer surfaces.

#### Scenario: runtime-owned path needs team behavior
- **WHEN** runtime-owned session, turn, workflow, or host-integration code needs package-owned team behavior
- **THEN** it SHALL resolve that behavior through canonical team protocol surfaces
- **AND** SHALL NOT require `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, or bound-host team wrapper methods as primary integration paths

