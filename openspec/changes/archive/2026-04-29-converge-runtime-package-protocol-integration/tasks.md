## 1. Package Protocol Scaffolding

- [x] 1.1 Add the runtime-owned package protocol carriers for `RuntimePackageManifest`, `PackageContext`, and `PackageContribution`.
- [x] 1.2 Add the shared capability-registry contract together with a minimal published capability-key catalog and ownership metadata shape.
- [x] 1.3 Add bounded package lifecycle-participant and host-facet contracts without changing host/session/turn ownership.
- [x] 1.4 Add first-class package-contribution carriers for shared core store bindings, model provider or route bindings, and job-executor bindings.
- [x] 1.5 Add focused tests that validate package manifests, contribution application order, capability binding lookup, and lifecycle or host-facet registration.

## 2. Kernel Assembly Convergence

- [x] 2.1 Replace the kernel-owned first-party package assembler table with manifest-backed package assembly wiring for official packages.
- [x] 2.2 Update runtime assembly to resolve selected official packages in dependency order and apply returned package contributions.
- [x] 2.3 Preserve current `runtime-core`, `runtime-default`, and `runtime-full` selection semantics and migration diagnostics while moving assembly behind manifests.
- [x] 2.4 Add regression coverage that the runnable kernel/session/turn skeleton still boots when optional packages are omitted.

## 3. Built-in Contribution Convergence

- [x] 3.1 Replace kernel-owned optional built-in loader tables with package-contributed tool, agent, and skill definitions for official packages.
- [x] 3.2 Preserve built-in owner metadata, disable or replacement behavior, and distribution-specific visibility after the built-in contribution migration.
- [x] 3.3 Add regression tests that built-in ownership and supported distribution composition still match the published first-party package model.

## 4. Control-Plane and Host-Seam Cleanup

- [x] 4.1 Extend the shared runtime control-plane contract to expose package-owned services through the capability registry instead of package-specific top-level service slots.
- [x] 4.2 Add runtime-owned dispatch points for package lifecycle participants at runtime start, recovery, session open, and session close while preserving core lifecycle ownership.
- [x] 4.3 Define and implement one shared discovery path for optional package-owned host facets together with a structured not-available outcome for absent facets.
- [x] 4.4 Add host-facet routing or equivalent capability-detected extension plumbing to the host bridge while keeping the mandatory host contract focused on shared runtime concerns.
- [x] 4.5 Migrate the most obvious package-specific host operations off the mandatory host bridge and behind package-owned facets.
- [x] 4.6 Add tests that optional package host features remain discoverable without making non-participating hosts non-conformant.

## 5. First-Party Package Migration

- [x] 5.1 Migrate `runtime-team` to contribute its control-plane objects, lifecycle hooks, built-ins, and host-facing workflow operations through the new package protocol.
- [x] 5.2 Migrate `runtime-openai` to contribute provider and route bindings through the package-contribution path instead of kernel-specific post-processing.
- [x] 5.3 Migrate `runtime-stores-file` to contribute shared core store bindings through the package-contribution path.
- [x] 5.4 Migrate the remaining official higher-level packages (`runtime-memory`, `runtime-planning`, `runtime-devtools`, `runtime-builtin-workflows`, `runtime-compaction`, `runtime-isolation`, and `runtime-hosts-reference`) onto manifest-backed contribution wiring.

## 6. Compatibility and Migration Hardening

- [x] 6.1 Ensure migrated primary runtime paths continue to treat `JobService` as authoritative and do not re-promote `TaskManager` as a core integration surface.
- [x] 6.2 Keep any temporary package-specific `RuntimeServices` fields only as bounded compatibility projections during migration and remove them once equivalent capability lookups are live.
- [x] 6.3 Add diagnostics and regression coverage for package contribution ownership, capability lookup failures, and compatibility fallbacks.

## 7. Documentation and Architecture Notes

- [x] 7.1 Update runtime architecture docs to describe the minimum protocol-integration target architecture, including manifests, contributions, capability lookup, lifecycle participants, and host facets.
- [x] 7.2 Update integration, extension, and migration guides to explain that package boundaries are defined by protocol attachment rather than directory placement alone.
- [x] 7.3 Document the explicit non-goals for this change: no purity rewrite, no flag-day `TaskManager` removal, and no immediate physical multi-distribution packaging split.
