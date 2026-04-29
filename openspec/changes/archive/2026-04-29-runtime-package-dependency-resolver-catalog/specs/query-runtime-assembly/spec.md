## ADDED Requirements

### Requirement: Runtime assembly metadata SHALL publish raw package candidates separately from the resolved graph
The runtime SHALL publish a `package_resolution` metadata section that reports the raw package candidate catalog, the package request inputs used for resolution, the resolved package graph, and resolution diagnostics. This section SHALL remain separate from `package_registration`, `package_manifests`, and `core_protocol_catalog`.

#### Scenario: metadata distinguishes candidate inventory from resolved package graph
- **WHEN** more than one package candidate is present for a package name or the candidate catalog contains packages that are not selected into the final runtime
- **THEN** `package_resolution.candidate_catalog` SHALL report the raw candidate inventory
- **AND** `package_resolution.resolved_graph` SHALL report only the selected candidate graph for the active runtime
- **AND** `package_manifests` SHALL continue to describe only the manifests that actually reached package assembly
