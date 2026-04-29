## ADDED Requirements

### Requirement: Runtime kernel default discovery roots SHALL use the WeaveRT workspace contract
The runtime SHALL use the WeaveRT workspace contract for its canonical default user and project discovery roots. `RuntimeConfig.for_project(...)` and equivalent default discovery behavior SHALL treat `~/.weavert` and `<project>/.weavert` as the canonical user-visible roots for tools, agents, skills, memory, and other discovered runtime assets.

#### Scenario: Caller uses default project bootstrap
- **WHEN** a caller constructs runtime configuration through the default project bootstrap path
- **THEN** the runtime SHALL resolve the canonical user root as `~/.weavert`
- **AND** it SHALL resolve the canonical project root as `<project>/.weavert`

### Requirement: Runtime kernel public bootstrap examples SHALL use the WeaveRT import root
The runtime SHALL expose `weavert` as the canonical public Python import root for kernel and assembly bootstrap APIs used by framework embedders.

#### Scenario: Embedder imports the runtime bootstrap API
- **WHEN** an embedder follows the canonical public bootstrap contract for creating runtime configuration or assembling the runtime
- **THEN** the public import root SHALL be `weavert`
- **AND** the runtime SHALL NOT require the embedder to import those APIs through `runtime` as the primary documented contract
