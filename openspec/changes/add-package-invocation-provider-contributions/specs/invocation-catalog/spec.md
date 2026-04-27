## MODIFIED Requirements

### Requirement: Runtime exposes a unified invocation catalog
The runtime SHALL maintain a unified invocation catalog that can aggregate invocable capabilities from multiple sources, including skills, package-contributed providers, and future command-like providers.

#### Scenario: Skill definitions project into invocation catalog
- **WHEN** the runtime loads a skill definition
- **THEN** it SHALL be able to expose that skill as an invocation entry without changing the skill execution backend

#### Scenario: Package-contributed provider projects into invocation catalog
- **WHEN** a selected runtime package contributes an invocation provider through the canonical package contribution path
- **THEN** the runtime SHALL include that provider's invocations in the same unified catalog used for built-in and config-supplied providers

## ADDED Requirements

### Requirement: Invocation-provider registration is deterministic before catalog resolution
The runtime SHALL complete provider registration through the shared invocation registry before hosts or sessions resolve the active invocation catalog.

#### Scenario: host inspects visible invocations after assembly
- **WHEN** a host or runtime helper requests the visible invocation catalog from an assembled runtime
- **THEN** the runtime SHALL resolve that catalog from the fully registered provider set for the active runtime
- **AND** SHALL NOT require lazy package-specific provider bootstrapping during the first session
