# Framework-Pack Workflows

Workflow-owned first-party add-ons now live under this workspace family.

## What this role family owns

- first-party workflow packages that are not scenario packs
- reusable planning, devtools, or built-in workflow surfaces shared across product shapes

## Concrete packages

- `planning/`: install `weavert-planning`, import `weavert_planning`, runtime activation `weavert-planning`
- `devtools/`: install `weavert-devtools`, import `weavert_devtools`, runtime activation `weavert-devtools`
- `builtin-workflows/`: install `weavert-builtin-workflows`, import `weavert_builtin_workflows`, runtime activation `weavert-builtin-workflows`

## Exposure tier

- These are direct public workflow add-ons rather than scenario-pack entrypoints.

## Ownership rule

- Keep reusable first-party workflow packages here.
- Use `packages/product-kits/` when the package is a scenario pack with product-profile defaults.

## See also

- `../README.md`
- `planning/README.md`
- `devtools/README.md`
- `builtin-workflows/README.md`
- `../../../docs/maintainers/pypi-release-readiness.md`
- `../../../examples/README.md`
