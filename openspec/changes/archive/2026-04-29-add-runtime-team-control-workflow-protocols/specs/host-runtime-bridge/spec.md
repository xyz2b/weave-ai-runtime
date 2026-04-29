## ADDED Requirements

### Requirement: Hosts SHALL be able to observe and resolve pending team control workflows through runtime-owned bridge surfaces
The runtime SHALL expose optional host-facing workflow surfaces that allow a bound host to observe pending team control workflows and submit typed workflow responses by `workflow_id` without fabricating raw control messages.

#### Scenario: host loads pending workflows after reconnect
- **WHEN** a bound host reconnects after missing prior team workflow events
- **THEN** it SHALL be able to query the runtime for the current pending team control workflows relevant to the bound team or leader session
- **AND** SHALL receive stable workflow identifiers, workflow kinds, and allowed response actions for each pending workflow

#### Scenario: host resolves a pending workflow through the runtime
- **WHEN** a bound host submits an allowed response for a pending team control workflow
- **THEN** the runtime SHALL validate that response through the same authority and state-machine checks used for model-driven workflow responses
- **AND** SHALL record the updated workflow state before emitting any follow-up observation events

### Requirement: Optional host workflow surfaces SHALL remain additive
The runtime SHALL keep workflow observation and resolution surfaces optional so model-driven team control continues to function correctly when a host does not implement them.

#### Scenario: no host workflow integration exists
- **WHEN** a bound host does not implement any optional team workflow observation or resolution surface
- **THEN** the runtime SHALL still allow leader-ingress workflow requests, teammate permission waits, and graceful shutdown workflows to proceed correctly
- **AND** SHALL degrade only by omitting those optional host-side workflow operations
