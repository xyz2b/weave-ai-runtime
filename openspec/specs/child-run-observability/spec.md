# child-run-observability Specification

## Purpose
TBD - created by archiving change close-agent-tool-behavior-gap. Update Purpose after archive.
## Requirements
### Requirement: Every child agent run produces a structured run record
The runtime SHALL write a structured child run record for every delegated, forked, background, denied, or early-failed child agent execution.

#### Scenario: synchronous child writes a terminal record
- **WHEN** a synchronous child agent completes execution
- **THEN** the runtime SHALL persist a terminal run record containing `run_id`, parent linkage, status, and terminal metadata
- **AND** it SHALL preserve the child message history outside the main transcript continuation contract

#### Scenario: denied child still writes a minimal record
- **WHEN** a child agent is denied before entering model execution
- **THEN** the runtime SHALL still persist a run record containing `run_id`, parent linkage, and terminal status
- **AND** it SHALL NOT drop the child execution from observability only because no model response was produced

### Requirement: Background child runs preserve true lifecycle state
The runtime SHALL preserve the actual lifecycle state of background child runs across sidechain records and host-visible observability.

#### Scenario: background child writes running then terminal states
- **WHEN** a child agent is dispatched in background mode
- **THEN** the runtime SHALL first persist a `running` child record
- **AND** it SHALL later update that child to its true terminal state after execution finishes

#### Scenario: background child does not upgrade denied or failed status
- **WHEN** a background child finishes in `denied`, `failed`, or another non-completed terminal state
- **THEN** the runtime SHALL preserve that exact terminal state in run records and host-visible lifecycle
- **AND** it SHALL NOT report the child as `completed` merely because it executed in the background

### Requirement: Forked and background child history stays queryable outside the main transcript
The runtime SHALL make child run records and child message history queryable by child identity without requiring callers to scrape the main transcript.

#### Scenario: child records are queryable by session
- **WHEN** a caller queries child runs for a session that spawned delegated or forked children
- **THEN** the runtime SHALL return a stable list of child run records for that session
- **AND** each record SHALL retain the linkage needed to associate it with its parent run and parent turn

#### Scenario: child messages are not merged into the main transcript
- **WHEN** a child run produces internal assistant or tool messages
- **THEN** the runtime SHALL keep those messages in the child sidechain history
- **AND** it SHALL NOT require the main transcript to duplicate the child's full internal message stream

### Requirement: Child lifecycle is exposed to hosts as a first-class observable surface
The runtime SHALL expose child run lifecycle updates to the host through a first-class observable surface rather than requiring hosts to infer child execution only from transcript text or generic notifications.

#### Scenario: host can observe child start and terminal state
- **WHEN** a child run is started and later reaches a terminal state
- **THEN** the runtime SHALL surface both lifecycle transitions to the host with the child `run_id` and status
- **AND** the terminal lifecycle payload SHALL align with the persisted child run record

### Requirement: Parent-facing child projection stays separate from sidechain truth

The runtime SHALL preserve a separation between parent-facing child result projection and child sidechain observability so parent context hygiene does not weaken child-run truth surfaces.

#### Scenario: Summary-first parent result does not erase child history

- **WHEN** a parent-facing child result is emitted under the default summary-first policy
- **THEN** the runtime SHALL keep the child's full internal message history in child sidechain storage or equivalent child-run records
- **AND** SHALL NOT require the parent-facing projection to duplicate that full history

#### Scenario: Child history remains queryable by child identity

- **WHEN** a caller inspects a child run whose parent received only a summary projection
- **THEN** the runtime SHALL still expose the child run record and child message history through child-run observability surfaces
- **AND** SHALL preserve the linkage needed to associate that child record with its parent execution

#### Scenario: Host observability retains full child-run truth

- **WHEN** the parent-facing child result is summary-only by default
- **THEN** host-visible child-run observability such as `CHILD_RUN` lifecycle events SHALL still align with the full child sidechain record
- **AND** SHALL NOT be reduced to the parent-facing summary projection contract

### Requirement: Production-oriented runtime profiles persist child-run history by default
The runtime SHALL provide a bundled durable child-run history path for production-oriented persistence profiles rather than leaving child-run durability entirely to ad hoc embedder injection.

#### Scenario: production profile recovers child-run history
- **WHEN** a production-oriented runtime profile persists child runs and the runtime is later restarted or reassembled against the same durable state
- **THEN** the runtime SHALL reload the persisted child-run records through its standard child-run observability surfaces
- **AND** those records SHALL preserve stable `run_id`, parent linkage, status, and terminal metadata

#### Scenario: lightweight profile publishes non-durable child-run behavior
- **WHEN** a lightweight runtime profile keeps child-run history in-memory only
- **THEN** the runtime SHALL publish that child-run durability is non-default or non-durable in assembly metadata
- **AND** the runtime SHALL NOT imply full child-run history recovery guarantees for that profile

### Requirement: Terminal child lifecycle can drive structured continuation without replacing typed observability
The runtime SHALL be able to derive a structured parent-session continuation signal from a terminal child run while preserving typed child-run records and lifecycle events as the source of truth.

#### Scenario: waiting parent session receives structured child completion signal
- **WHEN** a child run linked to a waiting parent session reaches a terminal state and continuation policy allows wake-up
- **THEN** the runtime SHALL be able to submit a structured continuation input for the parent session that includes the child run identity and terminal status
- **AND** SHALL NOT require callers to scrape custom transcript protocols to recover that child completion

#### Scenario: typed child-run observability remains authoritative
- **WHEN** a terminal child run also produces a continuation signal for its parent session
- **THEN** the runtime SHALL still persist the same terminal child run record and emit the same typed child-run lifecycle event for host-visible observability
- **AND** SHALL NOT replace typed child-run observability with transcript-only continuation text

#### Scenario: active parent turn does not receive duplicate continuation delivery
- **WHEN** the parent turn is still active and can already observe the child run through turn-local child-run events
- **THEN** the runtime SHALL avoid enqueueing a duplicate continuation signal for that same terminal child state
- **AND** SHALL preserve a single coherent child-run outcome across turn-local and session-level orchestration paths

