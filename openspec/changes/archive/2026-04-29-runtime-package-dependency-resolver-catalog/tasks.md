## 1. Catalog Model

- [x] 1.1 Introduce a package candidate descriptor and local package catalog container around `RuntimePackageManifest`, including candidate identity, source provenance, and dependency-constraint metadata.
- [x] 1.2 Normalize official first-party manifests and admitted external registrations into package candidates while preserving compatibility for current flat manifest dependencies.
- [x] 1.3 Define machine-readable package-resolution diagnostics for missing packages, conflicting constraints, incompatible candidates, and cyclic dependencies.

## 2. Resolution Engine

- [x] 2.1 Define a runtime-owned package request model that extends current distribution defaults and first-party `enabled_packages` / `disabled_packages` inputs while allowing explicit requests for admitted external package names.
- [x] 2.2 Resolve distribution defaults and explicit package requests into one concrete package candidate graph before package ordering and contribution assembly run.
- [x] 2.3 Feed the selected manifest graph into the existing dependency-ordering and package-contribution assembly flow without introducing a separate contribution contract.
- [x] 2.4 Stop assembly deterministically when resolution fails and surface the resulting diagnostics through the runtime-owned kernel path.

## 3. Metadata Integration

- [x] 3.1 Publish a `package_resolution` metadata section that reports the raw candidate catalog, resolution inputs, resolved graph, and resolution diagnostics.
- [x] 3.2 Keep `package_resolution` separate from `package_registration`, `package_manifests`, `package_lookup`, and `core_protocol_catalog` while preserving current first-party inventory metadata.

## 4. Coverage And Docs

- [x] 4.1 Add regression tests for legacy flat dependencies, successful graph resolution, missing-package failures, conflicting-constraint failures, incompatible-candidate failures, and cyclic dependency failures.
- [x] 4.2 Add regression tests proving only the resolved manifest graph reaches package ordering and contribution assembly even when the raw catalog contains extra candidates.
- [x] 4.3 Update architecture, integration, and migration docs to describe the local package catalog, bounded dependency constraint model, resolved-graph metadata, and the continued non-goals around remote discovery, install, and environment package management.
