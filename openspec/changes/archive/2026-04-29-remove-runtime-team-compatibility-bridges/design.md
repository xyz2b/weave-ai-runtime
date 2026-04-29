## Context

The runtime has already done most of the hard architectural work for `runtime-team`:
- canonical team capability keys exist;
- a canonical team workflow host facet exists;
- team replay and workflow recovery already have lifecycle-aware protocol hooks;
- owner-layer package-boundary docs already call the remaining team wrappers compatibility-only.

What still remains is a collection of runtime-facing and host-facing bridges that keep team vocabulary alive inside `runtime-core`:
- `RuntimeServices.team_*`
- `RuntimeAssembly.team_*`
- `BoundHostRuntime.list_team_workflows()`
- `BoundHostRuntime.respond_team_workflow()`
- `HostRuntime.emit_team_event()`

Those surfaces are exactly the kind of package-specific escape hatch the protocol-only target wants to eliminate.

## Goals / Non-Goals

**Goals:**
- Make capability lookup, host-facet lookup, lifecycle participation, and generic extension-event emission the only normative team integration surfaces.
- Remove package-specific team wrappers from runtime-owned primary paths and public owner-layer APIs.
- Preserve team workflow, recovery, replay, and host-integration behavior after the bridge removal.
- Publish protocol-only conformance expectations and structured rule findings for the team package path.

**Non-Goals:**
- Redesigning team workflow semantics, team persistence, or teammate orchestration policy.
- Reworking non-team package boundaries in the same change.
- Introducing a full general-purpose event bus with arbitrary subscription semantics.
- Rewriting host implementations beyond the bridge changes required to support generic extension events.

## Cross-Change Fit

This is the first Wave 2 breaking migration. It should land only after the Wave 1 authority and resolver cleanups have reduced unrelated churn in the owner-layer files, and before the terminal conformance/catalog change turns the team-bridge rule into an always-on gate.

Because this is host-facing and public-surface breaking, the rollout must be replacement-first:
- publish the generic extension-event contract and direct host-facet resolution path;
- publish migration metadata and one-to-one replacement guidance;
- then remove the package-specific wrappers.

## Decisions

### Decision: Replace `emit_team_event()` with a generic extension-event host contract

The mandatory host bridge will stop carrying team-specific vocabulary. Package-owned host event emission will instead use a generic extension-event emission surface with an explicit namespace and structured payload envelope.

Why this decision:
- it removes package nouns from the mandatory host bridge;
- it remains reusable if a second package later needs the same egress shape;
- it keeps the mandatory bridge small while still supporting package-owned host-facing events.

Alternatives considered:
- keep `emit_team_event()` as a permanent exception: rejected because it preserves a package-specific leak;
- force all package-owned host egress through ordinary notifications: rejected because package-owned structured events are not the same as user-visible runtime messages.

### Decision: Host-to-runtime team operations remain host facets

Host-facing team operations such as listing and responding to workflows remain exposed through the canonical team workflow host facet rather than new bound-host wrapper methods.

Why this decision:
- the facet already expresses optional package-owned host operations cleanly;
- it avoids replacing one package-specific wrapper with another;
- hosts that do not care about team remain unaffected.

Alternatives considered:
- keep `BoundHostRuntime` wrappers as public convenience APIs: rejected because public convenience wrappers tend to become normative again.

### Decision: Runtime-owned code no longer reads team projections directly

Runtime-owned code paths will use the canonical team capability keys and team workflow host facet directly. Any remaining projections will be removed or demoted out of owner-layer public APIs.

Why this decision:
- it completes the original boundary work instead of stopping halfway;
- it gives one source of truth for team integration;
- it reduces the risk that future runtime code quietly reintroduces package-specific branching.

Alternatives considered:
- keep projections but forbid new ones: rejected because the old ones would still influence new code.

### Decision: Team replay and recovery stay lifecycle-participant-owned

Session-open replay and recovery remain attached through lifecycle participants, and this change will treat any remaining direct controller or kernel assumptions as regressions.

Why this decision:
- it preserves lifecycle ownership clarity;
- it keeps package behavior bounded to runtime-owned phases;
- it lets the bridge-removal change stay focused on discovery and host integration.

