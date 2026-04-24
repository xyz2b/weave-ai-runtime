## ADDED Requirements

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
