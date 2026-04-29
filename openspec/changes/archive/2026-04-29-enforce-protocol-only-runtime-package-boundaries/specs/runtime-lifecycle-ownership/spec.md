## ADDED Requirements

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
