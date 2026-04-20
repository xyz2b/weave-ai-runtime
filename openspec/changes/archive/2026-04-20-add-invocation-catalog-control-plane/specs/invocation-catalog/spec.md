## ADDED Requirements

### Requirement: Runtime exposes a unified invocation catalog
The runtime SHALL maintain a unified invocation catalog that can aggregate invocable capabilities from multiple sources, including skills and future command-like providers.

#### Scenario: Skill definitions project into invocation catalog
- **WHEN** the runtime loads a skill definition
- **THEN** it SHALL be able to expose that skill as an invocation entry without changing the skill execution backend

### Requirement: Invocation visibility is resolved per session context
The runtime SHALL resolve invocation visibility using session-scoped context rather than registry-only static filtering.

#### Scenario: Path-scoped invocation remains hidden without matching context
- **WHEN** an invocation declares path-scoped activation metadata
- **AND** the current session context does not match those paths
- **THEN** the runtime SHALL hide that invocation from the active catalog

#### Scenario: Path-scoped invocation becomes visible after context match
- **WHEN** an invocation declares path-scoped activation metadata
- **AND** the current session context matches those paths
- **THEN** the runtime SHALL expose that invocation in the active catalog

### Requirement: User and model invocability are distinct policies
The runtime SHALL distinguish whether an invocation is user-invocable and whether it is model-invocable.

#### Scenario: Invocation visible to host but not model-callable
- **WHEN** an invocation is marked non-invocable by the model
- **THEN** the runtime SHALL allow hosts to inspect it without exposing it as model-callable capability

### Requirement: Root capability exposure uses resolved visible invocations
The runtime SHALL base root capability exposure on the resolved visible invocation set rather than raw registry entries.

#### Scenario: Main router receives only resolved visible capabilities
- **WHEN** the runtime composes root capability exposure for the main thread
- **THEN** it SHALL derive the visible invocation set from session-scoped resolution instead of directly from raw registry contents
