## ADDED Requirements

### Requirement: Teammate permission waits SHALL be gated by correlated team control workflows
The runtime SHALL convert teammate-originated privileged steps into correlated permission workflows, SHALL keep the teammate in `waiting_permission`, and SHALL postpone any host permission request until an authorized workflow responder approves continuation.

#### Scenario: leader rejects a permission workflow
- **WHEN** a leader resolves a pending teammate permission workflow with `reject`
- **THEN** the runtime SHALL resume the waiting teammate with a denied permission outcome
- **AND** SHALL NOT call the host permission bridge for that privileged step

#### Scenario: leader approval gates later host permission resolution
- **WHEN** a leader resolves a pending teammate permission workflow with `approve`
- **THEN** the runtime SHALL continue to any required host-mediated permission request only after that workflow decision has been recorded
- **AND** SHALL preserve the same workflow correlation through the final permission outcome delivered back to the teammate

### Requirement: Teammate stop operations SHALL use graceful shutdown workflows
The runtime SHALL implement teammate removal, explicit stop, and team deletion through correlated shutdown workflows. A targeted teammate SHALL enter `stopping`, SHALL stop claiming new work, and SHALL only reach `stopped` after graceful completion or timeout-driven forced cleanup.

#### Scenario: idle teammate stops without immediate teardown
- **WHEN** the runtime requests shutdown for a teammate that is currently idle
- **THEN** it SHALL mark that teammate `stopping`, acknowledge the shutdown workflow through the correlated workflow state, and complete cleanup without accepting new work in between
- **AND** SHALL persist the teammate's final `stopped` lifecycle state before runtime-owned member cleanup finishes

#### Scenario: team deletion waits for shutdown workflow completion
- **WHEN** a leader deletes a team that still has active teammate members
- **THEN** the runtime SHALL issue shutdown workflows to those teammates and wait for workflow completion or timeout according to the shutdown policy
- **AND** SHALL NOT immediately cancel the runners and delete teammate state before the shutdown workflows reach terminal outcomes

#### Scenario: shutdown timeout triggers forced cleanup
- **WHEN** a teammate remains in a non-terminal shutdown state past the shutdown workflow deadline
- **THEN** the runtime SHALL record the timeout or forced-close workflow outcome
- **AND** SHALL perform forced teammate cleanup only after that timeout policy has triggered
