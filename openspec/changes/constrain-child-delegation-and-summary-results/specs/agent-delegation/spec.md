## ADDED Requirements

### Requirement: Agent tool projects child results for parent context

The built-in `agent` tool SHALL return a summary-first projection of child execution by default so parent callers can observe child outcomes without ingesting full child history.

#### Scenario: Synchronous child returns a summary-first tool result

- **WHEN** the `agent` tool launches a synchronous child execution under the default child result policy
- **THEN** the tool result SHALL include child identity, terminal status, run identity, and summary
- **AND** SHALL NOT require nested child `messages` history in the default payload

#### Scenario: Compatibility mode allows detailed child payloads

- **WHEN** runtime policy explicitly enables detailed parent-facing child projections
- **THEN** the `agent` tool SHALL include detailed child message history in addition to summary
- **AND** SHALL keep summary and stable child identity fields present in that payload
