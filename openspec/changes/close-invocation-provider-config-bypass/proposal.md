## Why

The invocation registry already supports package-contributed providers, but `RuntimeConfig.extra_invocation_providers` still leaves one protocol-external registration tier alive. As long as runtime-owned assembly continues to treat config-supplied providers as a first-class canonical path, invocation-provider extensibility is still only partly package-driven.

To reach a fully protocol-only runtime core, invocation providers should attach the same way other package-owned runtime capabilities do: through `RuntimePackageManifest` and `PackageContribution`. This change closes the remaining config bypass and replaces it with a lightweight provider-only package pattern for embedders.

## What Changes

- Introduce the runtime-owned package-only invocation-provider extension contract as the normative way to add custom invocation providers.
- **BREAKING** remove `RuntimeConfig.extra_invocation_providers` as a canonical runtime assembly input.
- Define a lightweight provider-only runtime package pattern so embedders do not need a large package bundle just to contribute invocation providers.
- Keep the built-in skill invocation provider baseline, then register only package-contributed invocation providers after it.
- Update runtime assembly metadata, diagnostics, and docs so invocation-provider provenance no longer includes a config-owned bypass tier.
- Publish structured provider-provenance conformance findings so the terminal protocol-only gate can consume this rule family without re-implementing registry-specific audits.
- Add migration and conformance coverage for provider registration order, provenance, and replacement behavior under the package-only model.

## Capabilities

### New Capabilities
- `runtime-package-invocation-providers`: Defines the package-only contract for custom invocation-provider registration and lightweight provider-only runtime packages.

### Modified Capabilities
- `invocation-catalog`: Invocation-provider registration precedence and provenance become package-only after the built-in baseline rather than baseline-plus-config-bypass.
- `query-runtime-assembly`: Runtime assembly publishes invocation-provider provenance from the built-in baseline and package-contributed providers only.
- `query-runtime-conformance`: Conformance checks prove that invocation providers no longer enter the runtime through a config-owned bypass tier and publish structured rule findings for the terminal gate.

## Impact

- Affected code:
  - `src/runtime/runtime_kernel/config.py`
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/registries/invocation_registry.py`
  - `src/runtime/runtime_package_protocols.py`
  - `src/runtime/runtime_package_manifests.py`
  - `src/runtime/runtime_core_protocol_catalog.py`
- Affected docs and metadata:
  - invocation-provider path metadata
  - extension guide sections that still mention `extra_invocation_providers`
  - migration notes for embedder-supplied providers
- Affected external integrations:
  - embedders that currently inject custom invocation providers through config must convert them into provider-only runtime packages

## Roadmap Fit

- Rollout wave: Wave 2 breaking migration.
- Recommended order: land after the Wave 1 foundations and after the already-complete external package registration and package-contributed invocation-provider work, but before the terminal conformance/catalog change.
- Coordination note: this can land independently of `remove-runtime-team-compatibility-bridges`, but the two explicit embedder-facing breaks should not share the same flag day when avoidable.
- Breaking surface: provider-only package examples, templates, and migration docs should ship before the config-owned bypass is removed.

