# runtime-package-owner-layer-boundaries Specification

## Purpose
TBD - created by archiving change enforce-protocol-only-runtime-package-boundaries. Update Purpose after archive.
## Requirements
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

### Requirement: Runtime-owned primary paths SHALL use canonical package lookup seams
The runtime SHALL require any runtime-owned primary path that consumes first-party package behavior to resolve that behavior through canonical capability lookup, host-facet lookup, lifecycle participation, or shared job and task-list services, rather than through package-specific owner-layer slots or helpers.

#### Scenario: runtime-owned module needs a package-owned service
- **WHEN** a runtime-owned workflow, control-plane, or tool helper needs access to a first-party package service such as team workflows or teammates
- **THEN** it SHALL resolve that dependency through the canonical capability key, host facet, lifecycle participant, or shared control-plane service for that behavior
- **AND** SHALL NOT require `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, or another package-specific projection to exist as the only supported primary path

### Requirement: Retained compatibility projections SHALL be thin and non-authoritative
The runtime SHALL treat any retained package-specific owner-layer projections as compatibility-only wrappers that delegate to canonical services and do not own independent source-of-truth state.

#### Scenario: caller uses a retained compatibility projection
- **WHEN** a caller reads a retained package-specific projection such as `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, a host workflow helper, or `TaskManager`
- **THEN** the runtime SHALL serve that request from the underlying canonical capability, host-facet, job, or task-list path
- **AND** SHALL NOT allow the compatibility projection to bypass canonical validation or maintain divergent authoritative state

#### Scenario: new runtime-owned feature adds package integration
- **WHEN** a new runtime-owned feature needs to attach first-party package behavior after this change
- **THEN** it SHALL add that integration through a canonical protocol seam
- **AND** SHALL NOT introduce a new package-specific owner-layer slot as its primary runtime attachment path

### Requirement: Runtime assembly SHALL publish owner-layer boundary metadata
The runtime SHALL publish machine-readable metadata that identifies canonical package lookup paths, retained compatibility wrappers, and the exit criteria for removing those wrappers.

#### Scenario: assembled runtime reports canonical lookup guidance
- **WHEN** a runtime is assembled with one or more first-party packages
- **THEN** its runtime metadata SHALL identify the canonical capability keys, canonical host-facet keys, retained compatibility wrappers, and staged wrapper-exit criteria relevant to that assembled distribution

