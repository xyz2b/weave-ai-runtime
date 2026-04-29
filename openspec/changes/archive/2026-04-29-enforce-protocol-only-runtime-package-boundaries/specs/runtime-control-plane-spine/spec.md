## ADDED Requirements

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
