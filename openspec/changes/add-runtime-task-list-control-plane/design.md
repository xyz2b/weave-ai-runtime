## Context

The runtime currently has a single `TaskManager` abstraction that serves as an internal registry for background agent runs, memory jobs, and teammate execution projections. Built-in `task_create`, `task_get`, `task_update`, and `task_list` are thin wrappers over that registry, so they expose runtime job records rather than a Claude Code style planning checklist, while `task_stop` also uses the same overloaded name for background execution control.

That coupling creates three problems:

- Model-facing task tracking and runtime-internal background-job tracking share one data model even though they have different lifecycles, ownership rules, and persistence needs.
- The `task` namespace simultaneously refers to todo/task-list semantics and background execution semantics, which makes the public contract ambiguous.
- Hosts can receive notifications, but they do not have a stable runtime-owned API for reading or observing task-list state when they want to build their own UI or telemetry.
- User-defined agents can technically call the built-in task tools today, but the tools do not provide the planning semantics users expect and cannot be used as a reusable task-discipline primitive.

The change therefore needs two explicit runtime-owned control planes:

- `task_*` for model-facing todo/task-list planning
- `job_*` for runtime background execution control

Both surfaces must be host-agnostic, available to user-defined agents through normal tool-pool resolution where appropriate, and separated from each other in naming and storage.

## Goals / Non-Goals

**Goals:**

- Introduce a dedicated model-facing `TaskListService` separate from the existing internal background-job registry.
- Introduce an explicit background-job control surface that keeps runtime execution records out of the task-list namespace.
- Preserve host-agnostic runtime behavior: task-list semantics must work even when no host task panel exists.
- Let built-in and user-defined agents opt into the task workflow by including task tools in their allowed tool pool.
- Support Claude Code v2 style task fields: persistent list storage, `pending/in_progress/completed` status, `active_form`, `owner`, `blocks`, `blocked_by`, and metadata.
- Provide hidden reminder injection through a sidecar so the runtime can nudge agents to maintain stale task lists without requiring host UI.
- Expose optional host query/watch surfaces so hosts can build their own task experiences without taking ownership of orchestration.

**Non-Goals:**

- Reproducing Claude Code's exact terminal UI, task panel, or keyboard interaction model.
- Replacing the existing background job/task projection system used by agent execution, memory, or teammate orchestration.
- Unifying task lists and background jobs behind one public namespace.
- Making teammate scheduling depend on task lists in the first implementation.
- Standardizing a single visual host projection format beyond runtime-owned query/event surfaces.

## Terminology

- `task`: a model-facing task-list entry used for planning and progress tracking.
- `task list`: a persistent planning checklist resolved by runtime scope, typically session- or team-scoped.
- `job`: a runtime background execution record for long-lived work such as background agents, shell runs, or teammate execution projections.
- `TaskManager`: the existing internal runtime registry for background jobs and execution projections.
- `TaskListService`: the new runtime-owned service for Claude Code v2-style planning semantics.

## Scope Clarification

- Task lists are resolved from execution context, default to session/team scope, and may be inherited by child or delegated executions when they share the same planning context.
- Background jobs are execution records scoped to runtime runs or background-capable operations; they may be short-lived or numerous and must not be treated as planning tasks by default.
- Task identifiers and job identifiers live in separate namespaces. If a caller wants to relate them, it must do so through explicit metadata or linkage fields rather than by assuming one identifier can be reused as the other.

## Decisions

### 1. Split model-facing task lists from the internal background-job registry and from the public namespace

The runtime will keep the existing `TaskManager` for internal background-job and projection tracking. A new `TaskListService` will own the Claude Code style planning checklist. Public naming will also be split: `task_*` refers only to task lists, while `job_*` refers only to background execution records.

Why:

- Background jobs and planning tasks have different primary keys, status taxonomies, and persistence requirements.
- Reusing the current `ManagedTask` shape would force planning concerns into internal runtime code paths and further entrench the semantic overlap.
- Keeping both services explicit makes responsibilities and observability clearer.
- Naming the two surfaces differently removes the strongest source of API confusion.

Alternatives considered:

- Extend `TaskManager` to handle both semantics. Rejected because it would conflate internal runtime projections with model-facing planning data.
- Replace `TaskManager` outright. Rejected because memory/background agent/teammate flows already depend on it and do not need Claude-style planning semantics.

### 2. Introduce a persistent, scoped `TaskListService`

`TaskListService` will be added to `RuntimeServices` beside the existing internal task service. It will resolve a `task_list_id` from execution context and persist task records in a backend that can survive multiple turns and optional session resume.

The default implementation will be file-backed, with a storage model intentionally closer to the existing teammate mailbox approach than to in-memory dicts. The service contract should support:

