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

