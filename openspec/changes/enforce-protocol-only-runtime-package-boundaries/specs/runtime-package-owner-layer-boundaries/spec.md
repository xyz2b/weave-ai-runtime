## ADDED Requirements

### Requirement: Runtime owner layers SHALL consume package extensions only through runtime-owned protocols
The runtime SHALL require `runtime-core` owner layers to consume package-owned behavior only through runtime-owned protocol seams such as capability lookup, host-facet lookup, lifecycle participants, and bounded ingress completion receipts, rather than through new package-specific owner-layer fields, helper methods, or control-flow branches.

#### Scenario: package introduces owner-visible runtime behavior
- **WHEN** an official package adds runtime-owned behavior that must participate in session control, host integration, or runtime service discovery
- **THEN** the runtime SHALL attach that behavior through a published runtime-owned protocol seam
- **AND** it SHALL NOT require `SessionController`, `RuntimeAssembly`, `BoundHostRuntime`, `TurnEngine`, or shared `RuntimeServices` to grow a new package-specific primary integration path for that behavior

### Requirement: Compatibility wrappers SHALL remain bounded and non-canonical
The runtime MAY retain package-specific compatibility wrappers during migration, but those wrappers SHALL be bounded projections over canonical protocol lookup paths and SHALL NOT become the normative extension contract for package-owned behavior.

#### Scenario: runtime preserves a package-specific helper during migration
- **WHEN** the runtime retains a package-specific helper or top-level projection for migration compatibility
- **THEN** the same package-owned capability or host-visible operation SHALL remain available through the canonical runtime-owned protocol path
- **AND** the compatibility wrapper SHALL NOT expose unique behavior that is unavailable through the canonical lookup path
