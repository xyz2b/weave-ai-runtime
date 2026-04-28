## ADDED Requirements

### Requirement: Runtime main loop is exposed as an async-generator event stream
The runtime SHALL expose its main loop through an async-generator-driven event stream at both session and turn scope, and any aggregating helper SHALL be derived from that same event stream contract rather than bypassing it.

#### Scenario: Host consumes turn-level main loop events
- **WHEN** a caller executes a turn through the canonical streaming interface
- **THEN** the runtime SHALL emit ordered main-loop events such as request start, stream progress, finalized messages, and terminal completion through an async generator

#### Scenario: Aggregate helper reuses the same main loop
- **WHEN** a caller uses a non-streaming helper that returns aggregated turn or session results
- **THEN** the runtime SHALL derive that aggregated result from the same async-generator main-loop contract rather than introducing a separate execution path

### Requirement: Runtime main loop uses explicit phase and transition semantics
The runtime SHALL execute each turn through an explicit main-loop contract that distinguishes context preparation, request emission, model streaming, tool replay, stop handling, recovery, and terminal completion.

#### Scenario: Tool replay continues the same turn
- **WHEN** an assistant attempt emits executable tool uses
- **THEN** the runtime SHALL continue the same turn through tool replay and the next model continuation rather than re-entering through a new session command

#### Scenario: Blocked completion exposes a transition reason
- **WHEN** stop handling blocks further continuation for the current turn
- **THEN** the runtime SHALL surface a blocked transition reason before projecting the session into a waiting state

### Requirement: Runtime defines a formal turn state machine
The runtime SHALL define a named turn-level state machine with loop-carried state, legal phase transitions, structured recovery actions, and explicit terminal reasons rather than relying on implicit local variables or transcript inference.

#### Scenario: Recovery re-enters only through allowed states
- **WHEN** prompt-too-long, reactive compaction, or output-limit recovery requires another attempt
- **THEN** the runtime SHALL re-enter the turn only through an explicit rebuild or retry state such as request rebuild or request emission, instead of ad-hoc recursion or direct provider reentry

#### Scenario: Continuation reason is observable
- **WHEN** the turn advances to another iteration after tools, stop hooks, or budget policy
- **THEN** the runtime SHALL record an explicit continuation reason and associated recovery action in turn-state or host-visible metadata

### Requirement: Turn-final terminal and attempt-final outcomes are distinct contracts
The runtime SHALL distinguish provider-attempt completion from turn completion, and the host-facing terminal event SHALL be reserved for the unique final outcome of the turn.

#### Scenario: Tool continuation does not terminate the turn
- **WHEN** a provider attempt ends with tool use or another continuation-producing outcome
- **THEN** the runtime SHALL record that attempt outcome without emitting the final turn terminal, and SHALL continue through tool replay or recovery for the same turn

#### Scenario: Every turn emits exactly one final terminal
- **WHEN** a turn exits because it completed, hit `max_turns`, was interrupted, was blocked, or failed
- **THEN** the runtime SHALL emit exactly one turn-final terminal reason for that turn and SHALL emit no later turn events after that final terminal

#### Scenario: `engine.py` does not use `TERMINAL(tool_use)` for continuation
- **WHEN** [engine.py](/Users/xyzjiao/AIProject/AIRUNTIME/src/runtime/turn_engine/engine.py) handles an assistant attempt that stops because the model emitted tool use
- **THEN** it SHALL surface that as an attempt outcome or equivalent non-terminal signal, and SHALL NOT emit the host-facing final `TERMINAL` event until the turn actually finishes

### Requirement: Attempt-finished payload is explicit and stable
The runtime SHALL define a stable attempt-level outcome contract for each completed provider request, separate from the turn-final terminal contract.

#### Scenario: Attempt outcome carries required fields
- **WHEN** a provider request finishes within a still-active turn
- **THEN** the runtime SHALL expose an attempt outcome that includes at least iteration, request id, attempt stop reason, usage, error, abort reason, and whether tool calls were produced

