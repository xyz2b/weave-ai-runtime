## MODIFIED Requirements

### Requirement: Runtime provides a unified compaction manager
The runtime SHALL provide a unified compaction manager that is invoked through a turn-preparation contract before provider requests when runtime context pressure or compaction policy requires it.

#### Scenario: Preparing a turn under context pressure
- **WHEN** the runtime prepares a turn and the active compaction policy determines that context reduction is required
- **THEN** the runtime SHALL invoke the shared compaction manager through its turn-preparation contract rather than relying on scattered per-request compression helpers

### Requirement: Compaction integrates with resume-safe session behavior
The runtime SHALL preserve resume-safe semantics when compaction modifies session context, and session-level compaction markers SHALL only be persisted when a material compaction effect has actually been recorded.

#### Scenario: Session resumes after prior compaction
- **WHEN** a session resumes from transcript state after one or more compaction events
- **THEN** the runtime SHALL use the compaction manager's structured outputs and persisted compaction markers to preserve valid continuation behavior rather than treating the compacted state as an untracked prompt mutation

#### Scenario: Transcript rewrite without compaction effect does not stamp compaction metadata
- **WHEN** the runtime rewrites transcript state without a recorded compaction effect
- **THEN** it SHALL NOT update session metadata such as `last_compaction_at` as though a material compaction had occurred
