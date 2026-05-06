# Repository Workspace Layout

This repository now uses a workspace layout with one concrete package family and three placeholder families.

## Canonical roots

- `packages/core/`: concrete runtime package metadata and current `weavert` implementation code
- `packages/framework-packs/`: placeholder root for first-party add-on packs
- `packages/product-kits/`: placeholder root for product-oriented packages
- `packages/toolchain/`: placeholder root for developer tooling packages
- `docs/`: repository-owned guidance and architecture notes
- `tests/`: repository regression and acceptance coverage
- `examples/`: runnable examples and integration samples
- `upstreams/`: imported third-party source snapshots or mirrors
- `.local/`: repository-local generated state, scratch work, and durable demo artifacts

## Packaging ownership

The repository root `pyproject.toml` is a workspace coordinator only. Concrete packages own their own package-local metadata:

- root `pyproject.toml`: workspace metadata, shared developer configuration, and family declarations
- `packages/core/pyproject.toml`: the initial concrete `weavert` package metadata and console entrypoints
- placeholder family roots: documentation only until a follow-on change adds a concrete package inside the family

## Follow-on extraction rule

Follow-on extraction changes MUST place code into the workspace families instead of restoring new non-core modules under `packages/core/src/weavert/`.

Use this checklist before landing an extraction change:

1. Decide which package family owns the new code before writing files.
2. Add or update package-local metadata inside that family when the change creates a concrete package.
3. Keep the root `pyproject.toml` as a workspace coordinator instead of turning it back into the only publishable package definition.
4. Put runnable repository examples under `examples/`, imported third-party code under `upstreams/`, and repository-local scratch state under `.local/`.
5. Run `python3 scripts/check_workspace_layout.py` to confirm the workspace guardrails still pass.
