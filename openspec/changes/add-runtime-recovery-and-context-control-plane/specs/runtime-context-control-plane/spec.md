## ADDED Requirements

### Requirement: Runtime prepares an explicit active context view before each provider request
The runtime SHALL construct a structured active context view before each provider request, rather than deriving request messages only from transcript state plus ad-hoc compaction helpers.

#### Scenario: Context preparation returns request-ready view
- **WHEN** the runtime enters request preparation for a new attempt
- **THEN** it SHALL produce a structured preparation output that includes the active messages and prompt context that will shape the next provider request

### Requirement: Active context view is distinct from transcript truth
The runtime SHALL distinguish the transcript truth that represents persisted conversation history from the active context view that is actually sent to the model for the next attempt.

#### Scenario: Projection changes active view without rewriting transcript
- **WHEN** the runtime applies a non-destructive context projection to reduce request size
- **THEN** it SHALL update the active context view for the next provider request without treating that projection as a transcript rewrite

### Requirement: Context projection preserves continuation invariants
The runtime SHALL enforce hard projection invariants so that active-view reduction cannot remove or invalidate message structures required for safe continuation.

#### Scenario: Projection preserves latest user turn and system prompts
- **WHEN** the runtime reduces the active context view through a projection pass
- **THEN** it SHALL preserve the current system or developer prompt inputs and the latest user-turn input needed to make the next provider request interpretable

#### Scenario: Projection preserves tool pairing and continuation markers
- **WHEN** the runtime projects older assistant or tool payloads out of the active context view
- **THEN** it SHALL preserve valid `tool_use` / `tool_result` pairing together with compaction continuation markers, blocked or waiting resume cues, and stable attachment or artifact handles

### Requirement: Tool-result budget decisions are hook-driven within context preparation
The runtime SHALL expose a pluggable context-budget hook during context preparation and SHALL use that hook's decision to inline, summarize, or externalize tool results before the next provider request is built, rather than hardcoding business-specific budget calculation in the runtime.

#### Scenario: Registered budget hook externalizes a tool result
- **WHEN** a registered context-budget hook marks a tool result for summarization or externalization during request preparation
- **THEN** the runtime SHALL replace the replay payload for the next request with the hook-selected summarized result or stable artifact reference while preserving the full payload outside the active context view

#### Scenario: Missing budget hook falls back to pass-through behavior
- **WHEN** no context-budget hook is registered or the hook returns no decision for a tool result
- **THEN** the runtime SHALL preserve that result inline or otherwise apply the configured pass-through default rather than inventing a business-specific budget calculation internally

### Requirement: Context-budget hook receives a bounded structured request
The runtime SHALL invoke the configured context-budget hook with a structured request containing candidate-local tool-result views, prompt context, private-context view, and provider hints, and SHALL bound the hook's authority to candidate-local downgrade decisions only.

#### Scenario: Hook receives structured candidate and provider hints
- **WHEN** `ToolResultBudgetPass` prepares to evaluate tool results
- **THEN** the runtime SHALL provide the budget hook with stable candidate identifiers, tool metadata, payload access, optional size or token hints, and request-shaping hints such as provider, model, route, or reserved-output information

#### Scenario: Hook cannot reorder or rewrite transcript
- **WHEN** the budget hook returns a plan
- **THEN** the runtime SHALL apply only candidate-local `inline`, `summarize`, or `externalize` actions and SHALL NOT allow the hook to reorder replay slots or directly mutate transcript truth

### Requirement: Context-budget hook validation and fallback are deterministic
The runtime SHALL validate budget-hook plans deterministically and SHALL apply a configured fallback when the hook returns invalid decisions, times out, or raises an error.

#### Scenario: Invalid hook decisions are ignored with diagnostics
- **WHEN** the budget hook returns a decision for an unknown candidate, duplicates a candidate decision, or requests an invalid downgrade action
- **THEN** the runtime SHALL ignore only the invalid decision entries, preserve valid entries, and record diagnostics rather than inventing alternate business logic

