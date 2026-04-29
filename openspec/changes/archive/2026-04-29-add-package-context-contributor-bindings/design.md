## Context

Today the runtime has a real prompt/private context boundary and a real context-assembly phase, but the contributor side is still asymmetric. Collect-style context producers such as hooks, memory, and task discipline live behind specific `RuntimeServices` fields, while package contribution protocol only formalizes capabilities, host facets, lifecycle participants, store bindings, model bindings, job executors, and ingress receipts.

That means a new first-party package that wants to add request-time context has no generic manifest-backed attachment path. It must either widen `RuntimeServices`, hide behind an unrelated capability, or patch turn-engine assembly directly. All three options are the opposite of the microkernel direction.

## Goals / Non-Goals

**Goals:**

- Add a manifest-backed package contribution type for collect-style context contributors.
- Let runtime-owned context assembly invoke package-contributed contributors through explicit runtime-owned stages.
- Preserve the existing prompt/private carrier split and deterministic merge rules.
- Keep current first-party contributors migratable without flag-day removal of existing service slots.

**Non-Goals:**

- Replacing `CompactionManager` with a generic contributor abstraction.
- Designing a public third-party authoring API for arbitrary external context plugins.
- Generalizing context contributors into an event bus or arbitrary request interceptor system.
- Changing prompt/private merge semantics beyond what is needed to support package-contributed contributors.

## Decisions

### 1. Add an explicit package contribution type for collect-style context contributors

The package protocol will gain a new contribution type for context contributors. Each binding will carry at least a stable name, owner metadata, stage identifier, and contributor implementation or factory.

Why this decision:

- it lets packages attach request-time context behavior without widening `RuntimeServices`
- it keeps contributor ownership visible in metadata and diagnostics
- it fits the existing manifest-backed contribution model better than ad hoc config callbacks

Alternatives considered:

- register context contributors only through the capability registry: rejected because contributors are staged execution participants, not simple lookup objects
- keep using package-specific `RuntimeServices` fields: rejected because it preserves the current asymmetry

### 2. Context contributors stay runtime-owned and stage-ordered

The runtime, not packages, will own the canonical stage order for context assembly. Packages choose which published stage to attach to and their relative ordering within that stage, but they do not define new global stage topology by default.

Why this decision:

- it preserves runtime ownership of prompt assembly and request preparation
- it avoids package-defined ordering races
- it keeps testing and conformance tractable

Alternatives considered:

- allow every package to invent arbitrary new top-level stages: rejected because it would make assembly ordering non-portable
- flatten all contributors into unordered execution: rejected because merge and dependency behavior would become incidental

### 3. Generic context contributors are collect-style only; compaction remains a dedicated service

`CompactionManager` has explicit `prepare_turn()` and continuation semantics that participate in main-loop control. This change therefore does not subsume compaction into the generic contributor binding. Generic contributors cover collect-style prompt/private additions, while compaction remains a dedicated control-plane subsystem that may still expose prompt-visible outputs.

Why this decision:

- compaction owns request-shaping and continuation decisions, not just append-only context collection
- it avoids collapsing two different lifecycles into one misleading abstraction
- it reduces migration risk for the main loop

Alternatives considered:

- fold compaction into the same contributor registry immediately: rejected because it would blur main-loop ownership and expand scope too far

### 4. The contributor output contract reuses the prompt/private carrier model

Package-contributed context contributors will emit prompt-visible fragments and runtime-private updates through the same structured carrier model already used by current runtime context assembly. New package contributors do not get a privileged bypass around prompt-safety or private-state boundaries.

Why this decision:

- it keeps one prompt/private contract for all contributors
- it preserves observability and testability
- it avoids reintroducing the old unstructured metadata-bag pattern

Alternatives considered:

- allow package contributors to mutate request text or raw metadata in place: rejected because it breaks determinism and privacy boundaries

### 5. Collect-style contributor failures degrade with diagnostics instead of aborting turn preparation

Package-contributed collect-style context contributors are best-effort request enrichers, not authoritative main-loop owners. If one raises, times out, or returns an invalid output shape, the runtime will omit that contributor's output for the affected request and record owner- and stage-aware diagnostics instead of silently applying partial state or crashing request preparation by default.

Why this decision:

- collect-style contributors should not own turn liveness the way compaction or the provider path does
- optional package contributors need a bounded degradation path
- diagnostics are more useful than implicit partial mutation or untyped exceptions

Alternatives considered:

- abort the turn whenever any contributor fails: rejected because it gives optional package enrichers disproportionate authority over request execution
- silently ignore invalid output without diagnostics: rejected because it makes debugging assembly drift too hard

## Risks / Trade-offs

- [Existing service slots remain visible during migration] -> Mitigation: keep them compatibility-scoped, document the canonical contributor registry, and convert runtime-owned primary paths first.
- [Packages may need richer ordering than stage plus integer order] -> Mitigation: start with bounded stage ordering and only add dependency edges if a second real package needs them.
- [Contributor failures could become hard to debug] -> Mitigation: record owner-aware diagnostics and stage attribution in runtime metadata and tests, and define deterministic omission behavior for invalid or failing contributors.
- [Compaction stays a special subsystem] -> Mitigation: document that this is intentional because compaction owns continuation semantics, not just contribution aggregation.

## Migration Plan

1. Add context-contributor bindings and registry support to the package protocol and shared runtime services.
2. Teach turn-engine context assembly to execute package-contributed collect-style contributors through published runtime-owned stages.
3. Migrate current first-party collect-style contributors to bind through the new mechanism while keeping compatibility projections where needed.
4. Update docs and regression tests so package-owned context assembly is described and verified through the new canonical path.

Rollback is straightforward because existing collect-style service slots can remain as bounded compatibility surfaces while a migrated contributor is moved back temporarily if needed.

## Open Questions

None for this proposal stage. The main architectural defaults are fixed here: collect-style contributors become package-contributed, stage-ordered runtime participants, while compaction remains a distinct main-loop service.
