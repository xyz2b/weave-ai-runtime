## Context

The runtime now satisfies the core shape of the target architecture: runtime assembly is manifest-backed, distributions are explicit, package contributions attach through protocol-owned seams, stable core protocols are published separately from package metadata, and a protocol-only conformance gate already protects the main boundary rules.

What remains is not another missing backbone feature. The remaining gaps are terminal-closure gaps:

1. a bounded but still-visible compatibility layer remains in the public surface area (`TaskManager`, compatibility projections for memory/compaction/isolation/team, shared legacy `runtime_context` expectations, and legacy agent-owned hook authoring);
2. the weakest first-party mechanism package (`runtime-isolation`) still advertises `worktree` and `remote` through stub leases instead of production-grade semantics;
3. durable transcript and child-run history are still uneven defaults across distributions, so lifecycle/recovery observability depends too much on embedder-side wiring rather than bundled runtime profiles.

This change is therefore a closure-and-hardening change. It should finish the microkernel rollout rather than introduce another partial seam.

## Goals / Non-Goals

**Goals:**
- Retire or explicitly isolate the remaining compatibility-only runtime surfaces so the default primary path is genuinely protocol-only.
- Replace stub isolation behavior with honest runtime semantics for `worktree` and `remote`, including preparation, metadata, cleanup, and failure signaling.
- Define bundled persistence profiles that make transcript and child-run durability an explicit runtime product decision instead of an accidental side effect of host injection.
- Publish closure metadata and conformance outputs that answer, in one place, whether a runtime instance is still relying on legacy surfaces or non-production defaults.
- Update architecture and migration documentation so the codebase has one authoritative explanation of what is complete, what is legacy-only, and what remains intentionally out of scope.

**Non-Goals:**
- Introducing a remote package marketplace, install/publish workflow, auto-discovery, or Python environment package management.
- Redesigning stable core protocols that are already working, such as package contributions, context contributors, lifecycle phases, host facets, jobs, task lists, or child-run continuation.
- Shipping a bundled universal remote-execution backend; the goal is to eliminate dishonest stub semantics, not to force one transport choice.
- Performing a blind flag-day API deletion without a documented migration path.

## Decisions

### Decision: Compatibility retirement is explicit, published, and default-denying

The runtime will define a finite compatibility-retirement contract that lists the remaining legacy surfaces, their migration targets, and whether they are still available in the default runtime surface or only behind an explicit legacy mode/profile.

The initial retirement set includes:
- `TaskManager` as a public primary control-plane dependency;
- shared authoritative writes through legacy `runtime_context` paths;
- package-specific compatibility projections such as `RuntimeServices.memory`, `RuntimeServices.compaction`, `RuntimeServices.isolation`, and retained team projections when used as canonical discovery;
- legacy agent-owned hook authoring surfaces that still look like ordinary v1 extensibility.

Legacy enablement will be modeled per compatibility family rather than as one undifferentiated global escape hatch. A coarse legacy preset may still exist, but it must expand into a published family-level allowlist so the closure report can state exactly which legacy families remain enabled.

Why this decision:
- today's runtime already knows these are compatibility-only, but callers still have to infer retirement state indirectly from multiple metadata blocks;
- closure requires a runtime-level answer to "is this surface still normative or only tolerated?";
- default-denying legacy access is the cleanest way to stop new code from extending the migration window indefinitely.

Alternatives considered:
- remove every remaining compatibility surface in one flag day: rejected because it would create unnecessary embedder churn and muddy rollout ownership;
- leave compatibility surfaces indefinitely with warnings only: rejected because that preserves architectural ambiguity and keeps the rollout permanently unfinished;
- use one opaque global legacy switch only: rejected because it hides which surface families still block closure.

### Decision: Persistence becomes a first-party profile, not an accidental host detail

The runtime will publish explicit persistence profiles for transcript and child-run history. At minimum:
- small/runtime-core style profiles may remain lightweight and in-memory by default;
- `runtime-full` becomes the initial production-oriented first-party profile and SHALL bundle a durable transcript path and a durable child-run path through first-party package wiring rather than requiring ad hoc host assembly;
- `runtime-default` remains lightweight in this change, but it must publish that weaker contract explicitly rather than looking equivalent to `runtime-full`.

This implies adding a first-party child-run durable binding story alongside the existing file-backed transcript/job/task/team store bundle.

Why this decision:
- child runs are part of the framework's observability truth, so leaving their durability entirely optional undermines the maturity of the lifecycle model;
- the codebase already treats distribution/package composition as a product surface, which is the right place to declare persistence expectations;
- it keeps "minimal runtime" and "production runtime" both valid without pretending they are equivalent.

Alternatives considered:
- make every distribution durable by default: rejected because `runtime-core` is intentionally lightweight and embeddable;
- move durable child-run persistence into `runtime-default` immediately: rejected for now because it widens default behavior more than needed for terminal closure;
- keep child-run durability as host-only wiring forever: rejected because the runtime would continue to under-specify one of its own core observability surfaces.

### Decision: `worktree` becomes concrete through a filesystem-local lease; `remote` becomes honest and adapter-backed

