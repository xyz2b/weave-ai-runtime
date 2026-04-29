# runtime-session-ingress Specification

## Purpose
TBD - created by archiving change align-runtime-ingress-context-lifecycle-boundaries. Update Purpose after archive.
## Requirements
### Requirement: Session inputs are normalized through a dedicated ingress pipeline
The runtime SHALL normalize every inbound session event through a dedicated ingress pipeline before transcript mutation, turn execution, or host-visible replay for that event.

#### Scenario: User prompt is admitted through ingress
- **WHEN** a caller submits a user prompt to a session
- **THEN** the runtime SHALL produce an ingress result that contains normalized session messages and an explicit decision about whether turn execution should start

#### Scenario: Non-query input is resolved without raw turn execution
- **WHEN** an inbound event resolves to a local-only or session-only outcome
- **THEN** the runtime SHALL complete that outcome through ingress without passing the raw inbound payload directly into `TurnEngine`

### Requirement: Ingress results separate normalized messages from side effects and private state
The ingress pipeline SHALL return structured outputs that distinguish normalized transcript messages, host-visible replay outputs, prompt-visible additions, runtime-private context updates, and turn-admission state.

#### Scenario: Local-only ingress result suppresses turn admission
- **WHEN** ingress resolves an inbound event into replay outputs or session-only effects without requiring model execution
- **THEN** the ingress result SHALL set turn admission to false while still exposing the normalized outputs needed by the host or transcript

#### Scenario: Query-admitted ingress result carries private updates separately
- **WHEN** ingress admits a turn that needs runtime-private execution metadata
- **THEN** the ingress result SHALL expose those private updates separately from prompt-visible additions and normalized transcript messages

### Requirement: Ingress classifies common inbound sources into deterministic outcome channels
The ingress pipeline SHALL classify user prompts, local commands, host-generated prompts, task notifications, and rejected inputs into explicit outcome channels rather than relying on raw command-type fallbacks.

#### Scenario: Local command resolves without prompt leakage
- **WHEN** ingress receives a slash command or other local-only control input
- **THEN** it SHALL resolve that input into replay, transcript, or private-only outcomes as explicitly classified by ingress and SHALL NOT implicitly re-encode it as ordinary user prompt text

#### Scenario: Rejected input stays outside transcript and admitted turns
- **WHEN** ingress rejects an inbound input
- **THEN** it SHALL avoid appending transcript messages or starting turn execution for that input, while still allowing rejection replay output or private diagnostics when applicable

### Requirement: Ingress result uses a formal admission and replay protocol
The ingress pipeline SHALL expose a formal protocol for admission decisions and host-visible replay outputs instead of encoding those decisions only through booleans or loose metadata fields.

#### Scenario: Admission decision is structured
- **WHEN** ingress finishes evaluating an inbound event
- **THEN** it SHALL return a structured admission object that includes at least admission kind and reason

#### Scenario: Replay outputs are distinct from transcript messages
- **WHEN** ingress needs to surface host-visible output that is not identical to a transcript message
- **THEN** it SHALL return that output through a dedicated replay-output protocol instead of overloading normalized transcript messages

### Requirement: Session control executes ingress results rather than raw inbound payloads
Session control SHALL record and execute only the normalized messages and context emitted by ingress, and SHALL preserve resumable transcript state before the first model request of an admitted turn.

#### Scenario: Admitted prompt is persisted before request emission
- **WHEN** ingress admits a user prompt for turn execution
- **THEN** the session controller SHALL append the normalized ingress messages to transcript state before the first model request for that turn is emitted

#### Scenario: Ingress-defined role and visibility are preserved
- **WHEN** ingress classifies an inbound input as system, host-generated, task-scoped, or user-visible
- **THEN** the session controller SHALL record and replay the ingress-defined role and visibility semantics rather than recomputing them from the raw command type alone

### Requirement: Ingress owns turn admission semantics for generated inputs
The runtime SHALL require system-generated, host-generated, and task-generated inputs to pass through the same ingress admission contract as user prompts.

