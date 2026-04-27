## ADDED Requirements

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
