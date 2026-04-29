# runtime-job-control-plane Specification

## Purpose
TBD - created by archiving change generalize-runtime-job-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Runtime owns a shared generic job control plane
The runtime SHALL provide a shared generic job control plane for background and long-running execution, and SHALL keep that control plane separate from planning task-list semantics.

#### Scenario: runtime starts a background execution
- **WHEN** the runtime starts a background-capable execution such as an agent run, shell command, memory job, teammate execution projection, or other registered executor-backed work item
- **THEN** the runtime SHALL create or update a job record in the shared job control plane
- **AND** SHALL NOT require a planning task-list entry to exist for that execution to be tracked

#### Scenario: job lifecycle transitions
- **WHEN** a job transitions among `pending`, `running`, `completed`, `failed`, or `stopped`
- **THEN** the runtime SHALL update the corresponding shared job record
- **AND** SHALL expose that lifecycle independently from task-list state

### Requirement: Job executors are pluggable and runtime-registered
The runtime SHALL allow background work to be executed through runtime-registered job executors addressed by executor kind, rather than by hardcoding one execution transport or one workload type into the control plane.

#### Scenario: runtime submits a job for a registered executor kind
- **WHEN** a caller submits a job whose `executor_kind` matches a registered job executor
- **THEN** the runtime SHALL dispatch that job through the matching executor
- **AND** SHALL keep the shared job contract independent from whether the executor internally uses `asyncio`, subprocesses, threads, or remote infrastructure

#### Scenario: runtime rejects an unknown executor kind
- **WHEN** a caller submits a job whose `executor_kind` is not registered in the runtime
- **THEN** the runtime SHALL reject that submission with a structured executor-resolution error
- **AND** SHALL NOT create a fake running job record for the unknown executor kind

### Requirement: Embedders register custom executors through runtime assembly config
The runtime SHALL expose a stable config-time registration contract for custom job executors, and SHALL NOT require embedders to define executors as tools or mutate runtime internals after assembly as the primary integration path.

#### Scenario: embedder supplies a direct executor binding
- **WHEN** an embedder provides a custom executor binding for an `executor_kind` through runtime configuration
- **THEN** the runtime SHALL register that executor kind during runtime assembly
- **AND** SHALL make it available to the shared job control plane without requiring tool-definition discovery

#### Scenario: embedder supplies a factory-backed executor binding
- **WHEN** an embedder provides a factory-backed executor binding through runtime configuration
- **THEN** the runtime SHALL instantiate that executor during runtime assembly after core runtime services are available
- **AND** SHALL register the resulting executor under the configured `executor_kind`

#### Scenario: configured executor overrides a built-in executor kind
- **WHEN** runtime configuration provides an executor binding whose `executor_kind` matches a built-in executor kind
- **THEN** the runtime SHALL use the configured executor binding for that kind in the assembled runtime
- **AND** SHALL make that override explicit through the shared executor registry rather than by ambiguous late mutation

### Requirement: Job records expose generic lifecycle and typed sidecar linkage
The runtime SHALL expose generic job records for common execution-control concerns, and SHALL allow those records to link to executor-specific sidecars without flattening all sidecar details into the shared schema.

#### Scenario: executor publishes sidecar linkage
- **WHEN** a submitted job has executor-specific observability such as an `AgentRunRecord`, shell output buffer, mailbox claim snapshot, or equivalent sidecar state
- **THEN** the runtime SHALL expose typed linkage from the shared job record to that sidecar state
- **AND** SHALL keep generic job fields limited to lifecycle, scope, control capability, summary, result, and error concerns

#### Scenario: caller reads a generic job record
- **WHEN** a host, tool, or runtime consumer reads a job record through the shared control plane
- **THEN** the runtime SHALL return the generic job record without requiring the caller to parse executor-native state blobs as the primary control surface
- **AND** MAY expose sidecar references or summarized sidecar metadata for correlation

### Requirement: Job records use a fixed minimum authoritative field set
The runtime SHALL treat shared `JobRecord` fields for identity, lifecycle, control, visibility, linkage, result or error envelope, metadata, and sidecar refs as the authoritative minimum record shape.

#### Scenario: runtime persists or returns a shared job record
- **WHEN** the runtime persists, loads, or serializes a shared job record
- **THEN** it SHALL preserve the minimum authoritative fields for job identity, executor kind, summary, lifecycle state, stop intent, timestamps, visibility, parent linkage, result or error envelope, metadata, and sidecar refs
- **AND** SHALL NOT require executor-specific top-level fields to exist in order for the shared control plane to function

#### Scenario: executor needs specialized state beyond the shared record
- **WHEN** an executor needs to expose specialized runtime state beyond the minimum shared job record
- **THEN** the runtime SHALL surface that state through sidecar refs or sidecar-owned metadata
- **AND** SHALL NOT treat executor-specific top-level record fields as part of the required shared job contract

### Requirement: Executor result contracts are minimal lifecycle patches
The runtime SHALL define executor-to-service result contracts as minimal lifecycle patches rather than as executor-native handles or free-form payloads.

#### Scenario: executor accepts job start
- **WHEN** a job executor reports successful submission for a job
- **THEN** its start result SHALL include at least the reconciled shared job status
- **AND** MAY include shared capability updates, shared metadata patches, result or error envelope updates, and sidecar refs
- **AND** SHALL NOT require the shared job contract to expose executor-native live handles such as subprocess objects or event-loop task instances

