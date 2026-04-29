## ADDED Requirements

### Requirement: Hosts can query and watch jobs through the shared job control plane
The runtime SHALL expose host-facing query and watch surfaces for jobs that are backed by the shared job control plane rather than by executor-specific polling contracts.

#### Scenario: host lists or reads jobs
- **WHEN** a bound host queries runtime jobs for a given session, team, or equivalent scope
- **THEN** the runtime SHALL return shared job records visible to that scope
- **AND** SHALL expose enough generic metadata for the host to distinguish lifecycle state, executor kind, and linkage

#### Scenario: host subscribes to job changes
- **WHEN** a bound host registers a job watch callback for a visible scope
- **THEN** the runtime SHALL deliver job snapshot updates or equivalent watch payloads from the shared job control plane
- **AND** SHALL NOT require the host to subscribe to executor-specific channels just to observe shared job lifecycle changes

### Requirement: Hosts can request runtime-owned job stops
The runtime SHALL allow bound hosts to request stop for visible jobs through the shared host/runtime bridge.

#### Scenario: host stops a running job
- **WHEN** a bound host requests stop for a visible running job
- **THEN** the runtime SHALL route that stop request through the shared job control plane
- **AND** SHALL return the resulting job state or a structured stop error under the same runtime-owned contract used by other job consumers

