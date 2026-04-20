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
The runtime SHALL define stable runtime semantics for `none`, `worktree`, and `remote` isolation modes, including preparation, metadata exposure, and lifecycle cleanup expectations.

#### Scenario: Remote isolation is selected
- **WHEN** a runtime execution path resolves to `remote` isolation
- **THEN** the runtime SHALL route that execution through the remote isolation adapter contract instead of treating `remote` as an unhandled enum value

### Requirement: Delegated execution cannot weaken the resolved isolation boundary
The runtime SHALL ensure that delegated execution paths do not weaken the already resolved isolation boundary of the parent context.

#### Scenario: Parent context is already isolated
- **WHEN** a parent agent or skill executes under an isolation boundary and then delegates further work
- **THEN** the runtime SHALL preserve that boundary or apply a narrower one, but SHALL not silently downgrade to a weaker isolation mode

