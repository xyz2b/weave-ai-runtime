## Context

The runtime has already made first-party packages manifest-backed, but `runtime-core` still owns too much of the official package catalog story:
- package-role tables live in kernel-adjacent code;
- official manifest catalogs are assembled through kernel-owned tables and mapping helpers;
- architecture guarantees about protocol-only behavior are documented, but not fully enforced by a machine-checkable conformance gate.

That means two regressions remain possible:
1. adding or evolving an official package still nudges contributors toward kernel edits;
2. a future patch can reintroduce compatibility-surface dependence without an automatic failure signal.

## Goals / Non-Goals

**Goals:**
- Make the official first-party package catalog manifest-backed and self-describing rather than kernel-switch-owned.
- Keep supported distributions stable while sourcing them from the official package catalog provider.
- Publish explicit assembly and conformance provenance in runtime metadata.
- Add a protocol-only conformance gate that blocks known forbidden regressions.
- Aggregate structured rule findings from the earlier protocol-only cleanup changes instead of duplicating subsystem-specific audits.

**Non-Goals:**
- Turning the runtime into a remote package marketplace or adding install/publish workflows.
- Changing supported distribution names or product identity.
- Redesigning package dependency resolution beyond what catalog ownership and provenance require.
- Replacing human architectural review with conformance alone.

## Cross-Change Fit

This is the Wave 3 terminal change. It should merge last, because it turns the earlier four roadmap items from architectural intent into a hard conformance gate.

The terminal gate should consume subsystem-owned findings whenever possible:
- privileged service-slot findings from `eliminate-privileged-runtime-package-service-slots`;
- context-authority findings from `retire-runtime-context-and-taskmanager-compat`;
- team-bridge findings from `remove-runtime-team-compatibility-bridges`;
- provider-provenance findings from `close-invocation-provider-config-bypass`.

That keeps subsystem logic close to subsystem ownership and prevents this final change from turning into an oversized re-audit patch.

## Decisions

### Decision: Official package catalog ownership becomes manifest-backed and self-describing

The runtime will define an official package catalog provider that returns manifest-backed catalog entries, ownership metadata, and distribution-composition data without relying on package-name-specific kernel assembly switch logic as the architectural source of truth.

Why this decision:
- it makes official package ownership consistent with the package protocol model;
- it lowers the cost of evolving the official package set;
- it makes provenance publishable and inspectable.

Alternatives considered:
- keep the kernel-owned tables but annotate them better: rejected because the architecture would still be kernel-switch-owned;
- jump straight to fully dynamic entrypoint discovery: rejected because the official catalog still benefits from explicit runtime ownership and stable provenance.

### Decision: Supported distributions remain explicit but consume catalog data

The runtime will keep the supported distributions `runtime-core`, `runtime-default`, and `runtime-full`, but the distribution composition logic will consume catalog entries instead of hand-maintained assembly switch logic.

Why this decision:
- it preserves user-facing stability;
- it removes the need for contributors to update parallel assembly tables;
- it keeps composition semantics inspectable in one place.

Alternatives considered:
- replace supported distributions with free-form package sets only: rejected because supported product identity still matters.

### Decision: Protocol-only conformance becomes a first-class runtime output

The runtime will publish a protocol-only conformance summary and enforce rules for forbidden compatibility surfaces and forbidden package-specific kernel assembly branches.

The initial forbidden set includes:
- runtime-owned primary-path dependence on `TaskManager`;
- runtime-owned primary-path dependence on raw authoritative `runtime_context`;
- runtime-owned primary-path dependence on privileged dedicated service slots for memory, compaction, or isolation;
- runtime-owned primary-path dependence on package-specific team projections or bridges;
- canonical invocation-provider registration through config-owned bypasses;
- kernel-owned package-name-specific assembly branch dependence where catalog-backed manifest ownership should be authoritative.

Why this decision:
- it turns architectural guidance into an enforceable rule;
- it gives CI and embedders the same machine-readable signal;
- it prevents silent backsliding after the earlier boundary changes land.

Alternatives considered:
- keep the checks in architecture docs only: rejected because the target state is now important enough to enforce.

### Decision: Conformance aggregates subsystem-owned rule findings instead of re-encoding every audit

The terminal conformance summary will aggregate structured findings emitted by the earlier cleanup changes where possible, and only add final assembly-branch-specific checks here.

Why this decision:
- it prevents duplicated audit logic across multiple roadmap changes;
- it keeps failure attribution precise;
- it lets each subsystem evolve its own finding shape while the terminal gate consumes a stable top-level summary.

