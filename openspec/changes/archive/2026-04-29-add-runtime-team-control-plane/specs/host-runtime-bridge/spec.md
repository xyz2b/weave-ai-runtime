## ADDED Requirements

### Requirement: Hosts can observe structured team lifecycle and routing events through headless bridge surfaces
The runtime SHALL expose optional host-facing integration surfaces for structured team lifecycle, membership, and routed team-message events so hosts can render or automate teammate behavior without the runtime owning UI state.

#### Scenario: host observes team lifecycle updates
- **WHEN** a team is created, a teammate member is spawned, or a team is deleted
- **THEN** a bound host that enables the runtime's optional team-facing bridge surfaces SHALL be able to observe those lifecycle updates as structured runtime-owned events
- **AND** the runtime SHALL keep team state authoritative even if no host-side UI is present

#### Scenario: host observes routed team control events
- **WHEN** the runtime routes a structured team control event such as permission mediation, teammate shutdown, or teammate termination
- **THEN** a bound host that enables the runtime's optional team-facing bridge surfaces SHALL be able to receive a structured event describing that routing outcome
- **AND** SHALL NOT be required to scrape transcript text or generic notifications to infer that control-plane event

### Requirement: The minimal v1 team host bridge SHALL be a single optional structured event sink
The runtime SHALL keep the first host-facing team bridge minimal by using one optional structured event sink or equivalent compat callback rather than a mandatory family of UI-oriented callbacks.

#### Scenario: host binds one structured team-event sink
- **WHEN** a host provides the runtime's optional team-event observation sink
- **THEN** the runtime SHALL be able to deliver team lifecycle, routing, and control-plane events through that single structured channel
- **AND** SHALL NOT require separate dedicated callbacks for each specific team event type in order to expose v1 teammate mode

#### Scenario: structured team events carry stable correlation fields
- **WHEN** the runtime emits a structured team event to a bound host sink
- **THEN** that event SHALL include stable routing identity such as `event_type`, `team_id`, and `leader_session_id`
- **AND** SHOULD include additional correlation fields such as `member_id`, `message_id`, or `correlation_id` when those fields exist for the emitted event

### Requirement: Optional team-facing host surfaces SHALL remain additive
The runtime SHALL treat team-facing host surfaces as additive observation or integration hooks, and SHALL NOT require every bound host to implement them in order for team control to function.

#### Scenario: host does not implement optional team-facing surfaces
- **WHEN** a host binds to the runtime without implementing any optional team-facing observation surface
- **THEN** the runtime SHALL still allow team creation, team routing, teammate execution, and deletion to function correctly
- **AND** SHALL degrade only by omitting those optional structured side-channel events for that host

#### Scenario: runtime-owned team queries do not depend on host callbacks
- **WHEN** a framework consumer needs current team state for rendering or automation
- **THEN** the runtime SHALL keep team state authoritative in the runtime-owned control plane rather than requiring the host bridge to become the source of truth
- **AND** the optional host team sink SHALL remain observational rather than state-owning
