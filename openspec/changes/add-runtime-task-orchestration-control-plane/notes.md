## Implementation Notes

- `TaskListService` now owns derived orchestration semantics on top of persistence:
  - structured orchestration errors (`blocked`, `already_claimed`, `owner_busy`, `dependency_cycle`)
  - derived readiness state (`available`, `blocked`, `claimed`, `in_progress`, `completed`)
  - atomic `claim`, `release`, `assign_next`, `task_block`, and `task_unblock` helpers
- `task_update` is now intentionally narrower:
  - owner mutation moved to `task_claim` / `task_release`
  - dependency-edge mutation moved to `task_block` / `task_unblock`
- host and model-facing task-list snapshots now include runtime-owned readiness projections:
  - per-task `readiness_state` and `unresolved_blockers`
  - list-level `available_task_ids` / `blocked_task_ids`
- terminal child runs keep typed `CHILD_RUN` observability as the primary contract and can additionally wake parent sessions through admitted runtime-generated continuation ingress.

## Contract Tests

- `tests/test_task_list_control_plane.py`
  - service-level availability derivation, blocker enforcement, owner-busy behavior, dependency-cycle rejection, orchestration tools, host snapshot coverage
- `tests/test_child_run_continuation.py`
  - waiting-session wake-up, ready-session queueing, duplicate-delivery suppression while preserving typed `CHILD_RUN` events
