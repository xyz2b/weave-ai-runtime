## 1. Team Control-Plane State

- [x] 1.1 Add durable team control-plane models for team records, leader binding, team-scoped context metadata, and persistent teammate member records.
- [x] 1.2 Add the durable indexing needed to enforce the v1 rule that one leader session can own at most one active team at a time.
- [x] 1.3 Implement the default durable team store for create, load, update, tombstone/delete, and active-team lookup by leader session.
- [x] 1.4 Implement control-plane service helpers for `team_create` with idempotent active-team reuse for an already-bound leader session.
- [x] 1.5 Implement control-plane service helpers for teammate-member registration with unique same-team `name` validation and leader-only lifecycle authority.
- [x] 1.6 Implement control-plane service helpers for member removal and full team deletion, including cleanup of leader binding and team-scoped private-context state.
- [x] 1.7 Add focused service-level tests for durable team creation, active-team reuse, unique teammate naming, leader-only lifecycle authority, member persistence, and deletion semantics.

## 2. Team Message Bus And Routing

- [x] 2.1 Add structured team-message envelope models for direct, broadcast, and control-plane message kinds with stable `message_id`, sender identity, recipient scope, and correlation metadata.
- [x] 2.2 Implement the durable team message bus publish/read primitives for same-team direct delivery and persisted routing metadata.
- [x] 2.3 Implement broadcast fan-out behavior where `to="*"` resolves to all active members of the caller's active team except the sender.
- [x] 2.4 Implement public recipient resolution rules for `to="leader"` and teammate-name addressing inside the caller's active team.
- [x] 2.5 Reject cross-team recipient resolution and other v1-invalid public addressing before routing proceeds.
- [x] 2.6 Implement the leader-ingress routing adapter that maps leader-visible collaboration messages into runtime-generated session ingress inputs.
- [x] 2.7 Implement the teammate-delivery routing adapter that maps teammate-recipient messages into work items backed by `PersistentTeammateOrchestrator`.
- [x] 2.8 Implement optional host-observation emission for routed lifecycle and control-plane events without making host delivery authoritative.
- [x] 2.9 Add routing tests for direct delivery, broadcast fan-out, sender exclusion, same-team name resolution, cross-team rejection, correlated control messages, and separation from teammate work-item storage.

## 3. Built-in Team Tools And Runtime Wiring

- [x] 3.1 Add built-in tool definitions for `team_create` and `team_delete` matching the frozen v1 request/response contract.
- [x] 3.2 Add built-in tool definitions for `team_spawn` and `team_send` matching the frozen v1 request/response contract.
- [x] 3.3 Implement built-in input validation and normalization for active-team resolution, disallowing caller-supplied `team_id` and enforcing the public `to` / `name` contract.
- [x] 3.4 Implement the `team_create` built-in handler against the runtime-owned control plane, including idempotent reuse of an existing active team for the same leader session.
- [x] 3.5 Implement the `team_spawn` built-in handler against the runtime-owned control plane, including teammate execution defaults such as `cwd`, `model`, `model_route`, `permission_mode`, `isolation`, and `max_turns`.
- [x] 3.6 Implement the `team_send` built-in handler against the structured team message bus for both direct and broadcast delivery.
- [x] 3.7 Implement the `team_delete` built-in handler against the runtime-owned control plane, including coordinated teardown of active team state.
- [x] 3.8 Wire the team control plane and team message bus into `RuntimeServices`, `RuntimeKernel`, and runtime assembly so tool execution and runtime-owned routing share the same service instances.
- [x] 3.9 Add built-in tool tests covering structured results, reused-versus-created team results, invalid team-state errors, leader-only lifecycle authority, and direct versus broadcast send behavior.

## 4. Teammate Runner Lifecycle

- [x] 4.1 Add a runtime-owned teammate runner manager that keeps persistent team members addressable while reusing `PersistentTeammateOrchestrator` as the execution substrate.
- [x] 4.2 Implement teammate-runner registration and startup during `team_spawn`, preserving stable teammate identity across multiple routed messages.
- [x] 4.3 Implement teammate message dispatch from routed team messages into orchestrator work items while preserving existing permission-bridge behavior and teammate-scoped private context.
- [x] 4.4 Implement idle retention and reuse so a teammate can return to idle after each routed execution and remain addressable for later work.
- [x] 4.5 Implement teammate shutdown and cleanup on member removal or `team_delete`, including runner-manager and orchestrator-side cleanup.
- [x] 4.6 Add regression tests for multi-message teammate reuse, idle-to-active transitions, permission-bridge continuity, shutdown cleanup, and unchanged teammate recovery invariants.

## 5. Leader Ingress And Host Integration

- [x] 5.1 Implement the leader-ingress envelope builder for leader-visible collaboration messages so they enter session ingress as runtime-generated admitted-turn inputs with preserved routing metadata.
- [x] 5.2 Implement the default `WAITING` leader-session policy: admitted team collaboration input drains immediately and resumes the leader without host re-submission.
- [x] 5.3 Implement the default `READY` leader-session policy: admitted team collaboration input is queued by default and does not auto-drain unless an explicit runtime policy enables it.
- [x] 5.4 Implement the default `RUNNING` leader-session policy: admitted team collaboration input is queued for later ordered handling and does not interrupt the active turn.
- [x] 5.5 Implement control-plane ingress handling for permission, shutdown, and similar envelopes so they resolve by default as `local_only` or `replay_only` outcomes with `private_updates`.
- [x] 5.6 Add a structured runtime-owned team-event model for host observation of lifecycle, routing, and control-plane outcomes.
- [x] 5.7 Extend the host bridge and compat adapter with one optional structured team-event sink without making it mandatory for all hosts.
- [x] 5.8 Implement fallback behavior when no host team sink is bound so routing and teardown remain correct and only structured side-channel observation is omitted.
- [x] 5.9 Add tests for waiting-session resume, ready-session queueing, running-session non-interruption, control-message private/replay outcomes, structured host event emission, and no-sink fallback behavior.

## 6. Docs And Contract Coverage

- [x] 6.1 Update runtime architecture docs to describe the split between the team control plane, the team message bus, and `PersistentTeammateOrchestrator`.
- [x] 6.2 Document the built-in `team_create`, `team_spawn`, `team_send`, and `team_delete` contracts, including the v1 addressing and authority rules.
- [x] 6.3 Document the leader-ingress defaults for `WAITING`, `READY`, and `RUNNING` sessions and the transcript-hidden handling of control-plane envelopes.
- [x] 6.4 Document the minimal headless host integration model so framework consumers know they are expected to build UI or automation on top of runtime-owned state and optional team events.
- [x] 6.5 Add or update change-level notes and contract tests that pin the headless, UI-agnostic teammate mode behavior and the frozen v1 public contract.
