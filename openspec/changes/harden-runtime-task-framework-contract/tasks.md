## 1. Task Contract And Lifecycle

- [ ] 1.1 Narrow the public `task_update` schemas, validators, and summaries to the supported non-orchestration fields only.
- [ ] 1.2 Extend task-list models and service helpers with canonical archival fields `is_archived`, `archived_at`, and `archived_by`.
- [ ] 1.3 Implement archive validation that requires `completed` status before a task can be archived.
- [ ] 1.4 Implement unarchive and delete validation that requires archived state before those retirement transitions succeed.
- [ ] 1.5 Return canonical retirement error codes for invalid archive, unarchive, delete, and repeated archive transitions.
- [ ] 1.6 Make archived tasks immutable outside retirement operations and exact-read paths.
- [ ] 1.7 Hide archived tasks from default task snapshots and add `include_archived` handling for task-list reads.
- [ ] 1.8 Exclude archived tasks from readiness summaries and orchestration derivation outputs.
- [ ] 1.9 Suppress archived dependency references in default active-work list projections.
- [ ] 1.10 Preserve full dependency data for exact lookup and archived-visible task projections.
- [ ] 1.11 Preserve dependency cleanup and structured errors across archive, unarchive, and delete flows.

## 2. Built-In Task Surfaces

- [ ] 2.1 Add a built-in `task_archive` tool definition and implementation.
- [ ] 2.2 Add built-in `task_unarchive` and `task_delete` tool definitions and implementations.
- [ ] 2.3 Make built-in `task_get` archival-aware for exact id lookup and expose canonical archival metadata in task payloads.
- [ ] 2.4 Extend built-in `task_list` input handling with archived-visibility controls.
- [ ] 2.5 Update built-in task payload helpers to emit archival markers and suppress hidden archived dependency edges in default list views.
- [ ] 2.6 Add built-in tool tests for narrowed `task_update` and unsupported raw orchestration-field updates.
- [ ] 2.7 Add built-in tool tests for retirement tools and canonical lifecycle error codes.
- [ ] 2.8 Add built-in tool tests for archived exact lookup, archived-visible list output, and delete edge cleanup.

## 3. Host Bridge Task Control

- [ ] 3.1 Add runtime-kernel helpers for basic task creation, retrieval, and non-orchestration updates that return canonical task payloads or structured errors.
- [ ] 3.2 Add runtime-kernel helpers for task orchestration mutations: claim, release, assign-next, block, and unblock.
- [ ] 3.3 Add runtime-kernel helpers for task retirement mutations: archive, unarchive, and delete.
- [ ] 3.4 Extend `BoundHostRuntime` and host base surfaces with `create_task`, `get_task`, and `update_task`.
- [ ] 3.5 Extend `BoundHostRuntime` and host base surfaces with `claim_task`, `release_task`, `assign_next_task`, `block_task`, and `unblock_task`.
- [ ] 3.6 Extend `BoundHostRuntime` and host base surfaces with `archive_task`, `unarchive_task`, and `delete_task`.
- [ ] 3.7 Make host `get_task(...)` archival-aware for exact id lookup and return the same canonical archival fields and lifecycle error categories as the tool path.
- [ ] 3.8 Extend host task query APIs with `include_archived` handling and hidden-archived edge suppression.
- [ ] 3.9 Extend host task watch APIs with `include_archived` handling and hidden-archived edge suppression.
- [ ] 3.10 Add host-facing regression coverage for direct task mutation flows and archived exact lookup behavior.

## 4. Durability, Docs, And Verification

- [ ] 4.1 Change the default file-backed task-list store to temp-write plus atomic replace persistence.
- [ ] 4.2 Document the single-writer boundary of the default task-list store and the need for a custom store in multi-writer deployments.
- [ ] 4.3 Add persistence tests for crash-safe replace-write behavior and recovery from interrupted writes.
- [ ] 4.4 Add regression tests for archived exact lookup, archived snapshot visibility, and hidden-archived dependency filtering.
- [ ] 4.5 Add regression tests for canonical retirement errors and unsupported raw orchestration-field updates.
- [ ] 4.6 Update runtime integration docs to describe the hardened task framework contract and host mutation APIs.
- [ ] 4.7 Update runtime extension and architecture docs to describe the retirement lifecycle and default durability boundary.
