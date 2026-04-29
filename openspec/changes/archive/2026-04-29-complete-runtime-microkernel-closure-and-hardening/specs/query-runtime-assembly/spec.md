## ADDED Requirements

### Requirement: Runtime assembly publishes closure and hardening state separately from core protocol metadata
The runtime SHALL publish closure and hardening state through a dedicated closure report at `runtime.services.metadata["closure_report"]` and `runtime.metadata["closure_report"]`, separate from the stable core protocol catalog, package inventory, and package lookup metadata.

#### Scenario: caller inspects closure report
- **WHEN** a caller inspects assembly metadata for closure or hardening information
- **THEN** the runtime SHALL publish a dedicated closure report that describes retained legacy surfaces, isolation readiness, persistence profile, and current closure status
- **AND** the runtime SHALL keep that report separate from the stable core protocol catalog entries themselves

### Requirement: Runtime assembly publishes active persistence and isolation readiness state
The runtime SHALL publish the active persistence profile and isolation readiness state for the selected assembly so embedders can distinguish lightweight and production-oriented runtime shapes.

#### Scenario: runtime-core and runtime-full report different hardening state
- **WHEN** a caller compares assembly metadata for smaller and larger supported runtime shapes
- **THEN** the runtime SHALL preserve the same stable core protocol catalog where required
- **AND** it SHALL allow closure-report fields such as persistence profile, child-run durability, transcript durability, and isolation readiness to vary by assembled runtime shape
