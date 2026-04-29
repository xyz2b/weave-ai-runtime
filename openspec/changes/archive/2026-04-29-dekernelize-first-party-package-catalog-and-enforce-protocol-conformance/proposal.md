## Why

Even after the remaining compatibility bridges are removed, two things can still pull the architecture back toward `runtime-core` package awareness: the official first-party package catalog is still owned by kernel-side tables and switch logic, and there is not yet a formal conformance gate that fails when runtime-owned primary paths reintroduce forbidden compatibility surfaces or package-specific assembly branches.

This change closes the loop. It moves the official package catalog to a manifest-backed ownership model and adds a protocol-only conformance gate, so the target architecture becomes both structurally true and mechanically enforced.

## What Changes

- Replace kernel-owned official first-party package tables and assembly switch logic with a manifest-backed official package catalog provider.
- Keep supported distribution composition, but source it from the official package catalog rather than hard-coded kernel-owned assembly tables.
- Publish explicit assembly provenance for the official package catalog, resolved package graph, and protocol-only conformance summary.
- Aggregate per-rule findings from the privileged-service-slot, context-authority, task-authority, team-bridge, provider-provenance, and kernel-assembly rule families into one terminal protocol-only gate.
- Add protocol-only conformance rules that fail when runtime-owned primary paths depend on forbidden compatibility surfaces or package-specific kernel assembly branches.
- Treat the kernel-owned package catalog tables and similar assembly branches as retired implementation details rather than canonical runtime architecture.

## Capabilities

### New Capabilities
- `runtime-package-catalog-ownership`: Defines manifest-backed ownership for the official first-party package catalog and supported distribution composition.

### Modified Capabilities
- `runtime-kernel`: Kernel boot and package selection consume the official package catalog provider rather than hard-coded package-name-specific assembly tables.
- `query-runtime-assembly`: Assembled runtimes publish official package-catalog provenance, resolved package-graph provenance, and protocol-only conformance summary metadata.
- `query-runtime-conformance`: Conformance checks detect forbidden compatibility-surface dependence and package-specific kernel assembly branches, using structured rule findings from the earlier roadmap changes where possible.

## Impact

- Affected code:
  - `src/runtime/package_profiles.py`
  - `src/runtime/runtime_package_manifests.py`
  - `src/runtime/runtime_package_resolution.py`
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/runtime_core_protocol_catalog.py`
- Affected metadata and diagnostics:
  - first-party package catalog metadata
  - runtime assembly provenance
  - protocol-only conformance summary
- Affected docs:
  - package/distribution architecture docs
  - migration notes for official package catalog ownership
  - conformance and extension guidance

## Roadmap Fit

- Rollout wave: Wave 3 terminal enforcement.
- Recommended order: land last, after `retire-runtime-context-and-taskmanager-compat`, `eliminate-privileged-runtime-package-service-slots`, `remove-runtime-team-compatibility-bridges`, and `close-invocation-provider-config-bypass` have already published their canonical metadata and structured rule findings.
- Downstream effect: this change should not introduce a new public API break, but it will harden CI and runtime conformance so that any missing earlier cleanup becomes an immediate failure.
- Test ownership: this change owns the final cross-distribution protocol-only matrix across `runtime-core`, `runtime-default`, and `runtime-full`.
