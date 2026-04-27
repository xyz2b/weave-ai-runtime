## Why

The runtime has already established `RuntimePrivateContext`, `PromptContextEnvelope`, `JobService`, and `TaskListService` as the intended shared contracts, but raw `runtime_context` maps and `TaskManager` compatibility still remain close enough to primary paths that they continue to shape owner-layer APIs and control-flow decisions. That keeps legacy compatibility surfaces alive as architecture, not just as adapters.

To reach a true protocol-only runtime core, those surfaces need to stop being authoritative. The runtime should still be able to normalize or project legacy inputs, but new and refactored primary paths must consume authoritative state only through the structured context carriers and shared job/task control planes.

## What Changes

- Define `RuntimePrivateContext` and `PromptContextEnvelope` as the only authoritative shared carriers for runtime-private and prompt-visible request state.
- Restrict raw `runtime_context` handling to boundary normalization and compatibility adapters rather than owner-layer primary logic.
- Define `TaskManager` explicitly as a legacy facade over `JobService` and `TaskListService` rather than an authoritative control-plane dependency.
- Remove runtime-owned primary-path dependence on `TaskManager` materialization and raw `runtime_context` mutation.
- Add conformance checks and structured findings that detect authoritative writes through raw `runtime_context` or new primary-path dependence on `TaskManager`.

## Capabilities

### New Capabilities
- `runtime-primary-context-authority`: Defines structured prompt/private carriers as the authoritative shared context contract and limits raw `runtime_context` to compatibility normalization.
- `runtime-taskmanager-compatibility`: Defines `TaskManager` as a bounded legacy facade over the shared job and task-list control planes.

### Modified Capabilities
- `runtime-control-plane-spine`: The shared control-plane contract treats structured context carriers and shared job/task services as authoritative rather than raw `runtime_context` or `TaskManager`.
- `runtime-session-ingress`: Session ingress and session control propagate authoritative private state through structured carriers rather than raw compatibility maps.
- `query-runtime-conformance`: Conformance checks detect new primary-path reliance on `TaskManager` or authoritative raw `runtime_context` mutation and publish structured rule findings for the terminal protocol-only gate.

## Impact

- Affected code:
  - `src/runtime/runtime_kernel/kernel.py`
  - `src/runtime/runtime_services/__init__.py`
  - `src/runtime/session_runtime/controller.py`
  - `src/runtime/session_runtime/ingress.py`
  - `src/runtime/tasking.py`
  - `src/runtime/builtins/tool_impls.py`
  - `src/runtime/jobs.py`
  - `src/runtime/task_lists.py`
  - `src/runtime/control_plane.py`
- Affected contracts:
  - public helper APIs that still accept or return raw `runtime_context`
  - compatibility `TaskManager` entry points and metadata
  - conformance and migration metadata for legacy context and task surfaces
- Affected docs:
  - runtime architecture and migration notes
  - control-plane extension guidance
  - task/job and context-boundary docs

## Roadmap Fit

- Rollout wave: Wave 1 foundation.
- Recommended order: land first in the roadmap, because it shrinks the authoritative owner-layer seams in `controller.py`, `control_plane.py`, and `runtime_services` before the service-slot migration adds new typed resolvers in those same areas.
- Downstream dependencies: `eliminate-privileged-runtime-package-service-slots` benefits from the smaller authority surface, and `dekernelize-first-party-package-catalog-and-enforce-protocol-conformance` consumes this change's structured rule findings as part of the terminal gate.
- Breaking surface: boundary parameters and explicit compatibility facades remain in place here; this is an internal authority cleanup, not a flag-day public API removal.

