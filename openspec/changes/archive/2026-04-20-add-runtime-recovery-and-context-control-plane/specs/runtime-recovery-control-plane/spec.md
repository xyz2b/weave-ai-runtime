## ADDED Requirements

### Requirement: Runtime exposes a turn-scoped recovery policy
The runtime SHALL evaluate provider attempt outcomes, stop-phase outcomes, explicit recovery state, and current context preparation outputs through a turn-scoped recovery policy before deciding whether to halt, continue the same turn, rebuild the request, compact-and-retry, or retry with override.

#### Scenario: Context-limit failure selects compact-and-retry
- **WHEN** an attempt finishes with a retryable context-limit classification and the current context preparation pipeline can reduce the active context view
- **THEN** the runtime SHALL produce a `compact_and_retry` recovery decision instead of immediately finalizing the turn

#### Scenario: Non-retryable provider failure halts the turn
- **WHEN** an attempt finishes with a failure classification that is not retryable
- **THEN** the runtime SHALL produce a `halt` recovery decision and the turn SHALL surface a failure-class terminal reason

### Requirement: Recovery state is loop-carried and explicit
The runtime SHALL carry explicit recovery state across turn iterations, including retry counters, prior compaction attempts, and pending request overrides, rather than inferring recovery only from the latest attempt outcome.

#### Scenario: Output-limit retries consume explicit counter state
- **WHEN** repeated attempts in the same turn hit an output-limit classification
- **THEN** the runtime SHALL increment and consult an explicit recovery counter before deciding whether to continue, retry with override, or halt

#### Scenario: Prior reactive compaction attempt prevents recovery spiral
- **WHEN** the runtime has already attempted compact-and-retry for the active failure class in the current turn
- **THEN** the recovery policy SHALL use explicit recovery state to avoid re-entering the same compact-and-retry path indefinitely

### Requirement: Recovery action selection follows a bounded decision matrix
The runtime SHALL map failure classifications, stop outcomes, loop exhaustion, and tool-infrastructure outcomes onto a bounded recovery decision matrix instead of introducing per-branch local retry logic in the turn engine.

#### Scenario: Interrupted attempt halts without retry
- **WHEN** an attempt finishes as interrupted or aborted
- **THEN** the recovery policy SHALL select `halt` rather than re-entering compact, rebuild, or retry-with-override paths

#### Scenario: Max-turns or tool-infrastructure exhaustion does not retry
- **WHEN** the runtime exhausts max-turns or cannot continue because required tool execution infrastructure is unavailable
- **THEN** the recovery policy SHALL select `halt` and preserve the corresponding terminal-class outcome rather than attempting an additional provider request

### Requirement: Request override is a shared runtime control surface
The runtime SHALL support a shared request-override state that can be written by recovery logic, skills, and stop-phase outcomes, and SHALL merge those inputs deterministically before the next provider request is built.

#### Scenario: Recovery and skill contribute request overrides
- **WHEN** a skill contributes a request override and a later recovery decision also contributes a request override in the same turn
- **THEN** the runtime SHALL merge those override inputs through a deterministic runtime contract before the next request is emitted

#### Scenario: Retry-with-override rebuilds the next request
- **WHEN** the recovery policy returns `retry_with_override`
- **THEN** the runtime SHALL rebuild the next provider request using the effective merged request override instead of reusing the prior request unchanged

### Requirement: Request override precedence and lifetime are deterministic
The runtime SHALL apply deterministic precedence and one-shot consumption semantics to shared request overrides so that skill, stop-phase, and recovery inputs cannot leak ambiguously across attempts or resumed turns.

#### Scenario: Recovery override outranks skill and stop override
- **WHEN** skill, stop-phase, and recovery logic all provide a value for the same request-override field in one turn
- **THEN** the runtime SHALL resolve that field through a deterministic precedence contract in which recovery remains authoritative over lower-precedence override sources

#### Scenario: Override is consumed by the next emitted request
- **WHEN** the next provider request is successfully built and emitted using an effective merged request override
- **THEN** the runtime SHALL clear that pending override unless the turn outcome explicitly marks a resumable override snapshot for later continuation

### Requirement: Recovery and override persistence boundaries are explicit
The runtime SHALL distinguish turn-local recovery state from explicitly resumable continuation metadata and SHALL NOT persist retry counters, in-flight recovery branches, or pending overrides across resumed sessions unless those fields are explicitly serialized as resumable metadata.

#### Scenario: New user turn starts with cleared recovery counters
- **WHEN** a prior turn has finished and a new user turn begins
- **THEN** the runtime SHALL start that turn with fresh recovery counters rather than inheriting retry state from the earlier turn

#### Scenario: Resume restores only explicit continuation metadata
- **WHEN** a blocked or waiting turn resumes after session persistence
- **THEN** the runtime SHALL restore only explicitly serialized continuation metadata such as resumable override snapshots or compaction continuation inputs rather than restoring opaque in-flight recovery state

### Requirement: Failure classification and terminal precedence are deterministic
The runtime SHALL apply deterministic precedence so that failure-class outcomes remain authoritative over blocking or waiting-class outcomes proposed later in stop handling.

#### Scenario: Stop hook cannot rewrite provider failure into blocked
- **WHEN** an attempt finishes with a failure-class outcome and stop handling later proposes a blocking continuation outcome
- **THEN** the runtime SHALL preserve the failure-class terminal reason and SHALL NOT emit a final blocked or waiting-class terminal for that turn

#### Scenario: Blocking applies only to non-failure attempts
- **WHEN** stop handling proposes a blocking continuation outcome for an attempt that did not already terminate with a failure-class reason
- **THEN** the recovery policy SHALL be allowed to convert that turn into a blocked or waiting-class outcome

### Requirement: Recovery decisions are observable
The runtime SHALL expose structured recovery decisions and their reasons through turn-scoped transition metadata or equivalent host-visible events.

#### Scenario: Host observes recovery action and reason
- **WHEN** the runtime decides to continue, rebuild, compact-and-retry, retry with override, or halt
- **THEN** the emitted turn transition metadata SHALL include the selected recovery action and the reason that produced it
