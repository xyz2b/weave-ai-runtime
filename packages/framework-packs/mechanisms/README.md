# Framework-Pack Mechanisms

Mechanism-owned first-party add-ons now live under this workspace family.

## What this role family owns

- first-party runtime mechanisms such as compaction or isolation
- packages that shape runtime behavior without becoming capability packs or product kits

## Concrete packages

- `compaction/`: `weavert-compaction` via the `weavert_compaction` import root
- `isolation/`: `weavert-isolation` via the `weavert_isolation` import root

## Ownership rule

- Put reusable runtime mechanisms here when they belong to the first-party add-on family.
- Keep app-specific policy and UX outside this family.

## See also

- `../README.md`
- `compaction/README.md`
- `isolation/README.md`
- `../../../docs/architecture/request-lifecycle.md`
