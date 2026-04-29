## ADDED Requirements

### Requirement: Child-run continuation inputs carry summary-aware completion context

The runtime SHALL attach summary-aware child completion context to child-run continuation inputs so resumed parent sessions receive the child outcome without scraping child transcript text.

#### Scenario: Waiting session resumes from terminal child completion

- **WHEN** a waiting session is resumed from a terminal child run through runtime-owned continuation delivery
- **THEN** the admitted continuation context SHALL include child identity, terminal status, and summary
- **AND** SHALL NOT require the resumed parent turn to query child transcript text just to understand the child outcome

#### Scenario: Ready session queues summary-aware child completion for later drain

- **WHEN** a ready session receives a child completion input that is queued without immediate turn admission
- **THEN** ingress SHALL preserve the same summary-aware child completion context for that queued input
- **AND** SHALL replay that context unchanged when the queued input is later admitted
