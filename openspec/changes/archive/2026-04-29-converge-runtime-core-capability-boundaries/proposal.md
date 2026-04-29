## Why

The runtime already has the core shape of a general AI runtime framework, but its public surface still mixes kernel concerns, official first-party capabilities, coding-agent-oriented built-ins, and compatibility bridges. That makes it harder to explain what the stable v1 contract is, what users should extend, and which parts are implementation details rather than framework boundaries.

Now is the right time to converge those boundaries. The project no longer needs Claude Code feature parity as its primary product goal; it needs a clearer runtime-core contract, a smaller public hook surface, and an official packaging story that keeps `main-router`, memory, and team orchestration as first-party core capabilities without forcing every implementation detail into the kernel itself.

## What Changes

- Introduce an official capability-packaging model that separates `runtime-core` from first-party capability packages such as memory and team orchestration, while preserving a `runtime-default` distribution that still boots with `main-router`.
- Define a stable v1 extension story that explicitly centers `tool`, `agent`, `skill`, `host`, and a reduced hook surface, and does not treat kernel internals as ordinary user extension points.
- Split bundled runtime definitions into a smaller core built-in pack versus optional first-party capability or workspace-oriented packs, while preserving `main-router` as the default root agent and keeping builtin replacement/override paths.
- Keep memory and teammate orchestration as official runtime capabilities, but allow their default implementations and auxiliary control-plane logic to live outside the core kernel package boundary.
- Reduce the public hook surface to a smaller stable catalog, narrow the set of recommended registration surfaces, and make callback-first hook integration the primary v1 contract.
- De-emphasize slash command, plugin command, and MCP prompt productization as non-v1 priorities while retaining the generic invocation-provider extension seam.
- Continue compatibility cleanup by freezing legacy bridges such as `TaskManager` and shared `runtime_context` as bounded migration surfaces rather than ongoing primary integration contracts.

## Capabilities

### New Capabilities
- `runtime-capability-packages`: Official packaging and assembly contract for `runtime-core`, first-party capability packages, and the supported `runtime-default` / `runtime-full` distributions.

### Modified Capabilities
- `builtin-runtime-pack`: Built-in definitions are reclassified into a smaller core pack plus optional first-party packs, while `main-router` remains part of the default boot path and built-ins remain replaceable.
- `memory-subsystem`: Memory remains an official first-party runtime capability even when its implementation is packaged outside the core kernel boundary.
- `teammate-orchestration`: Team and teammate orchestration remain official first-party runtime capabilities even when their implementation is packaged outside the core kernel boundary.
- `hook-system`: The authoritative public phase catalog is reduced to a smaller stable v1 surface and advanced/internal phases are no longer promoted as ordinary extension points.
- `runtime-hook-configuration-platform`: Stable hook authoring, handler, and effect contracts are narrowed around a callback-first public surface with fewer guaranteed registration modes.

## Impact

- Affected code: `src/runtime/runtime_kernel/`, `src/runtime/builtins/`, `src/runtime/hooks/`, `src/runtime/runtime_services/`, `src/runtime/memory/`, `src/runtime/teammate_orchestration/`, `src/runtime/team_*`, and packaging/export surfaces under `src/runtime/__init__.py`.
- Affected docs: runtime architecture, integration, extension, definition-authoring, hook-platform, and positioning docs.
- Public contract impact: clearer runtime-core versus capability-package boundaries; smaller stable hook surface; explicit first-party status for `main-router`, memory, and team orchestration; unchanged recommendation that users extend through `tool`, `agent`, `skill`, `host`, and approved hook APIs.
- Compatibility impact: legacy `TaskManager`, shared `runtime_context`, and oversized hook/public builtin surfaces are narrowed or demoted rather than further expanded.
