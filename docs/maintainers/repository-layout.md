# Repository Layout

This page is for maintainers and contributors working on the repository itself.

## Who is this for?

- Maintainers and contributors working on this repository rather than first-time framework adopters.

## Prerequisites

- Read `../README.md` first so the public docs flow stays intact.
- Use `../../examples/README.md` as the runnable validation path while changing the repo.

## Top-level directories

- `docs/` -> public docs, deep dives, and maintainer notes
- `examples/` -> runnable validation path and advanced integration samples
- `packages/` -> publishable package workspace
- `tests/` -> repo-level validation
- `openspec/` -> change proposals, specs, and archived design work
- `upstreams/` -> imported upstream source trees and provenance notes

## Package families

- `packages/framework-core/` -> core `weavert` runtime package
- `packages/framework-packs/` -> first-party add-on capability, mechanism, integration, and workflow packages
- `packages/product-kits/` -> scenario and common-kit packages
- `packages/toolchain/` -> starter, testing, and repository tooling

For the current framework-pack role map, see `../framework-packs/README.md`.

## Canonical roots

- `packages/framework-core/` -> concrete runtime package metadata and the current `weavert` implementation code
- `packages/framework-packs/` -> family root for concrete first-party add-on packs
- `packages/product-kits/` -> family root for concrete product-kit and common-kit packages
- `packages/toolchain/` -> family root for concrete developer tooling packages
- `docs/` -> repository-owned guidance, deep dives, and maintainer notes
- `tests/` -> repository regression and acceptance coverage
- `examples/` -> runnable examples and integration samples
- `upstreams/` -> imported third-party source snapshots or mirrors
- `.local/` -> repository-local generated state, scratch work, and durable demo artifacts

## Packaging ownership

The repository root `pyproject.toml` is a workspace coordinator only. Concrete packages own their own package-local metadata:

- root `pyproject.toml` -> workspace metadata, shared developer configuration, and family declarations
- `packages/framework-core/pyproject.toml` -> `weavert` runtime package metadata
- each concrete package under `packages/framework-packs/` owns its own local metadata
- `packages/toolchain/starter/pyproject.toml` -> `weavert-starter` CLI metadata
- each concrete package under `packages/product-kits/` and `packages/toolchain/` owns its own local metadata

## Follow-on extraction guardrail

Follow-on extraction changes must place code into the workspace families instead of restoring new non-core modules under `packages/framework-core/src/weavert/`.

Use this checklist before landing an extraction change:

1. Decide which package family owns the new code before writing files.
2. Add or update package-local metadata inside that family when the change creates a concrete package.
3. Keep the root `pyproject.toml` as a workspace coordinator instead of turning it back into the only publishable package definition.
4. Put runnable repository examples under `examples/`, imported third-party code under `upstreams/`, and repository-local scratch state under `.local/`.
5. Run `python3 packages/toolchain/scripts/check_workspace_layout.py` to confirm the workspace guardrails still pass.

## Documentation rule of thumb

- root `README.md` is a landing page
- `docs/README.md` is the docs home
- end-user guides stay separate from maintainer notes
- examples remain a validation index, not the primary getting-started path

## Next step

- Read `migration-notes.md` when a repository move also changes public boundaries or packaging assumptions.
- Use `validation-findings.md` if the repo change also needs an evidence trail or follow-up ledger.
- Open `../../CONTRIBUTING.md` before turning the layout rules into a contributor workflow change.

## See also

- `../README.md`
- `../reference/workspace-layout.md`
- `migration-notes.md`
