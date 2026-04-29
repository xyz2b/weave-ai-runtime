## ADDED Requirements

### Requirement: Runtime assembly metadata SHALL publish package registration separately from package inventory
The runtime SHALL publish a `package_registration` metadata section that describes accepted and rejected external manifest registrations and their diagnostics. This section SHALL remain separate from `first_party_packages`, `first_party_package_catalog`, `package_manifests`, `package_lookup`, and `core_protocol_catalog`.

#### Scenario: caller inspects metadata after external package registration
- **WHEN** a caller inspects runtime assembly metadata after one or more external package registrations were processed
- **THEN** the metadata SHALL expose `package_registration.accepted`, `package_registration.rejected`, and `package_registration.diagnostics`
- **AND** `package_manifests` SHALL describe only the merged admitted manifest set that actually participated in assembly
- **AND** stable protocol metadata SHALL remain in `core_protocol_catalog` instead of being redefined inside `package_registration`
