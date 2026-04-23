## 1. Job Models And Persistence

- [x] 1.1 Add shared job enums and model carriers for `JobStatus`, generic control capabilities, and typed sidecar refs.
- [x] 1.2 Add immutable request and filter carriers for `JobScopeFilter` and `JobSubmitRequest`.
- [x] 1.3 Add minimal executor result carriers for `JobStartResult`, `JobStopResult`, and `JobRecoveryResult`.
- [x] 1.4 Define the `JobRecord` shape, including lifecycle timestamps, visibility metadata, result or error envelope, and sidecar linkage fields.
- [x] 1.5 Define a `JobStore` protocol for create, upsert, get, list, and watch-oriented persistence operations.
- [x] 1.6 Implement the default durable job store using the same file-backed patterns already used by runtime-owned task-list or teammate persistence.
- [x] 1.7 Add the canonical job serializer that converts persisted job records into the shared host and tool payload shape.
- [x] 1.8 Add the shared lifecycle transition validator and the bounded `TaskStatus <-> JobStatus` compatibility mapping helpers.

## 2. Job Service And Executor Registry

- [x] 2.1 Define `JobExecutor`, `JobExecutorFactory`, and the executor-side context contract using `Protocol`-style runtime interfaces.
- [x] 2.2 Implement a runtime-owned executor registry keyed by `executor_kind`, including explicit override behavior for built-in kinds.
- [x] 2.3 Implement `JobService.get(...)` and `JobService.list(...)` with shared scope filtering over the durable store.
- [x] 2.4 Implement `JobService.submit(...)` so it resolves an executor, creates or persists the shared job record, and returns the authoritative `JobRecord`.
- [x] 2.5 Implement `JobService.stop(...)` so it enforces `not_found`, `not_running`, and `not_stoppable` semantics before delegating to the owning executor.
- [x] 2.6 Implement `JobService.watch(...)` with callback-based scope subscriptions and shared snapshot delivery.
- [x] 2.7 Add shared job-control error types or error mapping helpers for executor-resolution failures and stop failures.

## 3. Runtime Assembly And Stage A Compatibility

- [x] 3.1 Extend `RuntimeConfig` with `job_executors` and add the `JobExecutorBinding` config contract.
- [x] 3.2 Implement assembly-time resolution for direct executor bindings and factory-backed executor bindings.
- [x] 3.3 Wire the shared job service and executor registry into `RuntimeServices`, `RuntimeKernel`, and `RuntimeAssembly`.
- [x] 3.4 Preserve existing foreground runtime wiring so `TurnEngine`, `SessionController`, `AgentRuntime`, and `SkillExecutor` do not depend on the new control plane for synchronous execution.
- [x] 3.5 Introduce a Stage A `TaskManager` compatibility adapter backed by `JobService` for create, get, update, list, list_visible, stop, and stop-handler registration.
- [x] 3.6 Route legacy `task_manager`-shaped constructor seams and helper contexts through the Stage A compatibility adapter without changing their call signatures yet.

## 4. Public Job Surfaces

- [x] 4.1 Rework built-in job serialization so `job_get`, `job_list`, and `job_stop` return shared job payloads instead of `ManagedTask`-shaped internals.
- [x] 4.2 Rewire built-in `job_get` to resolve visibility and lookup through `JobService.get(...)`.
- [x] 4.3 Rewire built-in `job_list` to use `JobService.list(...)` with session and team-aware scope filtering.
- [x] 4.4 Rewire built-in `job_stop` to use `JobService.stop(...)` and shared structured stop errors.
- [x] 4.5 Extend the runtime kernel and bound host bridge with job `list`, `get`, `watch`, and `stop` methods backed by `JobService`.
- [x] 4.6 Add tests for host and tool-facing job payloads, scope visibility, watcher callbacks, and structured stop errors.

## 5. Background Agent Migration

- [x] 5.1 Implement the first-party `agent` executor so it can submit and own background agent jobs through the shared control plane.
- [x] 5.2 Create shared job records for background agent runs that link to agent-specific sidecars such as `AgentRunRecord`.
- [x] 5.3 Migrate `AgentDispatcher` background submission to `JobService.submit(...)` without changing synchronous or forked agent execution paths.
- [x] 5.4 Bridge background stop handling from `JobService.stop(...)` into the agent executor so current cancellation behavior is preserved.
- [x] 5.5 Project background agent terminal states back into the shared job record while preserving existing `CHILD_RUN` emission and child-run continuation logic.
- [x] 5.6 Add regression tests covering background agent submission, terminal projection, stop handling, sidecar linkage, and unaffected child-run continuation behavior.

## 6. Memory And Teammate Migration

- [x] 6.1 Migrate background memory extraction to create or update shared job records while preserving memory-owned batching and merge state.
- [x] 6.2 Migrate background memory consolidation to create or update shared job records while preserving consolidation-specific sidecar data.
- [ ] 6.3 Add regression tests for background memory job lifecycle projection, deduplicated queue behavior, and recovery-oriented visibility.
- [x] 6.4 Migrate teammate active execution projections to shared job records without changing teammate identity or mailbox ownership semantics.
- [x] 6.5 Map teammate waiting-permission, running, completed, failed, and stopped execution-facing states onto the shared job plane while keeping teammate state authoritative.
- [ ] 6.6 Add regression tests for teammate job projection lifecycle, waiting-permission updates, terminal transitions, and mailbox recovery invariants.

## 7. Extensibility, Stage B Freeze, And Follow-up Cleanup

- [x] 7.1 Add at least one documented non-agent executor integration path using `RuntimeConfig.job_executors` to validate that the control plane is not agent-specific.
- [x] 7.2 Add tests for custom executor registration, factory-backed executor instantiation, and explicit override of built-in executor kinds.
- [x] 7.3 Convert remaining runtime-owned direct `TaskManager` usages in `src/runtime/` to the shared job service or the explicit Stage A compatibility layer.
- [x] 7.4 Freeze Stage B compatibility by documenting that `ManagedTask` is deprecated and no longer widened for new job-plane capabilities.
- [x] 7.5 Add compatibility tests that pin legacy `TaskManager` behavior to the shared job source of truth during the frozen Stage B window.
- [x] 7.6 Update runtime architecture and integration docs to describe `job` vs `task`, executor registration, sidecar linkage, and host-consumable job APIs.
- [x] 7.7 Write the Stage C cleanup checklist that removes `RuntimeServices.task_manager`-style primary integration points after all frozen-compat exit criteria are met.
