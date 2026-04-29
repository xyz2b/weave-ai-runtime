## ADDED Requirements

### Requirement: External runtime package registration SHALL be explicit and config-owned
The runtime SHALL expose an explicit config-owned registration input for local external runtime package manifests, such as `RuntimeConfig.extra_package_manifests`. This input SHALL accept local `RuntimePackageManifest` definitions or manifest entrypoints that resolve to the same manifest contract. Callers that do not use this input SHALL continue to receive the existing first-party distribution package set unchanged.

#### Scenario: caller registers a local external manifest
- **WHEN** a caller supplies an external runtime package manifest through the config-owned registration input
- **THEN** the runtime SHALL admit that manifest through the same runtime-owned registration flow used to prepare first-party manifests for assembly
- **AND** SHALL NOT require the caller to patch `FIRST_PARTY_PACKAGE_SPECS` or `official_runtime_package_manifests()`

#### Scenario: caller omits external registration
- **WHEN** a caller does not supply any external runtime package manifests
- **THEN** the runtime SHALL assemble the same first-party package set that the selected distribution and explicit `enabled_packages` / `disabled_packages` inputs would have produced before this change

### Requirement: Registered external manifests SHALL be validated before admission
The runtime SHALL validate each external package manifest before admitting it to the merged package set. Validation SHALL cover manifest shape, duplicate external package names, collisions with reserved official first-party package names, and dependency references against the selected first-party and admitted external manifest set. A failed validation MUST reject that external manifest before package contribution assembly begins. This change SHALL NOT define an implicit or explicit override mode for package-name collisions.

#### Scenario: external registration reuses another external package name
- **WHEN** two external manifests are registered with the same package name for one runtime instance
- **THEN** the runtime SHALL reject the later registration with a deterministic collision diagnostic
- **AND** SHALL NOT admit both manifests into the active merged package set

#### Scenario: external registration reuses an official first-party package name
- **WHEN** an external manifest is registered with the same package name as an official first-party runtime package
- **THEN** the runtime SHALL reject that registration as a reserved-name collision
- **AND** SHALL NOT replace the official first-party manifest implicitly

#### Scenario: external manifest depends on an unknown package
- **WHEN** an external manifest declares a dependency that is not present in the selected first-party package set or the admitted external manifest set
- **THEN** the runtime SHALL reject that external manifest before contribution assembly
- **AND** SHALL emit a machine-readable dependency-validation diagnostic

### Requirement: External registration SHALL preserve protocol-only trust boundaries
The runtime SHALL admit external packages only through the published `RuntimePackageManifest` and `PackageContribution` seams used by first-party packages. Registration SHALL preserve provenance showing that a package came from an external registration path, and SHALL NOT treat arbitrary objects or kernel-owned table mutation as an equivalent package integration path.

#### Scenario: manifest entrypoint does not resolve to a runtime package manifest
- **WHEN** an external registration entrypoint resolves to an object that does not satisfy the `RuntimePackageManifest` contract
- **THEN** the runtime SHALL reject that registration during registration validation
- **AND** SHALL emit a trust-boundary diagnostic instead of treating the object as an ad hoc kernel extension
