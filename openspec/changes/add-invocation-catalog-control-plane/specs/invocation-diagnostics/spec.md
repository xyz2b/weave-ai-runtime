## ADDED Requirements

### Requirement: Runtime explains invocation visibility decisions
The runtime SHALL provide diagnostics explaining why an invocation is visible, hidden, or non-invocable.

#### Scenario: Host inspects hidden invocation
- **WHEN** a host requests diagnostics for an invocation that is currently hidden
- **THEN** the runtime SHALL report which activation or visibility rules caused it to be hidden

### Requirement: Diagnostics distinguish path mismatch from indeterminate context
The runtime SHALL distinguish between invocations hidden because path activation did not match and invocations hidden because the current session context was insufficient to prove a match.

#### Scenario: Host inspects invocation hidden by explicit path mismatch
- **WHEN** an invocation declares path-scoped activation metadata
- **AND** the runtime establishes that the current session context does not match those paths
- **THEN** diagnostics SHALL mark the hidden reason as a path mismatch

#### Scenario: Host inspects invocation hidden by insufficient context
- **WHEN** an invocation declares path-scoped activation metadata
- **AND** the runtime cannot establish whether the current session context matches those paths
- **THEN** diagnostics SHALL mark the hidden reason as indeterminate context rather than explicit mismatch

### Requirement: Diagnostics distinguish user invocability from model invocability
The runtime SHALL expose diagnostics separately for user invocability and model invocability.

#### Scenario: Invocation is user-invocable but not model-invocable
- **WHEN** an invocation can be triggered by a host surface but is disabled for model invocation
- **THEN** the runtime SHALL expose diagnostics that preserve both decisions separately

### Requirement: Invocation layer preserves non-escalation
The runtime SHALL not allow invocation metadata to expand capabilities already bounded by skill, agent, or session policy ceilings.

#### Scenario: Invocation metadata cannot widen tool exposure
- **WHEN** an invocation wraps a skill with restricted `allowed-tools` semantics
- **THEN** the invocation layer SHALL preserve those ceilings rather than widening the available capability set