`worktree` isolation will gain a real first-party implementation with deterministic prepare/cleanup behavior and host-visible lease metadata. The initial hardening pass will use a filesystem-local prepared lease directory that does not require a Git repository or a bundled VCS-specific dependency to exist. `remote` will no longer return a fake successful stub lease; it will either use a configured remote adapter contract or fail with a structured not-available/not-configured outcome before execution proceeds.

Why this decision:
- the current `stub=true` semantics are the single clearest sign that the mechanism layer is not finished;
- a filesystem-local lease is honest and broadly available, while keeping room for future Git-optimized variants;
- `remote` does not need one blessed backend, but it must stop masquerading as implemented when no backend exists.

Alternatives considered:
- leave both modes as semantic placeholders: rejected because the runtime already publishes them as stable isolation modes;
- require Git worktrees as the only first-party implementation: rejected because the runtime must remain usable outside Git repos;
- require a bundled remote backend now: rejected because transport selection is product-specific and would over-expand this change.

### Decision: Closure state is published through a canonical closure report

The runtime will publish a dedicated closure/hardening report at `runtime.services.metadata["closure_report"]` and `runtime.metadata["closure_report"]`. It will sit beside, not inside, the stable core protocol catalog and package-resolution metadata.

The report will at minimum describe:
- the compatibility-retirement inventory and legacy-family activation state;
- active persistence profile;
- transcript and child-run durability state, plus the declared durability state of other supported persistence surfaces;
- isolation readiness by mode;
- whether the current assembly is considered closure-green.

Why this decision:
- the stable core protocol catalog answers "what is the contract"; it does not answer "how much legacy is still enabled here";
- embedders need one clear runtime-owned place to inspect closure state;
- conformance should consume the same report rather than rebuilding hidden logic.

Alternatives considered:
- overload `core_protocol_catalog` with closure state: rejected because it mixes stable contract metadata with rollout-state metadata;
- keep closure state spread across migration, compatibility, and conformance blocks only: rejected because callers must currently reconstruct the real answer manually.

### Decision: Hook compatibility is narrowed into explicit legacy behavior

Agent-owned legacy hook envelopes, especially agent frontmatter hooks, will no longer present as ordinary public v1 extension surfaces. Supported legacy skill/invocation hook envelopes remain up-converted into the canonical registration schema, but agent-owned legacy envelopes will either be rejected by default or require explicit legacy compatibility enablement, while preserving documented migration targets through runtime config, host/session APIs, and skill-facing hook surfaces.

Why this decision:
- this is the last major authoring surface that still looks first-class while the docs already classify it as compatibility-only;
- leaving it soft-deprecated invites new usage and prolongs migration indefinitely;
- hook behavior affects trust, policy, and diagnostics, so ambiguous authoring status is more dangerous here than for a passive metadata field.

Alternatives considered:
- keep emitting warnings forever: rejected because warning-only compatibility is exactly how migration never ends;
- remove all legacy definition-owned hooks immediately, including supported skill/invocation up-conversion paths: rejected because the runtime still has valid non-legacy hook authoring surfaces that should remain public.

## Risks / Trade-offs

- [Compatibility retirement breaks embedders that quietly relied on deprecated helpers] -> Mitigation: publish a finite retirement inventory, explicit legacy mode, migration targets, and conformance-backed docs before default removal.
- [Adding persistence profiles confuses users about distribution identity] -> Mitigation: keep distribution/package selection as the product identity and publish profile metadata rather than inventing a second hidden assembly axis.
- [Worktree implementation introduces filesystem complexity] -> Mitigation: keep the first-party implementation narrow and deterministic, with clear cleanup ownership and structured lease metadata.
- [Remote isolation remains backend-dependent] -> Mitigation: require honest structured failure when no adapter is configured, and keep the runtime contract adapter-based rather than backend-specific.
- [Closure metadata duplicates existing migration/conformance information] -> Mitigation: treat the closure report as the top-level summary and keep deeper metadata blocks as supporting detail.

## Migration Plan

1. Introduce the compatibility-retirement inventory and canonical closure report in metadata without immediately removing every legacy access point.
2. Add bundled persistence-profile metadata and first-party durable child-run store wiring for `runtime-full`.
3. Replace stub isolation behavior with a real filesystem-local worktree lease implementation and explicit remote-adapter failure semantics.
4. Narrow default public access to legacy compatibility surfaces and agent-owned legacy hook authoring paths, keeping explicit family-level legacy enablement only where needed for staged migration.
5. Extend runtime-conformance coverage to fail closure-red assemblies and verify persistence/isolation expectations across the supported distribution matrix.
6. Update architecture, migration, and extension docs to reflect the final boundary story.

Rollback strategy:
- Closure metadata can remain even if individual retirements are postponed.
- If a compatibility removal proves too disruptive, keep the surface behind explicit legacy mode rather than restoring it as a silent default path.
- If worktree hardening regresses local execution, revert to the previous `none` mode fallback only with explicit diagnostics; do not restore fake `stub=true` success semantics.

## Open Questions

- None. This change is intended to be implementation-ready; the remaining rollout work is engineering, not product-definition ambiguity.