#### Scenario: Turn aggregates reuse attempt payload
- **WHEN** a caller uses a non-streaming aggregate such as `run_turn()`
- **THEN** the runtime SHALL derive its per-attempt records from the same explicit attempt-level outcome contract rather than reconstructing them from the final turn terminal

### Requirement: Runtime owns turn-scoped orchestration
The runtime SHALL own turn-scoped orchestration of context assembly, tool coordination, memory and hook sidecars, budget policy, recovery decisions, and state transitions rather than delegating those decisions to provider adapters, hosts, or individual tools.

#### Scenario: Provider stop reason requires recovery
- **WHEN** a provider emits a stop reason or terminal condition that requires continuation, retry, or halting
- **THEN** the runtime SHALL translate that provider outcome into a runtime recovery action through its own main-loop policy

#### Scenario: Multiple control-plane concerns shape the next continuation
- **WHEN** context assembly, tool replay, and memory sidecars all affect the next provider request
- **THEN** the runtime SHALL coordinate those concerns through the same turn-state and transition contract rather than requiring the host or provider layer to reconcile them

### Requirement: Pre-turn sidecars are supervised and deterministic
The runtime SHALL support pre-turn sidecar tasks for control-plane preparation, with deterministic join, cancellation, and restart semantics before provider request emission.

#### Scenario: Sidecars join before provider request
- **WHEN** a turn starts with relevant memory retrieval or hook-context collection enabled
- **THEN** the runtime SHALL allow those sidecars to run before provider request emission and SHALL join them at a defined preparation boundary before the request is emitted

#### Scenario: Invalidated sidecars are restarted
- **WHEN** compaction or recovery changes request-shaping inputs that a sidecar depended on
- **THEN** the runtime SHALL cancel, ignore, or restart stale sidecar work before emitting the next provider request

### Requirement: Compaction and recovery are first-class main-loop actions
The runtime SHALL treat compaction and recovery as explicit main-loop actions rather than scattered helper logic or provider-specific terminal handling.

#### Scenario: Context pressure triggers pre-request compaction
- **WHEN** context pressure or active compaction policy requires request shaping before a provider call
- **THEN** the runtime SHALL apply compaction through the main-loop preparation phase and SHALL preserve structured continuation metadata for the following phases

#### Scenario: Budget or provider stop reason triggers recovery
- **WHEN** provider stop reasons or runtime budget policy indicate that the current attempt cannot safely finish as-is
- **THEN** the runtime SHALL select a structured recovery action such as halt, retry, or compact-and-retry through the same main-loop transition contract

### Requirement: Stop phase yields structured post-turn effects
The runtime SHALL execute a stop phase that can produce structured post-turn effects for hooks, diagnostics, persistence triggers, and session integration before the turn is considered terminal.

#### Scenario: Stop phase runs before terminal completion
- **WHEN** an assistant attempt completes without further tool use
- **THEN** the runtime SHALL execute the stop phase before committing final terminal completion for that turn

#### Scenario: Session integration consumes explicit post-turn effects
- **WHEN** session-scoped persistence or background extraction depends on the turn outcome
- **THEN** the runtime SHALL expose those needs through structured post-turn effects or equivalent turn-outcome data rather than requiring session logic to infer them only from transcript mutations

### Requirement: Turn terminal reasons project deterministically to session state
The runtime SHALL define explicit turn terminal reasons and a deterministic projection from those reasons to the outer session state machine.

#### Scenario: Blocking turn projects to waiting session
- **WHEN** the turn ends with a blocking terminal reason such as stop-hook prevention or another continuation-limiting guard
- **THEN** the session controller SHALL project the session to `WAITING` and preserve the continuation context required to resume later

#### Scenario: Interrupted turn projects to interrupted session
- **WHEN** the turn ends because streaming or tool execution was aborted
- **THEN** the session controller SHALL project the session to `INTERRUPTED` rather than reporting a normal ready/completed state

