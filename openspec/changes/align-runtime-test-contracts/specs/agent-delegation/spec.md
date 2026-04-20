## MODIFIED Requirements

### Requirement: Agent tool returns structured child run identity
The `agent` tool SHALL return structured child run identity and terminal execution information so callers can observe delegated work deterministically, and its `terminal_metadata` surface SHALL stay aligned with the child run record instead of collapsing to a minimal summary.

#### Scenario: synchronous child returns run identity
- **WHEN** the `agent` tool launches a synchronous child execution
- **THEN** the tool result SHALL include at least `run_id`, `turn_id`, `agent`, `status`, and `terminal_metadata`
- **AND** `terminal_metadata` SHALL preserve the child's stable terminal fields together with additive runtime metadata emitted for that child run
- **AND** it SHALL expose any effective model or route hints that shaped that execution

#### Scenario: background child returns task and run identity
- **WHEN** the `agent` tool launches a background child execution
- **THEN** the tool result SHALL include both `task_id` and `run_id`
- **AND** it SHALL identify the child as background execution rather than reporting only a generic success payload
