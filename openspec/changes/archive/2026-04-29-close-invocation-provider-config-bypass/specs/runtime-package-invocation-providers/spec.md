## ADDED Requirements

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