#### Scenario: Non-blocking terminal returns session to ready
- **WHEN** the turn ends with a surfaced terminal such as completed, max-turn exhaustion, prompt-too-long, or model error that does not require waiting
- **THEN** the session controller SHALL return the session to `READY` after emitting terminal diagnostics, unless the controller itself has entered a stronger fault state such as `FAILED`

### Requirement: Failure-class terminal reasons take precedence over blocking projections
The runtime SHALL preserve failure-class turn terminal reasons ahead of stop-hook or waiting projections, and SHALL NOT rewrite provider/model failures into blocking/waiting outcomes.

#### Scenario: Model error is not rewritten to blocked
- **WHEN** a provider attempt ends in model error or abort and later stop handling also proposes blocking or waiting
- **THEN** the runtime SHALL preserve the failure-class terminal reason and SHALL NOT emit a final `blocked` or waiting-class terminal for that turn

#### Scenario: Blocking applies only to non-failure attempts
- **WHEN** stop hooks or policy gates request a blocking continuation outcome
- **THEN** the runtime SHALL apply that blocking projection only if the underlying attempt did not already terminate in a failure-class reason such as model error, prompt-too-long, image error, or abort

### Requirement: Status projection uses explicit terminal reasons rather than convenience booleans
The runtime SHALL project session state, child-run status, and similar outer statuses from explicit terminal reasons and terminal metadata, and SHALL NOT classify outcomes only from a derived boolean such as `completed`.

#### Scenario: Child run error is not mislabeled as max turns
- **WHEN** a child run ends with a terminal reason such as model error, interruption, or blocked continuation
- **THEN** the runtime SHALL preserve that explicit terminal reason in child-run status projection instead of collapsing every non-completed run into `max_turns`

#### Scenario: Derived completed flag does not override terminal reason
- **WHEN** the runtime exposes a convenience field such as `completed: bool`
- **THEN** that field SHALL be derived from the explicit terminal reason and SHALL NOT be used as the authoritative input for session or child-run status projection

#### Scenario: `agent_execution_service.py:202` projects child-run state from terminal reason
- **WHEN** [agent_execution_service.py](/Users/xyzjiao/AIProject/AIRUNTIME/src/runtime/agent_execution_service.py#L202) classifies the result of `run_turn()`
- **THEN** it SHALL map child-run status from the explicit turn terminal reason, and SHALL NOT infer `MAX_TURNS` only because `completed` is `false`

### Requirement: TurnResult keeps attempt-level and turn-level semantics separate
The runtime SHALL define `TurnResult` so that per-attempt outcomes and the turn-final outcome cannot be confused.

#### Scenario: TurnResult stop reason is turn-final only
- **WHEN** `run_turn()` returns a `TurnResult`
- **THEN** `TurnResult.stop_reason` SHALL represent only the explicit turn-final terminal reason and SHALL NOT contain an intermediate attempt reason such as `tool_use`

#### Scenario: TurnResult attempts remain attempt-scoped
- **WHEN** `run_turn()` returns multiple attempt records
- **THEN** `TurnResult.attempts[]` SHALL represent attempt-level outcomes only, while `completed` SHALL remain a derived convenience flag from the turn-final terminal reason

### Requirement: Compatibility migration away from legacy terminal semantics is explicit
The runtime SHALL define and execute a compatibility migration for existing consumers that currently treat host-facing `TERMINAL` as an attempt-level signal.

#### Scenario: Legacy terminal consumers are redirected
- **WHEN** an existing consumer depends on `TERMINAL(stop_reason=tool_use)` or similar legacy attempt-final semantics
- **THEN** the runtime SHALL provide a documented migration path to `ATTEMPT_FINISHED` or equivalent attempt metadata and SHALL reserve host-facing `TERMINAL` for turn-final use only

#### Scenario: Transitional metadata does not become authoritative
- **WHEN** compatibility shims temporarily mirror old fields during migration
- **THEN** those legacy fields SHALL remain non-authoritative and SHALL NOT override the new explicit attempt-level and turn-final contracts
