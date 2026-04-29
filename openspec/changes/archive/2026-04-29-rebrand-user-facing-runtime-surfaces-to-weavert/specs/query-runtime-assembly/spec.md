## ADDED Requirements

### Requirement: Runtime assembly metadata SHALL publish WeaveRT-branded public identifiers
The runtime SHALL publish WeaveRT-branded public identifiers throughout assembly inspection surfaces that embedders consume directly. Canonical distribution names, package names, capability identifiers, protocol identifiers, and extension namespaces surfaced through runtime metadata SHALL use `weavert-*` and `weavert.*`.

#### Scenario: Caller inspects assembled runtime metadata
- **WHEN** a caller inspects runtime metadata, package catalogs, package resolution metadata, protocol catalogs, or capability lookup summaries
- **THEN** the canonical public identifiers in those inspection surfaces SHALL use `weavert-*` and `weavert.*`
- **AND** legacy `runtime-*` and `runtime.*` names SHALL NOT be advertised as the canonical assembly output
