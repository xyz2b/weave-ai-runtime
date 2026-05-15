# Package Workspace

[English](README.md) | [简体中文](README.zh-CN.md)

This page indexes the publishable implementation code under `packages/`.

Every concrete package directory with its own `pyproject.toml` is in the official first-party PyPI publication scope.
The repository root `pyproject.toml` stays unpublished as a workspace coordinator.

## What lives here

- `framework-core/` owns the concrete `weavert` runtime package.
- `framework-packs/` owns first-party add-on packages that extend the runtime outside the core import root.
- `product-kits/` owns scenario packs plus shared product-kit packages.
- `toolchain/` owns developer tooling such as the adoption-path starter generator and the validation-path testing kit.

## Ownership rule

- Only concrete packages own a local `pyproject.toml`.
- Family roots stay as documented indexes while their concrete packages own package-local metadata.
- New code should land in the family that owns it instead of drifting back into the core package by default.

## Exposure tiers

- `framework-core/` is the primary public runtime entrypoint.
- `framework-packs/` are direct public add-ons whose runtime activation names either match or closely track their install names.
- `product-kits/common/` packages are lower-layer shared kits with distinct install, import, and runtime activation identities.
- `product-kits/` scenario kits are higher-layer profile entrypoints that compose the lower-layer kits.
- `toolchain/` packages are public developer tooling, except `weavert-toolchain-scripts`, which remains maintainer-oriented.

## How to read this tree

- Start with `framework-core/` when the question is about the runtime kernel or public `weavert` surface.
- Use `framework-packs/` when the question is about first-party add-on capabilities, mechanisms, integrations, or workflows.
- Use `product-kits/` when the question is about scenario packs or shared product-kit composition.
- Use `toolchain/` when the question is about adoption or validation tooling rather than runtime assembly.

## See also

- `../README.md`
- `../docs/README.md`
- `../docs/maintainers/pypi-release-readiness.md`
- `framework-core/README.md`
- `product-kits/README.md`
- `toolchain/README.md`
