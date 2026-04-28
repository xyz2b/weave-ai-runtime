## ADDED Requirements

### Requirement: Canonical public Python package surface SHALL use WeaveRT names
The framework SHALL publish a canonical public Python package surface that uses the WeaveRT product contract. User-facing installation metadata, import examples, and public module entrypoints SHALL use `weavert` as the Python package name instead of `ai-agent-runtime` or `runtime`.

#### Scenario: User installs and imports the framework
- **WHEN** an application developer installs the framework and follows the documented public Python API
- **THEN** the canonical package metadata SHALL identify the package as `weavert`
- **AND** the canonical import examples and public entrypoints SHALL use `import weavert`

### Requirement: Canonical user workspace state SHALL live under `.weavert`
The framework SHALL expose `.weavert` as the canonical user-visible workspace state root for discovered definitions and persisted runtime state such as tools, agents, skills, memory, transcripts, task state, team state, and isolation working data.

#### Scenario: Runtime resolves user-visible workspace state
- **WHEN** the runtime creates or discovers user-visible project or user-home state through its default conventions
- **THEN** it SHALL use `.weavert` as the canonical root directory name
- **AND** it SHALL NOT publish `.runtime` as the default documented user-facing root

### Requirement: Canonical first-party distribution and package identifiers SHALL use WeaveRT names
The framework SHALL expose WeaveRT-branded first-party distribution and package identifiers for every user-configurable built-in distribution, first-party package, and package ownership surface. Canonical identifiers SHALL use the `weavert-*` form instead of `runtime-*`.

#### Scenario: Embedder configures first-party package selection
- **WHEN** an embedder selects a built-in distribution, enables a first-party package, disables a first-party package, or inspects built-in ownership metadata
- **THEN** the canonical identifiers SHALL use `weavert-*` names
- **AND** the runtime SHALL NOT publish `runtime-*` names as the primary documented contract

### Requirement: Canonical public capability and extension namespaces SHALL use WeaveRT names
The framework SHALL expose WeaveRT-branded public capability keys, protocol identifiers, host-facet identifiers, and extension-event namespaces. Canonical public identifiers SHALL use the `weavert.*` namespace instead of `runtime.*`.

#### Scenario: Embedder inspects public runtime metadata or extension events
- **WHEN** an embedder inspects runtime metadata, capability lookup results, protocol catalogs, host-facet names, or emitted extension events
- **THEN** the canonical public identifiers SHALL use the `weavert.*` namespace
- **AND** legacy `runtime.*` identifiers SHALL NOT be advertised as canonical public names
