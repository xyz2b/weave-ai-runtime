# Package System

WeaveRT uses explicit package composition so capability stays inspectable.

## Who is this for?

- Readers evaluating how the runtime is assembled, executed, and persisted under the hood.

## Prerequisites

- Read `../concepts/runtime-model.md` first.
- Use the relevant concept pages as vocabulary support before treating this as the deeper architecture layer.

## Distribution layers

- `weavert-core`
  - runtime kernel and stable contracts
- `weavert-default`
  - core plus common first-party capability packages
- `weavert-full`
  - default plus richer workflows, mechanisms, and integrations

Distribution chooses a coarse baseline.
It does not remove the need for explicit package reasoning.

## Package roles

Current first-party roles include:

- capability packages
  - `weavert-memory`, `weavert-team`
- mechanism packages
  - `weavert-compaction`, `weavert-isolation`
- integration packages
  - `weavert-openai`, `weavert-hosts-reference`, `weavert-stores-file`
- workflow packages
  - `weavert-planning`, `weavert-devtools`, `weavert-builtin-workflows`

## Package protocol attachment

A real runtime package is more than "some files in a folder".
The package boundary is meaningful when it participates through a manifest-backed protocol surface such as:

- `RuntimePackageManifest`
- dependency-ordered resolution
- `PackageContribution`
- capability registry lookup
- lifecycle participation

This is why package composition belongs in runtime assembly rather than in ad hoc directory conventions.

## Admitted versus active packages

External packages usually join in two phases:

- admission
  - manifests become candidates through `extra_package_manifests`
- activation
  - the package becomes part of the resolved graph through `requested_packages` and compatible resolution

This distinction matters because a package can be visible as a candidate without actually contributing runtime surfaces yet.

## Why this matters operationally

Explicit package activation helps you answer:

- which surface is present
- which package owns it
- whether a package was merely admitted or actually active
- how a scenario pack relates to host ownership

## Scenario packs are still package composition

Scenario packs do not replace distributions or `.weavert/`.
They are still ordinary package-selection surfaces layered on top of the runtime package system.

## Next step

- Use `../guides/use-scenario-packs.md` when you are activating a product profile or shared package set.
- Open `../reference/runtime-config.md` when you want the concrete assembly fields that drive package posture.
- Read `../maintainers/migration-notes.md` if you are mapping older package-boundary assumptions to the new layout.

## See also

- `../concepts/packages-and-scenario-packs.md`
- `../deep-dives/weavert-scenario-runtime-pack-architecture.md`
- `../maintainers/runtime-boundary-migration-ledger.md`
