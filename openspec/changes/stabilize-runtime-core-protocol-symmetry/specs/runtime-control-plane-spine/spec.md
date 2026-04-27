## ADDED Requirements

### Requirement: Control-plane assembly publishes canonical core protocol inventory
The runtime SHALL publish a canonical inventory of stable core protocols as part of control-plane assembly, including the authoritative discovery or binding path for each protocol.

#### Scenario: assembled control plane is inspected for protocol guidance
- **WHEN** a caller or conformance test inspects the assembled control-plane metadata
- **THEN** the runtime SHALL identify the canonical control-plane and adjacent protocol surfaces for transcript persistence, jobs, task lists, permissions, elicitation, context contributors, invocation providers, and host binding
- **AND** SHALL distinguish those canonical protocol paths from compatibility-only helper surfaces