#### Scenario: Host-generated prompt becomes a meta ingress input
- **WHEN** the host injects a prompt or control message that should influence model execution without behaving like ordinary user text
- **THEN** ingress SHALL classify that input explicitly and SHALL expose whether it is prompt-visible, replay-visible, or private-only

#### Scenario: Task notification does not implicitly create a new turn
- **WHEN** a queued task or background notification enters the session
- **THEN** ingress SHALL decide whether it becomes transcript-only state, replay output, or an admitted turn instead of allowing task notifications to implicitly enter the turn loop as raw prompts

### Requirement: Child-run continuation inputs carry summary-aware completion context

The runtime SHALL attach summary-aware child completion context to child-run continuation inputs so resumed parent sessions receive the child outcome without scraping child transcript text.

#### Scenario: Waiting session resumes from terminal child completion

- **WHEN** a waiting session is resumed from a terminal child run through runtime-owned continuation delivery
- **THEN** the admitted continuation context SHALL include child identity, terminal status, and summary
- **AND** SHALL NOT require the resumed parent turn to query child transcript text just to understand the child outcome

#### Scenario: Ready session queues summary-aware child completion for later drain

- **WHEN** a ready session receives a child completion input that is queued without immediate turn admission
- **THEN** ingress SHALL preserve the same summary-aware child completion context for that queued input
- **AND** SHALL replay that context unchanged when the queued input is later admitted

### Requirement: Team-routed leader inputs SHALL enter the leader session through structured ingress
The runtime SHALL route leader-visible teammate messages and eligible team-generated collaboration inputs into the leader session through structured ingress outcomes rather than by directly mutating transcript text or UI-local inbox state.

#### Scenario: teammate message becomes a leader-visible generated input
- **WHEN** a routed team message targets the current leader session and is classified as model-visible collaboration input
- **THEN** the runtime SHALL submit that input through the session ingress pipeline as a runtime-generated event with explicit admission semantics
- **AND** SHALL preserve routing metadata separately from ordinary user-prompt text

#### Scenario: team control message resolves without transcript leakage
- **WHEN** a routed team control message targets the leader session but is classified as private-only, local-only, or replay-only state
- **THEN** the runtime SHALL resolve it through ingress as private updates, replay outputs, or equivalent non-transcript outcomes
- **AND** SHALL NOT require the raw control envelope to be appended to transcript-visible session history

### Requirement: Leader-directed team ingress SHALL follow explicit session-state admission defaults
The runtime SHALL apply stable default drain and queuing behavior for leader-directed team ingress based on the leader session state, and SHALL not treat teammate traffic as an implicit interrupt channel.

#### Scenario: waiting leader resumes from collaboration input by default
- **WHEN** a leader session in `WAITING` receives a leader-visible collaboration message from the team bus
- **THEN** the runtime SHALL submit that message through ingress with admitted-turn semantics
- **AND** SHALL drain it by default so the waiting leader can resume without a host re-submission step

#### Scenario: ready leader queues collaboration input by default
- **WHEN** a leader session in `READY` receives a leader-visible collaboration message from the team bus
- **THEN** the runtime SHALL submit that message through ingress with admitted-turn semantics
- **AND** SHALL queue it by default rather than auto-draining it immediately

#### Scenario: running leader is not interrupted by teammate traffic
- **WHEN** a leader session in `RUNNING` receives a leader-visible collaboration message from the team bus
- **THEN** the runtime SHALL queue that admitted ingress input for later ordered handling
- **AND** SHALL NOT interrupt or start a second concurrent turn solely because the teammate message arrived

#### Scenario: control envelopes stay private or replay-only by default
- **WHEN** a team-routed control envelope targets the leader session and does not need model-visible collaboration text
- **THEN** the runtime SHALL prefer `local_only` or `replay_only` ingress outcomes with `private_updates`
- **AND** SHALL keep that control traffic transcript-hidden unless an explicit runtime policy chooses otherwise

### Requirement: Leader-actionable team control workflows SHALL enter the leader session as synthesized ingress requests
The runtime SHALL translate leader-actionable team control workflows into runtime-generated ingress inputs that summarize the requested action and expose the stable `workflow_id`, while keeping raw control transport envelopes private by default.

