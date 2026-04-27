## ADDED Requirements

### Requirement: Optional package-owned host interactions SHALL use host facets and generic extension events
The runtime SHALL expose optional package-owned host interactions through canonical host facets for host-to-runtime operations and through the generic extension-event host contract for runtime-to-host structured package events.

#### Scenario: host performs an optional team workflow operation
- **WHEN** a host needs to list or respond to package-owned team workflow operations
- **THEN** the runtime SHALL expose that operation through the canonical team workflow host facet
- **AND** SHALL NOT require a package-specific workflow helper method on the mandatory host bridge or bound-host owner surface

#### Scenario: runtime emits a package-owned team event
- **WHEN** the runtime emits a structured package-owned team event for host consumption
- **THEN** it SHALL emit that event through the generic extension-event host contract
- **AND** SHALL NOT require a package-specific team event method on the mandatory host bridge

### Requirement: Removed team bridge surfaces SHALL publish canonical replacements and absence semantics
The runtime SHALL publish canonical replacement paths and bounded absence semantics for each removed team-specific host-facing or bound-host bridge surface.

#### Scenario: caller inspects team bridge migration metadata
- **WHEN** a caller or conformance test inspects migration metadata for removed team bridge surfaces
- **THEN** the runtime SHALL identify each removed surface's canonical replacement path
- **AND** SHALL describe the bounded behavior when `runtime-team` is absent rather than restoring a wrapper on the mandatory host bridge