Alternatives considered:
- reintroduce direct replay helpers while removing public wrappers: rejected because that would simply move the leak inward.

### Decision: This change is intentionally breaking at the owner-layer API surface

To reach a real 100% protocol-only team path, the package-specific owner-layer API bridges need to stop being part of the public contract.

Why this decision:
- the repo already documents them as compatibility-only;
- keeping them alive indefinitely would undermine the target state;
- clear breakage with a migration path is easier to reason about than a permanent shadow API.

Alternatives considered:
- preserve the wrappers forever as deprecated aliases: rejected because the point of this change is to remove them as architecture-shaping surfaces.

### Decision: Removed team bridges ship with a one-to-one replacement matrix

The change will publish a one-to-one replacement matrix and bounded absence semantics for every removed team-specific owner-layer bridge.

The minimum matrix covers:
- `RuntimeServices.team_*` -> canonical team capability or resolved service lookup; if `runtime-team` is absent, the capability stays absent rather than projecting a synthetic wrapper;
- `RuntimeAssembly.team_*` -> assembled runtime package lookup plus canonical capability or host-facet resolution; if `runtime-team` is absent, no top-level projection remains;
- `BoundHostRuntime.list_team_workflows()` -> canonical team workflow host facet list operation; if `runtime-team` is absent, the optional facet is unavailable without widening the mandatory host bridge;
- `BoundHostRuntime.respond_team_workflow()` -> canonical team workflow host facet respond operation; if `runtime-team` is absent, callers receive the explicit not-available behavior defined for the facet path;
- `HostRuntime.emit_team_event()` -> generic extension-event host contract; unknown namespaces remain ignorable under the extension-event contract.

Why this decision:
- it turns the breaking migration into a deterministic replacement exercise rather than a scavenger hunt;
- it keeps optional-package absence semantics explicit across distributions;
- it prevents a convenience wrapper from reappearing because one caller lacked a documented replacement path.

Alternatives considered:
- rely on prose migration notes without a surface-by-surface matrix: rejected because the removed surfaces are heterogeneous and host-facing;
- preserve one or two wrappers as convenience aliases: rejected because that would blur the protocol-only boundary again.

### Decision: Team conformance findings must be published in a terminal-gate-friendly shape

The change will publish structured conformance findings for the team bridge rules rather than relying only on test names or ad hoc log inspection.

Why this decision:
- the final protocol-only gate should aggregate team bridge status without re-implementing team-specific audits;
- hosts and CI need a machine-readable explanation for failures;
- it keeps the breaking migration attributable even when multiple roadmap changes are complete.

Alternatives considered:
- let the terminal gate rediscover bridge usage from scratch: rejected because it would duplicate subsystem logic and increase drift risk.

## Risks / Trade-offs

- [Hosts break when `emit_team_event()` disappears] -> Mitigation: introduce the generic extension-event contract first and document the migration before removing the team-specific method.
- [External callers relied on bound-host team wrappers] -> Mitigation: document direct facet resolution and provide migration notes with one-to-one replacement examples.
- [Runtime-owned code accidentally retains one projection path] -> Mitigation: add explicit conformance coverage and metadata assertions for forbidden team bridges.
- [Generic extension-event envelopes are underspecified] -> Mitigation: publish namespace, payload, and unknown-event handling rules in the same change.

## Migration Plan

1. Introduce the generic extension-event host contract and migrate team event emitters onto it.
2. Migrate runtime-owned team code paths to canonical capability/facet resolution only.
3. Publish the one-to-one replacement matrix, bounded absence semantics, and migration metadata for the host-facing wrapper and bridge removals.
4. Remove package-specific team projections from runtime assembly, runtime services, and bound-host surfaces.
5. Publish structured team-bridge conformance findings and update migration docs.

Rollback strategy:
- If a host migration regresses unexpectedly, temporarily restore a thin adapter from the removed team-specific bridge to the generic extension-event contract while keeping the canonical protocol path intact.

## Open Questions

- Should the extension-event envelope carry a schema version per namespace, or rely on namespace versioning alone?
- Do we want to keep a dedicated helper for resolving host facets on `BoundHostRuntime`, or require callers to route entirely through the assembled runtime surface?
- Once team is fully protocol-only, which package should be the next candidate for wrapper elimination?
