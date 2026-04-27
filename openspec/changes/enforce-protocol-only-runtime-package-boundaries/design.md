## Context

The runtime already has a real package protocol model: official first-party packages publish manifests, return structured contributions, bind capabilities, register lifecycle participants, and expose optional host-visible operations through host facets. That work tightened the biggest assembly seams, but the runtime still retains several owner-layer leaks that let package behavior bypass the normative protocol path.

Today those leaks cluster in four places:

1. `SessionController` still contains package-specific replay and delivery-ack behavior for team message and workflow flows.
2. `RuntimeAssembly`, `BoundHostRuntime`, and `RuntimeServices` still expose package-specific team helper surfaces and top-level compatibility slots alongside capability and host-facet lookup.
3. The host bridge still carries package-specific vocabulary such as `emit_team_event()` even though optional package-visible operations are otherwise moving behind shared extension seams.
4. `TaskManager` and legacy `runtime_context` compatibility continue to appear in runtime-owned hot paths even after `JobService`, `TaskListService`, and `RuntimePrivateContext` became the intended shared control surfaces.

The goal of this change is not to rewrite the runtime into a theoretically pure microkernel. The goal is narrower: make the published package protocols the only normative path for owner-layer package behavior, freeze new owner-layer leaks, and migrate the most expensive remaining leaks without forcing a flag day for compatibility wrappers that embedders or tests still use.

## Goals / Non-Goals

**Goals:**
- Define a clear owner-layer boundary: `runtime-core` owner layers consume package behavior only through runtime-owned protocols.
- Move package-owned session-open replay off controller special cases and into lifecycle participants.
- Add a bounded ingress completion-receipt protocol for post-ingress acknowledgements.
- Make capability and host-facet lookup the canonical discovery paths for package-owned runtime services and host helpers.
- Keep compatibility wrappers available during migration, but explicitly demote them to non-canonical projections.
- Prevent new runtime-owned primary paths from reintroducing `TaskManager` as an authoritative control surface.

**Non-Goals:**
- A purity-driven microkernel rewrite.
- Immediate removal of all compatibility wrappers, projections, or helper properties.
- Introduction of a generalized package event bus before a second package demonstrates the shared need.
- Opening external or third-party package registration in the same change.
- Redesigning the semantics of team workflows, teammate orchestration, or background jobs beyond the boundary changes required here.

## Decisions

### Decision: Owner layers consume package extensions only through runtime-owned protocols

The normative rule for `runtime-core` owner layers is:
- package-owned runtime objects are discovered through capability lookup;
- package-owned host-visible helpers are discovered through host-facet lookup;
- package-owned startup/recovery/session replay behavior attaches through lifecycle participants;
- package-owned post-ingress acknowledgements attach through bounded ingress completion receipts.

This rule applies to `SessionController`, `TurnEngine`, `RuntimeAssembly`, `BoundHostRuntime`, and the shared `RuntimeServices` surface. Those layers may keep temporary compatibility wrappers during migration, but they must not grow new package-specific fields, helper methods, or direct package-noun execution paths.

Why this decision:
- it turns the existing package protocol model into a real architectural boundary instead of a preferred-but-optional style;
- it prevents the next package feature from widening core owner layers the way team workflow replay and helpers did;
- it gives tests and follow-up changes one clear question to ask: “is this path protocol-owned or package-owned?”

Alternatives considered:
- keep capability/facet/lifecycle seams as guidance only: rejected because current owner-layer leaks would continue to multiply;
- remove all wrappers immediately: rejected because the repository still has broad direct usage of compatibility helper surfaces.

### Decision: Session-open replay moves into lifecycle participants

Package-owned session-open replay will migrate from controller-specific code paths to `SESSION_OPEN` lifecycle participants. `SessionController` will continue to own session start/resume ordering, state transitions, ingress execution, transcript persistence, and session cleanup. Packages may participate only inside those runtime-owned phases.

The intended session-open timing is:
- `SessionController` restores transcript, persisted metadata, and resumable private session state;
- the runtime dispatches `SESSION_OPEN` participants while session ownership still remains with `SessionController`;
- participants may replay or enqueue package-owned pending state inside that bounded phase;
- `SessionController` then marks the session ready and performs any controller-owned waiting-session drain or replay follow-up.

