## 1. Contribution Model

- [x] 1.1 Add a package contribution type for invocation providers, including owner metadata and deterministic registration fields.
- [x] 1.2 Extend runtime package manifest helpers so first-party packages can return invocation-provider contributions without kernel-specific wiring.
- [x] 1.3 Define the compatibility story for `RuntimeConfig.extra_invocation_providers` in runtime metadata and docs.

## 2. Kernel And Registry Integration

- [x] 2.1 Register package-contributed invocation providers during kernel build before invocation diagnostics and visible catalog resolution are finalized, with explicit precedence of built-in baseline first, package providers second, and config providers last.
- [x] 2.2 Preserve the built-in skill provider baseline while moving package-owned non-skill providers onto the canonical package contribution path.
- [x] 2.3 Keep provider-name replacement diagnostics and invocation-definition conflict diagnostics authoritative in `InvocationRegistry` for package-contributed, built-in, and config-supplied providers alike.

## 3. First-Party Adoption

- [x] 3.1 Identify first-party invocation sources that currently require config or kernel-specific registration and migrate them to package-contributed providers where appropriate.
- [x] 3.2 Ensure package-contributed providers can construct any required provider objects without introducing a new top-level package assembly stage.
- [x] 3.3 Record provider ownership and registration origin in runtime diagnostics or metadata for debugging and migration visibility.

## 4. Coverage And Docs

- [x] 4.1 Add regression tests for deterministic provider registration order, same-name provider replacement diagnostics, invocation-definition conflict diagnostics, and unchanged path-aware visibility semantics.
- [x] 4.2 Add regression tests proving package-contributed providers appear in host-visible catalogs before the first session executes.
- [x] 4.3 Update architecture and extension docs to describe package contribution as the canonical package-owned invocation-provider path and `extra_invocation_providers` as the bounded embedder-facing path.
