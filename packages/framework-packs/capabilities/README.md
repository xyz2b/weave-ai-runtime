# Framework-Pack Capabilities

Capability-owned first-party add-ons now live under this workspace family.

## What this role family owns

- reusable first-party capability packages
- package surfaces that add runtime-visible capability without becoming product kits or toolchain utilities

## Concrete packages

- `memory/`: `weavert-memory` via the `weavert_memory` import root
- `team/`: `weavert-team` via the `weavert_team` import root

## Ownership rule

- Put reusable capability surfaces here when they belong to the first-party add-on family.
- Use `packages/product-kits/` when the surface is really a scenario pack or shared product-kit package.

## See also

- `../README.md`
- `memory/README.md`
- `team/README.md`
- `../../../docs/README.md`
