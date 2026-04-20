## MODIFIED Requirements

### Requirement: Runtime provides a unified compaction manager
The runtime SHALL provide a unified compaction manager that is invoked by the broader context-control pipeline when runtime context pressure or compaction policy requires transcript-changing material reduction, rather than relying on scattered per-request compression helpers.

#### Scenario: Preparing a turn under material context pressure
- **WHEN** the runtime prepares a turn and the active compaction policy determines that transcript-changing context reduction is required
- **THEN** the runtime SHALL invoke the shared compaction manager rather than relying on scattered per-request compression helpers

#### Scenario: Projection-only context reduction does not trigger material compaction
- **WHEN** the runtime can satisfy request-shaping limits through non-destructive context projection without transcript-changing reduction
- **THEN** the broader context-control pipeline SHALL be able to complete that preparation without treating it as a material compaction-manager rewrite

### Requirement: Compaction results carry continuation semantics
The runtime SHALL represent material compaction outcomes as structured results that can include compacted messages, summaries, boundary metadata, and continuation semantics needed for safe turn execution and resume-safe transcript behavior.

#### Scenario: Compaction changes the turn context
- **WHEN** a material compaction step rewrites or summarizes the active turn context
- **THEN** the compaction manager SHALL return a structured result that the runtime can use to continue turn execution with explicit continuation semantics

#### Scenario: Session resumes after prior compaction
- **WHEN** a session resumes from transcript state after one or more material compaction events
- **THEN** the runtime SHALL use the compaction manager's structured outputs to preserve valid continuation behavior rather than treating the compacted state as an untracked prompt mutation

### Requirement: Compaction manager supports ordered strategies
The runtime SHALL allow the compaction manager to orchestrate ordered material-compaction strategies so that lightweight and heavyweight transcript-changing compaction behaviors share one runtime contract within the broader context-control pipeline.

#### Scenario: Runtime applies multiple material compaction stages
- **WHEN** the runtime is configured with more than one material compaction strategy
- **THEN** the compaction manager SHALL apply those strategies through an ordered orchestration contract instead of requiring each strategy to wire itself into turn preparation separately

