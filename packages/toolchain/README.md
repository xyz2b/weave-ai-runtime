# Toolchain

This family root indexes concrete developer-side toolchain packages.

## What this family owns

- developer-side tooling that stays outside runtime package selection
- the adoption-path starter generator, validation-path testing kit, and repository support scripts

## Concrete packages

- `starter/` -> canonical import root `weavert_starter`, owns the adoption-path starter generator
- `testing/` -> canonical import root `weavert_testing`, owns the validation-path testing kit
- `scripts/` -> repository support scripts

## Ownership rule

- These packages remain outside runtime package selection.
- Reach them through developer workflows, imports, or CLI entrypoints rather than runtime package activation.

## See also

- `../README.md`
- `starter/README.md`
- `testing/README.md`
- `../../docs/getting-started/starter-scaffolds.md`
- `../../examples/README.md`
