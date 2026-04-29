# runtime-compaction-manager Specification

## Purpose
TBD - created by archiving change add-long-context-compaction-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Runtime provides a unified compaction manager
The runtime SHALL provide a unified compaction manager that is invoked through a turn-preparation contract before provider requests when runtime context pressure, route-owned context window policy, or compaction policy requires it.

#### Scenario: Preparing a turn under context pressure
- **WHEN** the runtime prepares a turn and the active compaction policy determines that context reduction is required
- **THEN** the runtime SHALL invoke the shared compaction manager through its turn-preparation contract rather than relying on scattered per-request compression helpers

#### Scenario: Preparing a turn with a known route-owned context window snapshot
- **WHEN** the runtime prepares a turn for a resolved route and final model whose context window snapshot includes known input limits and reserved output headroom
- **THEN** the runtime SHALL allow the compaction manager or equivalent request-shaping policy to derive proactive pre-request compaction triggers from that snapshot
- **AND** SHALL NOT require provider-specific context-window logic to be hardcoded directly into the main loop

#### Scenario: Context-window request shaping emits context-window-oriented metadata
- **WHEN** turn preparation applies tool-result downgrade, spillover, or equivalent request-shaping decisions because of context-window pressure
- **THEN** the runtime SHALL record the resulting policy tag, diagnostics, and effect kind using context-window-oriented metadata names or canonical aliases
- **AND** SHALL keep any temporary budget-named compatibility metadata subordinate to the canonical context-window-oriented contract

#### Scenario: Canonical context-window diagnostics and effects remain bounded
- **WHEN** context-window hook validation or execution produces diagnostics or effects during turn preparation
- **THEN** the runtime SHALL emit canonical diagnostics such as `context_window_hook_error` or `context_window_hook_unparseable`
- **AND** SHALL use a canonical effect kind such as `CONTEXT_WINDOW_DECISION`
- **AND** SHALL NOT require hosts to inspect provider-specific error strings to understand whether a context-window rewrite occurred

#### Scenario: Unknown context window snapshot degrades to reactive compaction recovery
- **WHEN** the runtime cannot resolve a known context window snapshot for the current resolved route or final model
- **THEN** it SHALL allow turn execution to proceed without proactive context-window-derived compaction
- **AND** SHALL rely on reactive context-limit recovery or equivalent fallback behavior rather than rejecting execution because context window metadata is missing

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

### Requirement: Compaction manager SHALL attach to owner layers through a canonical package-service protocol binding
The runtime SHALL attach the unified compaction manager to owner-layer and execution-layer runtime paths through the canonical compaction service-family protocol binding rather than through `RuntimeServices.compaction` as a privileged source-of-truth slot.

#### Scenario: turn preparation invokes compaction
- **WHEN** the runtime prepares a turn and needs compaction behavior
- **THEN** the runtime SHALL resolve that behavior through the canonical compaction service-family protocol binding
- **AND** SHALL treat any retained `RuntimeServices.compaction` field as a compatibility projection rather than the normative binding surface

