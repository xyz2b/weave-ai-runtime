# Core Package

`packages/core/` is the first concrete workspace package.

- Package metadata lives in `packages/core/pyproject.toml`.
- The current `weavert` implementation root lives in `packages/core/src/weavert/`.
- Follow-on extraction changes should move non-core code into the other workspace families instead of restoring new add-ons under the core tree.