- `resolve_list_id(context)`
- `create(list_id, payload)`
- `get(list_id, task_id)`
- `list(list_id)`
- `update(list_id, task_id, patch)`
- `delete(list_id, task_id)`
- `claim(list_id, task_id, owner)`
- `watch(list_id)` or equivalent callback registration for host projections

These are service-level operations. The first public built-in model surface only exposes `task_create`, `task_get`, `task_update`, and `task_list`; service-level delete/claim helpers remain internal or future extension points unless a later change promotes them into the public tool contract.

Why:

- File-backed storage gives host-independent persistence and keeps future multi-process or swarm usage possible.
- A scoped list id lets parent/child runs share a checklist when appropriate without forcing one list per agent.
- A service boundary keeps the backend replaceable for embedders who want database-backed storage.

Alternatives considered:

- Keep task lists only in transcript/private context. Rejected because hosts need query surfaces and task state should not depend on transcript scanning.
- Keep task lists only in session memory. Rejected because it breaks resume and external host projection.

### 3. Resolve task lists by session/team context, not by built-in agent type

Task-list access will be driven by context, not special-cased agent classes.

Resolution order:

1. explicit override from runtime/private context
2. inherited parent or delegated execution override
3. team-scoped or orchestration-scoped list id when present
4. session id fallback

Any agent, including user-defined agents, can participate by having the task tools in its tool pool. No built-in-agent-only fast path will be introduced.

Why:

- The framework must work for user-defined agents, not only the built-in pack.
- Session/team-scoped lists match the collaboration model better than per-agent todo silos for the v2 task shape.
- Explicit override keeps future host workflows possible.

Alternatives considered:

- One task list per agent. Rejected because it makes cross-agent work sharing and host projection harder, and diverges from the v2 task intent.
- Built-in-agent-only enablement. Rejected because it conflicts with framework extensibility.

### 4. Re-scope built-in `task_*` tools to task lists and move background control to `job_*`

Built-in `task_create`, `task_get`, `task_update`, and `task_list` will become model-facing task-list tools. Background execution control will move to an explicit `job_*` namespace, with `job_get`, `job_list`, and `job_stop` as the primary model-visible controls.

The tool schemas will move toward Claude v2-style task fields:

- create: required `subject`; optional `description`, `active_form`, `owner`, dependency fields, and metadata
- update: required `task_id`; partial mutations for `status`, `subject`, `description`, `active_form`, `owner`, dependency fields, and metadata
- list/get: resolved `task_list_id` plus full persisted task entry or list snapshot
- errors: structured tool-visible categories such as `not_found`, `invalid_request`, `invalid_transition`, and `multiple_in_progress` when strict validation is enabled

The job tool schemas will target runtime execution records instead:

- get/list: job status, type, summary, linkage, and terminal metadata
- stop: requires `job_id`, rejects unknown or non-running jobs with structured `not_found` / `not_running` errors, and does not mutate any task-list entry

Why:

- The current mixed namespace makes both planning and runtime control harder to reason about.
- Using `task_*` only for todo semantics matches Claude Code's conceptual split even if Claude itself still carries legacy naming.
- A normal built-in tool surface keeps user-defined agent integration trivial.

Alternatives considered:

- Keep `task_stop` as the primary background control tool. Rejected because it preserves the semantic mismatch after the rest of the API has been split.
- Introduce parallel `todo_*` tools and keep current `task_*` tools unchanged. Rejected because it would preserve the semantic mismatch and create two partially overlapping planning surfaces.

### 5. Implement task-discipline as a sidecar, not a host/UI behavior

Hidden reminder injection will be implemented through a request-assembly sidecar via `RuntimeServices.hooks.collect()` or an equivalent dedicated context contribution service, not via UI affordances and not via experimental `critical_system_reminder`.

The sidecar will:

- activate only when the current tool pool includes the task-list tools
- inspect task-list state plus a small amount of session-local counter state
- inject hidden prompt fragments when the task list has gone stale relative to a configured turn threshold
- avoid dependence on host rendering
- coexist with an opt-in strict single-`in_progress` policy rather than assuming every shared task list must be strictly single-threaded

Why:

- Sidecars are the runtime's formal pre-turn context contribution surface.
- The host may not implement any task UI.
- Using sidecar fragments keeps the reminder model-visible but host-hidden.

Alternatives considered:

- Host-only reminders. Rejected because the runtime cannot depend on UI.
- `critical_system_reminder`. Rejected because current docs mark it as unstable authoring surface.

### 6. Expose host-facing query and watch surfaces through the runtime bridge, not mandatory host callbacks

Hosts should be able to consume task-list state and, where useful, background-job state, but they should not be required to implement new callbacks just to enable runtime semantics. The host bridge extension will therefore expose runtime-owned query/watch APIs through `BoundHostRuntime` or equivalent bridge accessors.

