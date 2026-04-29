## Context

The runtime already has a persistent task-list control plane and a separate runtime-owned background job registry, but orchestration semantics still stop at storage and prompt discipline. `blocks` / `blocked_by` are primarily persisted fields, `task_list` returns raw snapshots without readiness derivation, and claim-like behavior is not exposed as a dedicated blocker-aware contract. At the same time, child agent execution already emits typed `CHILD_RUN` events and structured `AgentRunRecord` objects, but those terminal child-run outcomes do not reliably re-enter the parent session as continuation-driving inputs.

This change assumes the task-list persistence split introduced by [add-runtime-task-list-control-plane/proposal.md](../add-runtime-task-list-control-plane/proposal.md) is already landed as the baseline contract. It is a refinement of that control plane, not an alternative design.

That leaves four practical gaps:

- task dependency enforcement still depends too much on model behavior rather than runtime-owned atomic rules
- dependency edges can drift because forward and reverse links are treated as generic mutable fields
- hosts, sidecars, and models each need to recompute "what task is available" from raw task snapshots
- waiting coordinators are observable but not self-driving, because background child completion does not automatically participate in session continuation policy

This change needs to preserve the existing control-plane split:

- `TaskManager` remains the runtime-owned registry for background execution and projections
- typed `CHILD_RUN` events remain the primary host/SDK observability surface
- task orchestration stays host-agnostic and does not depend on a built-in UI

The design therefore extends the existing task-list control plane instead of replacing it, and layers continuation policy on top of the existing child-run observability contract instead of introducing a transcript-only XML protocol.

## Goals / Non-Goals

**Goals:**

- Formalize task orchestration as runtime-owned control-plane semantics rather than prompt convention.
- Add atomic `claim`, `release`, `assign_next`, and validated dependency-edge operations to the task-list service.
- Expose derived orchestration views such as available, blocked, unresolved blockers, and in-progress summaries.
- Introduce dedicated built-in orchestration tools so claim and dependency maintenance no longer rely on generic `task_update` patches.
- Allow terminal child runs to wake waiting parent sessions through structured ingress and continuation policy while preserving typed `CHILD_RUN` observability.
- Keep host integrations snapshot-oriented and runtime-owned rather than host-scheduled.

**Non-Goals:**

- Reproducing Claude Code's XML `<task-notification>` protocol or coordinator transcript contract.
- Replacing `TaskManager` or merging planning tasks back into the background execution registry.
- Introducing a separate standalone scheduler service outside the existing task-list control plane.
- Making teammate orchestration depend on task lists in this change.
- Designing a rich host push transport beyond callback/query surfaces for the first iteration.

## Decisions

### 1. Extend `DefaultTaskListService` into a task-graph orchestration service

The runtime will build orchestration semantics into the existing task-list service rather than introducing a new external scheduler abstraction. The service will continue to own persistence and list resolution, but it will also gain dedicated orchestration operations such as `claim`, `release`, `assign_next`, `add_dependency`, `remove_dependency`, and `list_view`.

Why:

- task orchestration is a direct refinement of the persisted task-list graph rather than a second independent state machine
- the service already owns list-level locking, which is the correct place to make claim and dependency updates atomic
- a second scheduler service would duplicate snapshot loading, lock ownership, and task validation logic

Alternatives considered:

- Add a separate `TaskOrchestrator` above `TaskListService`. Rejected because it would either need to reimplement locking or call back into the service for every mutation, splitting one control-plane concern across two modules.
- Leave orchestration entirely to prompt policy. Rejected because dependency validation, ownership races, and readiness derivation are runtime concerns.

### 2. Treat claim and dependency maintenance as dedicated operations, not generic patch fields

Orchestration-critical mutations will no longer be modeled as arbitrary `task_update` patches. Dependency edges and claim-like ownership transitions will instead flow through dedicated operations with their own validation and error codes.

This means:

- `task_update` remains for non-orchestration fields and permitted status changes
- `task_claim`, `task_release`, and `task_assign_next` become the public model surface for ownership and next-task acquisition
- `task_block` and `task_unblock` become the public model surface for dependency maintenance
- direct public owner mutation and raw dependency-edge patches are removed from the built-in task-update contract
- built-in `task_claim` and `task_assign_next` use `set_in_progress=true` as their default state-advance behavior
- `task_release` clears owner and returns unresolved claimed work to `pending`

Why:

- orchestration-critical fields need stronger invariants than generic partial patch semantics can provide
- structured errors such as `blocked`, `already_claimed`, `owner_busy`, and `dependency_cycle` belong on dedicated operations
- separating orchestration operations makes host, model, and test expectations much clearer

Alternatives considered:

- Keep `task_update` as a "do everything" patch surface and add internal validation hooks. Rejected because the external contract would still encourage callers to bypass orchestration semantics.

Migration mapping for callers:

- owner assignment via `task_update.owner` -> `task_claim`
- owner clearing for unresolved work -> `task_release`
- dependency-edge mutation via `task_update.blocks` / `task_update.blocked_by` -> `task_block` / `task_unblock`

### 3. Compute task availability as a derived view, not stored state

Availability will be computed from the current task snapshot rather than persisted as an additional field. The derived view will classify tasks such as:

- `available`
- `blocked`
- `claimed`
- `in_progress`
- `completed`

and will also expose list-level summaries such as `available_task_ids`, `blocked_task_ids`, and unresolved blocker identifiers.

Why:

