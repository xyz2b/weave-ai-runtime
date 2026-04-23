## Why

The runtime currently uses the `task` name for two different concerns: model-facing planning and runtime-internal background execution tracking. That semantic overlap makes the built-in `task_*` tools misleading, hides the boundary between todo-style task lists and background jobs, and makes it harder for hosts and user-defined agents to consume either surface correctly.

## What Changes

- Add a runtime-owned task-list control plane for model-facing work planning, with `task_*` reserved exclusively for todo/task-list semantics.
- Add an explicit background-job control surface, with `job_*` reserved for runtime execution records such as background agents, shell runs, and other long-lived jobs.
- Add a persistent `TaskListService` with session/team-scoped list resolution, task ownership, dependency tracking, and host-consumable query/watch surfaces.
- Re-scope the built-in `task_create`, `task_get`, `task_update`, and `task_list` tools to operate on task lists rather than background-job records.
- Introduce built-in `job_get`, `job_list`, and `job_stop` tools for background execution control, with `job_*` as the only public background-control namespace.
- Add an optional hidden task-reminder sidecar that nudges agents to maintain the task list without requiring any built-in UI.
- Ensure user-defined agents can opt into the task-list workflow by including the task tools in their tool pool, without depending on special built-in agent types.

## Capabilities

### New Capabilities

- `task-list-control-plane`: runtime-owned task-list service, persistence, list resolution, task ownership/dependency semantics, and hidden reminder injection for model-facing task discipline.
- `background-job-control-plane`: runtime-owned background-job registry and model/host-facing job inspection and stop surfaces, separate from task-list semantics.

### Modified Capabilities

- `builtin-runtime-pack`: built-in tool naming and behavior split into `task_*` for task lists and `job_*` for background execution control.
- `host-runtime-bridge`: hosts can optionally query, observe, and project task-list state without taking ownership of task orchestration or requiring a built-in task panel.

## Impact

- Affected code: `src/runtime/builtins/tools.py`, `src/runtime/builtins/tool_impls.py`, `src/runtime/runtime_services/__init__.py`, session/turn private-context wiring, host bridge surfaces, and task-related tests.
- New code: task-list models/store/service modules, background-job control surfaces, task reminder sidecar, and host-facing projection/query interfaces.
- Contract: built-in `task_*` is reserved for task-list semantics, and built-in `job_*` is reserved for background execution semantics.
- Documentation: runtime integration, extension, and architecture docs need to distinguish background jobs from model-facing task lists with explicit naming.

## Terminology

- `task`: a model-facing todo/task-list entry owned by the new `TaskListService`.
- `job`: a runtime background execution record owned by the background-job control plane.
- `TaskManager`: the existing internal runtime registry that continues to track background execution and projection state; it is not the new planning checklist service.
