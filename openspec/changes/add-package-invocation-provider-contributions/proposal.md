## Why

The runtime already has a unified invocation catalog, but provider registration is still asymmetric. `SkillInvocationProvider` is hard-wired during kernel assembly, and any other provider must arrive through `RuntimeConfig.extra_invocation_providers`, which means a first-party package cannot add invocation sources through the same manifest and contribution path used for built-ins, capabilities, host facets, or model routes.

This gap matters now because package-owned command-like surfaces are growing, and each new provider should not require another kernel-specific or config-specific registration path. Invocation providers need to become first-class package contributions before external package registration is even considered.

## What Changes

- Introduce package contribution support for invocation providers, including owner metadata and deterministic registration behavior.
- Register package-contributed invocation providers during kernel assembly so they participate in the same invocation registry and diagnostics flow as built-in and config-supplied providers.
- Define deterministic provider registration precedence: built-in skill provider baseline first, package-contributed providers second, and config-supplied providers last, with same-name provider replacement treated as an explicit override path distinct from invocation-definition conflict resolution.
- Keep `RuntimeConfig.extra_invocation_providers` as a bounded embedder compatibility and override surface rather than removing it in a flag day.
- Make package-contributed providers part of the canonical invocation catalog story instead of treating them as ad hoc side inputs.
- Preserve current path-aware and policy-aware catalog resolution semantics while allowing more package-owned invocation sources to join the same catalog.
- Explicitly defer external package ABI design, remote plugin distribution, and non-runtime installation concerns.

## Capabilities

### New Capabilities
- `runtime-package-invocation-providers`: Defines how runtime packages contribute invocation providers to the shared invocation registry through manifest-backed package contributions.

### Modified Capabilities
- `invocation-catalog`: The unified catalog now aggregates package-contributed invocation providers through the canonical package contribution path in addition to built-in and config-supplied providers.
- `query-runtime-assembly`: Kernel and runtime assembly register package-contributed invocation providers deterministically before hosts resolve the active invocation catalog.

## Impact

- Affected code:
  - `src/runtime/runtime_package_protocols.py`
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/runtime_kernel/config.py`
  - `src/runtime/registries/invocation_registry.py`
  - `src/runtime/invocation_catalog.py`
  - `src/runtime/runtime_package_manifests.py`
- Affected docs:
  - `docs/current-system-architecture.md`
  - `docs/runtime-integration-guide.md`
  - `docs/runtime-user-extension-guide.md`
- Affected contracts:
  - package contribution schema for invocation providers
  - invocation-registry registration order, provider replacement rules, and owner-aware diagnostics
  - compatibility status of `extra_invocation_providers`
