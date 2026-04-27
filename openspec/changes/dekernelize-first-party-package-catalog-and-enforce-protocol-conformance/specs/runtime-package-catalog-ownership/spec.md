## ADDED Requirements

### Requirement: Official first-party package catalog SHALL be manifest-backed and self-describing
The runtime SHALL define the official first-party package catalog as a manifest-backed self-describing catalog rather than as package-name-specific kernel assembly switch logic.

#### Scenario: runtime loads the official first-party package catalog
- **WHEN** the runtime prepares the official first-party package inventory for package selection and assembly
- **THEN** it SHALL obtain that inventory through the official manifest-backed package catalog
- **AND** SHALL preserve package identity, role, dependency, and assembly provenance in that catalog

### Requirement: Supported distribution composition SHALL consume the official package catalog
The runtime SHALL derive supported distribution composition from the official package catalog rather than from hand-maintained package-specific kernel assembly switch tables.

#### Scenario: runtime assembles a supported distribution
- **WHEN** the runtime assembles `runtime-core`, `runtime-default`, or `runtime-full`
- **THEN** it SHALL derive the package composition for that supported distribution from the official package catalog
- **AND** SHALL preserve the same supported distribution names and semantics while removing kernel-owned package-specific assembly switch logic as the source of truth
