## Context

The runtime already has a usable task-list control plane, but embedders still face four contract gaps:

- built-in `task_update` schemas advertise owner and dependency mutations that the service layer now rejects
- hosts can read and watch task lists, but cannot drive the same task plane through a stable bridge API
- task retirement exists only as an internal delete helper, with no explicit public archive/delete lifecycle
- the default file-backed store persists snapshots, but does not yet define a strong crash-safety and concurrency boundary for framework consumers

This change is intentionally narrower than the earlier task-list and task-orchestration proposals. It does not re-open task/job separation or scheduler semantics. It hardens the framework-facing contract that embedders and product code are expected to rely on.

## Goals / Non-Goals

**Goals:**

- Make public task mutation schemas match actual runtime validation.
- Add stable host mutation APIs for the shared task plane.
- Define an explicit task-retirement lifecycle with reversible archival and destructive deletion.
- Specify the durability and single-writer boundary of the default file-backed task-list store.
- Keep derived readiness and orchestration semantics aligned with the new retirement model.

**Non-Goals:**

- Introducing a new database-backed task store in the default runtime.
- Adding host-owned scheduling or readiness recomputation.
- Expanding the task status enum beyond `pending`, `in_progress`, and `completed`.
- Designing a rich UI contract for task panels, filters, or shortcuts.

## Decisions

### 1. Public task mutation contracts will align around dedicated operations

The runtime will treat `task_update` as a narrow partial update surface for non-orchestration fields only:

- `status`
- `subject`
- `description`
- `active_form`
- `metadata`

Ownership and dependency mutations will remain dedicated operations:

- `task_claim`
- `task_release`
- `task_assign_next`
- `task_block`
- `task_unblock`

The same split will apply to host APIs. Hosts will not receive a privileged "raw patch anything" mutation path.

Why:

- the service layer already enforces this split, so keeping wider public schemas creates a false contract
- dedicated operations preserve structured orchestration errors and reduce caller ambiguity
- host and tool callers should see one authoritative task mutation model

Alternatives considered:

- Keep broader `task_update` schemas and rely on runtime errors. Rejected because it leaves client generators, docs, and callers with an inaccurate contract.
- Re-open raw owner/dependency patches for hosts only. Rejected because it would create a second, less safe control path.

### 2. Task retirement will be modeled as archival metadata, not a new task status

The runtime will keep work status and record visibility separate:

- `status` remains `pending | in_progress | completed`
- archival is represented by explicit archival fields on the task record:
  - `is_archived`
  - `archived_at`
  - `archived_by`

The default lifecycle is:

1. active task
2. completed task
3. archived task
4. deleted task

The first implementation will require a task to be `completed` before it can be archived, and a task to be archived before it can be deleted. Unarchive restores an archived task to the visible completed state.

Archived tasks are otherwise immutable:

- `task_update`
- `task_claim`
- `task_release`
- `task_assign_next`
- `task_block`
- `task_unblock`

will reject archived targets rather than mutating them. Repeated archive and invalid retirement transitions will use stable lifecycle error codes:

- `archive_requires_completed`
- `delete_requires_archived`
- `already_archived`
- `not_archived`
- `archived_task_immutable`

Archived tasks remain persisted, but default task-list and orchestration views hide them unless the caller opts in with `include_archived=true`. Archived tasks never appear in readiness summaries such as `available_task_ids` or `blocked_task_ids`.

Why:

- archive is a visibility and retention concern, not active work progress
- keeping archive orthogonal avoids widening the planning status state machine
- archive-before-delete gives the framework a safer destructive-workflow boundary

Alternatives considered:

- Add `archived` as a task status. Rejected because it overloads planning progress with storage/visibility semantics.
- Expose delete only, without archive. Rejected because product-facing consumers usually need reversible cleanup before destructive removal.

### 3. Bound host runtime will expose first-class task mutation methods

The bound host bridge will add runtime-owned task mutation methods alongside existing query/watch methods. The expected surface is:

- `create_task(...)`
- `get_task(...)`
- `update_task(...)`
- `claim_task(...)`
- `release_task(...)`
- `assign_next_task(...)`
- `block_task(...)`
- `unblock_task(...)`
- `archive_task(...)`
- `unarchive_task(...)`
- `delete_task(...)`

These methods will resolve the task-list scope the same way the tool path does and will return the same canonical task snapshot shape or structured errors.

Why:

- hosts need a direct way to let users manipulate the shared task plane
- routing host actions back through agent tool execution is the wrong abstraction boundary
- symmetric host and tool payloads reduce duplicated translation logic

