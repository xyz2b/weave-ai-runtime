## ADDED Requirements

### Requirement: Session ingress SHALL propagate authoritative private state through structured carriers
The runtime SHALL propagate ingress-owned private updates and session-private state through structured authoritative carriers rather than through raw compatibility maps.

#### Scenario: ingress emits runtime-private updates
- **WHEN** session ingress classifies an inbound event and emits runtime-private updates
- **THEN** session control SHALL merge those updates into authoritative structured private-state carriers
- **AND** SHALL NOT require raw `runtime_context` mutation as the authoritative persistence path for those updates
