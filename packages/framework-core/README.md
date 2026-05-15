# Core Package

This page indexes `packages/framework-core/`, which owns the runtime kernel and shared framework primitives.

## What this package owns

- the public `weavert` runtime package
- the runtime kernel and stable assembly surfaces
- shared framework primitives that still belong in the core import root

## Canonical names

- install name: `weavert`
- import root: `weavert`
- runtime activation: `weavert-core`

## Exposure tier

- This is the primary public runtime package.
- The install and import name stay `weavert`, while runtime package selection refers to `weavert-core`.

## Adjacent families

- `packages/framework-packs/` owns first-party add-on packages extracted from the core package.
- `packages/product-kits/` owns scenario packs and shared product-kit packages.
- `packages/toolchain/` owns the starter and testing tooling used around the runtime.

## See also

- `../README.md`
- `../../docs/maintainers/pypi-release-readiness.md`
- `../framework-packs/README.md`
- `../product-kits/README.md`
- `../../docs/concepts/runtime-model.md`
- `../../docs/architecture/overview.md`
