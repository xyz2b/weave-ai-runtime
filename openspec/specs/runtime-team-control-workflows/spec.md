# runtime-team-control-workflows Specification

## Purpose
TBD - created by archiving change add-runtime-team-control-workflow-protocols. Update Purpose after archive.
## Requirements
### Requirement: Team control workflows SHALL be persisted as authoritative correlated records
The runtime SHALL persist each negotiated team control interaction as a runtime-owned workflow record keyed by a stable `workflow_id`, and SHALL treat that record as the authoritative source of pending and terminal workflow state rather than relying on transport delivery state alone.

#### Scenario: workflow record exists before request delivery
- **WHEN** the runtime creates a permission or shutdown workflow request
- **THEN** it SHALL persist a workflow record containing at least the workflow kind, team identity, requester identity, expected responder identity, current status, request payload, and deadline metadata before routing the corresponding control delivery
- **AND** SHALL reuse the same `workflow_id` as the correlation identity for any emitted team control messages, ingress metadata, or host-facing workflow events

#### Scenario: workflow state survives runtime restart
- **WHEN** the runtime restarts while a team control workflow remains non-terminal
- **THEN** it SHALL reload that persisted workflow record and reconstruct any pending wait, timeout, or recovery tracking needed for the workflow
- **AND** SHALL NOT require the original message-bus delivery state to be the only source of truth for whether the workflow is still pending

### Requirement: Team control workflows SHALL enforce typed response authority
The runtime SHALL require every workflow response to reference an existing non-terminal `workflow_id`, and SHALL validate that the responder identity and response action are allowed for the current workflow kind and workflow state before mutating workflow status.

#### Scenario: leader resolves a pending permission workflow
- **WHEN** the leader submits an allowed response such as `approve` or `reject` for a pending permission workflow
- **THEN** the runtime SHALL record that response against the matching workflow record
- **AND** SHALL reject any response from an unauthorized teammate or unrelated caller for that same pending permission workflow

#### Scenario: duplicate or stale response is rejected
- **WHEN** a caller submits a response for an unknown, timed-out, or already terminal workflow
- **THEN** the runtime SHALL reject that response without reopening or mutating the terminal workflow state
- **AND** SHALL preserve the previously recorded terminal outcome unchanged

### Requirement: Team control workflows SHALL define timeout and forced-closure outcomes
The runtime SHALL assign timeout policy to pending team control workflows and SHALL produce explicit terminal timeout or forced-closure outcomes when those deadlines expire without a valid completion path.

#### Scenario: permission workflow times out
- **WHEN** a pending permission workflow reaches its deadline before an authorized response is recorded
- **THEN** the runtime SHALL mark that workflow with a terminal timeout outcome
- **AND** SHALL resume the blocked teammate with a denied or equivalent non-approved permission result tied to the same `workflow_id`

#### Scenario: shutdown workflow times out
- **WHEN** a pending shutdown workflow reaches its deadline before graceful completion finishes
- **THEN** the runtime SHALL record a timeout or forced-close terminal outcome for that workflow
- **AND** SHALL run the defined forced cleanup policy before removing the teammate from runtime-owned state

