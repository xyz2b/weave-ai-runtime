# runtime-package-integration-protocols Specification

## Purpose
TBD - created by archiving change converge-runtime-package-protocol-integration. Update Purpose after archive.
## Requirements
### Requirement: Official runtime packages SHALL publish package manifests
The runtime SHALL treat each official first-party package as a manifest-backed package integration unit that declares its package identity, package role, runtime-core dependency relationship, and package assembly entrypoint.

#### Scenario: Kernel prepares selected first-party packages
- **WHEN** the runtime selects one or more official first-party packages for assembly
- **THEN** it SHALL resolve those packages through manifest-backed package records rather than through package-name-specific assembly branches alone
- **AND** each manifest SHALL identify the package name and dependency ordering metadata required for assembly

### Requirement: Package assembly SHALL return structured package contributions
The runtime SHALL require manifest-backed package assembly to return a structured contribution result that may include capability bindings, built-in definitions, lifecycle participants, host facets, store or provider bindings, job executors, and diagnostics.

#### Scenario: Package contributes multiple runtime surfaces
- **WHEN** an official package contributes both runtime-owned capabilities and built-in definitions
- **THEN** its assembly result SHALL expose those contributions through one structured package-contribution contract
- **AND** the runtime SHALL apply those contributions without requiring package-specific mutation paths for each contribution kind

### Requirement: Store, provider, and job-executor bindings SHALL be attachable through package contributions
The runtime SHALL treat shared core store bindings, model provider or route bindings, and job-executor bindings as first-class package-contribution kinds so that official packages do not require kernel-specific post-processing to attach those bindings.

#### Scenario: Provider package contributes model bindings
- **WHEN** an official provider package contributes model provider or route bindings
- **THEN** the runtime SHALL attach those bindings through the shared package-contribution path
- **AND** it SHALL NOT require package-name-specific kernel post-processing as the primary integration contract for that provider package

#### Scenario: Store package contributes shared core stores
- **WHEN** an official adapter package contributes transcript, job, or task-list store bindings
- **THEN** the runtime SHALL attach those bindings through the shared package-contribution path
- **AND** it SHALL keep those store bindings observable as package-owned contributions rather than implicit kernel-owned defaults

#### Scenario: Package contributes job executors
- **WHEN** an official package contributes one or more job-executor bindings
- **THEN** the runtime SHALL register those executors through the shared package-contribution path
- **AND** it SHALL preserve the shared `JobService` as the authoritative execution-control surface for those executors

### Requirement: Runtime SHALL expose package-owned capabilities through a capability registry
The runtime SHALL provide a shared capability-registry contract that allows package-owned runtime objects to be bound to stable capability keys and resolved by consumers without promoting each package-owned object to a dedicated top-level core service field.

#### Scenario: Consumer resolves a package-owned runtime object
- **WHEN** a runtime execution path or package-owned helper needs access to an optional package-owned runtime object
- **THEN** it SHALL be able to resolve that object through the shared capability-registry contract
- **AND** the runtime SHALL NOT require a permanent dedicated top-level core service field for that object solely because one official package uses it

### Requirement: Package-owned lifecycle behavior SHALL attach through bounded lifecycle participants
The runtime SHALL allow official packages to register bounded lifecycle participants for runtime start, runtime recovery, session open, and session close phases while preserving runtime-owned host, session, and turn ownership.

#### Scenario: Package needs recovery or session replay behavior
- **WHEN** an official package needs runtime recovery or session-scoped replay behavior
- **THEN** it SHALL attach that behavior through the package lifecycle-participant contract
- **AND** the runtime SHALL preserve host-, session-, and turn-scope ownership in the core lifecycle managers

### Requirement: Optional package-specific host operations SHALL attach through host facets
The runtime SHALL allow official packages to expose optional package-specific host operations through package-owned host facets or equivalent capability-detected host extensions instead of requiring every such operation to widen the mandatory host bridge.

#### Scenario: Package adds optional host-visible workflow operations
- **WHEN** an official package needs host-visible operations that are not required by every host
- **THEN** the runtime SHALL expose those operations through a package-owned host-facet contract
- **AND** hosts that do not use that package SHALL NOT be required to implement those optional operations as part of the mandatory host bridge

