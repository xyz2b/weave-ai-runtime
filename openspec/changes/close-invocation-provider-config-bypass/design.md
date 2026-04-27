## Context

Package-contributed invocation providers already exist and are registered in a deterministic tier ahead of config-supplied providers, but the runtime still admits a config-owned bypass through `RuntimeConfig.extra_invocation_providers`. That keeps invocation-provider extensibility out of line with the broader runtime-package story, where package-owned extensions are expected to enter through manifests and contributions.

The goal here is not to remove extensibility. The goal is to make invocation-provider extensibility consistent with the package protocol model by replacing the config tier with a lightweight provider-only package pattern.

## Goals / Non-Goals

**Goals:**
- Remove the config-owned invocation-provider bypass from runtime assembly.
- Make package contribution the only normative invocation-provider extension path after the built-in baseline.
- Preserve deterministic provider registration order and provenance metadata.
- Give embedders a lightweight migration path through provider-only runtime packages.
- Publish structured conformance findings that a terminal protocol-only gate can aggregate.

**Non-Goals:**
- Redesigning the invocation-definition conflict rules.
- Removing the built-in skill invocation-provider baseline.
- Reworking broader package registration or dependency-resolution semantics outside what provider-only packages need.
- Turning invocation providers into definition-discovery artifacts instead of runtime packages.

## Cross-Change Fit

This is the second Wave 2 breaking migration. It should land after the Wave 1 authority and resolver cleanup, and before the terminal conformance/catalog change that turns provider provenance into a hard protocol-only rule.

Because this is embedder-facing, the rollout should stay isolated from the team bridge break when practical. That keeps migration attribution clear and avoids coupling host contract churn with package-registration churn in a single flag day.

## Decisions

### Decision: Invocation providers become package-only extensions after the built-in baseline

The runtime will keep the built-in skill invocation-provider baseline and then admit custom invocation providers only through `PackageContribution.invocation_providers`.

Why this decision:
- it aligns provider extensibility with the runtime package protocol story;
- it removes one of the last remaining config-owned assembly bypasses;
- it keeps provider provenance and ordering simpler.

Alternatives considered:
- keep config providers as a permanent second-class tier: rejected because the target state is protocol-only;
- discover providers directly from definition directories: rejected because providers are runtime assembly objects, not definition markdown.

### Decision: Support lightweight provider-only packages

Embedders will be able to create tiny runtime packages whose only job is to contribute invocation providers.

Why this decision:
- it preserves embedder ergonomics after the config bypass is removed;
- it avoids forcing a large package shape for a small extension;
- it reuses the existing external package registration path.

Alternatives considered:
- require every embedder to vendor provider changes into a larger runtime package: rejected because it creates unnecessary friction.

### Decision: Provider-only packages use the ordinary runtime package manifest shape

This change will not introduce a dedicated manifest role just for provider-only packages. A provider-only package remains an ordinary runtime package with a documented minimal shape:
- ordinary package identity and manifest metadata;
- any baseline dependencies it requires, with `runtime-core` as the common baseline in ordinary cases;
- one or more `invocation_providers` contributions;
- optional ordering metadata that continues to use the existing package and contribution ordering rules.

Why this decision:
- it avoids inventing a new package taxonomy for a narrow extension case;
- it keeps provider-only packages compatible with the existing external package registration path;
- it lets docs, examples, and conformance reason about provider-only packages as ordinary packages with a minimal contribution surface.

Alternatives considered:
- add a dedicated `provider-only` manifest role immediately: rejected because it adds taxonomy churn before the ordinary package shape has proven insufficient;
- leave the minimal shape implicit: rejected because embedders need a crisp migration target once the config bypass disappears.

### Decision: Provider provenance metadata will drop the config tier entirely

Invocation-provider metadata and runtime-assembly metadata will publish only:
- the built-in baseline tier;
- package-contributed provider registrations.

Why this decision:
- the metadata should reflect the actual canonical paths;
- conformance becomes simpler when the bypass is gone;
- docs and tests can share the same provenance story.

Alternatives considered:
- keep the config tier in metadata as a hidden legacy path: rejected because hidden paths are exactly what this change is eliminating.

### Decision: Removal is breaking, but migration is straightforward

This change is intentionally breaking for embedders that currently use `RuntimeConfig.extra_invocation_providers`, but the migration path is direct: wrap that provider in a provider-only runtime package and register it through the existing external package path.

Why this decision:
- long-term consistency is worth the short-term API break;
- the migration target already exists in the runtime package model;
- the smaller break now prevents indefinite dual-path complexity.

### Decision: Provider conformance findings must be published independently of the final gate

This change will publish structured provider-provenance findings itself rather than expecting the terminal protocol-only gate to rediscover provider registration paths from scratch.

Why this decision:
- the invocation registry already knows the provider tiers and ordering semantics;
- it keeps subsystem-specific logic close to the subsystem that owns it;
- it allows the final gate to aggregate stable rule results instead of duplicating registry audits.

Alternatives considered:
- let the final gate inspect raw provider registration state directly: rejected because it couples the terminal change to invocation-registry internals.

## Risks / Trade-offs

- [Embedders view package wrapping as too much ceremony] -> Mitigation: provide a lightweight provider-only package pattern and examples.
- [Some tests still assume the config tier exists] -> Mitigation: migrate metadata and test helpers in the same change.
- [Provider provenance regressions become harder to interpret during migration] -> Mitigation: make registration metadata explicit and remove the old tier entirely rather than leaving a mixed state.

## Migration Plan

1. Define and document the provider-only runtime package pattern, including its ordinary minimal manifest shape.
2. Publish a provider-only package example or template that tests and docs can share.
3. Migrate runtime assembly and metadata to baseline-plus-package-only provider registration.
4. Remove `RuntimeConfig.extra_invocation_providers` from canonical assembly logic.
5. Publish structured provider-provenance findings, then update tests, docs, and migration notes for the new package-only path.

Rollback strategy:
- If an embedder migration is blocked unexpectedly, temporarily restore a compatibility adapter that converts the old config input into an ephemeral package contribution internally while keeping the package-only contract as the documented target.

## Open Questions

- Do we want a helper CLI/template for generating provider-only packages as part of the migration docs?
- Beyond the ordinary minimal package shape, do we later want an additive metadata label that marks a package as provider-only for diagnostics or UX?