#### Scenario: permission workflow becomes a leader-visible generated input
- **WHEN** a teammate creates a permission workflow that requires leader action
- **THEN** the runtime SHALL submit a generated ingress input that includes a readable workflow summary together with the `workflow_id`
- **AND** SHALL preserve the raw structured control payload as private routing metadata rather than appending the raw envelope to transcript-visible session history

#### Scenario: non-actionable control update stays private
- **WHEN** a team control message only acknowledges delivery, reports terminal workflow state, or otherwise does not require new leader action
- **THEN** the runtime SHALL resolve that update through private or replay-only ingress outcomes
- **AND** SHALL NOT create a new model-visible turn solely because that non-actionable control update arrived

### Requirement: Workflow ingress SHALL expose typed response metadata for runtime-owned tools
The runtime SHALL attach workflow kind, requester identity, allowed response actions, and correlation metadata to leader ingress private state so runtime-owned workflow-response tools can validate follow-up decisions without parsing transcript text.

#### Scenario: leader receives allowed actions with a workflow request
- **WHEN** leader ingress admits a team control workflow request that expects a leader response
- **THEN** the associated ingress metadata SHALL include the workflow kind, `workflow_id`, requester identity, and the allowed response actions for the current workflow state
- **AND** SHALL keep that metadata available to the runtime-owned tool execution path for the corresponding leader turn

### Requirement: Lifecycle-critical team control workflows SHALL be prioritized over ordinary teammate chatter at ingress
The runtime SHALL prioritize leader-actionable team control workflows that affect lifecycle safety, such as shutdown requests, ahead of ordinary teammate chatter when choosing which actionable ingress request to surface next for the leader session.

#### Scenario: shutdown workflow is surfaced before lower-priority teammate chatter
- **WHEN** the leader session has both a pending leader-actionable shutdown workflow and ordinary teammate chatter eligible to become actionable ingress
- **THEN** the runtime SHALL surface the shutdown workflow request first
- **AND** SHALL NOT delay that lifecycle-critical control request solely because lower-priority teammate chatter arrived earlier or in the same delivery window

### Requirement: Completion receipts SHALL use an explicit ingress-owned descriptor
The ingress protocol SHALL represent post-ingress acknowledgements as `IngressCompletionReceipt` descriptors carried on `SessionIngressResult.completion_receipts`, rather than as ad hoc metadata keys or controller-owned package branches.

#### Scenario: ingress publishes a completion receipt
- **WHEN** an ingress result needs to expose post-ingress acknowledgement work
- **THEN** it SHALL publish an `IngressCompletionReceipt` on `SessionIngressResult.completion_receipts`
- **AND** that descriptor SHALL include a stable `receipt_id` and a named `kind`
- **AND** any receipt payload consumed by the runtime-owned executor SHALL remain opaque to `SessionController`

### Requirement: Ingress results SHALL expose bounded completion receipts for post-ingress acknowledgements
The ingress pipeline SHALL allow a structured ingress result to carry bounded completion receipts that session control can execute after ingress-defined transcript, replay, and private-state effects have been committed.

#### Scenario: ingress requires a post-ingress acknowledgement
- **WHEN** an inbound event requires a deterministic acknowledgement or receipt after ingress effects are committed
- **THEN** the ingress result SHALL expose that acknowledgement through a bounded completion-receipt protocol
- **AND** it SHALL NOT require the session controller to infer that acknowledgement solely from package-specific metadata keys inside normalized messages or private updates

### Requirement: Session control SHALL execute completion receipts without package-specific ingress branches
The session controller SHALL execute ingress completion receipts through the shared ingress protocol rather than through package-specific acknowledgement helper branches.

#### Scenario: package-owned delivery acknowledgement completes after ingress execution
- **WHEN** a package-owned inbound flow requires a delivery acknowledgement after transcript, replay, or private-state effects are applied
- **THEN** the session controller SHALL execute the bounded completion receipt emitted by ingress
- **AND** it SHALL preserve session-owned ingress ordering without introducing a package-specific acknowledgement path in session control

