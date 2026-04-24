## ADDED Requirements

### Requirement: Built-in runtime pack SHALL expose a typed `team_respond` tool for workflow resolution
The runtime SHALL bundle a `team_respond` tool that resolves pending team control workflows by `workflow_id` and typed response action, and SHALL derive authority from the caller's runtime team role rather than from raw control-message composition.

#### Scenario: leader resolves a pending permission workflow
- **WHEN** a leader invokes `team_respond` for a pending permission workflow with an allowed action such as `approve` or `reject`
- **THEN** the runtime SHALL record that workflow response through the runtime-owned workflow service
- **AND** SHALL return a structured tool result describing the updated workflow status and workflow identity

#### Scenario: teammate acknowledges or completes shutdown
- **WHEN** a targeted teammate invokes `team_respond` for its pending shutdown workflow with an allowed action such as `acknowledge` or `complete`
- **THEN** the runtime SHALL accept that response only if that teammate is the authorized responder for the current shutdown workflow state
- **AND** SHALL preserve the same `workflow_id` across the updated shutdown lifecycle

#### Scenario: invalid workflow response is rejected
- **WHEN** a caller invokes `team_respond` for an unknown, unauthorized, or already terminal workflow
- **THEN** the runtime SHALL reject that tool call with a structured workflow error
- **AND** SHALL leave the existing workflow state unchanged
