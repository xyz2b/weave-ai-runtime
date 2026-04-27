## ADDED Requirements

### Requirement: Runtime SHALL publish canonical protocol bindings for package-owned privileged service families
The runtime SHALL publish runtime-owned canonical protocol bindings for package-owned control-plane service families that would otherwise require privileged dedicated owner-layer service slots.

#### Scenario: package contributes a canonical service-family binding
- **WHEN** a selected runtime package contributes a memory, compaction, or isolation service family implementation
- **THEN** the runtime SHALL bind that implementation through the published service-family protocol surface
- **AND** SHALL preserve package ownership metadata for that canonical binding

### Requirement: Runtime-owned primary paths SHALL consume privileged service families only through canonical protocol bindings
Runtime-owned primary paths SHALL resolve memory-, compaction-, and isolation-owned behavior through the published canonical protocol bindings rather than through package-specific dedicated service fields.

#### Scenario: owner-layer path needs package-owned service behavior
- **WHEN** session control, turn preparation, tool runtime, or delegated execution needs memory-, compaction-, or isolation-owned behavior
- **THEN** the runtime SHALL resolve that behavior through the canonical service-family protocol binding
- **AND** SHALL NOT require a package-specific dedicated `RuntimeServices` field to remain the source of truth for that behavior

### Requirement: Retained dedicated service fields SHALL be compatibility-only projections
If the runtime retains dedicated service fields for migration compatibility, those fields SHALL be compatibility-only projections over the canonical service-family protocol bindings and SHALL NOT expose unique semantics unavailable through the canonical bindings.

#### Scenario: legacy embedder reads a retained dedicated service field
- **WHEN** a legacy embedder or compatibility test reads a retained dedicated field such as `RuntimeServices.memory`
- **THEN** the runtime SHALL resolve that field from the canonical service-family protocol binding
- **AND** SHALL publish that field's compatibility-only status through runtime metadata or equivalent diagnostics