- availability is a function of status, ownership, and unresolved blockers, so persisting it would create cache invalidation problems
- the runtime already loads full list snapshots under a per-list lock, so the derived view is cheap and deterministic
- one runtime-owned readiness computation removes duplicated logic from models, sidecars, hosts, and tests

Alternatives considered:

- Persist `available` on each task. Rejected because every status or dependency mutation would need cross-task recomputation and stale derived state would become another correctness risk.

### 4. Keep typed `CHILD_RUN` events as observability truth and layer continuation on top

Terminal child runs will continue to emit typed `CHILD_RUN` turn-stream events and persisted `AgentRunRecord` snapshots. Continuation behavior will be layered on top through a child-run continuation bridge that can convert eligible terminal child runs into structured session ingress events when policy allows.

The preferred first implementation is:

- retain the existing typed `CHILD_RUN` event path for turn-local and host-visible observability
- add a runtime-owned continuation bridge service
- reuse `TASK_NOTIFICATION`-style session ingress with explicit `admission_kind=admit_turn` metadata for runtime-generated continuation input
- avoid any XML transcript protocol or child-run result scraping

Why:

- typed lifecycle events are already the strongest contract in the runtime and should remain the source of truth
- continuation is a policy decision, not a replacement for observability
- reusing ingress preserves one admission pipeline for user prompts and runtime-generated follow-up inputs

Alternatives considered:

- Inject child completion directly as prompt text without ingress. Rejected because it would bypass session control and blur runtime/private state boundaries.
- Introduce a Claude Code style XML protocol. Rejected because it duplicates typed child-run records and forces hosts to parse transcript text for runtime semantics.
- Add a brand-new command type on day one. Rejected for the first iteration because ingress metadata already supports explicit admission override and keeps the transport surface smaller.

### 5. Default continuation policy should be conservative

The initial continuation policy will auto-resume `WAITING` sessions by default. `READY` sessions will queue admitted continuation inputs without immediately starting a new turn unless an explicit runtime policy enables eager resume, and `RUNNING` sessions will only queue continuation inputs for later drain.

The bridge will also deduplicate deliveries and avoid double-reporting when the parent turn is still active and can already observe the child via turn-local `CHILD_RUN` events.

Why:

- `WAITING` sessions are the clearest case where the runtime is blocked on an external completion
- aggressively resuming all ready sessions risks surprising hosts and making background activity feel nondeterministic
- dedupe and active-turn guards are required because typed child-run events and continuation signals coexist

Alternatives considered:

- Auto-resume all sessions. Rejected as too aggressive for the first rollout.
- Never auto-resume, only enqueue. Rejected because it would preserve the core "waiting coordinator does not wake up" problem.

### 6. Host integration remains snapshot/query oriented

Hosts will consume runtime-owned orchestration snapshots and watch callbacks rather than owning the scheduler. The bridge surface will expose query and watch methods for task orchestration views, while claim validation, dependency maintenance, and continuation policy stay runtime-owned. The first host payload shape will at minimum include per-task readiness state plus list-level `available_task_ids` and `blocked_task_ids`.

Why:

- hosts should be able to render or observe orchestration state without reproducing runtime logic
- full-snapshot callbacks are easier to reason about than delta streams for a first implementation
- this matches the runtime's current emphasis on host-agnostic control planes

Alternatives considered:

- Require hosts to resolve available tasks themselves from raw snapshots. Rejected because it duplicates orchestration logic.
- Add mandatory push-only host protocols. Rejected because some hosts only need polling/query access.

## Risks / Trade-offs

- [Broader task-list service surface] → Mitigation: keep orchestration helpers in the same module but with clear internal helpers, dedicated error types, and focused tests for claim, dependency, and availability semantics.
- [Breaking change in `task_update`] → Mitigation: document replacements clearly, return structured `invalid_request` errors for orchestration fields, and update built-in tool docs and tests together.
- [Continuation races or duplicate wakeups] → Mitigation: add active-turn guards, delivered-record dedupe, and waiting-only auto-resume defaults.
- [Availability view can become a catch-all dumping ground] → Mitigation: keep it strictly derived from persisted task state and limit it to readiness-oriented fields rather than duplicating the whole persistence model in new shapes.
- [Host expectations may drift from runtime policy] → Mitigation: expose full snapshots and keep runtime as the only source of truth for claim and dependency validation.

## Migration Plan

1. Extend the task-list service with orchestration helpers, derived views, and structured orchestration errors.
2. Add built-in orchestration tools and narrow `task_update` so dependency and claim-style mutations no longer flow through raw patch semantics.
3. Update `task_list` and host-facing query/watch surfaces to expose derived orchestration views.
4. Add the child-run continuation bridge, live session lookup, and admitted-ingress submission path behind conservative policy defaults.
5. Update task-discipline reminders, architecture docs, and tests to use runtime-derived availability rather than ad hoc prompt heuristics.
6. Archive or otherwise mark the prerequisite task-list control-plane change as landed before advertising this orchestration layer as independently deployable.

Rollback strategy:

- continuation auto-resume can be disabled via runtime policy while preserving typed child-run observability
- orchestration tools can be removed from tool pools if needed, while the underlying persistent task-list surface remains intact
- the previous raw `task_update` behavior is not intended to remain as a compatibility fallback once this change ships

## Open Questions

- None for the first implementation. Public owner mutation is routed exclusively through `task_claim` / `task_release`, `assign_next` uses FIFO selection only, and callback-based host watch surfaces are the chosen first host contract.
