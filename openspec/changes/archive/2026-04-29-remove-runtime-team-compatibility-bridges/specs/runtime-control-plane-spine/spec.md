## ADDED Requirements

### Requirement: Runtime-owned primary paths SHALL remain independent of team-specific projections and wrappers
The runtime SHALL require runtime-owned team behavior to resolve through canonical team capability keys, host facets, lifecycle participants, and extension-event contracts rather than through package-specific projections or wrapper methods on owner-layer surfaces.

#### Scenario: runtime-owned path needs team behavior
- **WHEN** runtime-owned session, turn, workflow, or host-integration code needs package-owned team behavior
- **THEN** it SHALL resolve that behavior through canonical team protocol surfaces
- **AND** SHALL NOT require `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, or bound-host team wrapper methods as primary integration paths
