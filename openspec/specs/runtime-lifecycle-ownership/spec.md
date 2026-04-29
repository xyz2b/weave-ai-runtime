# runtime-lifecycle-ownership Specification

## Purpose
TBD - created by archiving change align-runtime-ingress-context-lifecycle-boundaries. Update Purpose after archive.
## Requirements
### Requirement: Host lifecycle has an explicit owner independent of session lifecycle
The runtime SHALL assign host startup, readiness, and shutdown to an explicit host-binding owner rather than coupling those transitions to per-session start and close.

#### Scenario: Bound host serves multiple sessions under one lifecycle
- **WHEN** a bound host runtime creates or runs more than one session within the same host scope
- **THEN** the runtime SHALL allow those sessions to share one host startup/ready period rather than starting and stopping the host around each session

#### Scenario: Session close does not implicitly shut down host
- **WHEN** a session is closed while the bound host remains active
- **THEN** the runtime SHALL complete session teardown without calling host shutdown as part of that session close

### Requirement: Bound host runtime acts as an explicit host-scope lifecycle manager
The runtime SHALL allow the bound host surface to act as an explicit host-scope lifecycle manager, including context-managed startup and shutdown behavior.

#### Scenario: Bound host supports context-managed scope
- **WHEN** a caller enters a bound host runtime scope
- **THEN** the runtime SHALL support entering that scope through an explicit lifecycle boundary that performs host startup and ready before session work begins

#### Scenario: Exiting host scope shuts down after managed session close
- **WHEN** a caller exits a bound host runtime scope
- **THEN** the runtime SHALL close any remaining managed sessions before performing host shutdown

#### Scenario: Manual lifecycle path matches context-managed semantics
- **WHEN** a caller drives the bound host through explicit `startup()`, `ready()`, and `shutdown()` calls instead of `async with`
- **THEN** the runtime SHALL preserve the same host-scope ownership semantics and shutdown ordering as the context-managed path

### Requirement: Session controller owns session-scoped lifecycle semantics
The session controller SHALL own session start/end events, transcript persistence, session memory artifacts, and session-scoped cleanup, and its close path SHALL be idempotent.

#### Scenario: Session start initializes session resources
- **WHEN** a session is started or resumed into an active execution path
- **THEN** the session controller SHALL initialize session-scoped resources and dispatch session-start semantics without taking ownership of host startup

#### Scenario: Session close emits end semantics exactly once
- **WHEN** a session is closed after success, interruption, or failure
- **THEN** the session controller SHALL dispatch session-end semantics and session-scoped cleanup exactly once, even if close is called multiple times

### Requirement: One-shot helper surfaces guarantee session close
Runtime one-shot helpers such as `run_prompt()` and `stream_prompt()` SHALL guarantee that the session they create is closed on success, interruption, and error paths.

#### Scenario: `run_prompt()` closes session after success
- **WHEN** a caller uses a one-shot helper that completes a prompt successfully
- **THEN** the runtime SHALL close the helper-owned session before returning the aggregated result

#### Scenario: streaming helper closes session after interruption or error
- **WHEN** a caller uses a streaming one-shot helper and the turn terminates through interruption or error
- **THEN** the runtime SHALL still close the helper-owned session before the helper exits

### Requirement: Bound host tracks managed sessions for deterministic shutdown
The runtime SHALL track helper-owned or bound-owned sessions within the active host scope so shutdown can close them deterministically.

#### Scenario: Helper-owned session is registered and deregistered
- **WHEN** a one-shot helper or host-bound helper creates a session inside an active host scope
- **THEN** the runtime SHALL register that session as managed and SHALL remove it from the registry when session close completes

#### Scenario: Shutdown ordering closes sessions before host shutdown
- **WHEN** the active host scope ends while managed sessions remain open
- **THEN** the runtime SHALL close those sessions and complete session-scoped cleanup before invoking host shutdown

#### Scenario: Session close failure does not skip remaining cleanup
- **WHEN** one managed session fails during host-scope shutdown
- **THEN** the runtime SHALL continue best-effort cleanup for the remaining managed sessions, collect diagnostics for the failure, and only then resolve the terminal shutdown outcome

### Requirement: Long-lived sessions remain reusable within an active host scope
The runtime SHALL allow long-lived sessions to submit multiple prompts within an already active host scope without duplicating host lifecycle transitions.

#### Scenario: Reused session submits multiple prompts
- **WHEN** a caller creates a session explicitly and submits multiple prompts through that session
- **THEN** the runtime SHALL preserve session continuity and SHALL NOT require host startup/shutdown between those prompts

#### Scenario: Host shutdown remains an explicit outer action
- **WHEN** the active host scope is no longer needed after one or more sessions complete
- **THEN** host shutdown SHALL occur only through the explicit host-lifecycle owner rather than as a side effect of normal session completion

