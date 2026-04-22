## ADDED Requirements

### Requirement: Runtime exposes stable hook points at main-loop decision boundaries
The runtime SHALL expose named public hook points for context assembly, request shaping, post-response handling, and recovery decision as part of the main-loop contract rather than leaving those integration points hidden inside helper-specific implementation details.

#### Scenario: Context-assembly hook runs before provider request
- **WHEN** the main loop prepares the next active request context for an attempt
- **THEN** the runtime SHALL provide a public hook point before and/or after context assembly that executes before provider request emission

#### Scenario: Post-response hook runs before continuation selection
- **WHEN** a provider response has been materialized but the runtime has not yet committed to tool replay, stop handling, or retry selection
- **THEN** the runtime SHALL provide a public hook point where integrations can observe or shape that response before continuation selection is finalized

#### Scenario: Recovery hook runs before transition commit
- **WHEN** the main loop is about to commit a recovery action such as halt, retry, or rebuild
- **THEN** the runtime SHALL provide a public hook point for recovery decision handling before the transition is finalized and emitted

### Requirement: Hook-driven decisions are consumed through canonical main-loop transitions
The runtime SHALL consume request overrides, continuation requests, blocking outcomes, and other main-loop-affecting hook results through the same state-machine and recovery contract used for native runtime decisions, and SHALL NOT allow public hook integrations to bypass turn-state accounting or terminal precedence.

#### Scenario: Pre-model hook changes request shape through canonical path
- **WHEN** a `PreModelRequest` hook returns a request override for the current attempt
- **THEN** the runtime SHALL apply that override through the canonical request-shaping path for that attempt rather than mutating provider adapter state out of band

#### Scenario: Recovery hook request preserves canonical reason
- **WHEN** a recovery-related public hook requests retry, halt, or rebuild
- **THEN** the runtime SHALL resolve that request through the canonical recovery transition contract and SHALL preserve the selected reason in host-visible metadata

### Requirement: Public hook phases map to stable main-loop layers and ordering
The runtime SHALL assign every public hook phase to a stable main-loop layer and SHALL preserve the relative ordering between those layers as part of the public integration contract.

#### Scenario: Context-preparation phases complete before request emission
- **WHEN** a turn advances through context preparation toward request emission
- **THEN** any public `PreCompact`, `PostCompact`, `UserPromptSubmit`, `PreContextAssemble`, and `PostContextAssemble` hook points SHALL occur before `PreModelRequest`
- **AND** `PreModelRequest` SHALL occur before the provider request is committed

#### Scenario: Tool and stop phases occur after response materialization
- **WHEN** a provider response has been materialized for the current attempt
- **THEN** `PostModelResponse` SHALL occur before the runtime commits to either tool replay or stop-phase handling
- **AND** any `PreToolUse` / `PostToolUse` / `PostToolUseFailure` or `Stop` hook handling SHALL occur before the corresponding `RecoveryDecision`

#### Scenario: Cross-cutting phases declare non-bypass integration points
- **WHEN** the runtime exposes public cross-cutting phases such as `Notification`, `Elicitation`, `ElicitationResult`, or `SubagentStop`
- **THEN** the runtime SHALL define the canonical subsystem boundary where those phases fire and where their supported effects are consumed
- **AND** those phases SHALL NOT bypass turn-state accounting merely because they are not on the linear request path

### Requirement: Public hook effects have canonical consumption points in the runtime loop
The runtime SHALL define, for each public effect field allowed on a public phase, the canonical point in the runtime loop or sibling subsystem where that field is consumed.

#### Scenario: Additional context is consumed before prompt envelope freeze
- **WHEN** a public phase such as `UserPromptSubmit`, `PreContextAssemble`, or `PostContextAssemble` returns `additional_context`
- **THEN** the runtime SHALL consume that context before the request-facing prompt/context envelope is finalized for the relevant attempt

#### Scenario: Updated tool input is consumed only on the pre-tool boundary
- **WHEN** a `PreToolUse` hook returns `updated_input`
- **THEN** the runtime SHALL apply that update before the normalized tool executor invocation
- **AND** the runtime SHALL NOT treat `updated_input` as a portable effect field on later tool or recovery phases

#### Scenario: Stop and recovery effects flow through the recovery contract
- **WHEN** a `Stop`, `PostModelResponse`, or `RecoveryDecision` hook produces `request_override`, `injected_messages`, `continue_execution`, or other transition-shaping results
- **THEN** the runtime SHALL consume those results through the canonical recovery/request-shaping path before selecting the next turn phase or terminal outcome

#### Scenario: Elicitation result is consumed before host fallback
- **WHEN** an `Elicitation` hook produces `elicitation_result`
- **THEN** the runtime SHALL satisfy the active elicitation request from that hook result before invoking any fallback host-side elicitation handler
