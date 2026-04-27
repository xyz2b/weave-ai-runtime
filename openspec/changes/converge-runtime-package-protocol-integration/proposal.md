## Why

The runtime has already converged on a real framework shape: a stable kernel/session/turn spine, explicit first-party package and distribution modeling, and a growing set of official capability, mechanism, provider, adapter, and workflow packages. That makes package boundaries important enough to document and refine, but the current integration model still leaves `runtime-core` aware of too many first-party package details, especially around hard-coded assembly, package-owned built-ins, host-side extensions, and retained compatibility seams such as `TaskManager`.

Now is the right time to capture a narrower next step. The framework is large enough that adding new first-party packages should stop requiring repeated kernel edits, but it is not yet mature enough to justify a purity-driven microkernel rewrite or immediate physical multi-distribution split. This change therefore documents and proposes a minimum high-value protocol-integration architecture: keep the existing runtime skeleton and supported distributions, but move package attachment toward manifest-driven contributions, capability lookup, lifecycle participants, and package-owned host facets so the most expensive couplings can be removed without freezing unstable semantics too early.

## What Changes

- Introduce a runtime-owned package integration protocol that lets first-party packages attach to `runtime-core` through explicit manifests and contributions instead of kernel-owned per-package special cases.
- Define a minimum package assembly model centered on `RuntimePackageManifest`, `PackageContext`, and `PackageContribution`, with package contributions covering capability bindings, built-in definitions, lifecycle participants, host facets, store or provider bindings, job executors, and diagnostics.
- Add a stable capability-registry contract so package-owned runtime objects may be discovered through stable capability keys rather than long-lived package-specific fields on the shared runtime service surface.
- Add a package-owned host-facet contract so optional host-visible package functionality, such as team-specific workflow operations, can be exposed without repeatedly widening the mandatory core host bridge.
- Reclassify package-owned built-ins as package contributions rather than kernel-owned optional loader tables, while preserving the current first-party ownership model and supported `runtime-core`, `runtime-default`, and `runtime-full` distributions.
- Keep the current architectural conclusion that shared kernel/session/turn structure and core control-plane primitives remain in `runtime-core`, including `task_*`, `job_*`, main routing, host/permission/elicitation contracts, and the core execution stack.
- Keep the current architectural conclusion that `runtime-planning` remains a higher-level profile or workflow package that consumes shared planning primitives from `runtime-core` rather than taking ownership of those primitives.
- Keep the current architectural conclusion that this work is **not** a full microkernel-purity rewrite, **not** an immediate multi-wheel packaging split, and **not** a flag-day removal of `TaskManager` compatibility; instead it freezes new core-facing package special cases and moves the most expensive remaining couplings toward protocol seams in staged follow-up work.
- Document a migration direction for the most visible remaining boundary leaks:
  - kernel-owned first-party package assembler tables
  - kernel-owned optional built-in loader tables
  - package-specific fields on `RuntimeServices`
  - package-specific methods on the host bridge
  - runtime-owned hot-path dependence on `TaskManager` compatibility where `JobService` should be authoritative

## Capabilities

### New Capabilities
- `runtime-package-integration-protocols`: The manifest-, contribution-, capability-registry-, lifecycle-participant-, and host-facet-based contract for attaching first-party runtime packages to `runtime-core` without widening package-specific kernel knowledge.

### Modified Capabilities
- `runtime-kernel`: Kernel assembly changes from package-name-specific attachment toward manifest-driven package discovery, dependency ordering, and contribution application while preserving the current runnable kernel/session/turn skeleton.
- `runtime-control-plane-spine`: The shared runtime control-plane contract gains capability-registry and package-contribution integration semantics so execution surfaces consume package-owned control-plane services through stable runtime contracts rather than package-specific fields.
- `builtin-runtime-pack`: First-party built-ins continue to ship from official packages, but their registration and ownership flow changes from kernel-owned optional loader tables toward package-contributed built-in definitions.
- `host-runtime-bridge`: Optional package-specific host operations move behind package-owned host facets or equivalent capability-detected extensions instead of repeatedly widening the mandatory host bridge surface.
- `runtime-lifecycle-ownership`: Runtime-owned lifecycle phases admit package lifecycle participants without transferring host-, session-, or turn-scope ownership away from the core lifecycle managers.

## Impact

- Affected code: `src/runtime/runtime_kernel/`, `src/runtime/builtins/`, `src/runtime/runtime_services/`, `src/runtime/hosts/`, `src/runtime/session_runtime/`, `src/runtime/turn_engine/`, `src/runtime/team/`, `src/runtime/memory/`, `src/runtime/openai_package.py`, `src/runtime/stores_file/`, `src/runtime/tasking.py`, and related public exports under `src/runtime/__init__.py`.
- Affected first-party package boundaries: `runtime-core`, `runtime-memory`, `runtime-team`, `runtime-planning`, `runtime-compaction`, `runtime-isolation`, `runtime-openai`, `runtime-devtools`, `runtime-hosts-reference`, `runtime-stores-file`, and `runtime-builtin-workflows`.
- Affected docs: runtime architecture, integration, extension, and migration notes should describe the minimum target architecture as “package integration through protocols and contributions” rather than “directory-level package split alone.”
- Public/runtime contract impact: the supported distribution names and first-party package taxonomy remain intact, but package attachment semantics become more explicit and more reusable for future first-party or embedder-owned packages.
- Compatibility impact: `TaskManager` remains a bounded compatibility facade during migration, and this change intentionally avoids requiring a flag-day removal or full physical packaging split before protocol seams are documented.
