## Context

The runtime already has the core shape of a framework rather than a single bundled agent product:

- `RuntimeKernel`, `SessionController`, and `TurnEngine` form a stable kernel/session/turn skeleton.
- first-party package roles and supported distributions are already explicit (`runtime-core`, `runtime-default`, `runtime-full`).
- several first-party subsystems have already been split conceptually into capability, mechanism, adapter, provider, or profile/workflow packages.

That progress is real, but current package integration still leaves `runtime-core` aware of too many first-party package details. Source study during exploration surfaced five recurring boundary leaks:

1. kernel-owned first-party package assembler tables
2. kernel-owned optional built-in loader tables
3. package-specific slots on `RuntimeServices`
4. package-specific methods added to the host bridge
5. retained hot-path dependence on `TaskManager` compatibility

The key conclusion from the exploration is not that the current framework should perform a purity-driven rewrite. The runtime is not yet at the point where a full microkernel clean-room pass, immediate multi-wheel split, or total elimination of first-party knowledge would pay back the disruption. The conclusion is narrower:

- the framework is already large enough that adding or evolving first-party packages should stop requiring repeated kernel edits;
- the framework is not yet stable enough to freeze every package concern into a maximally generic plugin system.

This design therefore proposes a minimum protocol-integration target architecture.

```text
runtime-core
├─ runtime/session/turn skeleton
├─ shared registries
├─ hooks / permissions / elicitation / jobs / task_lists
├─ package manifest loader + dependency ordering
├─ capability registry
└─ host facet router

first-party packages
├─ contribute capabilities
├─ contribute tools / agents / skills
├─ contribute lifecycle participants
├─ contribute host facets
├─ contribute store/provider/executor bindings
└─ stop widening core with package-specific slots
```

The intended outcome is “packages attach through protocols and contributions” rather than “packages merely live in different folders.”

## Goals / Non-Goals

**Goals:**
- Preserve the current runtime skeleton and supported distributions while reducing the most expensive package-to-core couplings.
- Introduce one explicit package integration model centered on manifests, contributions, capability lookup, lifecycle participants, and host facets.
- Keep `task_*`, `job_*`, main routing, host/permission/elicitation contracts, and the kernel/session/turn stack in `runtime-core`.
- Preserve the conclusion that `runtime-planning` remains a higher-level profile/workflow package consuming shared planning primitives from `runtime-core` rather than owning those primitives.
- Give future first-party packages one repeatable attachment path so adding a package does not require editing multiple kernel-owned switch tables.
- Freeze the growth of new package-specific core service fields and host-bridge methods.
- Continue compatibility cleanup by pushing `TaskManager` toward a bounded edge surface while leaving `JobService` authoritative.

**Non-Goals:**
- Rewriting the runtime into a theoretically pure microkernel in one change.
- Requiring a flag-day removal of `TaskManager` compatibility.
- Splitting the repository into multiple Python distributions or wheels as part of this change.
- Promoting every current first-party package concept into a permanent core contract.
- Turning package integration into a fully open-ended third-party plugin marketplace before first-party seams stabilize.

## Decisions

### Decision: Introduce a minimum package assembly protocol

The runtime will define one package assembly model based on three cooperating contracts:

- `RuntimePackageManifest`: package identity, role, dependencies, and assembly entrypoint
- `PackageContext`: the runtime-owned assembly context handed to a package
- `PackageContribution`: the structured result returned by package assembly

This replaces repeated kernel-owned special-case attachment logic as the primary integration story.

Why this decision:
- it removes the need for `runtime-core` to keep growing new per-package assembly branches;
- it keeps package attachment explicit and ordered;
- it gives first-party packages a stable place to contribute built-ins, capabilities, and host extensions.

Alternatives considered:
- keep hard-coded first-party assembler maps and only improve docs: rejected because it documents the problem without reducing the cost of the next package split;
- jump directly to filesystem- or entrypoint-based dynamic plugin discovery: rejected because it would over-rotate into a broad plugin system before the minimum first-party seams are stable.

### Decision: Add a capability registry instead of widening `RuntimeServices`

The runtime will expose a capability registry for package-owned runtime objects. Packages bind stable capability keys to owned objects, and consumers resolve those capabilities through lookup rather than through long-lived package-specific fields on `RuntimeServices`.

The first target uses are the places where package-owned objects currently leak directly into shared runtime surfaces, especially for team-oriented services.

Why this decision:
- it preserves one shared runtime control-plane surface without making that surface remember every optional package by name;
- it allows package-specific objects to exist without promoting them into permanent top-level core fields;
- it makes package-level ownership more explicit for diagnostics and migration.

Alternatives considered:
- keep adding package-specific `RuntimeServices` fields: rejected because it permanently couples the control-plane spine to first-party package inventory;
- create many package-specific registries: rejected because it would replace one broad problem with several narrower ad hoc lookup patterns.

### Decision: Built-ins become package contributions, not kernel-owned optional tables

Official tools, agents, and skills will continue to be owned by official first-party packages, but their attachment path will converge on package-contributed built-ins rather than kernel-owned optional loader tables.

`runtime-core` will still keep the core built-ins it truly owns. Higher-level packages will contribute their own built-ins under a unified contribution flow.

Why this decision:
- it aligns built-in ownership with package ownership;
- it removes a second package-specific table from the kernel path;
- it keeps existing distribution semantics intact while making package attachment more regular.

Alternatives considered:
- move all built-ins back into `runtime-core`: rejected because it would reverse the capability-boundary work already completed;
- leave ownership split but attachment kernel-owned: rejected because it keeps the highest-friction part of the current architecture unchanged.

### Decision: Package-specific host operations move behind host facets

