## ADDED Requirements

### Requirement: Runtime SHALL own a durable team registry and leader binding
The runtime SHALL provide a durable team control plane that can create, load, and delete teams, and SHALL bind each team to a stable leader session or equivalent leader execution identity without depending on bundled UI state.

#### Scenario: leader creates a new team
- **WHEN** a lead agent invokes the runtime's team-creation contract
- **THEN** the runtime SHALL create a durable team record with a stable `team_id`
- **AND** SHALL persist the leader binding needed to route future team traffic and team-scoped context for that team

#### Scenario: leader cannot own two active teams at once
- **WHEN** a leader session that already owns an active team invokes the runtime's team-creation contract again
- **THEN** the runtime SHALL return or reuse that existing active team binding
- **AND** SHALL NOT create a second concurrent active team for the same leader session

#### Scenario: runtime deletes a team
- **WHEN** a caller invokes the runtime's team-deletion contract for an existing team
- **THEN** the runtime SHALL remove or tombstone the durable team record under runtime-owned lifecycle rules
- **AND** SHALL stop treating that `team_id` as an active routing target after deletion completes

### Requirement: Team membership SHALL be persistent and team-scoped
The runtime SHALL represent leader and teammate membership as persistent team-scoped identities that survive across multiple messages or executions, and SHALL NOT redefine team membership from transient task IDs or one-shot work items.

#### Scenario: teammate handles multiple messages over time
- **WHEN** the same teammate member processes one team-routed message and later processes another
- **THEN** the runtime SHALL preserve the same team-member identity across both executions
- **AND** SHALL allow individual run IDs, work-item IDs, or projected task IDs to change independently

#### Scenario: leader session receives team context
- **WHEN** a session is bound as the leader of a team
- **THEN** the runtime SHALL make the corresponding team-scoped private context available to that leader session
- **AND** SHALL preserve that team scope independently from any specific foreground turn

### Requirement: Runtime SHALL manage persistent teammate members above the shared teammate execution substrate
The runtime SHALL allow a team to spawn and keep teammate members addressable over time, while continuing to reuse the shared teammate execution substrate for individual teammate executions.

#### Scenario: team spawns a teammate member
- **WHEN** the lead agent invokes the runtime's teammate-spawn contract for an active team
- **THEN** the runtime SHALL register a persistent teammate member for that team
- **AND** SHALL initialize the runtime-owned runner or coordination state needed to route future work to that teammate member

#### Scenario: teammate member returns to idle and stays addressable
- **WHEN** a persistent teammate member finishes its current execution and has no immediately pending routed work
- **THEN** the runtime SHALL allow that teammate member to return to an idle or equivalent available state
- **AND** SHALL keep that teammate member addressable for later team-routed work until it is explicitly removed or shut down

### Requirement: Team lifecycle authority SHALL remain leader-owned in v1
The runtime SHALL treat team creation, teammate spawning, and team deletion as leader-owned lifecycle operations in the first iteration, and SHALL NOT allow teammates to create nested teams or add new teammates.

#### Scenario: teammate cannot spawn another teammate
- **WHEN** a caller operating as a teammate attempts to invoke the teammate-spawn contract for the current team
- **THEN** the runtime SHALL reject that request as an invalid authority escalation
- **AND** SHALL leave the existing team membership unchanged

#### Scenario: teammate cannot create a second nested team
- **WHEN** a caller operating as a teammate attempts to invoke team creation while already bound to a team-scoped teammate identity
- **THEN** the runtime SHALL reject that request
- **AND** SHALL NOT create a nested or sibling team owned by that teammate execution context

### Requirement: Team control-plane contracts SHALL remain headless and host-extensible
The runtime SHALL expose team lifecycle and membership state through runtime-owned contracts and optional host-facing integration surfaces, and SHALL NOT require a bundled UI state model in order for team control to function.

#### Scenario: headless host uses the team control plane
- **WHEN** a host binds the runtime without any built-in teammate UI implementation
- **THEN** the runtime SHALL still allow team creation, teammate spawning, message routing, and deletion to function
- **AND** SHALL keep any optional team-facing host surfaces additive rather than mandatory for correctness
