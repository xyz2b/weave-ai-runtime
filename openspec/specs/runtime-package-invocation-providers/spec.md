# runtime-package-invocation-providers Specification

## Purpose
TBD - created by archiving change add-package-invocation-provider-contributions. Update Purpose after archive.
## Requirements
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

### Requirement: Custom invocation providers SHALL attach through runtime package contributions
The runtime SHALL require custom invocation providers to attach through `RuntimePackageManifest` and `PackageContribution.invocation_providers` rather than through a config-owned runtime assembly bypass.

#### Scenario: embedder contributes a custom invocation provider
- **WHEN** an embedder needs to add a custom invocation provider to the runtime
- **THEN** the runtime SHALL admit that provider through a runtime package manifest and package contribution
- **AND** SHALL NOT require a config-owned provider-registration bypass as part of the normative extension contract

### Requirement: Runtime SHALL support lightweight provider-only runtime packages
The runtime SHALL support lightweight runtime packages whose only purpose is to contribute one or more invocation providers.

#### Scenario: provider-only package is registered
- **WHEN** an embedder registers a runtime package whose contribution surface contains invocation providers and no broader runtime subsystem
- **THEN** the runtime SHALL be able to assemble and admit that package under the ordinary runtime package contract
- **AND** SHALL NOT require unrelated built-ins or runtime-owned services to exist just because the package contributes invocation providers

### Requirement: Provider-only packages SHALL use an ordinary minimal manifest shape
The runtime SHALL treat provider-only packages as ordinary runtime packages with a documented minimal manifest shape rather than requiring a dedicated provider-only manifest role.

#### Scenario: embedder authors a provider-only manifest
- **WHEN** an embedder authors a provider-only runtime package manifest
- **THEN** the runtime SHALL accept ordinary package identity and dependency metadata plus one or more `invocation_providers` contributions as sufficient for the normative package shape
- **AND** SHALL continue to apply the ordinary package and contribution ordering rules without requiring a dedicated provider-only taxonomy

