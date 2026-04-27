## Context

The runtime already models invocation sources through `InvocationProvider` and `InvocationRegistry`, and the current architecture docs explicitly say the catalog can aggregate more than skills. But the actual assembly path is still split:

- skill invocations are wired by kernel-owned code
- extra providers arrive through `RuntimeConfig.extra_invocation_providers`
- package contributions do not have an invocation-provider contribution type

That split is survivable for one or two hard-coded providers, but it does not scale to a package-oriented architecture. Package-owned invocation sources should attach through the same manifest-backed contribution mechanism that already carries other package-owned surfaces.

## Goals / Non-Goals

**Goals:**

- Add a manifest-backed contribution type for invocation providers.
- Make package-contributed providers register through the same invocation registry used by built-in and config-supplied providers.
- Preserve current visibility, path-scoping, and policy-filtering semantics of the invocation catalog.
- Keep current embedder config override points available during migration.

**Non-Goals:**

- Designing an external plugin marketplace or download workflow.
- Replacing `InvocationRegistry` with a capability-registry abstraction.
- Changing invocation execution policy, visibility policy, or diagnostics semantics beyond what package contribution support requires.
- Introducing a new package assembly stage unless it is strictly necessary.

## Decisions

### 1. Invocation providers get their own package contribution type

Invocation providers will be added to `PackageContribution` as a dedicated contribution surface instead of being smuggled through generic capabilities.

Why this decision:

- providers are registry inputs, not long-lived control-plane services
- owner-aware diagnostics are easier to express directly
- it preserves a clear distinction between lookup objects and catalog-population objects

Alternatives considered:

- register providers through the capability registry: rejected because it would overload capability lookup with registry-population semantics
- keep package providers in `RuntimeConfig.extra_invocation_providers`: rejected because that keeps package registration asymmetric

### 2. Provider registration happens during kernel build, not runtime start

Package-contributed invocation providers will be discovered from manifest contributions early enough that the kernel can register them before hosts or sessions resolve invocation catalogs. No new top-level package assembly stage is required; the kernel can apply provider contributions after definition discovery and before invocation diagnostics are finalized.

Why this decision:

- invocation catalogs must be available before session execution starts
- provider registration is a kernel concern, not a runtime-lifecycle concern
- it avoids introducing a new stage just for one contribution type

Alternatives considered:

- add a dedicated package assembly stage for invocation providers: rejected because it increases assembly complexity without a demonstrated second use case
- register package providers lazily during the first session: rejected because it makes diagnostics and host-visible catalogs nondeterministic

### 3. Registration precedence is explicit and split from definition conflict resolution

Provider registration order will be:

- built-in skill provider baseline first
- package-contributed providers second
- config-supplied providers last

Within the package-contributed tier, registrations are ordered by `InvocationProviderContribution.order`, then by package dependency order, and then by contribution name so cross-package overrides stay deterministic.

If a later provider reuses the same `provider.name`, the invocation registry will replace the earlier provider and emit a provider-replacement diagnostic. After registration is complete, invocation-definition conflicts inside the surviving provider set remain owned by `InvocationRegistry`'s existing definition conflict rules.

Why this decision:

- it matches the current registry replacement behavior
- it gives packages a deterministic canonical slot without taking override power away from embedders
- it separates provider-container precedence from invocation-definition shadowing semantics

Alternatives considered:

- leave provider precedence implicit in registration order only: rejected because callers would have no stable override contract
- let package-contributed providers override config-supplied providers: rejected because embedders need a stronger local override surface

### 4. `extra_invocation_providers` remains a compatibility and embedder surface

This change does not remove `RuntimeConfig.extra_invocation_providers`. Instead, package-contributed providers become the canonical first-party package path, while config-supplied providers remain available for embedders and targeted overrides.

Why this decision:

- embedders still need a direct config-owned path
- it reduces migration churn for existing integrations
- it keeps package contribution and embedder config as distinct extension stories

Alternatives considered:

- remove `extra_invocation_providers` immediately: rejected because it would break existing integrations for little architectural gain

### 5. Provider conflicts remain invocation-registry concerns

Conflict resolution, shadowing rules, and diagnostics remain owned by `InvocationRegistry`. Package contribution changes how providers arrive at the registry, not how visible invocations are resolved once there.

Why this decision:

- it keeps provider registration and invocation resolution decoupled
- it preserves existing conflict and diagnostics semantics
- it minimizes surprise for hosts and tests that already consume invocation diagnostics

Alternatives considered:

- make package contribution own conflict resolution: rejected because that would split authority away from the invocation registry

## Risks / Trade-offs

- [Package providers may need richer kernel context than plain provider objects] -> Mitigation: allow contribution bindings to carry a factory or equivalent deferred construction path without introducing a new assembly stage.
- [Two registration paths remain visible during migration] -> Mitigation: document package contribution as canonical for packages and `extra_invocation_providers` as embedder-facing compatibility.
- [Provider ordering bugs could change catalog visibility unexpectedly] -> Mitigation: keep deterministic registration order, owner-aware diagnostics, and explicit regression tests for conflict cases.
- [First-party package providers might duplicate definition discovery behavior] -> Mitigation: keep provider responsibilities narrow and push raw tool/agent/skill loading concerns back to existing registries where appropriate.

## Migration Plan

1. Add invocation-provider contributions to the package protocol and runtime package manifest helpers.
2. Register package-contributed providers during kernel build alongside the built-in skill provider baseline and config-supplied providers.
3. Update docs and diagnostics to describe package-contributed providers as the canonical package-owned path into the unified invocation catalog, while documenting that current official distributions do not yet ship a non-skill provider through that path.
4. Add regression coverage for deterministic provider ordering, shadowing diagnostics, and unchanged path or policy-aware catalog resolution.

Rollback is low-risk because `extra_invocation_providers` remains available and package-owned providers can temporarily be re-registered through config if needed.

## Open Questions

None for this proposal stage. The main default is resolved here: invocation providers become a dedicated package contribution type, but the invocation registry remains the authoritative owner of catalog resolution and conflict behavior.
