## Why

The runtime already has manifest-backed package contributions, capability lookup, lifecycle participants, and host facets, but `runtime-core` still gives a few package-owned services privileged direct entry into owner-layer hot paths through `RuntimeServices.memory`, `RuntimeServices.compaction`, and `RuntimeServices.isolation`. As long as those dedicated slots remain canonical, the framework is still protocol-first rather than protocol-only.

This is the next structural seam to close. The runtime is now mature enough to move those package-owned services behind explicit runtime-owned protocol bindings without changing their behavioral semantics, which makes it possible to finish the microkernel boundary work without conflating it with a larger feature rewrite.

## What Changes

- Introduce explicit runtime-owned package-service protocol bindings for package-owned control-plane services that still reach owner layers through privileged dedicated slots.
- Make runtime-owned primary paths resolve memory-, compaction-, and isolation-owned behavior through canonical protocol bindings rather than direct `RuntimeServices` service slots.
- Reclassify `RuntimeServices.memory`, `RuntimeServices.compaction`, and `RuntimeServices.isolation` as bounded compatibility projections over canonical protocol bindings instead of normative extension surfaces.
- Publish protocol ownership, provenance, compatibility metadata, and structured conformance findings so embedders and later roadmap gates can distinguish canonical service bindings from retained projections.
- Preserve current memory, compaction, and isolation runtime behavior while migrating the lookup path that runtime-owned code uses to reach those behaviors.
- Add regression coverage that owner-layer runtime paths no longer require privileged package-specific service slots to remain operational.

## Capabilities

### New Capabilities
- `runtime-package-service-protocols`: Defines runtime-owned protocol bindings for package-owned control-plane services that previously depended on privileged `RuntimeServices` slots.

### Modified Capabilities
- `runtime-control-plane-spine`: Package-owned control-plane services are consumed through canonical protocol bindings rather than privileged dedicated service slots.
- `runtime-memory-manager`: The reference memory manager remains the same behavioral subsystem, but it attaches to runtime-owned owner layers through a protocol binding rather than a privileged `RuntimeServices.memory` slot.
- `runtime-compaction-manager`: The shared compaction manager remains the same behavioral subsystem, but it attaches to runtime-owned owner layers through a protocol binding rather than a privileged `RuntimeServices.compaction` slot.
- `runtime-isolation-control-plane`: Isolation preparation and cleanup remain the same behavioral subsystem, but they attach to runtime-owned owner layers through a protocol binding rather than a privileged `RuntimeServices.isolation` slot.
- `query-runtime-conformance`: Conformance checks prove that runtime-owned primary paths no longer depend on privileged dedicated service slots as the canonical source of truth.

## Impact

- Affected code:
  - `src/runtime/runtime_services/__init__.py`
  - `src/runtime/runtime_package_protocols.py`
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/session_runtime/controller.py`
  - `src/runtime/turn_engine/engine.py`
  - `src/runtime/tool_runtime.py`
  - `src/runtime/builtins/tool_impls.py`
  - `src/runtime/agent_execution_service.py`
  - `src/runtime/control_plane.py`
- Affected runtime metadata and diagnostics:
  - control-plane service ownership metadata
  - compatibility-surface metadata for retired privileged slots
  - package lookup and conformance metadata
- Affected docs:
  - runtime architecture and migration notes
  - extension guide material that still treats privileged service slots as canonical

## Roadmap Fit

- Rollout wave: Wave 1 foundation.
- Recommended order: land after `retire-runtime-context-and-taskmanager-compat` when practical, because both changes touch `controller.py`, `control_plane.py`, and related owner-layer helpers; this change can then attach typed service-family resolvers to the cleaned authority surface.
- Downstream dependencies: `remove-runtime-team-compatibility-bridges`, `close-invocation-provider-config-bypass`, and `dekernelize-first-party-package-catalog-and-enforce-protocol-conformance` reuse the same canonical-vs-compatibility metadata story when they harden protocol-only conformance.
- Breaking surface: no public flag day is planned here; `RuntimeServices.memory`, `RuntimeServices.compaction`, and `RuntimeServices.isolation` remain compatibility projections during this change.

