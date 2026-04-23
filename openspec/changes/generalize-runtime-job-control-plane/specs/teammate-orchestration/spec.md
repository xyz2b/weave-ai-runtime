## ADDED Requirements

### Requirement: Teammate execution projections SHALL integrate with the shared job control plane
runtime SHALL project active teammate executions into the shared job control plane while preserving teammate identity, mailbox state, and permission-wait linkage as higher-level orchestration state.

#### Scenario: teammate claims a mailbox work item
- **WHEN** a teammate transitions from idle to active by claiming a mailbox work item that results in execution
- **THEN** runtime SHALL create or update a shared job record representing that active execution projection
- **AND** SHALL keep teammate identity and mailbox claim state authoritative outside the generic job record

#### Scenario: teammate lifecycle updates an active execution projection
- **WHEN** a teammate execution enters running, waiting-permission, completed, failed, or stopped outcomes
- **THEN** runtime SHALL update the corresponding shared job record to reflect the execution-facing lifecycle state
- **AND** SHALL continue to derive teammate notifications, mailbox recovery, and teammate identity from teammate-owned orchestration state rather than from job identity alone