#### Scenario: executor responds to stop or recovery
- **WHEN** a job executor reports the outcome of stop or recovery processing
- **THEN** its stop or recovery result SHALL include the reconciled shared job status
- **AND** MAY include shared metadata patches, result or error envelope updates, capability updates, and sidecar refs
- **AND** SHALL allow the shared job service to remain the authoritative owner of the persisted job record

### Requirement: Job query, watch, and stop semantics are scope-aware
The runtime SHALL support scope-aware job listing, lookup, watch, and stop semantics over the shared job control plane.

#### Scenario: caller lists visible jobs
- **WHEN** a host or model-visible tool lists jobs for a given execution scope such as session or team scope
- **THEN** the runtime SHALL return only the job records visible to that scope
- **AND** SHALL include enough generic metadata to distinguish job kind, lifecycle state, and linkage

#### Scenario: caller watches a scope for job changes
- **WHEN** a host or runtime consumer registers a watch for a job scope
- **THEN** the runtime SHALL emit job snapshots or equivalent callback payloads when the visible set changes
- **AND** SHALL NOT require executor-specific polling logic to observe lifecycle changes

#### Scenario: caller stops a running job
- **WHEN** a caller requests stop for a visible job that is running and marked stoppable
- **THEN** the runtime SHALL route that request through the owning executor
- **AND** SHALL update shared job state to reflect the resulting terminal or stopping outcome

#### Scenario: caller stops a non-runnable or unknown job
- **WHEN** a caller requests stop for a job that is not visible, not running, or not stoppable
- **THEN** the runtime SHALL return a structured `not_found`, `not_running`, or `not_stoppable` style error
- **AND** SHALL preserve the existing job record state

### Requirement: Shared job lifecycle transitions are runtime-validated
The runtime SHALL validate shared job lifecycle transitions against the shared job state machine rather than treating executor-emitted states as unvalidated source of truth.

#### Scenario: executor starts a job
- **WHEN** an executor reports its start result for a newly submitted job
- **THEN** the runtime SHALL allow the shared job lifecycle to transition from `pending` to `running`, `completed`, or `failed`
- **AND** SHALL reject or normalize invalid start transitions before persisting the authoritative job record

#### Scenario: stop processing updates a running or pending job
- **WHEN** stop is requested for a pending or running job
- **THEN** the runtime SHALL allow transition to `stopped`, or a retained `running` state with `stop_requested=true` while stop remains in progress
- **AND** SHALL preserve terminal-state invariants if the job has already reached `completed`, `failed`, or `stopped`

#### Scenario: recovery reconciles an in-flight job
- **WHEN** the runtime invokes executor-driven recovery for a recoverable in-flight job
- **THEN** the runtime SHALL allow reconciliation from `running` to `running`, `completed`, `failed`, or `stopped`
- **AND** SHALL keep the shared job service as the validator and persister of the reconciled lifecycle state

### Requirement: Shared job payload serialization is canonical across host and tool surfaces
The runtime SHALL serialize shared job records into one canonical payload shape for host-facing and tool-facing job inspection surfaces.

#### Scenario: job inspection uses canonical fields
- **WHEN** a caller reads a single job through a built-in tool surface or host bridge surface
- **THEN** the runtime SHALL serialize that job with the same canonical top-level fields for identity, executor kind, lifecycle state, control flags, timestamps, visibility, linkage, result or error envelope, metadata, and sidecar refs
- **AND** SHALL NOT require each surface to invent its own per-record field names

#### Scenario: job listing reuses canonical record shape
- **WHEN** a caller lists visible jobs through a built-in tool surface or host bridge surface
- **THEN** the runtime SHALL reuse the same canonical per-job payload shape used by single-job inspection
- **AND** SHALL allow list-oriented surfaces to differ only in outer container structure rather than in the serialized shape of each job record

### Requirement: Job records are durable and recoverable at the control-plane layer
The runtime SHALL persist shared job records independently from executor transport so that hosts and runtime services can recover job visibility and terminal history across runtime restarts or session reattachment.

#### Scenario: runtime restarts after a terminal job
- **WHEN** the runtime is restarted after a job has already reached a terminal state
- **THEN** the shared job control plane SHALL still be able to return that persisted terminal job record
- **AND** SHALL preserve terminal status, timestamps, result or error envelope, and sidecar linkage metadata sufficient for correlation

#### Scenario: runtime restarts with a recoverable in-flight job
- **WHEN** the runtime restarts while a recoverable executor-backed job is still in flight or resumable
- **THEN** the control plane SHALL reload the shared job record and delegate recovery or reconciliation to the owning executor
- **AND** SHALL NOT silently drop the job from shared visibility solely because the original in-memory handle no longer exists

### Requirement: Legacy `TaskManager` compatibility is job-service-backed and bounded
The runtime SHALL treat any retained `TaskManager` compatibility as a deprecated facade over the shared job control plane rather than as an independent source of truth.

#### Scenario: legacy caller reads or stops through `TaskManager`
- **WHEN** a legacy runtime caller or embedder accesses job state through a retained `TaskManager` compatibility surface
- **THEN** the runtime SHALL resolve that interaction against the shared job control plane
- **AND** SHALL keep the shared job record as the authoritative lifecycle source

#### Scenario: new job-plane capabilities are introduced after compatibility freeze
- **WHEN** the runtime adds new shared job-control capabilities such as richer watcher payloads, executor-specific recovery metadata, or new sidecar linkage fields
- **THEN** the runtime SHALL expose those capabilities through the shared job APIs
- **AND** SHALL NOT require widening `ManagedTask` or promoting legacy `TaskManager` compatibility to the primary control surface

