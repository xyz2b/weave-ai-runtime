## ADDED Requirements

### Requirement: Background memory work SHALL project through the shared job control plane
runtime SHALL register background memory extraction and consolidation work in the shared job control plane while preserving memory-specific queue and synthesis semantics.

#### Scenario: runtime schedules background memory extraction
- **WHEN** runtime schedules a background memory extraction pass for a session, agent, or scope
- **THEN** it SHALL create or update a shared job record for that background memory work
- **AND** SHALL keep memory-specific batching, merge, or extraction metadata in memory-owned sidecar state rather than flattening them into the generic job schema

#### Scenario: background memory work reaches a terminal state
- **WHEN** a background memory extraction or consolidation run completes, fails, or is stopped
- **THEN** runtime SHALL update the corresponding shared job record with the resulting lifecycle state
- **AND** SHALL preserve any memory-specific output or diagnostics through the memory subsystem's own result path or sidecar linkage

