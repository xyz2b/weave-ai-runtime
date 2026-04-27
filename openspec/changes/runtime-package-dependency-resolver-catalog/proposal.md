## Why

The current package loader can only topologically order one manifest per package name. That is enough for today’s official first-party set, but it is not enough for a runtime that wants explicit external package registration, versioned candidates, optional package sets, or useful diagnostics when dependencies conflict.

This gap is downstream of external registration and should stay separate from it. Once the runtime can register local package candidates, it needs a deterministic package catalog and dependency resolver that selects one manifest graph before assembly begins, without also turning into a package installer.

## What Changes

- Introduce a local runtime package catalog that normalizes official first-party manifests and accepted external registrations into package candidates, and can hold more than one local candidate per package name before deterministic dependency resolution.
- Define package candidate identity, dependency constraints, compatibility diagnostics, and resolution outcomes separately from the package contribution assembly contract.
- Resolve distribution baselines and explicit package requests into a single manifest graph before the runtime performs dependency ordering and contribution application.
- Surface structured diagnostics for missing packages, conflicting constraints, cyclic dependencies, and incompatible candidate selections.
- Keep the resolver local and install-agnostic; do not add remote fetching, publishing, or environment package management in this change.
- Preserve a migration path from the current single-manifest-per-name first-party world so the runtime can adopt catalog resolution incrementally.

## Capabilities

### New Capabilities
- `runtime-package-catalog-resolution`: Defines the local package catalog, dependency constraint model, and deterministic manifest-graph resolution contract used before package assembly.

### Modified Capabilities
- `runtime-kernel`: Package assembly changes from direct selection of one manifest per name to resolution of a manifest graph from a local package catalog before dependency ordering.
- `query-runtime-assembly`: Assembled runtime metadata reports the resolved package graph and resolution diagnostics separately from raw registered package candidates.

## Impact

- Affected code:
  - `src/runtime/runtime_package_protocols.py`
  - `src/runtime/runtime_package_manifests.py`
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/runtime_kernel/config.py`
  - `src/runtime/package_profiles.py`
- Affected docs:
  - `docs/current-system-architecture.md`
  - `docs/runtime-integration-guide.md`
  - `docs/runtime-migration-notes.md`
- Affected contracts:
  - local runtime package catalog model
  - package dependency and compatibility constraint schema
  - resolution diagnostics and resolved-graph metadata
