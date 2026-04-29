## Why

The runtime is already converging on a microkernel shape, but its stable core protocols are still expressed asymmetrically. Some are config-owned injection points, some are shared service slots, some are registry participants, and some are only described in docs or migration metadata. That makes it harder to tell which seams are truly stable, which are package-owned additions, and which surfaces are compatibility carryovers.

After owner-layer tightening, package context contributors, and package invocation providers, the next gap is protocol symmetry: the runtime needs one canonical catalog of stable core protocols and their authoritative binding or discovery surfaces before it opens broader external package registration and dependency-resolution work.

## What Changes

- Define a stable core protocol catalog for the runtime, covering at least `TranscriptStore`, `JobService`, `TaskListService`, `PermissionService`, `ElicitationService`, context contributors, invocation providers, and the host bridge.
- Publish, for each stable core protocol, its canonical owner, binding boundary, discovery surface, compatibility status, and versioned minimum schema in runtime assembly metadata and integration docs.
- Separate stable core protocol entries from distribution-specific package capabilities, host facets, and compatibility wrappers so package growth does not redefine the core protocol catalog.
- Keep protocol-catalog metadata separate from package-specific lookup and compatibility metadata so there is one source of truth for stable core protocols and a different one for package-owned canonical keys and wrappers.
- Add conformance and integration guidance that verify different runtime distributions expose the same stable core protocol identities even when selected first-party packages differ.
- Keep current first-party package taxonomy and contribution model intact; this change documents and normalizes the core protocol matrix rather than redesigning package registration.
- Explicitly defer external package registration, multi-candidate package catalogs, semantic-version resolution, and physical packaging split concerns to later changes.

## Capabilities

### New Capabilities
- `runtime-core-protocol-catalog`: Defines the stable set of core runtime protocols, their canonical binding or discovery surfaces, and their separation from optional package capabilities and compatibility wrappers.

### Modified Capabilities
- `runtime-control-plane-spine`: The assembled control plane publishes a canonical inventory of stable core protocols and their authoritative discovery paths instead of relying on mixed conventions.
- `query-runtime-assembly`: Assembled runtimes expose stable core protocol metadata separately from distribution package inventory and compatibility projections.

## Impact

- Affected code:
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/runtime_services/__init__.py`
  - `src/runtime/runtime_kernel/config.py`
  - `src/runtime/hosts/base.py`
  - `src/runtime/registries/invocation_registry.py`
  - `src/runtime/task_lists.py`
  - `src/runtime/jobs.py`
- Affected docs:
  - `docs/current-system-architecture.md`
  - `docs/runtime-integration-guide.md`
  - `docs/runtime-user-extension-guide.md`
  - `docs/runtime-migration-notes.md`
- Affected contracts:
  - versioned runtime metadata describing stable core protocols
  - canonical binding and discovery guidance for shared runtime protocols
  - conformance expectations across runtime distributions
