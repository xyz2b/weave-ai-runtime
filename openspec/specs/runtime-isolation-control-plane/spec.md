# runtime-isolation-control-plane Specification

## Purpose
TBD - created by archiving change add-skill-policy-and-isolation-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Runtime enforces isolation through a formal isolation contract
The runtime SHALL enforce agent and skill isolation through a formal isolation control plane rather than a definition-only enum.

#### Scenario: Agent requests worktree isolation
- **WHEN** an agent or delegated execution context resolves to `worktree` isolation
- **THEN** the runtime SHALL use the isolation control plane to prepare and expose the isolated execution environment before turn execution begins

### Requirement: Isolation modes have stable runtime semantics
The runtime SHALL define stable runtime semantics for `none`, `worktree`, and `remote` isolation modes, including concrete preparation behavior, metadata exposure, lifecycle cleanup expectations, and honest failure behavior when a requested backend is unavailable.

#### Scenario: worktree isolation creates a real local lease
- **WHEN** an execution path resolves to `worktree` isolation
- **THEN** the runtime SHALL prepare a real isolated working directory or equivalent isolated local lease target before execution begins
- **AND** the runtime SHALL publish lease metadata that identifies the source working directory, prepared target, effective isolation mode, and cleanup owner

#### Scenario: remote isolation without a configured backend fails before execution
- **WHEN** an execution path resolves to `remote` isolation but no remote adapter is configured for that runtime
- **THEN** the runtime SHALL return a structured `not_available`, `not_configured`, or equivalent failure outcome before model or tool execution begins
- **AND** the runtime SHALL NOT emit a successful stub lease that claims remote isolation was prepared

#### Scenario: remote isolation uses configured adapter semantics
- **WHEN** an execution path resolves to `remote` isolation and a remote adapter is configured
- **THEN** the runtime SHALL delegate preparation and cleanup to that adapter through the isolation control-plane contract
- **AND** the runtime SHALL expose adapter identity and effective remote lease metadata through the resulting isolation lease

### Requirement: Delegated execution cannot weaken the resolved isolation boundary
The runtime SHALL ensure that delegated execution paths do not weaken the already resolved isolation boundary of the parent context.

#### Scenario: Parent context is already isolated
- **WHEN** a parent agent or skill executes under an isolation boundary and then delegates further work
- **THEN** the runtime SHALL preserve that boundary or apply a narrower one, but SHALL not silently downgrade to a weaker isolation mode

### Requirement: Isolation control-plane behavior SHALL attach to owner layers through a canonical package-service protocol binding
The runtime SHALL attach isolation preparation and cleanup behavior to owner-layer and execution-layer runtime paths through the canonical isolation service-family protocol binding rather than through `RuntimeServices.isolation` as a privileged source-of-truth slot.

#### Scenario: delegated execution resolves isolation
- **WHEN** delegated execution resolves an isolation boundary and needs preparation or cleanup behavior
- **THEN** the runtime SHALL resolve that behavior through the canonical isolation service-family protocol binding
- **AND** SHALL treat any retained `RuntimeServices.isolation` field as a compatibility projection rather than the normative binding surface

