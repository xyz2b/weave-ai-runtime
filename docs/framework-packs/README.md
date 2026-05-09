# Framework Packs

This page indexes the first-party add-on package families that live under `packages/framework-packs/`.
Use it when you want the packaging map for runtime add-ons before reading a concrete package README.

## What this page is for

- explain where first-party add-on packages live after the workspace split
- separate framework-pack families from the core `weavert` package and from scenario packs
- give one stable index for capability, mechanism, integration, and workflow package families

## What belongs here

- first-party add-on packages that extend the runtime outside the core `weavert` import root
- reusable framework-owned packages that should not be modeled as scenario packs or app-owned host code

Scenario packs do not live here.
They live under `packages/product-kits/`.

## Role families

- `capabilities/`: `weavert-memory`, `weavert-team`
- `mechanisms/`: `weavert-compaction`, `weavert-isolation`
- `integrations/`: `weavert-openai`, `weavert-hosts-reference`, `weavert-stores-file`
- `workflows/`: `weavert-planning`, `weavert-devtools`, `weavert-builtin-workflows`

## Canonical workspace roots

- `packages/framework-packs/capabilities/`
- `packages/framework-packs/mechanisms/`
- `packages/framework-packs/integrations/`
- `packages/framework-packs/workflows/`

## Canonical import roots

- `weavert_memory`
- `weavert_team`
- `weavert_compaction`
- `weavert_isolation`
- `weavert_openai`
- `weavert_hosts_reference`
- `weavert_stores_file`
- `weavert_planning`
- `weavert_devtools`
- `weavert_builtin_workflows`

## Read this next

- Want the package-family workspace index: [`../../packages/framework-packs/README.md`](../../packages/framework-packs/README.md)
- Want the scenario-pack side of the model: [`../../packages/product-kits/README.md`](../../packages/product-kits/README.md)
- Want the concept model for packages and scenario packs: [`../concepts/packages-and-scenario-packs.md`](../concepts/packages-and-scenario-packs.md)
- Want the runtime package-resolution view: [`../architecture/package-system.md`](../architecture/package-system.md)
