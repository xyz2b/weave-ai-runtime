# Framework Packs

This family root indexes first-party add-on packages that extend the runtime without belonging to the `weavert` core package.
Scenario packs do not live here; they live under `packages/product-kits/`.

## What this family owns

- first-party add-on packages that stay outside the core `weavert` import root
- role-oriented package families such as capabilities, mechanisms, integrations, and workflows

## Public release scope

- Every concrete package under this family is a public PyPI project.
- Runtime activation keeps using the framework-pack package names even when they match the distribution name.
- This family root remains an index only; it is not itself published.

## Exposure tier

- Framework packs are direct add-ons for adopters and maintainers who need a specific runtime extension without taking a full scenario profile.

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
- `../../docs/maintainers/pypi-release-readiness.md`
- `../../docs/framework-packs/README.md`
