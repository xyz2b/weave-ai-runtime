# Package Workspace

The repository's publishable implementation code lives under `packages/`.

Family layout:

- `core/` is the initial concrete package root and owns package-local metadata.
- `framework-packs/` is a placeholder family for first-party add-on packs extracted from the core runtime.
- `product-kits/` is a placeholder family for product-oriented workflow and scenario packages.
- `toolchain/` is a placeholder family for developer tooling packages that should not move back under the core import tree.

Only concrete packages own a local `pyproject.toml`. Family placeholders stay as documented indexes until follow-on extraction changes create real packages inside them.
