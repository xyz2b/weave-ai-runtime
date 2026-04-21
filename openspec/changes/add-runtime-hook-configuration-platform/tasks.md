## 1. Public Phase Contract

- [x] 1.1 Introduce an authoritative public phase registry that distinguishes `kernel public`, `control-plane public`, and `internal-only` stability tiers.
- [x] 1.2 Define typed payload contracts, minimum stable payload fields, and the per-phase effect-class / concrete-effect-field / external-handler matrix for the initial public phase catalog, including the new control-plane phases.
- [x] 1.3 Update hook validation and authoring surfaces so registrations are checked against the public phase registry, unlisted phases are treated as `internal-only`, and unsupported effect fields are rejected or surfaced through diagnostics.

## 2. Registration And Scope Model

- [x] 2.1 Introduce a normalized hook registration model that records source, source_ref, owner, scope, cleanup boundary, inheritance policy, handler manifest, and declared effect contract.
- [x] 2.2 Publish a canonical public authoring schema for runtime config, definition frontmatter, host APIs, session APIs, and turn APIs, and normalize legacy phase-keyed definition hooks into that schema before activation.
- [x] 2.3 Add runtime-level, host-level, definition-owned, session-scoped, and turn-scoped registration surfaces on top of the existing hook bus.
- [x] 2.4 Define and persist a stable precedence key across source kind, materialization boundary, and local declaration or call order for every active registration.
- [x] 2.5 Extend turn/session/child cleanup and session materialization paths so templates, turn-scoped hooks, and inherited registrations are activated, ordered, and released according to their declared scope.
- [x] 2.6 Publish typed `HookRegistrationRequest` and `HookRegistrationHandle` contracts for runtime, host, session, and turn APIs, including idempotent release and lifecycle states.
- [x] 2.7 Publish authoritative example fixtures or reference docs for runtime config, host API, session API, turn API, and stop/recovery approval flows so the public authoring surface is exercised end-to-end.

## 3. Handler Kinds And Adapter Execution

- [x] 3.1 Define a typed handler-manifest model for `callback`, `http`, `command`, `agent`, and `prompt`, including callback binding references for declarative config.
- [x] 3.2 Implement `callback` as the canonical typed hook execution path for trusted in-process integrations and normalize imperative callback registrations into the shared manifest model.
- [x] 3.3 Add an adapter layer that can normalize `http`, `command`, `agent`, and `prompt` handler outputs into the common structured hook effect contract.
- [x] 3.4 Add policy, trust, timeout, and failure handling by handler class so external execution can be allowed or denied independently from in-process callbacks.

## 4. Main-Loop Integration

- [x] 4.1 Wire the new public hook points into context assembly, request shaping, post-response handling, and recovery decision boundaries in the main loop.
- [x] 4.2 Publish and enforce the stable main-loop layer mapping for each public phase, including ordering relative to request emission, tool replay, stop handling, and recovery commit.
- [x] 4.3 Route hook-produced request overrides, continuation requests, blocking outcomes, and other phase-specific effect fields through their canonical request-shaping, tool, elicitation, notification, or recovery consumption paths.
- [x] 4.4 Preserve existing skill-hook behavior while migrating those paths onto the unified hook configuration platform.

## 5. Diagnostics And Conformance

- [x] 5.1 Publish a stable diagnostics schema for registration inventory and phase dispatch traces, including matched, blocked, ignored, winner, and applied-outcome sections.
- [x] 5.2 Add coverage for canonical authoring-schema normalization, multi-source registration precedence, deterministic aggregation, field-level winner attribution, phase-specific effect-field enforcement, scope-aware cleanup, and inherited child-execution behavior.
- [x] 5.3 Add correlation coverage so tool denials, elicitation satisfaction, request overrides, and blocked continuations can be traced back to hook dispatch diagnostics.
- [x] 5.4 Add coverage for policy-blocked external handlers, ignored effect fields, and sensitive-detail redaction in host-visible diagnostics.
- [x] 5.5 Add public inventory and dispatch-trace inspection APIs with stable query objects, bounded retrieval, and host/runtime/session semantic parity.
- [x] 5.6 Publish and automate a conformance matrix that covers public-phase validation, precedence winners, field-level merge attribution, tool denial, elicitation satisfaction, request-override propagation, stop/recovery correlation, scope cleanup, inheritance, and policy-blocked external handlers.
