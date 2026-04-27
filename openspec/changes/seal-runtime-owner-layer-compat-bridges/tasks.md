## 1. Canonical Owner-Layer Paths

- [x] 1.1 Audit runtime-owned `src/runtime/` call sites that still depend on package-specific owner-layer projections such as `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, or ad hoc `getattr(..., "team_*")` fallbacks, and map each one to its canonical capability or host-facet lookup path.
- [x] 1.2 Update runtime-owned team-control, team-message, and workflow helpers to resolve package-owned services through canonical capability accessors instead of package-specific top-level slots on shared runtime surfaces.
- [x] 1.3 Update runtime-owned tool and control-plane helpers to use `job_service` and `task_list_service` as authoritative state instead of widening `TaskManager`-shaped seams for new primary paths.

## 2. Compatibility Wrapper Tightening

- [x] 2.1 Refactor retained `RuntimeServices.team_*` and `RuntimeAssembly.team_*` projections so they remain thin delegating wrappers over canonical capability-registry results rather than independent owner-layer state.
- [x] 2.2 Refactor `BoundHostRuntime.list_team_workflows()` and `BoundHostRuntime.respond_team_workflow()` so they delegate through the canonical workflow service or host-facet-backed path while preserving their bounded compatibility behavior.
- [x] 2.3 Tighten `RuntimeServices.task_manager` and related legacy helper access so `TaskManager` remains a compatibility-only facade over shared job control rather than a renewed primary integration path.

## 3. Metadata And Documentation

- [x] 3.1 Update runtime assembly metadata to publish canonical capability keys, canonical host-facet keys, retained compatibility wrappers, and wrapper-exit criteria for the active distribution.
- [x] 3.2 Update `docs/runtime-integration-guide.md`, `docs/runtime-control-plane-extension-guide.md`, and `docs/runtime-migration-notes.md` to describe canonical package lookup paths and mark retained `team_*`, host workflow, and `TaskManager` surfaces as compatibility-only.

## 4. Regression Coverage

- [x] 4.1 Add tests proving runtime-owned workflow and control-plane code paths continue to work when only canonical capability and host-facet discovery are treated as authoritative.
- [x] 4.2 Add tests proving retained `RuntimeServices.team_*`, `RuntimeAssembly.team_*`, and `BoundHostRuntime` workflow helpers delegate to the same canonical services instead of diverging, and preserve the bounded absent-package behavior for list vs respond helpers.
- [x] 4.3 Add tests proving `TaskManager` compatibility remains job-service-backed and that assembled runtime metadata exposes canonical lookup guidance plus compatibility-wrapper status.
