## 1. Registration Input And Validation

- [x] 1.1 Add a config-owned external package registration input, such as `RuntimeConfig.extra_package_manifests`, together with manifest loading and normalization helpers.
- [x] 1.2 Validate registered external manifests for manifest shape, duplicate external package names, reserved official first-party package names, dependency references, and the absence of any override mode before admission.
- [x] 1.3 Define accepted/rejected registration records and machine-readable registration diagnostics with external provenance and trust-boundary details.

## 2. Kernel Integration

- [x] 2.1 Merge admitted external manifests with the selected first-party package set before package ordering and package contribution assembly.
- [x] 2.2 Ensure rejected external manifests never reach built-in, services, runtime, lifecycle, or host-facet package contribution assembly.
- [x] 2.3 Preserve unchanged first-party-only behavior when no external manifests are registered and keep external packages on the same manifest/contribution path as first-party packages.

## 3. Metadata And Diagnostics

- [x] 3.1 Publish a `package_registration` metadata section that reports accepted and rejected external registrations separately from `first_party_packages`, `package_manifests`, `package_lookup`, and `core_protocol_catalog`.
- [x] 3.2 Surface registration diagnostics and provenance in both runtime-services metadata and assembled runtime metadata for debugging and integration visibility.

## 4. Coverage And Docs

- [x] 4.1 Add regression tests for successful external registration, duplicate external package collisions, reserved first-party name collisions, and unknown dependency rejection.
- [x] 4.2 Add regression tests proving rejected external manifests never execute assembly entrypoints and that admitted manifests appear in merged package inventory metadata.
- [x] 4.3 Update architecture and extension docs to describe explicit local external package registration, collision rules, trust boundaries, and registration diagnostics.
