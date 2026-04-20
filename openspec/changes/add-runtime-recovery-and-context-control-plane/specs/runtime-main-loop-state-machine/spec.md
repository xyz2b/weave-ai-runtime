## MODIFIED Requirements

### Requirement: Runtime main loop uses explicit phase and transition semantics
The runtime SHALL execute each turn through an explicit main-loop contract that distinguishes context preparation, request emission, model streaming, tool replay, stop handling, recovery, and terminal completion, and SHALL route request-shaping work in `COMPACT_OR_REBUILD` through a context control plane and retry / terminal selection in `RECOVERY_DECISION` through a recovery policy rather than embedding those concerns as ad-hoc branch logic.

#### Scenario: Tool replay continues the same turn
- **WHEN** an assistant attempt emits executable tool uses
- **THEN** the runtime SHALL continue the same turn through tool replay and the next model continuation rather than re-entering through a new session command

#### Scenario: Context preparation delegates to context control plane
- **WHEN** the main loop enters `COMPACT_OR_REBUILD` for a new attempt
- **THEN** the runtime SHALL obtain the next request-shaping context from the context control plane rather than building the active request view only from transcript state and inline helper branches

#### Scenario: Recovery decision delegates to recovery policy
- **WHEN** the main loop enters `RECOVERY_DECISION` after an attempt, tool replay, or stop phase
- **THEN** the runtime SHALL obtain the next recovery action from the recovery policy rather than choosing retry or halt only through local branch logic

### Requirement: Pre-turn sidecars are supervised and deterministic
The runtime SHALL support pre-turn sidecar tasks for control-plane preparation, with deterministic join, cancellation, and restart semantics before provider request emission, and SHALL bind sidecar validity to the prepared context generation used for request shaping.

#### Scenario: Sidecars join before provider request
- **WHEN** a turn starts with relevant memory retrieval or hook-context collection enabled
- **THEN** the runtime SHALL allow those sidecars to run before provider request emission and SHALL join them at a defined preparation boundary before the request is emitted

#### Scenario: Invalidated sidecars are restarted
- **WHEN** context preparation changes the active context generation that a sidecar depended on
- **THEN** the runtime SHALL cancel, ignore, or restart stale sidecar work before emitting the next provider request

### Requirement: Compaction and recovery are first-class main-loop actions
The runtime SHALL treat hook-driven tool-result budget decisions, context projection, material compaction, and structured recovery selection as explicit main-loop actions rather than scattered helper logic or provider-specific terminal handling.

#### Scenario: Context preparation can reduce context without direct transcript mutation
- **WHEN** request shaping requires context reduction that does not require transcript-changing compaction
- **THEN** the runtime SHALL be able to apply that reduction through the context control plane before the provider call without treating it as an implicit transcript rewrite

#### Scenario: Budget hook or provider stop reason triggers structured recovery action
- **WHEN** provider stop reasons, output limits, or the configured budget hook / budget-policy result indicate that the current attempt cannot safely finish as-is
- **THEN** the runtime SHALL select a structured recovery action such as halt, continue, rebuild, compact-and-retry, or retry-with-override through the same main-loop transition contract

### Requirement: Stop phase yields structured post-turn effects
The runtime SHALL execute a stop phase that can produce structured post-turn effects and structured stop outcomes for hooks, diagnostics, continuation messages, request overrides, persistence triggers, and session integration before the turn is considered terminal.

#### Scenario: Stop phase can request same-turn continuation
- **WHEN** stop handling determines that the current turn should continue with additional runtime-provided messages or overrides
- **THEN** the runtime SHALL surface that result as a structured stop outcome that is consumed by recovery logic instead of finalizing the turn immediately

#### Scenario: Session integration consumes explicit post-turn effects
- **WHEN** session-scoped persistence or background extraction depends on the turn outcome
- **THEN** the runtime SHALL expose those needs through structured post-turn effects or equivalent turn-outcome data rather than requiring session logic to infer them only from transcript mutations

### Requirement: Control-plane observability metadata is canonical
The runtime SHALL expose a canonical minimum metadata schema for context preparation, recovery, and hook outcomes so hosts and diagnostics can observe the effective control-plane behavior without reconstructing it from transcript diffs alone.

#### Scenario: Context preparation emits canonical metadata
- **WHEN** a turn completes context preparation for an attempt
- **THEN** host-visible metadata SHALL include the prepared context generation together with effect summaries such as projection, compaction, spillover, or budget-policy indicators

#### Scenario: Recovery and hook outcomes emit canonical metadata
- **WHEN** the runtime resolves a recovery action or stop outcome
- **THEN** host-visible metadata SHALL include the selected recovery action, reason, relevant failure or terminal class, matched hook owners, and effective override-source information
