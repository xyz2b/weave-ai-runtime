## MODIFIED Requirements

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
