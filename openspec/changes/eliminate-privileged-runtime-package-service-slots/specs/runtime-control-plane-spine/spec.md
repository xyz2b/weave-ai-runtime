## ADDED Requirements

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
