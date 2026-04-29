## Context

The runtime now has enough real subsystems that “protocol” can no longer mean “whatever extension point happens to exist.” `TranscriptStore`, `JobService`, `TaskListService`, permission and elicitation services, context contributors, invocation providers, and the host bridge each have different binding shapes, but they all play the same architectural role: they are stable core seams that the runtime or embedders rely on across distributions.

Today that symmetry is under-documented. Some protocols are easy to discover because they are explicit config fields or service properties. Others are only implicit in runtime metadata, migration notes, or scattered docs. That is manageable while the audience is small, but it becomes brittle once package registration becomes more open and more contributors need to know which seams are canonical.

## Goals / Non-Goals

**Goals:**

- Publish one authoritative stable core protocol catalog for the runtime.
- Normalize how runtime metadata and docs describe the binding and discovery surface of each core protocol.
- Keep stable core protocols clearly separate from optional package capabilities, host facets, and compatibility wrappers.
- Add conformance coverage that checks catalog stability across distributions.

**Non-Goals:**

- Replacing all binding mechanisms with a single registry type.
- Removing compatibility wrappers in this change.
- Designing external package registration or dependency resolution.
- Collapsing package capabilities and stable core protocols into one undifferentiated extension catalog.

## Decisions

### 1. Protocol symmetry is a published catalog, not a mega-registry

This change will not force every core protocol through one registry abstraction. Instead, the runtime will publish a stable catalog that tells callers, tests, and docs:

- what the protocol is
- who owns it
- where it binds
- how it is discovered
- whether any compatibility surfaces still exist around it

Why this decision:

- the protocols already have different lifecycles and binding shapes
- a catalog solves the discoverability problem without flattening useful distinctions
- it keeps implementation churn low while clarifying architecture

Alternatives considered:

- invent a single universal protocol registry: rejected because it would over-normalize unrelated lifecycles
- leave symmetry as documentation-only prose: rejected because metadata and tests need a machine-readable contract

### 2. Every stable core protocol gets one canonical binding boundary

The catalog will declare one authoritative binding boundary per protocol class:

- config or store binding for transcript persistence
- shared service binding for jobs, task lists, permissions, and elicitation
- contributor registry for request-time context contributors
- invocation registry for invocation providers
- host binding for `HostRuntime`

Why this decision:

- it makes extension guidance concrete
- it prevents multiple “equally canonical” entrypoints from reappearing
- it gives later external registration work a cleaner base to build on

Alternatives considered:

- allow protocols to keep multiple primary binding stories: rejected because it defeats symmetry

### 3. Stable core protocols stay separate from package capabilities

Package capabilities, host facets, and lifecycle participants remain important, but they are not themselves the stable core protocol catalog. The catalog names the runtime’s shared microkernel seams; package capabilities plug into or around those seams.

Why this decision:

- it keeps the microkernel skeleton distinct from first-party package inventory
- it avoids making every package-contributed object look like a core protocol
- it aligns with the user’s target architecture diagram

Alternatives considered:

- merge package capabilities into the same top-level catalog: rejected because it confuses optional package additions with baseline runtime protocols

### 4. Conformance should verify the catalog across distributions

Different selected first-party packages may change capabilities and optional helpers, but they should not mutate the identity of the stable core protocol set. Conformance tests will therefore verify that assembled distributions publish the same core protocol entries and canonical discovery guidance.

Why this decision:

- it catches accidental drift early
- it makes the protocol catalog more than a documentation artifact
- it supports future external package work with a firmer baseline

Alternatives considered:

- rely on docs review alone: rejected because symmetry regressions are easy to miss without automated checks

### 5. The protocol catalog has a versioned minimum schema and a separate source-of-truth boundary

The stable core protocol catalog will publish a versioned machine-readable schema with minimum required fields such as protocol id, owner, binding boundary, discovery surface, and compatibility status. It will remain distinct from package-specific metadata blocks such as package inventory, package lookup, and compatibility projections.

Why this decision:

- later changes need something machine-readable, not just prose
- it prevents stable core protocol metadata from drifting into package-specific taxonomies
- it gives conformance tests a clear schema target

Alternatives considered:

- let the catalog remain an informal dict shape: rejected because later registration and resolver work will need a stronger contract
- duplicate package lookup and protocol catalog data in one mixed block: rejected because it would recreate the ambiguity this change is meant to remove

## Risks / Trade-offs

- [The catalog could become a stale documentation layer] -> Mitigation: generate it from runtime-owned metadata, version its minimum schema, and verify it in conformance tests.
- [Some protocols have awkward transitional compatibility stories] -> Mitigation: catalog compatibility explicitly instead of pretending the migration is already finished.
- [Consumers may overread the catalog as “everything is equally pluggable”] -> Mitigation: distinguish stable core protocols from optional package capabilities and document each protocol’s actual binding surface.
- [Too much symmetry pressure could erase useful differences] -> Mitigation: publish one catalog while keeping protocol-specific lifecycles and binding shapes where they matter.

## Migration Plan

1. Define the stable protocol catalog model and populate it from runtime-owned assembly metadata.
2. Update runtime assembly and control-plane docs so each core protocol names its canonical binding and discovery path.
3. Separate protocol catalog reporting from package inventory and compatibility projection reporting.
4. Add conformance coverage that checks catalog stability across assembled distributions.

Rollback is low-risk because this change mostly clarifies and exposes existing contracts. If a catalog entry is wrong, it can be corrected without breaking the underlying implementation path.

## Open Questions

None for this proposal stage. The key default is settled: protocol symmetry is enforced through an explicit catalog and conformance story, not through a universal registry rewrite.
