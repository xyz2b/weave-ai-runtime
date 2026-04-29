## ADDED Requirements

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