Alternatives considered:

- Expose only the service object to hosts. Rejected because that leaks private runtime internals into the public bridge.
- Add one generic `mutate_task_list` host RPC. Rejected because explicit methods are easier to document, type, and evolve safely.

### 4. The default file-backed store will become crash-safe but remain single-writer

`FileTaskListStore` will switch from direct in-place writes to temp-file plus atomic replace semantics for snapshot persistence. The runtime contract will explicitly state that the bundled store is single-runtime-writer only:

- one runtime process can safely mutate a task-list root
- process-local watchers are valid only within that runtime
- embedders that need multi-process or distributed writers must provide a custom `TaskListStore`

The runtime will not claim cross-process locking, leader election, or merge semantics for the default store.

Why:

- atomic replacement is the minimum durability guarantee embedders expect from a persisted control plane
- documenting the single-writer boundary is better than implying unsupported multi-process safety
- custom store injection already exists as the right escape hatch

Alternatives considered:

- Add file locks and claim multi-process support in the default store. Rejected because it adds platform-specific complexity without addressing distributed consistency fully.
- Leave direct writes as-is. Rejected because partial writes make the framework contract weaker than the runtime's intended positioning.

### 5. Retirement-aware snapshots will preserve orchestration correctness

Task-list queries and watches will gain an `include_archived` switch. Orchestration derivation will operate only on non-archived tasks for visibility summaries, while completed archived tasks remain resolved for persistence purposes until deleted.

Deletion will continue to clean dangling dependency edges in one mutation boundary. If archived tasks are deleted, surviving tasks must not retain stale `blocks` or `blocked_by` references.

Default active-work views will also suppress dependency references that target archived tasks. This keeps returned snapshots self-contained when archived tasks are hidden. Exact record lookups and archived-visible list views will preserve the full dependency data instead of filtering it away.

Why:

- embedders need a clean default "active work" view without losing historical records
- readiness summaries should never surface archived items as actionable work
- dependency cleanup must remain deterministic after retirement operations

Alternatives considered:

- Always include archived tasks in default snapshots. Rejected because it pollutes the normal planning surface and makes retirement largely cosmetic.

### 6. Exact task lookup is record-centric, not list-visibility-centric

`task_get` and host `get_task(...)` will return archived tasks by exact id lookup even when archived tasks are hidden from default list and watch views.

Why:

- exact lookup is the natural path for unarchive, delete, debugging, and historical inspection flows
- forcing `include_archived` onto id lookups would make retirement operations awkward and inconsistent with record-centric APIs
- list visibility and record retrievability are separate concerns

Alternatives considered:

- Hide archived tasks from exact lookup unless `include_archived=true`. Rejected because it makes archived records harder to manage and turns precise lookup into another list-like filtered query.

## Risks / Trade-offs

- [Archive-before-delete may feel stricter than some hosts expect] → Mitigation: keep the rule explicit in docs and expose both archive and delete APIs so hosts can build a two-step UX cleanly.
- [Adding host task mutation APIs broadens the public bridge surface] → Mitigation: mirror existing tool semantics and canonical payloads instead of inventing host-specific behavior.
- [Single-writer default store may disappoint embedders expecting shared filesystem concurrency] → Mitigation: state the boundary normatively and keep custom store replacement as the sanctioned extension path.
- [Archived task filtering can surprise callers that relied on "list everything"] → Mitigation: add `include_archived` on query/watch surfaces and document the default clearly.

## Migration Plan

1. Narrow built-in `task_update` schemas, validation docs, and tests to the supported mutation subset.
2. Add archival fields and retirement helpers to `TaskListEntry` / `TaskListService`, plus archive-aware snapshot filtering.
3. Introduce built-in `task_archive`, `task_unarchive`, and `task_delete` tools with structured error semantics.
4. Extend the runtime kernel and bound host bridge with task mutation and retirement methods that share canonical payloads with the tool path.
5. Switch `FileTaskListStore` persistence to atomic replace writes and document the single-writer boundary in runtime docs.
6. Add regression coverage for schema alignment, host mutation APIs, archive visibility, destructive deletion, and crash-safe persistence behavior.

Rollback strategy:

- host mutation methods and retirement tools can be removed from tool pools or bridge helpers if necessary without undoing the underlying task-list persistence model
- archival fields are additive and can be ignored by older readers during rollback
- atomic write changes are backward compatible with existing persisted snapshot files

## Open Questions

- None for this proposal revision. The first hardening slice will standardize archive-before-delete, default archived filtering, and a single-writer durability contract rather than deferring those choices.
