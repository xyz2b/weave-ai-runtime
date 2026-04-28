## ADDED Requirements

### Requirement: Canonical first-party built-in distributions and owners SHALL use WeaveRT package identifiers
The runtime SHALL expose WeaveRT-branded canonical identifiers for its first-party built-in distributions and built-in ownership matrix. Canonical distribution names SHALL use `weavert-core`, `weavert-default`, and `weavert-full`, and canonical built-in owner package names SHALL use `weavert-*`.

#### Scenario: Embedder inspects built-in ownership and supported distributions
- **WHEN** an embedder inspects the built-in runtime pack contract, first-party distribution list, or built-in owner metadata
- **THEN** the runtime SHALL publish `weavert-core`, `weavert-default`, and `weavert-full` as the canonical built-in distributions
- **AND** it SHALL publish canonical built-in owner package identifiers using the `weavert-*` prefix
