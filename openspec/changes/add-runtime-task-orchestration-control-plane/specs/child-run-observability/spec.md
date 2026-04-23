## ADDED Requirements

### Requirement: Terminal child lifecycle can drive structured continuation without replacing typed observability
The runtime SHALL be able to derive a structured parent-session continuation signal from a terminal child run while preserving typed child-run records and lifecycle events as the source of truth.

#### Scenario: waiting parent session receives structured child completion signal
- **WHEN** a child run linked to a waiting parent session reaches a terminal state and continuation policy allows wake-up
- **THEN** the runtime SHALL be able to submit a structured continuation input for the parent session that includes the child run identity and terminal status
- **AND** SHALL NOT require callers to scrape custom transcript protocols to recover that child completion

#### Scenario: typed child-run observability remains authoritative
- **WHEN** a terminal child run also produces a continuation signal for its parent session
- **THEN** the runtime SHALL still persist the same terminal child run record and emit the same typed child-run lifecycle event for host-visible observability
- **AND** SHALL NOT replace typed child-run observability with transcript-only continuation text

#### Scenario: active parent turn does not receive duplicate continuation delivery
- **WHEN** the parent turn is still active and can already observe the child run through turn-local child-run events
- **THEN** the runtime SHALL avoid enqueueing a duplicate continuation signal for that same terminal child state
- **AND** SHALL preserve a single coherent child-run outcome across turn-local and session-level orchestration paths
