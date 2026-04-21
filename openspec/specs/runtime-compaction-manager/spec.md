# runtime-compaction-manager Specification

## Purpose
TBD - created by archiving change add-long-context-compaction-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Runtime provides a unified compaction manager
The runtime SHALL provide a unified compaction manager that is invoked through a turn-preparation contract before provider requests when runtime context pressure or compaction policy requires it.

#### Scenario: Preparing a turn under context pressure
- **WHEN** the runtime prepares a turn and the active compaction policy determines that context reduction is required
- **THEN** the runtime SHALL invoke the shared compaction manager through its turn-preparation contract rather than relying on scattered per-request compression helpers

### Requirement: Compaction results carry continuation semantics
The runtime SHALL represent compaction outcomes as structured results that can include compacted messages, summaries, boundary metadata, and continuation semantics needed for safe turn execution.

#### Scenario: Compaction changes the turn context
- **WHEN** a compaction step rewrites or summarizes the active turn context
- **THEN** the compaction manager SHALL return a structured result that the runtime can use to continue turn execution with explicit continuation semantics

### Requirement: Compaction manager supports ordered strategies
The runtime SHALL allow the compaction manager to orchestrate ordered strategies so that lightweight and heavyweight compaction behaviors share one runtime contract.

#### Scenario: Runtime applies multiple compaction stages
- **WHEN** the runtime is configured with more than one compaction strategy
- **THEN** the compaction manager SHALL apply those strategies through an ordered orchestration contract instead of requiring each strategy to wire itself into turn preparation separately

### Requirement: Compaction integrates with resume-safe session behavior
The runtime SHALL preserve resume-safe semantics when compaction modifies session context, and session-level compaction markers SHALL only be persisted when a material compaction effect has actually been recorded.

#### Scenario: Session resumes after prior compaction
- **WHEN** a session resumes from transcript state after one or more compaction events
- **THEN** the runtime SHALL use the compaction manager's structured outputs and persisted compaction markers to preserve valid continuation behavior rather than treating the compacted state as an untracked prompt mutation

#### Scenario: Transcript rewrite without compaction effect does not stamp compaction metadata
- **WHEN** the runtime rewrites transcript state without a recorded compaction effect
- **THEN** it SHALL NOT update session metadata such as `last_compaction_at` as though a material compaction had occurred