#### Scenario: Hook error follows configured failure mode
- **WHEN** the budget hook raises, times out, or returns an unparsable plan
- **THEN** the runtime SHALL either continue with pass-through budget behavior or surface a structured preparation failure according to the configured budget-hook failure mode

### Requirement: Context preparation carries explicit generation semantics
The runtime SHALL assign an explicit context generation to each prepared active context view and SHALL use that generation to determine whether dependent sidecar work remains valid.

#### Scenario: Context rewrite invalidates stale sidecar output
- **WHEN** context preparation changes the active context view or prompt-shaping envelope after a sidecar task has started
- **THEN** the runtime SHALL treat sidecar output computed against the older context generation as stale and SHALL not apply it to the newer request

#### Scenario: Unchanged context preserves sidecar validity
- **WHEN** a new attempt reuses the same active context generation without changing request-shaping inputs
- **THEN** the runtime SHALL be allowed to reuse sidecar output computed for that generation

### Requirement: Context preparation emits structured effects for downstream phases
The runtime SHALL expose structured context-preparation effects, including projection, compaction, spillover, and sidecar-restart signals, so later phases do not need to infer them from raw message mutations.

#### Scenario: Main loop consumes structured context effects
- **WHEN** context preparation finishes for an attempt
- **THEN** the main loop SHALL be able to consume explicit preparation effects such as spillover metadata, material compaction metadata, and sidecar restart requirements without re-deriving them from transcript diffs

### Requirement: Resumable context metadata is persisted without persisting opaque active views
The runtime SHALL persist only explicit resumable context metadata needed to reconstruct the next prepared context after resume, and SHALL rebuild prepared active views from transcript truth plus that metadata instead of persisting opaque active-view snapshots.

#### Scenario: Resume rebuilds active context from truth and resumable metadata
- **WHEN** a blocked, waiting, or otherwise resumable session is loaded from persistence
- **THEN** the runtime SHALL reconstruct the next prepared context from transcript truth, compaction continuation data, and spillover artifact references rather than restoring a previously serialized active-message list verbatim

#### Scenario: Turn-local prepared state is not persisted verbatim
- **WHEN** a turn finishes without an explicit resumable continuation contract
- **THEN** the runtime SHALL discard turn-local prepared-context internals such as in-flight generation counters or transient active-message slices rather than persisting them as session state

### Requirement: Spillover artifacts have deterministic lifecycle and fallback semantics
The runtime SHALL maintain manifest-level lifecycle semantics for spillover artifacts, including retention while referenced, and SHALL apply a deterministic fallback when an artifact reference cannot be resolved.

#### Scenario: Referenced spillover artifact is retained for resume
- **WHEN** transcript or session continuation metadata still references a spillover artifact
- **THEN** the runtime SHALL retain or otherwise resolve that artifact for later replay or resume rather than garbage-collecting it opportunistically

#### Scenario: Missing artifact degrades with diagnostics instead of silent drop
- **WHEN** context preparation or replay encounters a missing spillover artifact reference
- **THEN** the runtime SHALL preserve the logical replay slot through a degraded placeholder or summary plus diagnostics rather than silently dropping that reference from continuation state

### Requirement: Control-plane configuration is resolved deterministically per turn
The runtime SHALL resolve context-control configuration such as budget hooks, failure modes, projection policy, compaction strategy chain, and retention policy through a deterministic precedence contract before the turn begins, and SHALL use that resolved snapshot consistently for the duration of the turn.

#### Scenario: Agent override outranks runtime default
- **WHEN** runtime defaults and agent-scoped configuration both provide a value for the same context-control setting
- **THEN** the runtime SHALL select the agent-scoped value according to the documented precedence contract

#### Scenario: Turn uses stable config snapshot
- **WHEN** a turn starts and the runtime resolves the control-plane configuration for that turn
- **THEN** later context-preparation passes in that turn SHALL consume the same resolved snapshot rather than mutating the full control-plane configuration mid-turn
