## ADDED Requirements

### Requirement: Leader-actionable team control workflows SHALL enter the leader session as synthesized ingress requests
The runtime SHALL translate leader-actionable team control workflows into runtime-generated ingress inputs that summarize the requested action and expose the stable `workflow_id`, while keeping raw control transport envelopes private by default.

#### Scenario: permission workflow becomes a leader-visible generated input
- **WHEN** a teammate creates a permission workflow that requires leader action
- **THEN** the runtime SHALL submit a generated ingress input that includes a readable workflow summary together with the `workflow_id`
- **AND** SHALL preserve the raw structured control payload as private routing metadata rather than appending the raw envelope to transcript-visible session history

#### Scenario: non-actionable control update stays private
- **WHEN** a team control message only acknowledges delivery, reports terminal workflow state, or otherwise does not require new leader action
- **THEN** the runtime SHALL resolve that update through private or replay-only ingress outcomes
- **AND** SHALL NOT create a new model-visible turn solely because that non-actionable control update arrived

### Requirement: Workflow ingress SHALL expose typed response metadata for runtime-owned tools
The runtime SHALL attach workflow kind, requester identity, allowed response actions, and correlation metadata to leader ingress private state so runtime-owned workflow-response tools can validate follow-up decisions without parsing transcript text.

#### Scenario: leader receives allowed actions with a workflow request
- **WHEN** leader ingress admits a team control workflow request that expects a leader response
- **THEN** the associated ingress metadata SHALL include the workflow kind, `workflow_id`, requester identity, and the allowed response actions for the current workflow state
- **AND** SHALL keep that metadata available to the runtime-owned tool execution path for the corresponding leader turn

### Requirement: Lifecycle-critical team control workflows SHALL be prioritized over ordinary teammate chatter at ingress
The runtime SHALL prioritize leader-actionable team control workflows that affect lifecycle safety, such as shutdown requests, ahead of ordinary teammate chatter when choosing which actionable ingress request to surface next for the leader session.

#### Scenario: shutdown workflow is surfaced before lower-priority teammate chatter
- **WHEN** the leader session has both a pending leader-actionable shutdown workflow and ordinary teammate chatter eligible to become actionable ingress
- **THEN** the runtime SHALL surface the shutdown workflow request first
- **AND** SHALL NOT delay that lifecycle-critical control request solely because lower-priority teammate chatter arrived earlier or in the same delivery window
