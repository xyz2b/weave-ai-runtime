## Why

The runtime now has a clear planning control plane in `runtime-core`, but it still lacks an official first-party package for planner-style agent profiles and planning-oriented workflow UX. That leaves `planner` / `coordinator` / `worker` patterns spread across docs and ad hoc prompts, and forces embedders to couple official planning behavior to `runtime-devtools` or custom project definitions instead of a documented package boundary.

Now is the right time to fix that. The package taxonomy already distinguishes core contracts from higher-level first-party experiences, and planning is the largest remaining first-party workflow surface that still lacks a canonical package boundary.

## What Changes

- Introduce `runtime-planning` as an official first-party profile/workflow package for planning-oriented agent profiles, tool-pool presets, and packaged workflow assets.
- Keep the planning control-plane primitives in `runtime-core`, including `TaskListService`, `task_*`, `job_*`, host task/job bridge methods, task/job namespace split, and derived orchestration/readiness semantics.
- Define the canonical boundary between planning control-plane ownership and planning profile ownership, so planner UX can evolve without weakening the core runtime contract.
- Add official first-party planning profiles such as `planner`, `coordinator`, and `worker`, and document how they compose `task_*`, `job_*`, team, and devtool surfaces.
- Update first-party package composition so `runtime-full` includes `runtime-planning`, while `runtime-default` remains focused on the supported baseline of core, memory, and team capabilities.
- Update built-in ownership and discovery rules so planning-oriented agents and related packaged workflows may ship from `runtime-planning` instead of being implied by docs or overloaded onto `runtime-devtools`.
- Add migration notes and diagnostics for users currently relying on the existing `plan` agent or custom planner prompts as the de facto first-party planning surface.

## Capabilities

### New Capabilities
- `runtime-planning-profiles`: Official first-party planner/coordinator/worker profile package contract, including ownership boundaries, recommended tool pools, and supported assembly/discovery behavior for `runtime-planning`.

### Modified Capabilities
- `builtin-runtime-pack`: The built-in pack contract is extended so planning-oriented first-party agents and workflow assets may ship from `runtime-planning`, with explicit canonical ownership and compatibility guidance relative to existing `runtime-devtools` agents.

## Impact

- Affected code: `src/runtime/package_profiles.py`, `src/runtime/builtins/`, `src/runtime/runtime_kernel/`, `src/runtime/runtime_services/`, `src/runtime/devtools/`, and new first-party package surfaces under `src/runtime/planning/` or equivalent.
- Affected docs: runtime architecture, integration, extension, package taxonomy, distribution composition, and migration notes.
- Public contract impact: introduces an official `runtime-planning` package boundary while preserving `task_*` / `job_*` and planning control-plane ownership in `runtime-core`.
- Compatibility impact: `runtime-default` remains unchanged; `runtime-full` grows a first-party planning pack; existing `plan` behavior may need compatibility aliases, clarified ownership, or deprecation guidance depending on final packaged profile design.
