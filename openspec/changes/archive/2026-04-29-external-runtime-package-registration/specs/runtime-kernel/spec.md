## ADDED Requirements

### Requirement: Kernel package assembly SHALL merge admitted external manifests with selected first-party manifests
The runtime kernel SHALL resolve the selected first-party package set from distribution defaults and explicit package toggles, then merge any admitted external package manifests into that set before package ordering and package contribution assembly run.

#### Scenario: admitted external package depends on a selected first-party package
- **WHEN** the selected distribution includes `runtime-core` and the caller registers an external manifest that depends on `runtime-core`
- **THEN** the kernel SHALL include the admitted external manifest in the merged package set
- **AND** SHALL order that merged set through the same dependency-ordering path used for first-party packages

### Requirement: Registration rejection SHALL happen before package contribution assembly
The runtime kernel SHALL surface package-registration diagnostics and exclude rejected external manifests before built-in, services, runtime, lifecycle, or host-facet package contributions are applied.

#### Scenario: rejected external manifest is excluded from assembly
- **WHEN** an external manifest is rejected during registration validation
- **THEN** the kernel SHALL record the rejection diagnostic before package assembly continues
- **AND** SHALL NOT call that rejected manifest's assembly entrypoint for any package assembly stage
