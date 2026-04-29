## Why

The runtime’s package protocol is now strong enough for first-party packages, but registration is still closed over `FIRST_PARTY_PACKAGE_SPECS` and `official_runtime_package_manifests()`. An embedder cannot register an additional runtime package through a runtime-owned public path; the only practical option is to patch kernel-owned tables or vendor first-party code.

The next architectural gap is therefore external registration, not dependency solving yet. The runtime needs an explicit local package registration story that uses the same manifest and contribution protocol as first-party packages before any multi-version catalog or resolver work makes sense.

## What Changes

- Introduce an explicit config-owned registration path for external or embedder-owned runtime package manifests.
- Validate and merge registered external package manifests with the official first-party package set before package assembly begins.
- Define collision, override, diagnostics, and trust-boundary rules for externally registered package names and owned surfaces.
- Require external packages to use the same manifest, contribution, capability, host-facet, and lifecycle contracts as first-party packages instead of adding a side-door integration path.
- Keep registration local and explicit; do not introduce semantic-version solving, multi-candidate catalogs, remote discovery, or installation concerns in this change.
- Preserve the existing first-party distribution defaults so callers who do not opt into external registration see no behavioral change.

## Capabilities

### New Capabilities
- `runtime-package-registration`: Defines the explicit runtime-owned registration path for local external package manifests and the validation rules that govern them.

### Modified Capabilities
- `runtime-kernel`: Kernel package discovery expands from official first-party manifests only to an explicit merged registration set that may include external package manifests.
- `query-runtime-assembly`: Assembled runtime metadata reports registered external packages and registration diagnostics separately from first-party package defaults.

## Impact

- Affected code:
  - `src/runtime/runtime_kernel/config.py`
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/runtime_package_manifests.py`
  - `src/runtime/runtime_package_protocols.py`
  - `src/runtime/package_profiles.py`
- Affected docs:
  - `docs/current-system-architecture.md`
  - `docs/runtime-integration-guide.md`
  - `docs/runtime-user-extension-guide.md`
- Affected contracts:
  - config-owned external package registration input
  - registration-time collision and diagnostics rules
  - assembled runtime metadata for external package registration