Why this decision:
- it removes package nouns from `SessionController` while preserving the existing lifecycle ownership model;
- it reuses an already-published protocol seam rather than creating a second controller plugin mechanism;
- it lets replay behavior remain package-owned without making session start logic package-aware.

Alternatives considered:
- keep package-specific replay hooks inside the controller: rejected because it keeps the owner layer coupled to package behavior;
- introduce a second dedicated replay registry: rejected because lifecycle participants already provide the right bounded phase model.

### Decision: Ingress gains bounded completion receipts instead of package-specific metadata handling

`SessionIngressResult` will gain a bounded completion-receipt protocol for post-ingress acknowledgements. For this change, the runtime-owned descriptor is named `IngressCompletionReceipt` and is carried directly on `SessionIngressResult.completion_receipts`. A completion receipt is an opaque runtime-owned descriptor executed by session control after ingress-defined transcript, replay, and private-state effects have been committed. `SessionController` will execute receipts without understanding package-specific receipt semantics.

The intended receipt execution model is:
- each ingress result may emit zero or more completion receipts;
- session control executes them in emitted order after transcript, replay, and private-state effects commit;
- receipt failure is fail-stop for the current receipt sequence, is surfaced through runtime-owned diagnostics/outcome handling, and does not trigger package-specific rollback branches for already-committed ingress effects;
- receipts stay intentionally opaque and bounded, and package implementations should tolerate at-least-once execution during retry or recovery.

The minimum contract we want to preserve at the type level is:
- `SessionIngressResult.completion_receipts` is an ordered tuple owned by the ingress result;
- each `IngressCompletionReceipt` has a stable `receipt_id`;
- each `IngressCompletionReceipt` has a named `kind` that resolves a runtime-owned execution path;
- any receipt payload stays opaque to `SessionController`, so package-specific branching does not reappear in owner layers.

This is intentionally narrower than a generic “post actions” framework. The first target is replacing package-specific metadata keys such as team delivery acknowledgements.

Why this decision:
- it removes package-specific acknowledgement logic from session control without losing deterministic post-ingress behavior;
- it fits the existing ingress contract, which already distinguishes normalized messages, replay outputs, prompt updates, and private updates;
- it avoids over-generalizing into a broad action framework before the concrete receipt use cases are proven.

Alternatives considered:
- keep package-specific metadata keys and helper methods: rejected because they perpetuate controller package knowledge;
- introduce a generic arbitrary action pipeline now: rejected because it would be too open-ended for the current scoped problem.

### Decision: Capability and host-facet lookup become the canonical package discovery APIs

Runtime-owned call paths, documentation, and tests will treat capability lookup and host-facet lookup as the canonical discovery paths for package-owned services. Existing package-specific wrappers such as top-level team properties or workflow helper methods may remain temporarily, but they are compatibility wrappers over the canonical lookup paths and must not provide unique semantics.

For the currently retained team surfaces, the authoritative discovery names remain the existing published keys:
- `RuntimeCapabilityKey.TEAM_CONTROL_PLANE`
- `RuntimeCapabilityKey.TEAM_MESSAGE_BUS`
- `RuntimeCapabilityKey.TEAM_WORKFLOWS`
- `RuntimeHostFacetKey.TEAM_WORKFLOWS`

Compatibility wrappers may continue to project these services on `RuntimeServices`, `RuntimeAssembly`, or bound-host helper methods, but they must resolve through those keys rather than maintaining a second owner-layer source of truth.

Why this decision:
- it ensures one stable discovery story for both runtime-owned and embedder-owned call sites;
- it makes capability and host-facet registries the actual source of truth rather than sidecar metadata;
- it allows compatibility wrappers to shrink over time without changing the normative package contract.

Alternatives considered:
- preserve wrappers as first-class public APIs alongside lookup: rejected because two equal-status discovery paths would keep boundary drift alive;
- delete wrappers immediately: rejected because migration and test churn would outweigh the design win in one patch.

### Decision: Package-specific host event egress stays compatibility-scoped for now

The current package-specific host event sink (`emit_team_event()`) will be treated as a bounded compatibility surface during this change. The runtime will avoid adding new package-specific host event methods, but it will also defer introducing a generalized package event bus until a second package demonstrates the same shared need.