Alternatives considered:
- make this change rediscover every forbidden surface by itself: rejected because it would create a large, fragile, cross-cutting audit patch.

### Decision: All protocol-only findings share one stable envelope

The aggregated protocol-only summary will require every rule family to publish findings through one stable envelope so subsystem-owned results are composable without bespoke parsing.

The shared envelope includes:
- `rule_id`
- `family`
- `status`
- `distribution`
- `evidence`
- `canonical_path`
- optional `compat_surface`
- optional `replacement_path`

Why this decision:
- CI and embedders need one parsing contract even when findings come from different subsystems;
- it keeps the final gate focused on policy instead of per-subsystem translation code;
- it makes failure attribution and historical comparisons stable across the rollout.

Alternatives considered:
- allow each subsystem to publish a different finding shape and normalize later: rejected because the normalization layer would become the real hidden contract;
- publish only free-form text in the summary: rejected because the terminal gate needs machine-readable evidence.

### Decision: Keep official catalog provenance and resolved graph provenance separate

The runtime will publish separate metadata for:
- official catalog provenance;
- runtime package registration and candidate provenance;
- resolved active package graph;
- protocol-only conformance summary.

Why this decision:
- each artifact answers a different question;
- it avoids collapsing "what exists" and "what was selected" into one ambiguous view;
- it aligns with the existing package registration and resolution metadata model.

Alternatives considered:
- merge all provenance into one flat metadata object: rejected because it reduces clarity and makes conformance harder to interpret.

### Decision: Terminal-gate green criteria are explicit and distribution-wide

The terminal protocol-only gate will only be considered green when every rule family reports `pass` across the supported distribution matrix and required optional-package presence cases.

The initial green criteria are:
- `runtime-core`, `runtime-default`, and `runtime-full` each publish the protocol-only summary;
- the privileged service-slot, context-authority, team-bridge, provider-provenance, and kernel-assembly families each report `pass` for the required scenarios in that matrix;
- optional package present or absent cases continue to expose bounded absence semantics rather than hidden compatibility fallbacks.

Why this decision:
- it prevents a partial rollout from being mistaken for terminal conformance;
- it keeps optional-package semantics part of the success criteria rather than a best-effort side test;
- it makes the step from summary-only to failing gate auditable.

Alternatives considered:
- define green per rule family without a cross-distribution matrix: rejected because protocol-only regressions often hide in package-absent or smaller distributions;
- treat summary publication alone as green: rejected because publication is necessary but not sufficient.

### Decision: The terminal gate rolls out summary-first, failure-second within the same change

This change will first publish the aggregated protocol-only summary in a shape CI and embedders can inspect, then wire that summary into failing conformance coverage once the earlier rule families are green.

Why this decision:
- it avoids a deadlock where the gate is introduced before its inputs are available;
- it lets the catalog refactor and the final gate share one terminal change without hiding migration status;
- it gives maintainers a clear checkpoint before making the summary mandatory.

Alternatives considered:
- introduce the hard failure path before publishing the summary: rejected because it obscures why the gate failed and makes rollout harder to stage.

## Risks / Trade-offs

- [Catalog refactor adds indirection without enough payoff] -> Mitigation: keep the official catalog provider explicit and self-describing rather than over-abstracting it.
- [Conformance gate becomes brittle] -> Mitigation: start with a narrow forbidden set tied to already-documented compatibility surfaces and boundary rules, and consume subsystem-owned findings where available.
- [Distribution composition becomes harder to trace] -> Mitigation: publish catalog and composition provenance directly in runtime metadata.

## Migration Plan

1. Introduce the official manifest-backed package catalog provider and migrate existing first-party catalog data into it.
2. Update supported distribution composition logic to consume the official catalog provider.
3. Publish official-catalog provenance, resolved-graph provenance, and an aggregated protocol-only conformance summary using the shared finding envelope.
4. Map each forbidden rule to a structured finding source, adding only the final kernel-assembly checks in this change.
5. Verify the explicit green criteria across the supported distribution and optional-package matrix.
6. Turn the aggregated summary into failing conformance coverage once the earlier rule families are green.
7. Remove or retire the superseded kernel-owned tables and switch helpers once the new path is proven.

Rollback strategy:
- If the catalog provider migration regresses selection or provenance, restore the previous tables behind the new provider interface temporarily while keeping the conformance model and metadata separation intact.

## Open Questions

- Should the official package catalog provider live alongside package manifests, or in a dedicated catalog module with manifest references?
- Do we want the protocol-only conformance summary published only in metadata, or also exposed through a dedicated query helper?
- Which forbidden assembly-branch patterns should be enforced syntactically versus behaviorally in the initial conformance gate?
