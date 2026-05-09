# Framework Packs

This family root indexes first-party add-on packages that extend the runtime without belonging to the `weavert` core package.
Scenario packs do not live here; they live under `packages/product-kits/`.

## What this family owns

- first-party add-on packages that stay outside the core `weavert` import root
- role-oriented package families such as capabilities, mechanisms, integrations, and workflows

## Role families

- `capabilities/`
- `mechanisms/`
- `integrations/`
- `workflows/`

## Ownership rule

- Do not add a family-level `pyproject.toml` here.
- Each concrete pack owns package-local metadata inside its role family.
- Use `packages/product-kits/` instead when the package is a scenario pack or shared product-kit package rather than a first-party add-on pack.

## See also

- `capabilities/README.md`
- `integrations/README.md`
- `mechanisms/README.md`
- `workflows/README.md`
- `../../docs/framework-packs/README.md`
