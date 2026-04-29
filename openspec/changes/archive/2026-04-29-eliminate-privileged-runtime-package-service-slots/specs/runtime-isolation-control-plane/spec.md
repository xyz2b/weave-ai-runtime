## ADDED Requirements

### Requirement: Isolation control-plane behavior SHALL attach to owner layers through a canonical package-service protocol binding
The runtime SHALL attach isolation preparation and cleanup behavior to owner-layer and execution-layer runtime paths through the canonical isolation service-family protocol binding rather than through `RuntimeServices.isolation` as a privileged source-of-truth slot.

#### Scenario: delegated execution resolves isolation
- **WHEN** delegated execution resolves an isolation boundary and needs preparation or cleanup behavior
- **THEN** the runtime SHALL resolve that behavior through the canonical isolation service-family protocol binding
- **AND** SHALL treat any retained `RuntimeServices.isolation` field as a compatibility projection rather than the normative binding surface
