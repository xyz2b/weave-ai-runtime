# runtime-package-catalog-resolution Specification

## Purpose
TBD - created by archiving change runtime-package-dependency-resolver-catalog. Update Purpose after archive.
## Requirements
### Requirement: Runtime package catalogs SHALL normalize manifests into candidate descriptors
The runtime SHALL represent pre-assembly package selection through a local catalog of package candidate descriptors. Each candidate descriptor SHALL wrap one `RuntimePackageManifest` and SHALL include at least `package_name`, `candidate_id`, `source`, and dependency-constraint metadata. Official first-party manifests and admitted external registrations MUST each normalize into at least one candidate descriptor before resolution begins.

#### Scenario: official and external manifests become package candidates
- **WHEN** the runtime prepares the package catalog for one runtime instance
- **THEN** each selected official first-party manifest SHALL appear as at least one package candidate descriptor
- **AND** each admitted external registration SHALL appear through the same candidate-descriptor model instead of bypassing the catalog

### Requirement: Dependency constraints SHALL support both legacy and structured forms
The runtime SHALL support the current flat `RuntimePackageManifest.dependencies` tuple as a compatibility dependency form, and SHALL also support structured dependency constraints that identify a target package name plus either an exact candidate reference or a bounded compatible version range.

#### Scenario: legacy flat dependency remains valid
- **WHEN** a package candidate is derived from a manifest that only declares flat package-name dependencies
- **THEN** the resolver SHALL interpret those dependencies as compatibility-path package requirements without forcing that manifest to adopt a richer candidate syntax first

#### Scenario: structured candidate constraint narrows selection
- **WHEN** a package candidate declares a structured dependency constraint that names a package and an exact candidate identity or compatible version range
- **THEN** the resolver SHALL use that structured constraint to narrow candidate selection for the target package

### Requirement: Package resolution SHALL use an explicit runtime-owned request model
The runtime SHALL resolve package candidates from a runtime-owned request model that combines distribution baseline package names with explicit caller package requests. This request model SHALL preserve compatibility for current first-party `enabled_packages` / `disabled_packages` inputs and SHALL allow explicit requests for admitted external package names without requiring those names to be added to `FIRST_PARTY_PACKAGE_SPECS`.

#### Scenario: legacy first-party package toggles remain valid resolution inputs
- **WHEN** a caller only uses the current distribution selection plus first-party `enabled_packages` / `disabled_packages`
- **THEN** the resolver SHALL interpret those inputs through the runtime-owned request model without requiring the caller to adopt a new external-package-specific API first

#### Scenario: caller explicitly requests an admitted external package
- **WHEN** a caller requests an admitted external package by package name for one runtime instance
- **THEN** the resolver SHALL include that package request in candidate-graph selection
- **AND** SHALL NOT require that external package name to be inserted into official first-party distribution tables

### Requirement: Resolution SHALL select one candidate graph or emit structured diagnostics
Given a distribution baseline and explicit package requests, the runtime SHALL resolve one candidate per package name into a concrete manifest graph or emit machine-readable diagnostics that explain why no valid graph exists. Diagnostics SHALL distinguish at least missing packages, conflicting constraints, incompatible candidates, and cyclic dependencies.

#### Scenario: requested package has no satisfiable candidate
- **WHEN** the package catalog does not contain any candidate that satisfies a requested package or dependency constraint
- **THEN** the resolver SHALL fail that resolution attempt with a structured missing-package or incompatible-candidate diagnostic

#### Scenario: competing constraints cannot be satisfied together
- **WHEN** two or more package constraints select incompatible candidates for the same package
- **THEN** the resolver SHALL fail that resolution attempt with a structured conflicting-constraints diagnostic instead of silently picking an arbitrary candidate

### Requirement: Resolved manifest graphs SHALL feed the existing assembly contract
After resolution succeeds, the runtime SHALL pass the selected manifest graph into the existing dependency-ordering and package-contribution assembly flow. The manifest assembly contract SHALL remain `RuntimePackageManifest` plus `PackageContribution`; the resolver SHALL NOT require a separate package-contribution protocol.

#### Scenario: resolved graph proceeds to package ordering
- **WHEN** the resolver produces a valid manifest graph for the requested runtime
- **THEN** the runtime SHALL order the selected manifests through the existing dependency-ordering path before contribution assembly
- **AND** SHALL assemble package contributions from the selected manifests without introducing a parallel package-contribution contract

