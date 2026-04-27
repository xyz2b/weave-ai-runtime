## ADDED Requirements

### Requirement: Official built-ins SHALL be attachable through package-contributed built-in definitions
The runtime SHALL allow official first-party packages to attach owned tools, agents, and skills through package-contributed built-in definitions rather than requiring kernel-owned optional loader tables as the primary attachment contract.

#### Scenario: Higher-level first-party package contributes built-ins
- **WHEN** an official first-party package owns one or more bundled tools, agents, or skills
- **THEN** the runtime SHALL be able to register those definitions through the package-contribution path
- **AND** the package ownership of those definitions SHALL remain observable through built-in ownership metadata or equivalent diagnostics

### Requirement: Built-in package contribution SHALL preserve supported distribution semantics
The runtime SHALL preserve the current supported distribution semantics for core and higher-level first-party built-ins when moving built-in attachment to package contributions.

#### Scenario: Runtime assembles different supported distributions
- **WHEN** the runtime assembles `runtime-core`, `runtime-default`, or `runtime-full`
- **THEN** it SHALL continue to expose the built-ins owned by the selected official packages for that distribution
- **AND** moving built-in attachment behind package contributions SHALL NOT require collapsing higher-level built-ins back into `runtime-core`

### Requirement: Built-in package contribution SHALL preserve disable and replacement semantics
The runtime SHALL preserve the current ability to disable or replace official built-in definitions when moving official built-in attachment behind package contributions.

#### Scenario: Caller disables an official package-contributed built-in
- **WHEN** a caller configures one or more official built-in tools, agents, or skills as disabled
- **THEN** the runtime SHALL suppress those definitions even if they are contributed by an official package
- **AND** it SHALL preserve the remaining package-contributed definitions for the selected distribution

#### Scenario: Caller replaces an official package-contributed built-in
- **WHEN** a caller supplies a replacement definition for an official built-in owned by a selected package
- **THEN** the runtime SHALL register the replacement under the same public built-in identity
- **AND** it SHALL preserve package ownership and diagnostic visibility semantics for that replacement path or equivalent migration metadata
