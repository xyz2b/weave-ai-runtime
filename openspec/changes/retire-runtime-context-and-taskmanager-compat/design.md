## Context

Two old compatibility surfaces still sit too close to the runtime's primary control-plane story:

- raw `runtime_context` maps that are still threaded through owner-layer APIs and helper flows;
- `TaskManager`, which has already been repositioned conceptually as a compatibility facade, but can still be materialized or consumed close to runtime-owned hot paths.

Both surfaces are documented as compatibility-only, but the code still treats them as more than that in a few places. As long as they remain nearby, new changes can keep accidentally extending them.

## Goals / Non-Goals

**Goals:**
- Make `RuntimePrivateContext` and `PromptContextEnvelope` the sole authoritative shared context carriers.
- Limit raw `runtime_context` to API-boundary normalization, legacy snapshots, or explicit compatibility adapters.
- Make `TaskManager` a pure legacy facade over `JobService` and `TaskListService`.
- Prevent runtime-owned primary paths from materializing or depending on `TaskManager` as an authoritative surface.
- Add structured conformance signals for both constraints.

**Non-Goals:**
- Removing every public parameter named `runtime_context` in one patch if a compatibility boundary still needs to accept it temporarily.
- Redesigning the job or task-list domain models.
- Changing prompt/private state semantics beyond their authority boundary.
- Reworking tool schemas or host APIs unless they are directly involved in the compatibility leak.

## Cross-Change Fit

This is the first Wave 1 foundation change. It centralizes authority before later roadmap items migrate more owner-layer lookups, which reduces merge churn in the shared controller and control-plane files.

Later roadmap changes depend on two outputs from this change:
- a smaller authoritative owner-layer surface that no longer treats raw `runtime_context` or `TaskManager` as primary-path state owners;
- structured conformance findings for the context-authority and task-authority rules that the final protocol-only gate can aggregate instead of rediscovering ad hoc.

## Decisions

### Decision: Raw `runtime_context` becomes an input-normalization boundary only

The runtime will continue to accept raw `runtime_context` only at legacy or convenience API boundaries, but it will immediately normalize that input into authoritative structured carriers before owner-layer logic proceeds.

Why this decision:
- it preserves compatibility while removing authority from the raw map;
- it makes it clear where compatibility ends and runtime-owned logic begins;
- it supports incremental migration without widening the leak further.

Alternatives considered:
- remove every `runtime_context` parameter immediately: rejected because it would cause unnecessary API churn;
- keep passing raw maps through the stack: rejected because that keeps the leak alive.

### Decision: `RuntimePrivateContext` is the only writable authoritative private-state carrier

Any authoritative runtime-private state mutation will flow through `RuntimePrivateContext` or session-ingress private updates, not through raw compatibility maps.

Why this decision:
- it aligns implementation with the documented boundary;
- it removes ambiguity about where private execution state lives;
- it simplifies auditing for prompt-safety and recovery behavior.

Alternatives considered:
- allow dual write paths temporarily: rejected because dual writes are how compatibility paths regain authority.

### Decision: `TaskManager` remains only as a legacy facade

`TaskManager` will stay available only as a legacy adapter over `JobService` and `TaskListService`, and runtime-owned primary paths will stop materializing it on demand.

Why this decision:
- it preserves compatibility for older callers;
- it keeps the shared job/task services as the only authoritative source of truth;
- it makes future removal far easier.

Alternatives considered:
- remove `TaskManager` outright in this change: rejected because some external compatibility callers may still rely on it;
- keep auto-materializing it for convenience: rejected because convenience keeps it alive in primary paths.

### Decision: Compatibility boundaries are explicit, finite, and published

The runtime will publish an explicit whitelist of the compatibility-only entry points that may still accept raw `runtime_context` payloads or materialize a `TaskManager` facade during the migration.

The initial whitelist is intentionally narrow:
- API-boundary ingress or convenience entry points that immediately normalize raw `runtime_context` into structured carriers;
- explicit legacy adapters that materialize `TaskManager` over `JobService` and `TaskListService`;
- read-only metadata or snapshot views that describe compatibility state without restoring authority to the legacy surface.

Why this decision:
- it keeps boundary drift visible and reviewable;
- it prevents ambiguous "temporary" helpers from becoming new sanctioned authority paths;
- it gives the terminal protocol-only gate a finite set of compatibility surfaces to audit.

Alternatives considered:
- rely on naming or conventions to imply boundary-only status: rejected because the leak is subtle and easy to reintroduce;
- allow ad hoc compatibility shims as long as they normalize quickly: rejected because ad hoc shims are exactly what makes authority boundaries drift over time.

### Decision: Conformance must assert both authority boundaries

The runtime will add structured conformance checks for:
- no authoritative primary-path writes through raw `runtime_context`;
- no new primary-path dependence on `TaskManager`.

Why this decision:
- these are the two most likely regressions once the migration starts;
- they are easier to enforce when written as machine-checkable rules rather than doc-only guidance;
- the terminal protocol-only gate can consume the resulting rule findings directly.

Alternatives considered:
- rely on code review alone: rejected because these are long-lived compatibility temptations.

## Risks / Trade-offs

- [Boundary adapters become noisy] -> Mitigation: centralize raw `runtime_context` normalization in a small number of helpers instead of duplicating it.
- [Some legacy callers still expect `TaskManager` to materialize automatically] -> Mitigation: keep an explicit compatibility adapter entry point while removing primary-path dependence.
- [Tests may silently keep using compatibility paths] -> Mitigation: add explicit conformance checks and metadata assertions for authority boundaries.
- [Partial migration leaves mixed authority] -> Mitigation: treat any remaining dual-write path as a blocker before the change is considered complete.

## Migration Plan

1. Identify and centralize all raw `runtime_context` normalization boundaries.
2. Migrate authoritative private-state writes to `RuntimePrivateContext` and ingress private updates only.
3. Remove runtime-owned primary-path reliance on `TaskManager` materialization and direct authority.
4. Publish the finite compatibility-boundary whitelist for raw `runtime_context` and `TaskManager`.
5. Keep explicit compatibility adapter surfaces only for the whitelisted boundaries where external callers still need them.
6. Publish compatibility metadata and structured conformance findings.

Rollback strategy:
- If a boundary migration regresses a legacy caller, restore the affected compatibility adapter while keeping the internal authoritative write path on the structured carrier.

## Open Questions

- Do we want a formal deprecation clock for public `runtime_context` parameters after this change lands?
- Should `TaskManager` move to a dedicated compatibility module to make owner-layer imports easier to audit?
- Which public helper APIs should stop accepting `runtime_context` entirely in the first follow-up patch?
