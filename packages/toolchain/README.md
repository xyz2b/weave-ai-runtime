# Toolchain

This family root indexes concrete developer-side toolchain packages.

## What this family owns

- developer-side tooling that stays outside runtime package selection
- the adoption-path starter generator, validation-path testing kit, and repository support scripts

## Public release scope

- Every concrete package under this family is a public PyPI project.
- None of these packages are runtime activation targets.
- `weavert-toolchain-scripts` stays published for maintainers, not as a recommended end-user entrypoint.

## Concrete packages

| Package root | Install name | Import root | Runtime activation | Exposure tier |
| --- | --- | --- | --- | --- |
| `starter/` | `weavert-starter` | `weavert_starter` | none | Developer entrypoint |
| `testing/` | `weavert-testing` | `weavert_testing` | none | Developer entrypoint |
| `scripts/` | `weavert-toolchain-scripts` | none | none | Maintainer-only utility |

## Ownership rule

- These packages remain outside runtime package selection.
- Reach them through developer workflows, imports, or CLI entrypoints rather than runtime package activation.

## See also

- `../README.md`
- `../../docs/maintainers/pypi-release-readiness.md`
- `starter/README.md`
- `testing/README.md`
- `../../docs/getting-started/starter-scaffolds.md`
- `../../examples/README.md`