Expected surfaces:

- `list_task_lists(...)`
- `get_task_list(list_id)`
- `watch_task_list(list_id, callback) -> unsubscribe`
- `list_jobs(...)` / `get_job(job_id)` for explicit background execution inspection where host integrations need it
- session-to-list resolution helpers for host projection

The first host-watch contract will be callback-based on the bound runtime surface, and each callback will receive a full current snapshot rather than a delta patch. Hosts that prefer polling can ignore watch registration and use the query APIs only; event-stream transports are out of scope for this change.

Why:

- This keeps the runtime usable in headless or minimal hosts.
- Hosts that want task UI can opt in without reimplementing orchestration.

Alternatives considered:

- Add mandatory task callbacks to `HostRuntime`. Rejected because many hosts do not need them and the runtime should stay functional without them.

## Public Contract

- `task_create`, `task_get`, `task_update`, and `task_list` are task-list-only APIs. They do not expose runtime background execution records.
- Background execution inspection and control is exposed through `job_get`, `job_list`, and `job_stop`.
- The runtime does not provide a parallel compatibility namespace for background-style `task_*` control. The documented public surface is the split `task_*` / `job_*` contract.

## Agent Integration Examples

### Planning Agent

Tool pool:

- `task_create`
- `task_get`
- `task_update`
- `task_list`

Expected behavior:

- Maintains a shared task list for the current session or team scope.
- Treats task entries as planning state only.
- Does not inspect or stop runtime background jobs because `job_*` is not in scope.

### Ops Agent

Tool pool:

- `job_get`
- `job_list`
- `job_stop`

Expected behavior:

- Inspects and controls background executions only.
- Does not mutate planning checklists because `task_*` is not in scope.
- Can be used by hosts or coordinators that want a narrow operational surface.

### Coordinator Agent

Tool pool:

- `task_create`
- `task_get`
- `task_update`
- `task_list`
- `job_get`
- `job_list`
- `job_stop`

Expected behavior:

- Uses `task_*` to maintain the plan and `job_*` to observe or stop concrete runtime executions.
- Must not assume a task id is also a job id.
- Can coordinate child agents by sharing a task list while still managing independent background jobs.

## Host Integration Examples

### Host Task Panel

A host that wants to render planning state should use runtime-owned task-list surfaces such as:

- `get_task_list(list_id)`
- `watch_task_list(list_id, callback)`
- session-to-list resolution helpers when the host starts from a session identifier

That host should treat the returned data as planning state rather than execution telemetry.

### Host Job Monitor

A host that wants to render execution telemetry should use explicit job surfaces such as:

- `list_jobs(scope)`
- `get_job(job_id)`

That host should treat the returned data as runtime execution state rather than as a todo list.

### Minimal or Headless Host

A host that implements neither surface should still receive correct runtime behavior. Task reminders, task-list persistence, and background-job tracking remain runtime-owned and do not depend on a built-in UI.

## Risks / Trade-offs

- [Service duplication] Two task-like services (`TaskManager` and `TaskListService`) can confuse contributors. → Mitigation: document the split as "background jobs vs model-facing task lists" and enforce separate module names.
- [Reminder noise] Hidden reminders can become repetitive or conflict with specialized workflows. → Mitigation: gate reminders on tool availability, make cadence configurable, and allow hosts or routes to disable task discipline.
- [Persistence complexity] File-backed list storage adds locking and schema-evolution concerns. → Mitigation: keep the initial schema simple, reuse existing filesystem patterns, and make the backend replaceable.
- [Host surface creep] Adding too much host task API could turn the runtime bridge into a UI framework. → Mitigation: expose only query/watch primitives and keep rendering concerns out of scope.

## Implementation Sequence

1. Add the shared runtime foundations: introduce `TaskListService`, its default backend, and execution-context `task_list_id` resolution without removing the current internal `TaskManager`.
2. Implement the task-list public surface: built-in `task_*` schemas/implementations plus task-list host query/watch surfaces.
3. Implement the background-job public surface: built-in `job_*` schemas/implementations, explicit job host query surfaces, and removal of task-named background control from the public pack.
4. Add task reminder sidecar injection and optional strict single-`in_progress` validation.
5. Update tests, docs, and integration guides to distinguish background jobs from model-facing task lists.

Rollback:

- Disable the new task-list service and task-discipline sidecar and remove the split public `task_*` / `job_*` surfaces if rollback is required.

## Resolved Defaults

- Strict single-`in_progress` enforcement remains an opt-in validation policy layered on top of the base task-list service; the base shared-list contract does not require it globally.
- The first host watch surface is a callback-based bound-runtime subscription that emits full snapshots; hosts that do not want callbacks can rely on polling through query APIs.