### Requirement: Package lifecycle participants SHALL preserve core lifecycle ownership
The runtime SHALL allow package-contributed lifecycle participants to run during runtime start, runtime recovery, session open, and session close without transferring host-, session-, or turn-scope ownership away from the core lifecycle managers.

#### Scenario: Session-close participant runs without owning session close
- **WHEN** an official package contributes session-close behavior through a lifecycle participant
- **THEN** the runtime SHALL invoke that participant within the runtime-owned session-close phase
- **AND** the `SessionController` SHALL remain the owner of session-close ordering, cleanup, and terminal state transitions

#### Scenario: Runtime-recovery participant runs without owning runtime startup
- **WHEN** an official package contributes runtime-recovery behavior through a lifecycle participant
- **THEN** the runtime SHALL invoke that participant within runtime-owned startup or recovery sequencing
- **AND** the bound host runtime, kernel assembly, and turn stack ownership model SHALL remain unchanged

### Requirement: Package lifecycle participants SHALL run in owner-defined deterministic order
The runtime SHALL invoke package-contributed lifecycle participants in a deterministic order defined by the runtime-owned lifecycle manager for the active phase.

#### Scenario: Multiple participants attach to the same lifecycle phase
- **WHEN** more than one official package contributes participants for the same runtime-owned lifecycle phase
- **THEN** the runtime SHALL invoke those participants in one deterministic owner-defined order
- **AND** that ordering SHALL remain under the control of the runtime-owned lifecycle manager rather than individual packages

### Requirement: Participant failure SHALL NOT bypass remaining owner-managed lifecycle work
The runtime SHALL treat package lifecycle participant failure as a lifecycle-phase failure signal or diagnostic without skipping the remaining owner-managed cleanup or sequencing obligations for that phase.

#### Scenario: Session-close participant fails during cleanup
- **WHEN** a package lifecycle participant fails during a runtime-owned session-close phase
- **THEN** the runtime SHALL continue the remaining owner-managed session-close sequencing on a best-effort basis
- **AND** it SHALL surface the participant failure through diagnostics, terminal metadata, or equivalent structured runtime reporting

#### Scenario: Runtime-recovery participant fails during startup recovery
- **WHEN** a package lifecycle participant fails during runtime-owned startup or recovery sequencing
- **THEN** the runtime SHALL report that participant failure through the runtime-owned recovery path
- **AND** it SHALL preserve runtime-owned control of the remaining startup or recovery sequencing outcome

### Requirement: Package-owned session-open replay SHALL attach through lifecycle participants without transferring session ownership
The runtime SHALL require package-owned session-open replay behavior to attach through runtime-owned lifecycle participants while preserving `SessionController` as the owner of session start, resume, ordering, and state transitions.

#### Scenario: package participates in session-open replay
- **WHEN** an official package needs to replay pending package-owned session input or state during session start or resume
- **THEN** it SHALL attach that replay through a `SESSION_OPEN` lifecycle participant or equivalent runtime-owned lifecycle seam
- **AND** the `SessionController` SHALL remain the owner of session-open semantics rather than delegating that ownership to the package

#### Scenario: session-open participant fails during replay
- **WHEN** a package-owned `SESSION_OPEN` participant fails while replaying package-owned session state
- **THEN** the runtime SHALL surface that failure through the runtime-owned lifecycle outcome path
- **AND** it SHALL preserve the existing host-scope and session-scope ownership semantics while reporting that failure

### Requirement: Session-open participants SHALL respect controller-owned start and resume ordering
The runtime SHALL preserve `SessionController` ownership of session-open ordering even when packages participate in `SESSION_OPEN`.

#### Scenario: package participates during session start or resume
- **WHEN** a session starts or resumes and package-owned replay is needed
- **THEN** the `SessionController` SHALL restore session-owned transcript and resumable private state before dispatching `SESSION_OPEN`
- **AND** package participants MAY replay or enqueue package-owned pending state only inside that bounded lifecycle phase
- **AND** the `SessionController` SHALL remain responsible for the final ready transition and any controller-owned waiting-session drain or replay follow-up

### Requirement: Team replay and recovery SHALL remain lifecycle-participant-owned during bridge removal
The runtime SHALL keep team recovery and session-open replay behavior attached through lifecycle participants while removing package-specific team bridges from runtime-owned owner-layer APIs.

#### Scenario: session resumes with pending team state
- **WHEN** a session resumes with package-owned team replay or recovery work pending
- **THEN** the runtime SHALL execute that work through the published lifecycle-participant phases
- **AND** SHALL NOT reintroduce a controller-owned or kernel-owned team replay special case during bridge removal

