## 1. Task Orchestration Service

- [ ] 1.1 Add task orchestration error types and derived view models to the task-list control plane.
- [ ] 1.2 Implement availability derivation helpers for available, blocked, claimed, in-progress, and completed task states.
- [ ] 1.3 Implement atomic `claim`, `release`, and `assign_next` operations with blocker and optional owner-busy validation.
- [ ] 1.4 Implement validated dependency helpers for add/remove edge operations, cycle rejection, and dangling-edge cleanup on delete.
- [ ] 1.5 Add focused service-level tests for availability derivation, blocker enforcement, owner-busy behavior, and cycle rejection.

## 2. Built-in Task Orchestration Tools

- [ ] 2.1 Add built-in tool definitions for `task_claim`, `task_release`, `task_assign_next`, `task_block`, and `task_unblock`.
- [ ] 2.2 Update task tool implementations to call the orchestration helpers and return structured orchestration errors.
- [ ] 2.3 Narrow the `task_update` contract so orchestration-critical mutations no longer flow through raw patch semantics.
- [ ] 2.4 Update `task_list` outputs to expose derived readiness summaries alongside persisted task snapshots.
- [ ] 2.5 Add built-in tool tests covering new orchestration tools and the breaking `task_update` behavior.

## 3. Child-Run Continuation Bridge

- [ ] 3.1 Add a live session lookup/registry surface that runtime-owned continuation logic can use to target parent sessions safely.
- [ ] 3.2 Implement a child-run continuation bridge with conservative wake-up policy, dedupe, and active-turn guards.
- [ ] 3.3 Extend session control with a runtime-generated event submission path that can queue and optionally drain admitted continuation inputs.
- [ ] 3.4 Invoke the continuation bridge from terminal child-run execution paths while preserving the existing typed `CHILD_RUN` observability contract.
- [ ] 3.5 Add tests for waiting-session wake-up, ready-session queueing, and duplicate-delivery suppression.

## 4. Host And Sidecar Integration

- [ ] 4.1 Extend host-facing runtime bridge surfaces to query and watch derived task orchestration snapshots.
- [ ] 4.2 Update task-discipline sidecar output to use derived available/blocked state instead of only raw unfinished tasks.
- [ ] 4.3 Add host-facing coverage for orchestration query/watch snapshots and task-list resolution behavior.

## 5. Docs And Contract Updates

- [ ] 5.1 Update runtime architecture and integration docs to distinguish task-list persistence from task orchestration semantics.
- [ ] 5.2 Document the new built-in orchestration tools and the `task_update` breaking change with migration guidance.
- [ ] 5.3 Add or update change-level notes and contract tests covering derived availability and child-run-driven continuation.
