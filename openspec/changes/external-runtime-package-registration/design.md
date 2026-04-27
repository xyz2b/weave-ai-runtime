## Context

The current runtime package story is intentionally first-party only. Package selection flows through `FIRST_PARTY_PACKAGE_SPECS`, `official_runtime_package_manifests()`, and distribution defaults, which keeps internal migration safe but leaves no explicit public registration path for embedder-owned packages.

That restriction made sense while package boundaries were still leaking. After the earlier boundary-tightening work, the next step is to let external packages register through the same manifest-backed protocol without also solving the harder problem of multi-version catalogs and dependency selection in the same change.

## Goals / Non-Goals

**Goals:**

- Add an explicit local registration path for external runtime packages.
- Keep first-party and external packages on the same manifest and contribution protocol.
- Define clear registration diagnostics, collision handling, and trust-boundary expectations.
- Preserve current first-party defaults for callers who do not opt into external registration.

**Non-Goals:**

- Multi-version package catalogs or dependency resolution.
- Remote package discovery, installation, or marketplace workflows.
- Implicit filesystem scanning or magical package auto-discovery.
- Relaxing owner-layer boundaries for external packages.

## Decisions

### 1. External package registration is explicit and config-owned

The runtime will add an explicit config-owned registration input, such as `RuntimeConfig.extra_package_manifests`, that accepts a bounded list of external package manifests or manifest entrypoints.

Why this decision:

- it keeps trust and provenance explicit
- it avoids surprising ambient discovery behavior
- it mirrors the existing explicit config story for other advanced integrations

Alternatives considered:

- auto-scan directories for package manifests: rejected because it creates ambiguous trust and loading rules
- require external packages to monkey-patch official catalogs: rejected because it defeats the purpose of a runtime-owned registration path

### 2. Registration handles one manifest per package name

This change will treat registration as a single-candidate operation per package name. If a caller tries to register multiple manifests for the same package name, the runtime will raise a deterministic collision diagnostic unless an explicit override mechanism is later introduced for narrowly scoped use.

Why this decision:

- it keeps registration simple and local
- it avoids smuggling a hidden resolver into the registration phase
- it leaves multi-candidate selection to the later catalog/resolver change

Alternatives considered:

- allow multi-version candidates immediately: rejected because that is resolver work, not registration work

### 3. External packages must use the same protocol seams as first-party packages

External packages do not receive a private integration API. They must attach through `RuntimePackageManifest`, `PackageContribution`, capability bindings, host facets, lifecycle participants, and other published protocol seams.

Why this decision:

- it keeps external packages from reopening owner-layer leaks
- it makes the public registration story a direct extension of the first-party protocol story
- it reduces the number of extension models the runtime has to support

Alternatives considered:

- provide a looser external-only escape hatch: rejected because it would immediately diverge from the microkernel direction

### 4. Registration diagnostics are first-class assembly outputs

Registration success, collisions, skipped manifests, and trust-boundary warnings should be surfaced in runtime assembly diagnostics and metadata before any package contribution is applied.

Why this decision:

- failures should be observable before runtime execution starts
- embedders need explainable diagnostics when a package is rejected
- later resolver work will build on the same diagnostics discipline

Alternatives considered:

- fail silently or late during contribution application: rejected because it obscures the registration boundary

## Risks / Trade-offs

- [Explicit registration is more verbose than auto-discovery] -> Mitigation: keep the API small and deterministic, and layer convenience tooling later if needed.
- [Single-candidate registration may feel restrictive] -> Mitigation: document that this change intentionally stops before resolver/catalog work; multi-candidate support belongs to the next stage.
- [External packages could still attempt to recreate owner-layer leaks] -> Mitigation: require the same protocol-only boundaries and validate contributions through the same runtime-owned contracts.
- [Official and external package names may collide in confusing ways] -> Mitigation: treat collisions as explicit registration diagnostics, not implicit last-write-wins behavior.

## Migration Plan

1. Introduce the config-owned external package registration input and validation path.
2. Merge validated external manifests with official first-party manifests before package ordering and assembly.
3. Surface registration diagnostics and registered external package inventory in runtime assembly metadata.
4. Update architecture and extension docs to describe external registration as explicit, local, and protocol-only.

Rollback is straightforward because callers who do not opt into external registration continue to use the existing first-party manifest flow unchanged.

## Open Questions

- Should explicit override of an official package name be supported later as a controlled dev-only mode, or should official package names remain permanently reserved?
- When later resolver work lands, should this config-owned registration input feed a new package catalog object directly or remain as a higher-level convenience layer?
