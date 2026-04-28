## MODIFIED Requirements

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
