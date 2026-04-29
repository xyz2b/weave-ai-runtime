## ADDED Requirements

### Requirement: Kernel package selection SHALL consume the official package catalog provider
The runtime kernel SHALL consume the official package catalog provider when selecting and assembling official first-party packages rather than relying on package-name-specific kernel assembly branch tables as the canonical package-selection contract.

#### Scenario: kernel assembles selected official packages
- **WHEN** the runtime kernel selects official first-party packages for assembly
- **THEN** it SHALL resolve those packages through the official package catalog provider
- **AND** SHALL NOT require package-name-specific kernel assembly branch tables to remain the canonical package-selection contract
