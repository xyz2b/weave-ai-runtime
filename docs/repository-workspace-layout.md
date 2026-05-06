# Repository Workspace Layout

This repository now uses a workspace layout with multiple concrete package roots grouped under family indexes.

## Canonical roots

- `packages/framework-core/`: concrete runtime package metadata and current `weavert` implementation code
- `packages/framework-packs/`: family root for concrete first-party add-on packs
- `packages/product-kits/`: family root for concrete product-kit and common-kit packages
- `packages/toolchain/`: family root for concrete developer tooling packages
- `docs/`: repository-owned guidance and architecture notes
- `tests/`: repository regression and acceptance coverage
- `examples/`: runnable examples and integration samples
- `upstreams/`: imported third-party source snapshots or mirrors
- `.local/`: repository-local generated state, scratch work, and durable demo artifacts

## Packaging ownership

The repository root `pyproject.toml` is a workspace coordinator only. Concrete packages own their own package-local metadata:

- root `pyproject.toml`: workspace metadata, shared developer configuration, and family declarations
- `packages/framework-core/pyproject.toml`: the `weavert` runtime package metadata
- each concrete package under `packages/framework-packs/` owns its own local metadata
- `packages/toolchain/starter/pyproject.toml`: the `weavert-starter` CLI metadata
- each concrete package under `packages/product-kits/` and `packages/toolchain/` owns its own local metadata

## Follow-on extraction rule

Follow-on extraction changes MUST place code into the workspace families instead of restoring new non-core modules under `packages/framework-core/src/weavert/`.

Use this checklist before landing an extraction change:

1. Decide which package family owns the new code before writing files.
2. Add or update package-local metadata inside that family when the change creates a concrete package.
3. Keep the root `pyproject.toml` as a workspace coordinator instead of turning it back into the only publishable package definition.
4. Put runnable repository examples under `examples/`, imported third-party code under `upstreams/`, and repository-local scratch state under `.local/`.
5. Run `python3 packages/toolchain/scripts/check_workspace_layout.py` to confirm the workspace guardrails still pass.
