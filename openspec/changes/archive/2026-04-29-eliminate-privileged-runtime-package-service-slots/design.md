## Context

The package protocol model is already strong enough to describe package-owned built-ins, capabilities, lifecycle participants, host facets, stores, providers, and job executors. The largest remaining owner-layer exception is a small set of privileged dedicated service slots that let a package-owned subsystem bypass protocol lookup and attach directly to core runtime surfaces:

- `RuntimeServices.memory`
- `RuntimeServices.compaction`
- `RuntimeServices.isolation`

Those fields still act as source-of-truth bindings for core runtime paths in `SessionController`, `TurnEngine`, `ToolRuntime`, and `AgentExecutionService`. That is a real architectural leak because the core owner layers can still only function if they know about a package-shaped slot instead of a runtime-owned protocol binding.

This change is intentionally narrower than redesigning memory semantics, compaction semantics, or isolation policy. The goal is to change how those subsystems attach to the microkernel, not what those subsystems do.

## Goals / Non-Goals

**Goals:**
- Remove privileged dedicated package-service slots as the canonical owner-layer integration path.
- Introduce explicit runtime-owned protocol bindings for memory, compaction, and isolation services.
- Keep runtime-owned code readable by exposing typed protocol accessors instead of scattering raw capability-string lookups throughout hot paths.
- Preserve current runtime behavior while changing binding ownership and discovery semantics.
- Publish enough metadata and structured conformance findings for tests and embedders to tell canonical protocol bindings from compatibility projections.

**Non-Goals:**
- Redesigning memory retrieval, extraction, or persistence behavior.
- Redesigning compaction policies, context-window logic, or continuation semantics.
- Redesigning isolation modes, lease semantics, or executor policy.
- Removing all compatibility projections in the same patch if a short migration window still reduces churn.
- Generalizing every package-owned service into one giant opaque interface.

## Cross-Change Fit

This is a Wave 1 foundation change. It is intentionally non-breaking at the public API layer and is best sequenced after `retire-runtime-context-and-taskmanager-compat` when possible, because both changes edit the same owner-layer files and the authority cleanup makes the later resolver migration smaller and easier to audit.

Later roadmap changes depend on two outputs from this change:
- canonical service-family binding metadata that distinguishes canonical bindings from retained projections;
- structured conformance findings that prove privileged service families are no longer sourced from dedicated slots.

## Decisions

### Decision: Introduce one explicit protocol binding per privileged service family

The runtime will publish explicit runtime-owned protocol bindings for the remaining privileged service families rather than treating `RuntimeServices.memory`, `RuntimeServices.compaction`, and `RuntimeServices.isolation` as special canonical fields.

The first published families are:
- memory runtime protocol
- compaction runtime protocol
- isolation runtime protocol

Why this decision:
- it closes the owner-layer leak without collapsing unrelated semantics into one oversized abstraction;
- it gives runtime-owned code one explicit lookup path per service family;
- it keeps package ownership visible in metadata and diagnostics.

Alternatives considered:
- keep using the existing fields and document them as special core slots: rejected because that preserves the leak;
- create one generic `package_service` bag: rejected because it loses semantic clarity and encourages more ad hoc branching.

### Decision: Runtime-owned code resolves protocol bindings through typed accessors, not raw capability strings

The runtime will centralize access through typed helpers on the runtime control-plane surface, so hot paths do not repeatedly spell raw capability strings or perform ad hoc fallback logic.

Why this decision:
- it preserves readability in owner-layer code;
- it makes future conformance checks easier because canonical lookup points are centralized;
- it avoids replacing one special case with many low-level lookup call sites.

Alternatives considered:
- inline `resolve_capability()` everywhere: rejected because it spreads protocol knowledge through every hot path;
- keep direct field access as a convenience alias: rejected because convenience aliases tend to become source of truth again.

### Decision: Existing `RuntimeServices` fields become derived compatibility projections only

For migration compatibility, the runtime may continue to expose `RuntimeServices.memory`, `RuntimeServices.compaction`, and `RuntimeServices.isolation`, but those fields become derived projections over the protocol bindings rather than canonical registration surfaces.

Why this decision:
- it allows a staged migration for tests and embedders;
- it keeps the source of truth in one place;
- it makes it possible to remove the projections later without changing protocol semantics.

Alternatives considered:
- remove the fields immediately: rejected because the churn is unnecessary if the runtime can first demote them safely;
- keep dual canonical paths indefinitely: rejected because it would preserve the ambiguity this change is trying to eliminate.

### Decision: Migration proceeds service family by service family

The runtime will migrate the privileged service families in a deliberate order:
1. memory protocol binding
2. compaction protocol binding
3. isolation protocol binding

Why this decision:
- memory has the broadest touch surface and proves the migration model;
- compaction is narrower but still heavily exercised in turn preparation;
- isolation has the smallest owner-layer surface and can move last once the helper patterns are settled.

Alternatives considered:
- move all three at once: rejected because debugging regressions across all three would be unnecessarily expensive.

### Decision: Conformance metadata must expose privileged-slot retirement explicitly

The runtime will publish metadata and structured conformance findings that mark the old privileged slots as compatibility-only and record the canonical protocol binding for each migrated service family.

Why this decision:
- architectural intent becomes machine-readable;
- docs, targeted regression tests, and the terminal protocol-only gate can consume the same source of truth;
- future changes can detect regressions rather than relying on memory.

Alternatives considered:
- rely on code review alone: rejected because this boundary has already regressed before.

## Risks / Trade-offs

- [Migration breaks a hot path that depended on implicit slot behavior] -> Mitigation: migrate one service family at a time with focused regression tests around each path.
- [Protocol helpers become thin wrappers over a still-hidden special case] -> Mitigation: make the helper resolve through protocol-owned bindings and mark the legacy fields as derived projections in metadata.
- [Memory service shape proves too broad for one protocol object] -> Mitigation: keep the family binding stable but allow the protocol object to surface narrower sub-behaviors internally.
- [Embedders keep using legacy fields and miss the new path] -> Mitigation: publish canonical binding metadata and update docs to make the compatibility status explicit.
- [Conformance remains informal] -> Mitigation: add metadata-backed assertions and targeted runtime tests in the same change.

## Migration Plan

1. Add protocol identifiers, ownership metadata, and typed resolver helpers for memory, compaction, and isolation service families.
2. Migrate memory-owned runtime paths to the protocol resolver and demote `RuntimeServices.memory` to a derived projection.
3. Migrate compaction-owned runtime paths to the protocol resolver and demote `RuntimeServices.compaction` to a derived projection.
4. Migrate isolation-owned runtime paths to the protocol resolver and demote `RuntimeServices.isolation` to a derived projection.
5. Publish compatibility metadata, structured conformance findings, and documentation that mark the old slots non-canonical.

Rollback strategy:
- Restore individual service-family call sites to their previous slot-backed lookup while keeping the protocol-binding scaffolding in place if a migration step regresses behavior.

## Open Questions

- Should guarded workspace roots remain part of the memory family protocol, or move to a narrower tool-policy protocol later?
- Do we want one shared ownership metadata shape for all protocol-bound package services, or service-family-specific metadata extensions?
- Once the projections are compatibility-only, do we keep them for one release cycle or remove them as soon as all runtime-owned call sites are migrated?

