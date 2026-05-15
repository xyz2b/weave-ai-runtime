# Framework-Pack Mechanisms

Mechanism-owned first-party add-ons now live under this workspace family.

## What this role family owns

- first-party runtime mechanisms such as compaction or isolation
- packages that shape runtime behavior without becoming capability packs or product kits

## Concrete packages

- `compaction/`: install `weavert-compaction`, import `weavert_compaction`, runtime activation `weavert-compaction`
- `isolation/`: install `weavert-isolation`, import `weavert_isolation`, runtime activation `weavert-isolation`

## Exposure tier

- These are direct public runtime-mechanism add-ons rather than scenario-pack entrypoints.

## Ownership rule

- Put reusable runtime mechanisms here when they belong to the first-party add-on family.
- Keep app-specific policy and UX outside this family.

## See also

- `../README.md`
- `compaction/README.md`
- `isolation/README.md`
- `../../../docs/maintainers/pypi-release-readiness.md`
- `../../../docs/architecture/request-lifecycle.md`
