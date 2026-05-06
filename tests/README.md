# Test Root

Repository regression coverage lives under `tests/`.

Tests should assume the canonical import roots are the workspace `packages/**/src/` directories, and example-facing acceptance coverage should point readers at `examples/README.md` instead of historical `demos/` paths. Framework-pack-owned smoke or ownership tests should live under `tests/framework-packs/` when they do not need to stay cross-cutting with the core runtime.
