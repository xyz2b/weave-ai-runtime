# Package Workspace

The repository's publishable implementation code lives under `packages/`.

Family layout:

- `core/` is the initial concrete package root and owns package-local metadata.
- `framework-packs/` is a family root for first-party add-on packs extracted from the core runtime.
- `product-kits/` is a placeholder family for product-oriented workflow and scenario packages.
- `toolchain/` is a placeholder family for developer tooling packages that should not move back under the core import tree.

Only concrete packages own a local `pyproject.toml`. Family roots stay as documented indexes while their concrete packages own the package-local metadata.
