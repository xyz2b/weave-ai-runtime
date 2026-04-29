## ADDED Requirements

### Requirement: Runtime SHALL provide a structured durable team message bus separate from teammate work-item storage
The runtime SHALL provide a structured team message bus for collaboration and control-plane messages, and SHALL keep that bus separate from the teammate execution work queue so collaboration routing does not depend on execution retry or claim mechanics.

#### Scenario: direct team message is persisted for a recipient
- **WHEN** a sender issues a direct team message to one leader or teammate recipient
- **THEN** the runtime SHALL persist a structured message envelope for that recipient through the team message bus
- **AND** SHALL NOT require the sender to write directly into the teammate execution work queue

#### Scenario: team broadcast fans out to multiple recipients
- **WHEN** a sender issues a team broadcast message
- **THEN** the runtime SHALL materialize delivery for each resolved recipient under the team message-bus contract
- **AND** SHALL preserve recipient-targeted routing metadata rather than treating the broadcast as an unaddressed transcript blob

#### Scenario: broadcast excludes the sender by default
- **WHEN** a sender issues a team broadcast to the active team
- **THEN** the runtime SHALL fan that broadcast out to the other active members of that same team
- **AND** SHALL NOT require the sender to receive an echoed delivery solely because the message was broadcast

### Requirement: Team control messages SHALL use typed correlated protocol envelopes
The runtime SHALL represent permission, shutdown, mode-change, and similar team control messages as typed structured protocol envelopes with stable correlation metadata instead of relying on raw free-form message text.

#### Scenario: permission request and response remain correlated
- **WHEN** a teammate-originated team control flow requires a permission request and later a permission response
- **THEN** the runtime SHALL preserve correlation metadata linking the response to the original request
- **AND** SHALL keep those messages distinguishable from ordinary teammate conversation payloads

#### Scenario: shutdown request is represented as a control message
- **WHEN** the runtime or a team member issues a teammate shutdown request
- **THEN** the runtime SHALL encode that request as a typed team control message
- **AND** SHALL NOT require recipients or hosts to infer shutdown intent only from raw display text

### Requirement: Team messages SHALL be routed through runtime-owned delivery adapters
The runtime SHALL route persisted team messages through runtime-owned delivery adapters that target leader ingress, teammate execution, or host-facing event surfaces as appropriate for the recipient and message type.

#### Scenario: leader-visible teammate message routes into session ingress
- **WHEN** a teammate sends a regular collaboration message to the team leader
- **THEN** the runtime SHALL route that message into the leader-side runtime delivery path such as session ingress or an equivalent runtime-owned session input contract
- **AND** SHALL NOT require a bundled UI inbox reducer to make that message visible to the leader session

#### Scenario: teammate recipient receives routed work through the teammate execution substrate
- **WHEN** a team message targets a teammate recipient and requires teammate-side model processing
- **THEN** the runtime SHALL route that message into the teammate-side delivery path backed by the shared teammate execution substrate
- **AND** SHALL preserve the recipient teammate's persistent identity while doing so

### Requirement: Public team messaging SHALL remain intra-team in v1
The runtime SHALL treat public team sends as messages scoped to the caller's active team, and SHALL reject cross-team recipient resolution in the first iteration.

#### Scenario: teammate name resolves inside the caller's active team
- **WHEN** a caller issues a public team send addressed to a teammate name
- **THEN** the runtime SHALL resolve that name only against the active team bound to the caller
- **AND** SHALL NOT search unrelated teams for a matching teammate identity

#### Scenario: cross-team delivery is rejected
- **WHEN** a routed public team message would require delivery to a leader or teammate outside the caller's active team
- **THEN** the runtime SHALL reject that delivery attempt under the team message-bus contract
- **AND** SHALL NOT silently bridge the message across team boundaries in v1
