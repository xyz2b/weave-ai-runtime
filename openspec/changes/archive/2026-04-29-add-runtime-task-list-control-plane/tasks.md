## 1. Shared Runtime Foundations

- [x] 1.1 Add task-list models and a `TaskListService` contract separate from the existing internal `TaskManager`
- [x] 1.2 Implement the default persistent task-list backend with scoped list resolution and stable task identifiers
- [x] 1.3 Thread resolved `task_list_id` state through session and delegated execution context without coupling it to built-in agent types

## 2. Task-List Public Surface

- [x] 2.1 Rework `task_create`, `task_get`, `task_update`, and `task_list` schemas and implementations to target `TaskListService` v2 task semantics
- [x] 2.2 Update built-in tool metadata, summaries, and validation so custom agents can consume `task_*` for todo lists through ordinary tool-pool resolution
- [x] 2.3 Expose runtime-owned task-list query APIs through the bound host/runtime bridge surface
- [x] 2.4 Add host-consumable task-list watch or change-notification plumbing without making host callbacks mandatory

## 3. Background-Job Public Surface

- [x] 3.1 Introduce `job_get`, `job_list`, and `job_stop` as the explicit background execution control surface
- [x] 3.2 Remove task-named background-job control paths from the built-in public pack so `task_*` and `job_*` are unambiguous
- [x] 3.3 Update built-in tool metadata, summaries, and validation so custom agents can consume `job_*` for background execution through ordinary tool-pool resolution
- [x] 3.4 Expose explicit background-job query surfaces separately from task-list APIs

## 4. Task Discipline Sidecar

- [x] 4.1 Add configurable task-discipline state and reminder policy for executions that have task tools available
- [x] 4.2 Implement hidden task reminder injection through a request-assembly sidecar without requiring host UI participation
- [x] 4.3 Add opt-in strict single-`in_progress` enforcement and structured validation failures for conflicting updates

## 5. Verification

- [x] 5.1 Add unit tests for task-list persistence, list-id resolution, task-tool structured errors (`not_found`, `invalid_request`, `multiple_in_progress` when enabled), and explicit no-cross-mutation assertions (`job_stop` does not mutate task lists, `task_update` does not alter job lifecycle state)
- [x] 5.2 Add integration tests covering custom-agent access, child execution inheritance, hidden reminders, callback-based host watch snapshots, and separate host bridge queries for task lists vs jobs

## 6. Documentation

- [x] 6.1 Update runtime integration and extension docs to define `task` vs `job`, document `TaskManager` vs `TaskListService`, and describe the split public contract for `task_*` and `job_*`
- [x] 6.2 Add documentation examples for planning-only agents, ops-only agents, coordinator agents, and host task-panel vs job-monitor integrations