### Requirement: Completion receipts SHALL execute in bounded post-commit order
The ingress protocol SHALL require completion receipts to execute only after ingress-defined transcript, replay, and private-state effects commit, and the session controller SHALL preserve the emitted receipt order.

#### Scenario: ingress emits multiple completion receipts
- **WHEN** an ingress result carries more than one completion receipt
- **THEN** the session controller SHALL execute those receipts in emitted order after ingress effects commit
- **AND** it SHALL NOT execute a later receipt before an earlier receipt has completed or failed

#### Scenario: completion receipt fails after ingress effects commit
- **WHEN** a completion receipt fails after transcript, replay, or private-state effects have already been applied
- **THEN** the runtime SHALL surface that failure through a runtime-owned outcome or diagnostics path
- **AND** it SHALL NOT require the session controller to infer or perform package-specific rollback logic for the already-committed ingress effects

### Requirement: Receipt execution failure SHALL be fail-stop for the active receipt sequence
The session controller SHALL stop executing later receipts from the same ingress result after the first receipt failure in that execution attempt.

#### Scenario: earlier receipt fails while later receipts remain pending
- **WHEN** one completion receipt fails and later receipts from the same ingress result have not yet run
- **THEN** the session controller SHALL stop the active receipt sequence at the failed receipt
- **AND** it SHALL surface the failure through the runtime-owned receipt outcome path
- **AND** it SHALL NOT treat the already-committed ingress effects as rolled back

### Requirement: Session ingress SHALL propagate authoritative private state through structured carriers
The runtime SHALL propagate ingress-owned private updates and session-private state through structured authoritative carriers rather than through raw compatibility maps.

#### Scenario: ingress emits runtime-private updates
- **WHEN** session ingress classifies an inbound event and emits runtime-private updates
- **THEN** session control SHALL merge those updates into authoritative structured private-state carriers
- **AND** SHALL NOT require raw `runtime_context` mutation as the authoritative persistence path for those updates

### Requirement: Runtime-generated continuation inputs can request explicit turn admission
The ingress pipeline SHALL allow runtime-generated continuation inputs to override default source-based admission behavior through explicit admission metadata on runtime-generated task notifications or an equivalent runtime-owned task-notification envelope.

#### Scenario: child-run continuation input is admitted as a turn
- **WHEN** the runtime submits a child-run continuation input as a runtime-generated task notification with explicit `admission_kind=admit_turn` intent for a parent session
- **THEN** ingress SHALL normalize that input through the same ingress pipeline used for other session events
- **AND** SHALL admit it as a new turn instead of forcing transcript-only handling

#### Scenario: ordinary task notification keeps default behavior without override
- **WHEN** a task or background notification enters ingress without explicit continuation-admission intent
- **THEN** the runtime SHALL preserve the default admission behavior for that notification source
- **AND** SHALL NOT automatically upgrade all task notifications into admitted turns

### Requirement: Waiting sessions can resume through admitted runtime-generated continuation inputs
Session control SHALL be able to queue and execute admitted runtime-generated continuation inputs without requiring the host to resubmit the same event as a user prompt.

#### Scenario: waiting session resumes from child-run completion
- **WHEN** a waiting session receives an admitted runtime-generated continuation input
- **THEN** the session controller SHALL be able to transition that input through ingress and the normal turn-execution stack
- **AND** SHALL not require a separate host-originated prompt to wake the session

#### Scenario: ready session queues continuation input by default
- **WHEN** a ready session receives an admitted runtime-generated continuation input under the default continuation policy
- **THEN** the session controller SHALL queue that input for subsequent execution without eagerly starting a new turn
- **AND** SHALL only auto-resume ready sessions when an explicit runtime policy enables that behavior

#### Scenario: running session queues continuation input for later execution
- **WHEN** a runtime-generated continuation input arrives while the session already has an active turn
- **THEN** the session controller SHALL queue that input for later execution or equivalent ordered handling
- **AND** SHALL NOT start a second concurrent turn for the same session solely because the continuation input was admitted

