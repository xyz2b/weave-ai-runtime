## Why

The runtime already has canonical package-extension seams such as capability lookup, host-facet lookup, lifecycle participants, and job or task control-plane services, but runtime-owned owner layers still expose retained package-specific projections like `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, and host workflow helper methods. That makes it too easy for new first-party package work to widen core surfaces again instead of attaching through the published protocol paths.

This change closes that remaining seam before the framework opens up broader package registration and dependency-resolution work. The immediate need is to freeze and tighten first-party owner-layer boundaries, not to remove every compatibility wrapper in one patch or to design the external package ABI yet.

## What Changes

- Define a runtime-owned owner-layer boundary contract: package-owned behavior SHALL be consumed through canonical capability lookup, host-facet lookup, lifecycle participation, and runtime-owned control-plane services rather than new package-specific top-level fields or helpers.
- Reclassify retained package-specific projections on `RuntimeServices`, `RuntimeAssembly`, and `BoundHostRuntime` as thin compatibility wrappers only, with canonical lookup paths documented as the normative integration surface.
- Require runtime assembly metadata and integration guidance to publish the canonical package lookup keys, the retained compatibility wrappers, and the exit criteria for removing those wrappers.
- Freeze remaining `TaskManager`-shaped runtime seams as compatibility-only accessors over the shared job and task-list control planes, without requiring flag-day removal in this change.
- Keep package-owned workflow host operations optional and host-facet-backed so team-specific helpers stop widening the mandatory host bridge contract.
- Define bounded absent-package behavior for retained workflow compatibility helpers: observation helpers may degrade to empty results, while mutating helpers fail with explicit not-available errors instead of widening `HostRuntime`.
- Explicitly defer third-party package registration, package catalogs, semantic version or dependency resolution, and full compatibility-wrapper removal to later staged changes.

## Capabilities

### New Capabilities
- `runtime-package-owner-layer-boundaries`: Defines the canonical owner-layer rule for consuming first-party package behavior and labels retained package-specific projections as non-canonical compatibility surfaces.

### Modified Capabilities
- `host-runtime-bridge`: Optional package-owned host operations are discovered through host facets, while retained package-specific host helpers remain bounded compatibility wrappers.
- `runtime-control-plane-spine`: Runtime-owned execution and service assembly paths consume package-owned control-plane functionality through canonical capability and job/task service lookup rather than package-specific top-level slots.

## Impact

- Affected code:
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/runtime_services/__init__.py`
  - `src/runtime/hosts/base.py`
  - `src/runtime/tasking.py`
  - `src/runtime/team_control_plane.py`
  - `src/runtime/team_message_bus.py`
  - `src/runtime/builtins/tool_impls.py`
- Affected docs:
  - `docs/runtime-integration-guide.md`
  - `docs/runtime-control-plane-extension-guide.md`
- Affected contracts:
  - runtime metadata describing canonical package lookup paths
  - compatibility status for retained `team_*` projections and host workflow helpers
  - `TaskManager` as a compatibility-only facade over runtime-owned job control services
