## ADDED Requirements

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
