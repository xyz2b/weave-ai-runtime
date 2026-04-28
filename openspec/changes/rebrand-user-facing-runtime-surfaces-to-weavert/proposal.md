## Why

The framework's current user-facing naming is split across multiple legacy surfaces: the published package is `ai-agent-runtime`, Python examples import `runtime`, default workspace state lives under `.runtime`, and first-party distribution, package, and protocol identifiers are all `runtime-*` or `runtime.*`. That naming no longer matches the intended product identity of WeaveRT, and it creates avoidable friction for embedders, documentation readers, and application developers.

We need one explicit rebrand change now so every supported user-facing contract converges on `WeaveRT` / `weavert` / `weave-ai-runtime`, while internal-only technical terminology can remain stable unless it leaks into a public contract.

## What Changes

- Rebrand the public Python package surface from `ai-agent-runtime` / `runtime` to `weavert`, including installation metadata and user-facing import examples.
- Rebrand the default user-visible workspace state root from `.runtime` to `.weavert`, including discovery roots and persisted runtime data directories that framework users are expected to inspect or manage.
- Rebrand first-party distribution and package identifiers that embedders configure directly from `runtime-*` to `weavert-*`.
- Rebrand public capability, protocol, and host-extension namespaces that embedders consume directly from `runtime.*` to `weavert.*`.
- Update user-facing documentation and migration guidance so examples, paths, and configuration snippets consistently use WeaveRT naming.
- Preserve internal-only technical class names and implementation terminology where they are not part of a user-visible contract.
- **BREAKING**: Existing installs, imports, default workspace paths, configured first-party package names, and public namespace identifiers that still use `ai-agent-runtime`, `runtime`, `.runtime`, `runtime-*`, or `runtime.*` will need migration to the new WeaveRT names.

## Capabilities

### New Capabilities
- `weavert-user-facing-contract`: Defines the canonical WeaveRT-branded install, import, workspace-root, first-party package, and public namespace contract for all user-facing framework surfaces.

### Modified Capabilities
- `runtime-kernel`: Public bootstrap and project discovery defaults move from the legacy package/import/root names to the WeaveRT contract.
- `query-runtime-assembly`: Runtime assembly metadata and inspection surfaces publish WeaveRT-branded distribution, package, and public namespace identifiers.
- `builtin-runtime-pack`: Canonical first-party distribution and package ownership identifiers exposed to embedders change from `runtime-*` to `weavert-*`.
- `runtime-memory-manager`: Default user-visible memory layout moves from `.runtime/memory` to `.weavert/memory`.
- `skill-activation-lifecycle`: Nested skill discovery and project skill roots move from `.runtime/skills` to `.weavert/skills`.
- `host-runtime-bridge`: Host-visible runtime extension namespaces and related public bridge identifiers move from `runtime.*` to `weavert.*`.

## Impact

- Affected code:
  - `pyproject.toml`
  - `src/runtime/**` public import and metadata surfaces
  - user-visible default path and package/namespace wiring in runtime assembly, package catalog, protocol catalog, memory, skill discovery, team control, and host bridge modules
- Affected docs:
  - `docs/runtime-integration-guide.md`
  - `docs/runtime-user-extension-guide.md`
  - `docs/runtime-definition-authoring-guide.md`
  - `docs/runtime-control-plane-extension-guide.md`
  - `docs/runtime-hook-configuration-platform.md`
  - `docs/runtime-migration-notes.md`
  - `docs/current-system-architecture.md`
  - `docs/layered-memory-runtime-v2.md`
- Affected contracts:
  - package install/import contract
  - default workspace-state directory contract
  - first-party distribution and package identifiers
  - public capability, protocol, and host-extension namespaces
