## ADDED Requirements

### Requirement: Kernel SHALL assemble selected official packages through manifest-driven dependency ordering
The runtime kernel SHALL assemble selected official first-party packages through manifest-driven dependency ordering and package contributions rather than relying on package-name-specific attachment logic as the primary official package integration mechanism.

#### Scenario: Assembling a runtime with several official packages
- **WHEN** the runtime kernel assembles a runtime that selects multiple official first-party packages
- **THEN** it SHALL resolve package dependency ordering from package manifests before applying package contributions
- **AND** it SHALL apply those packages through the shared package assembly path rather than requiring one custom kernel branch per package as the primary attachment contract

### Requirement: Kernel SHALL preserve the runnable core skeleton independent of optional package presence
The runtime kernel SHALL preserve the existing runnable kernel/session/turn skeleton when optional official packages are absent, while still allowing selected packages to contribute additional capabilities through the shared package integration contract.

#### Scenario: Runtime boots with only runtime-core-selected behavior
- **WHEN** the runtime assembles only the minimal core distribution or omits optional first-party packages
- **THEN** it SHALL still construct the kernel, session, and turn execution skeleton required for a runnable runtime
- **AND** optional package contribution points SHALL remain additive rather than a prerequisite for the core execution stack to exist
