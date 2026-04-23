## ADDED Requirements

### Requirement: Forked skill results reuse the child result projection contract

The runtime SHALL apply the same summary-first child result projection contract to forked skill `agent_result` payloads that it applies to direct `agent` tool child results.

#### Scenario: Forked skill returns a summary-first nested agent result

- **WHEN** a forked skill completes child execution under the default child result policy
- **THEN** the nested `agent_result` payload SHALL include stable child identity, terminal status, and summary
- **AND** SHALL NOT require nested child `messages` history in the default forked skill result payload

#### Scenario: Detailed compatibility mode still preserves summary in forked skill results

- **WHEN** runtime policy explicitly enables detailed parent-facing child projections for migration
- **THEN** a forked skill `agent_result` payload MAY include detailed child message history
- **AND** SHALL still preserve summary and stable child identity fields in that nested payload
