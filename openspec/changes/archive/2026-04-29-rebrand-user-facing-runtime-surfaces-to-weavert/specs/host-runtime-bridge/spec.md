## ADDED Requirements

### Requirement: Host-visible extension namespaces SHALL use WeaveRT identifiers
The runtime SHALL expose WeaveRT-branded canonical identifiers for host-visible extension-event namespaces and related public bridge metadata. When the host bridge surfaces capability-specific extension namespaces, the canonical namespace SHALL use the `weavert.*` form instead of `runtime.*`.

#### Scenario: Host receives a capability-specific extension event
- **WHEN** the runtime emits an extension event for a first-party capability such as team coordination
- **THEN** the host-visible canonical namespace SHALL use `weavert.*`
- **AND** the runtime SHALL NOT advertise `runtime.*` as the canonical public namespace for that event family
