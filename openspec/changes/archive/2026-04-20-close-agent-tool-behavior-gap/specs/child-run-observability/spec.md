## ADDED Requirements

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
