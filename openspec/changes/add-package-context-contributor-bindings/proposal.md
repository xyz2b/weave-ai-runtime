## Why

The runtime already has a unified context-assembly story, but package-owned pre-request context work still attaches through hard-coded shared service slots such as `hooks.collect()`, `memory.collect()`, and `task_discipline.collect()`. There is no generic package-contribution path for a first-party package to add prompt-visible or private-only context contributions without widening `RuntimeServices` or patching the turn engine.

This is the next internal protocol gap to close after sealing owner-layer compatibility bridges. The runtime needs one canonical package-owned context contributor contract before more first-party packages, and before any external package registration story would be safe to expose.

## What Changes

- Introduce a package contribution binding for generic context contributors, including owner metadata, deterministic ordering, and named runtime-owned context-assembly stages.
- Add a runtime-owned context contributor registry that lets packages attach prompt-visible fragments and runtime-private updates without requiring new `RuntimeServices.*` top-level slots.
- Route package-contributed context work through the same prompt/private carrier contract already used by runtime-owned context assembly, preserving prompt-safety and private-state separation.
- Define bounded failure semantics for package-contributed context participants so invalid or failing contributors are omitted with owner-aware diagnostics rather than silently mutating request state.
- Keep `CompactionManager` as a dedicated main-loop control-plane service instead of collapsing all request-shaping behavior into one generic contributor abstraction.
- Adapt current first-party collect-style contributors to the new package binding model over time, while keeping bounded compatibility for existing shared service access during migration.
- Explicitly defer third-party authoring ergonomics, remote package registration, and any attempt to turn context contributors into a generalized event bus.

## Capabilities

### New Capabilities
- `runtime-package-context-contributors`: Defines how runtime packages register collect-style context contributors that participate in prompt/private context assembly through runtime-owned stages.

### Modified Capabilities
- `runtime-control-plane-spine`: Context assembly gains a package-contributed context-contributor registry and canonical staged execution path instead of relying only on hard-coded shared service slots.
- `runtime-prompt-context-boundaries`: Package-contributed context participants use the same prompt-visible and runtime-private carrier separation as built-in control-plane contributors.

## Impact

- Affected code:
  - `src/runtime/runtime_package_protocols.py`
  - `src/runtime/runtime_package_manifests.py`
  - `src/runtime/runtime_services/__init__.py`
  - `src/runtime/turn_engine/engine.py`
  - `src/runtime/hooks/bus.py`
  - `src/runtime/memory/manager.py`
  - `src/runtime/task_discipline.py`
- Affected docs:
  - `docs/runtime-control-plane-extension-guide.md`
  - `docs/runtime-integration-guide.md`
  - `docs/current-system-architecture.md`
- Affected contracts:
  - package contribution schema for context contributors
  - runtime-owned context-assembly stage ordering
  - prompt/private output contract and bounded failure semantics for package-owned context contributors
