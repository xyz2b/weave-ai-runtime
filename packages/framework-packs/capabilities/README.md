# Framework-Pack Capabilities

Capability-owned first-party add-ons now live under this workspace family.

## What this role family owns

- reusable first-party capability packages
- package surfaces that add runtime-visible capability without becoming product kits or toolchain utilities

## Concrete packages

- `memory/`: install `weavert-memory`, import `weavert_memory`, runtime activation `weavert-memory`
- `team/`: install `weavert-team`, import `weavert_team`, runtime activation `weavert-team`

## Exposure tier

- These are direct public capability add-ons rather than scenario-pack entrypoints.

## Ownership rule

- Put reusable capability surfaces here when they belong to the first-party add-on family.
- Use `packages/product-kits/` when the surface is really a scenario pack or shared product-kit package.

## See also

- `../README.md`
- `memory/README.md`
- `team/README.md`
- `../../../docs/maintainers/pypi-release-readiness.md`
- `../../../docs/README.md`