Why this decision:
- it avoids locking in a generic event abstraction designed around one package’s needs;
- it keeps this change focused on sealing owner-layer leaks instead of inventing a new event framework;
- it still freezes further growth of package-specific host bridge methods.

Alternatives considered:
- immediately generalize to a package event bus: rejected because the abstraction would be premature;
- permanently bless `emit_team_event()` as the long-term package event path: rejected because it keeps package vocabulary in the mandatory host bridge story.

### Decision: `TaskManager` cleanup remains staged and orthogonal

This change will not remove `TaskManager`, but it will explicitly prohibit new runtime-owned primary paths from depending on `TaskManager` as an authoritative control plane. `JobService`, `TaskListService`, and `RuntimePrivateContext` remain the intended shared control surfaces. Existing `TaskManager`-shaped wrappers stay compatibility-only.

Why this decision:
- it keeps this boundary change tractable;
- it respects the already-documented staged migration from `TaskManager` to `JobService`;
- it avoids conflating package-boundary tightening with a broader background-work refactor.

Alternatives considered:
- remove `TaskManager` in the same change: rejected because it would materially enlarge the migration and test surface;
- ignore `TaskManager` entirely: rejected because boundary cleanup would otherwise keep inheriting a deprecated primary path.

### Decision: External package registration is deferred until first-party seams are sealed

The runtime will not introduce a general `extra_package_manifests` or third-party package catalog in this change. First-party owner-layer seams should become self-consistent before the protocol is widened into a public registration story.

Why this decision:
- it avoids freezing a half-migrated protocol as a public API;
- it keeps the work focused on tightening internal boundary discipline first;
- it preserves room to refine package context and collision policies before externalizing them.

Alternatives considered:
- open external package registration now: rejected because it would export the current transitional state.

## Risks / Trade-offs

- [Session-open replay regresses for team delivery or workflow recovery] → Mitigation: migrate replay behind `SESSION_OPEN` participants with explicit recovery and resume tests before removing controller special cases.
- [Completion receipts become an unbounded hidden action framework] → Mitigation: keep receipts opaque, bounded, and dedicated to deterministic post-ingress acknowledgements; explicitly defer a generic action system.
- [Compatibility wrappers remain in broad use and dilute the canonical lookup path] → Mitigation: update runtime-owned call paths, docs, and tests to use capability/facet lookup first; label wrappers as compatibility-only.
- [Host event compatibility causes confusion during migration] → Mitigation: freeze `emit_team_event()` semantics, avoid adding new package-specific host bridge methods, and document its compatibility status.
- [`TaskManager` cleanup scope creeps into a full control-plane rewrite] → Mitigation: limit this change to prohibiting new authoritative dependencies and narrowing the most obvious runtime-owned fallback paths.
- [Boundary work stalls future package extensibility] → Mitigation: explicitly defer external package registration only until the first-party seams are sealed, not indefinitely.

## Migration Plan

1. Add the owner-layer boundary and ingress completion-receipt contracts in specs and design docs.
2. Extend session-ingress models and controller execution flow to support bounded completion receipts.
3. Register package-owned session-open replay through lifecycle participants and migrate `runtime-team` replay off controller-owned special cases.
4. Route runtime-owned workflow helper paths through host-facet and capability lookup, keeping top-level helpers only as compatibility wrappers.
5. Demote package-specific runtime service slots and top-level assembly properties to explicit compatibility projections in docs, diagnostics, tests, and deprecation metadata.
6. Freeze `emit_team_event()` as a bounded compatibility sink and avoid expanding mandatory host bridge package vocabulary.
7. Narrow runtime-owned `TaskManager` fallbacks that still create or depend on authoritative task-manager-shaped state.

Rollback strategy:
- Because compatibility wrappers and projections remain during migration, rollback can restore migrated replay or helper paths while preserving the surrounding protocol scaffolding.

## Open Questions

- If a second control-plane pipeline later needs the same receipt semantics, should the runtime generalize `IngressCompletionReceipt` into a shared receipt carrier or keep ingress receipts as a dedicated protocol-local type?
- When a second package needs structured host event emission, should the runtime generalize to a package event extension surface or absorb those events into an existing host notification contract?
- Once first-party seams are sealed, should external package registration attach through explicit config-owned manifest catalogs, dynamic discovery, or both?
