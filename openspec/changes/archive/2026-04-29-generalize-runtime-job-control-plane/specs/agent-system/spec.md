## ADDED Requirements

### Requirement: Background agent execution SHALL submit through the shared job control plane
runtime SHALL route background agent execution through the shared job control plane while preserving agent-specific child-run sidecar semantics.

#### Scenario: runtime starts a background child agent
- **WHEN** runtime dispatches an agent execution whose resolved spawn mode is `background`
- **THEN** runtime SHALL create or submit a shared job for that execution through the shared job control plane
- **AND** SHALL preserve the agent run's `run_id`, parent linkage, and agent-specific metadata in the agent sidecar path rather than flattening them into the generic job schema

#### Scenario: background child agent reaches a terminal state
- **WHEN** a background child agent finishes with `completed`, `failed`, `denied`, or `stopped`
- **THEN** runtime SHALL update the corresponding shared job record to the matching terminal lifecycle outcome
- **AND** SHALL continue to emit or preserve the corresponding `AgentRunRecord` and `CHILD_RUN` observability contract