The mandatory host bridge will remain small and focused on common runtime concerns such as lifecycle, permission, elicitation, notifications, and turn events. Optional package-specific host operations will attach through host facets or equivalent capability-detected extension surfaces owned by the package.

Why this decision:
- it keeps `HostRuntime` from becoming a catalog of optional first-party features;
- it preserves the current conclusion that not every host must care about every first-party package;
- it gives packages like `runtime-team` a supported extension seam without forcing that seam into the mandatory core host API.

Alternatives considered:
- keep widening `HostRuntime` for each new official package feature: rejected because it hard-codes optional product surfaces into the mandatory host contract;
- forbid host-level package extensions entirely: rejected because some official package capabilities do need host-visible operations, but those operations should remain optional.

### Decision: Keep lifecycle ownership in core, but let packages attach lifecycle participants

Host scope ownership remains with the bound host runtime, session scope ownership remains with the session controller, and turn ownership remains with the turn engine. This change does not move ownership away from those layers.

Instead, packages may attach bounded lifecycle participants that run within runtime-owned lifecycle phases such as runtime start, recovery, session open, and session close.

Why this decision:
- it preserves the existing lifecycle-ownership model;
- it avoids package-specific replay or recovery branches being hand-written into kernel or session code;
- it provides a narrow place for package-owned background recovery or replay behavior to hook in.

Alternatives considered:
- allow packages to own independent lifecycle managers: rejected because it weakens the current single-owner lifecycle discipline;
- forbid package lifecycle hooks entirely: rejected because current package recovery and replay needs are real and already leaking into core code.

### Decision: Treat `TaskManager` cleanup as a staged coupling reduction, not a flag day

The design keeps the current conclusion that `JobService` is authoritative and `TaskManager` is compatibility-only. Package protocol convergence will not wait for a complete `TaskManager` deletion, but new or refactored package seams must not re-promote it as a primary integration surface.

Why this decision:
- it matches the existing staged compatibility plan already documented in job-control work;
- it keeps this change focused on package integration rather than coupling it to a large compatibility removal patch;
- it avoids freezing old compatibility assumptions into the new package protocol.

Alternatives considered:
- remove `TaskManager` immediately: rejected because it would enlarge this change beyond safe architectural convergence;
- ignore `TaskManager` until later: rejected because package integration work would otherwise keep inheriting the old seam.

### Decision: Do the minimum high-value convergence, not a purity rewrite

This change explicitly chooses a 70-percent architecture win over a 95-percent purity rewrite.

Concretely, the runtime will aim to:
- remove repeated kernel-owned package integration tables;
- stop growing package-specific top-level service fields;
- stop growing package-specific host methods;
- preserve current distributions and core ownership boundaries;
- defer physical package splitting and broader third-party plugin generalization.

Why this decision:
- it matches the current maturity of the framework;
- it captures the explored conclusion that the architecture is worth tightening, but not worth stalling for maximal purity;
- it keeps the next few package-oriented changes cheaper without forcing a broad product or repo restructuring decision now.

Alternatives considered:
- do nothing beyond documentation: rejected because the coupling cost is already visible in current first-party package integration;
- pursue full microkernel purity now: rejected because too many semantics are still stabilizing and the migration cost would dominate near-term value.

## Risks / Trade-offs

- [Package protocol introduced too early becomes another unstable seam] → Mitigation: keep the first protocol surface intentionally small; optimize for first-party convergence first, not a generalized marketplace.
- [Capability keys become vague or inconsistent] → Mitigation: start with a small published key set and tie each key to package ownership plus diagnostics metadata.
- [Host facets fragment host integration] → Mitigation: keep the mandatory host bridge small and stable, and require optional package operations to advertise themselves through one standard facet-discovery path.
- [Lifecycle participants could blur ownership] → Mitigation: preserve host/session/turn ownership in core and restrict participants to bounded runtime-owned phases.
- [`TaskManager` compatibility continues to leak into new paths] → Mitigation: treat any new primary runtime path that depends on `TaskManager` as a regression and keep `JobService` authoritative in the design and tasks.
- [Scope expands into physical repo or packaging refactors] → Mitigation: state explicitly that multi-distribution packaging is not part of this change and keep tasks focused on protocol seams, registries, and migration of the highest-cost couplings.

## Migration Plan

1. Introduce the protocol vocabulary and normative package integration contracts in specs and architecture docs.
2. Add the package manifest/contribution scaffolding in `runtime-core` without changing supported distribution names.
3. Add the capability registry and keep existing package-specific fields temporarily as compatibility projections where needed.
4. Convert package-owned built-in attachment from kernel-owned optional tables to package contributions.
5. Add host-facet routing and migrate the most obvious optional package host extensions behind that seam.
6. Migrate the most coupled first-party package paths first, especially `runtime-team`, then provider/store-oriented contributors such as `runtime-openai` and `runtime-stores-file`.
7. Remove or demote remaining core-facing package special cases after package contributions and capability lookup are proven out.

Rollback strategy:
- because this change preserves current distributions and keeps compatibility layers during migration, rollback remains available by retaining existing assembly and compatibility projections while reverting individual package-contribution migrations.

## Open Questions

- Should the first published capability-registry contract support only string keys in the first stage, or also typed key wrappers from day one?
- How much of `RuntimeServices` should be exposed directly through `PackageContext` in the first implementation, versus a narrower `CoreServicesView` introduced later?
- Which package-specific host operations should move first behind host facets: only team workflow operations, or also future package-owned host helpers added after this change?
- Should package manifests remain first-party and runtime-owned in the first implementation, or should embedder-owned package manifests also be supported immediately?
- After `runtime-team` is migrated behind capabilities and host facets, which remaining first-party package still imposes the highest residual kernel coupling and should be tackled next?
