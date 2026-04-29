## Why

`runtime-team` already has canonical capability keys, lifecycle participants, and a workflow host facet, but `runtime-core` still carries package-specific team bridges on the host contract, runtime assembly surface, bound-host helpers, and compatibility projections. As long as those bridges remain necessary for runtime-owned primary paths, team behavior still widens the microkernel instead of attaching through protocols alone.

This is the right time to finish that migration. The canonical team protocol surfaces already exist, and moving the remaining wrappers out of the normative path will make team the first first-party package that is truly protocol-only from the perspective of `runtime-core` owner layers.

## What Changes

- Make team capability keys and host facets the only normative discovery path for runtime-owned and host-owned team behavior.
- **BREAKING** remove package-specific team helper surfaces from `RuntimeAssembly`, `RuntimeServices`, and `BoundHostRuntime` as canonical APIs, keeping only protocol-owned access paths.
- Replace the package-specific `emit_team_event()` host-bridge method with a generic extension-event emission contract that does not embed team vocabulary in the mandatory host bridge.
- Keep team recovery and session-open replay behavior attached only through lifecycle participants rather than controller or kernel special cases.
- Publish structured conformance findings that prove team behavior remains available through canonical capability, host-facet, lifecycle, and extension-event paths with no dependence on package-specific bridges.
- Add migration notes and host-facing replacement examples for the removed wrappers and bridge methods.

## Capabilities

### New Capabilities
- `runtime-extension-host-events`: Defines a generic extension-event host-bridge contract for package-owned host event emission without package-specific bridge methods.

### Modified Capabilities
- `host-runtime-bridge`: Optional package-owned host interactions move to host facets and generic extension-event emission rather than package-specific team methods on the mandatory host bridge.
- `runtime-lifecycle-ownership`: Team replay and recovery behavior remain package-owned lifecycle participation rather than controller-owned or kernel-owned special cases.
- `runtime-control-plane-spine`: Runtime-owned primary paths stop depending on team-specific projections and helper wrappers.
- `query-runtime-conformance`: Conformance checks prove that team behavior remains protocol-only from the perspective of runtime-owned primary paths and publish structured rule findings for the terminal gate.

## Impact

- Affected code:
  - `src/runtime/hosts/base.py`
  - `src/runtime/runtime_services/__init__.py`
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/runtime_package_protocols.py`
  - `src/runtime/runtime_package_manifests.py`
  - `src/runtime/team_control_plane.py`
  - `src/runtime/team_message_bus.py`
  - `src/runtime/team_workflows.py`
  - `src/runtime/session_runtime/controller.py`
- Affected public/runtime contract:
  - bound-host workflow helpers
  - team-specific runtime projections
  - package-specific host event emission vocabulary
- Affected docs:
  - migration notes for team helper removal
  - host integration guidance for extension-event handling
  - package lookup and protocol-only architecture docs

## Roadmap Fit

- Rollout wave: Wave 2 breaking migration.
- Recommended order: land after the two Wave 1 foundation changes and before `dekernelize-first-party-package-catalog-and-enforce-protocol-conformance` turns protocol-only conformance into a terminal gate.
- Coordination note: this can land independently of `close-invocation-provider-config-bypass`, but the two explicit embedder-facing breaks should not share the same flag day when avoidable.
- Breaking surface: the generic extension-event contract, host-facet replacement path, and migration examples must be published before the package-specific wrappers are removed.

