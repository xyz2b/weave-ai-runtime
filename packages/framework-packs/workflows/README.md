# Framework-Pack Workflows

Workflow-owned first-party add-ons now live under this workspace family.

## What this role family owns

- first-party workflow packages that are not scenario packs
- reusable planning, devtools, or built-in workflow surfaces shared across product shapes

## Concrete packages

- `planning/`: `weavert-planning` via the `weavert_planning` import root
- `devtools/`: `weavert-devtools` via the `weavert_devtools` import root
- `builtin-workflows/`: `weavert-builtin-workflows` via the `weavert_builtin_workflows` import root

## Ownership rule

- Keep reusable first-party workflow packages here.
- Use `packages/product-kits/` when the package is a scenario pack with product-profile defaults.

## See also

- `../README.md`
- `planning/README.md`
- `devtools/README.md`
- `builtin-workflows/README.md`
- `../../../examples/README.md`
