## Context

The runtime already assembles the main package-extension mechanisms needed for a microkernel-style first-party package model: capability registry, lifecycle registry, host facets, manifest-driven package contributions, and shared job or task-list services. The current codebase also already exposes migration metadata that labels retained compatibility surfaces such as `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, `BoundHostRuntime.list_team_workflows()`, `BoundHostRuntime.respond_team_workflow()`, and `TaskManager`.

What remains incomplete is the owner-layer rule. Runtime-owned code paths still tolerate direct package-shaped projections and wrapper methods in places where canonical capability lookup, host-facet lookup, or shared job services should already be authoritative. If that remains informal, future first-party package work will keep widening core owner layers instead of attaching through the protocol seams that now exist.

This change therefore focuses on boundary tightening only. It does not reopen already-landed ingress or lifecycle work, and it does not attempt to define the external package registration or dependency-resolution story yet.

## Goals / Non-Goals

**Goals:**

- Make canonical package lookup paths the normative owner-layer integration surface for runtime-owned code.
- Freeze retained package-specific projections as compatibility wrappers that delegate to canonical services and do not become source-of-truth state.
- Keep the mandatory host bridge narrow by routing optional package-owned host operations through host facets.
- Keep `TaskManager` compatibility bounded behind shared job and task-list services without requiring immediate removal.
- Publish enough metadata, docs, and regression coverage to prevent new owner-layer leaks from reappearing.

**Non-Goals:**

- Third-party or embedder-owned package registration.
- Package catalogs, semantic-version resolution, or manifest dependency solving.
- Flag-day removal of `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, `BoundHostRuntime` workflow helpers, or `TaskManager`.
- Reworking session-ingress completion receipts or lifecycle replay semantics that have already been specified elsewhere.

## Decisions

### 1. Canonical owner-layer paths are registry-backed protocol seams

Runtime-owned primary paths will treat the following as canonical:

- capability lookup for package-owned runtime services
- host-facet lookup for optional host-visible package operations
- lifecycle participants for package-owned lifecycle work
- `JobService` and `TaskListService` for generic background and task state

This is the lowest-risk tightening because those seams already exist in runtime assembly and already vary correctly by selected first-party packages.

Alternatives considered:

- Keep direct package-specific fields as equally valid primary paths. Rejected because it preserves the exact leak this change is meant to stop.
- Remove all compatibility accessors immediately. Rejected because current embedders and internal helper code still rely on those shapes.

### 2. Retained compatibility projections remain thin, non-authoritative wrappers

`RuntimeServices.team_*`, `RuntimeAssembly.team_*`, `BoundHostRuntime.list_team_workflows()`, `BoundHostRuntime.respond_team_workflow()`, and `RuntimeServices.task_manager` remain available during migration, but they must delegate to canonical capability, host-facet, job, or task-list services. They must not own independent state, bypass canonical validation, or become required by any new runtime-owned primary path.

This preserves compatibility without leaving ambiguity about what is authoritative.

Alternatives considered:

- Keep wrappers unlabeled and rely on convention. Rejected because future code review cannot reliably distinguish sanctioned compatibility from new architecture debt.
- Remove wrapper surfaces in this change. Rejected because the migration cost is larger than the architectural value of doing so now.

### 3. Canonical lookup guidance is part of the runtime contract, not tribal knowledge

Runtime assembly metadata and integration documentation will publish:

- canonical capability keys
- canonical host-facet keys
- retained compatibility wrappers
- exit criteria for removing those wrappers

This turns the boundary rule into something tests and docs can pin, rather than an internal preference that can drift.

Alternatives considered:

- Document only in proposal or design artifacts. Rejected because the rule would not stay visible to implementation and embedder-facing guidance.

### 4. Optional package-owned host operations must not widen the mandatory host bridge

Team workflow observation or response helpers are useful, but they are package-owned and optional. The mandatory host bridge therefore stays limited to lifecycle, permission, elicitation, notifications, and turn events. Optional workflow operations are surfaced through host facets, with retained `BoundHostRuntime` workflow helpers delegating into that facet-backed path as compatibility wrappers.

Alternatives considered:

- Add package-specific methods directly to the required `HostRuntime` protocol. Rejected because it would make optional first-party package behavior look mandatory for all hosts.

Retained compatibility helpers will also have bounded absence semantics. Observation helpers such as workflow listing may degrade to empty results when the package is absent, while mutating helpers such as workflow response must fail with an explicit not-available error instead of widening the mandatory host bridge or requiring ad hoc host checks.

### 5. `TaskManager` stays compatibility-scoped behind the shared job control plane

The runtime already has a job-service-backed compatibility story for `TaskManager`. This change does not remove it, but it does tighten the owner-layer rule: runtime-owned primary code must use `job_service` or `task_list_service`, while `TaskManager` remains a deprecated projection for legacy constructors, helpers, and tests.

Alternatives considered:

- Delay any statement about `TaskManager` until full removal. Rejected because that leaves a live escape hatch for new runtime-owned code to keep depending on the wrong abstraction.

## Risks / Trade-offs

- [Compatibility surfaces remain visible and may still attract new usage] -> Mitigation: label them explicitly in metadata and docs, and add tests that pin them as delegating wrappers rather than primary paths.
- [Canonical lookup adds one more layer of indirection for debugging] -> Mitigation: keep runtime metadata and diagnostics explicit about capability owners, host-facet owners, and wrapper projections.
- [Host-facet-backed workflow helpers can fail when the relevant package is absent] -> Mitigation: keep absence semantics explicit and bounded so optional helpers degrade without widening the mandatory host bridge.
- [Leaving `TaskManager` in place may slow final cleanup] -> Mitigation: keep it compatibility-only, do not add new semantics to it, and preserve clear exit criteria for later removal.

## Migration Plan

1. Audit runtime-owned primary paths and switch any remaining package-specific owner-layer lookups to canonical capability, host-facet, job, or task-list access.
2. Keep retained top-level projections and helper methods, but reduce them to thin adapters over those canonical paths.
3. Update runtime metadata and extension docs so embedders see the canonical lookup contract and the bounded status of retained wrappers.
4. Add regression coverage that proves wrappers delegate correctly and that new runtime-owned paths are not forced to depend on them.

Rollback is low-risk because the compatibility surfaces stay in place throughout this change. If a migration step regresses behavior, the implementation can revert a call site back to the wrapper temporarily without changing the public compatibility shape.

## Open Questions

None for this proposal stage. The remaining unresolved work is intentionally deferred to later changes: external package registration, dependency resolution, and final compatibility-wrapper removal.
