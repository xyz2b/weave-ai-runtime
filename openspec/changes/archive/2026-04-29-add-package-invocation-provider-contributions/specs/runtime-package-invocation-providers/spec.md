## ADDED Requirements

### Requirement: Runtime packages SHALL be able to contribute invocation providers
The runtime SHALL allow a package manifest contribution to contribute invocation providers to the shared invocation registry with explicit package ownership metadata and deterministic registration semantics.

#### Scenario: package contributes an invocation provider
- **WHEN** a selected runtime package returns an invocation-provider contribution from its manifest contribution
- **THEN** the kernel SHALL register that provider in the shared invocation registry before the active invocation catalog is resolved
- **AND** SHALL preserve package ownership attribution for diagnostics and metadata

### Requirement: Package-contributed providers SHALL participate in the same registry and diagnostics flow
The runtime SHALL process package-contributed invocation providers through the same invocation registry conflict-resolution and diagnostics path used for built-in and config-supplied providers.

#### Scenario: package provider conflicts with another provider
- **WHEN** a package-contributed invocation provider emits an invocation definition that conflicts with another visible provider definition
- **THEN** the runtime SHALL resolve that conflict through the shared invocation-registry rules
- **AND** SHALL emit deterministic diagnostics rather than requiring package-specific conflict handling

### Requirement: Provider registration precedence and replacement SHALL be explicit
The runtime SHALL register invocation providers in deterministic precedence order: built-in skill provider baseline first, package-contributed providers second, and config-supplied providers last. When a later registration reuses the same `provider.name`, the runtime SHALL replace the earlier provider and emit an explicit provider-replacement diagnostic.

#### Scenario: config-supplied provider replaces same-name package provider
- **WHEN** a config-supplied invocation provider registers after a package-contributed provider with the same `provider.name`
- **THEN** the runtime SHALL keep the later config-supplied provider as the active provider for that name
- **AND** SHALL emit a provider-replacement diagnostic distinct from any invocation-definition conflict diagnostics

### Requirement: Package contributions SHALL NOT replace embedder config as the only provider input
The runtime SHALL keep a bounded config-owned invocation-provider registration path for embedders even after package-contributed providers become the canonical package-owned path.

#### Scenario: embedder adds a config-supplied provider
- **WHEN** a caller registers an invocation provider through runtime configuration instead of package contribution
- **THEN** the runtime SHALL still admit that provider into the shared invocation registry
- **AND** SHALL NOT require embedders to wrap every custom provider inside a runtime package manifest
