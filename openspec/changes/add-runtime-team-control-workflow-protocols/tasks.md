## 1. Workflow State And Authority

- [ ] 1.1 Add durable workflow record models, status enums, allowed-action helpers, and shared request/response protocol schema definitions for `permission` and `shutdown` team control workflows.
- [ ] 1.2 Implement the file-backed workflow store and the indexes needed to load workflows by `workflow_id`, team, responder, and terminal or pending state.
- [ ] 1.3 Wire a runtime-owned workflow service into runtime assembly, team control wiring, and any shared service containers so one authoritative workflow instance is used everywhere.
- [ ] 1.4 Implement recovery, deadline tracking, and terminal-state guards so pending workflows survive restart and duplicate responses cannot reopen completed workflows.
- [ ] 1.5 Add focused tests for workflow persistence, responder authority, duplicate or stale response rejection, timeout-state transitions, and shared protocol parse or serialize invariants.

## 2. Permission Workflow Gating

- [ ] 2.1 Replace the direct teammate permission passthrough in the teammate host bridge with creation of a correlated permission workflow and a waiter keyed by `workflow_id`.
- [ ] 2.2 Keep teammate snapshots and task projections in `waiting_permission` until the workflow has a valid response and any later host permission mediation has finished.
- [ ] 2.3 Continue host permission resolution only after workflow approval has been recorded, and preserve the same workflow correlation through the final permission outcome delivered back to the teammate.
- [ ] 2.4 Add regression tests for leader rejection without host permission calls, leader approval followed by host resolution, permission timeout denial, and restart recovery of pending permission waits.

## 3. Graceful Shutdown Workflow

- [ ] 3.1 Add shutdown workflow creation plus real `stopping` and `stopped` lifecycle transitions for member removal, explicit stop, and team deletion paths.
- [ ] 3.2 Teach teammate runner and drain logic to stop claiming new work once shutdown begins while allowing in-flight work to finish or close safely.
- [ ] 3.3 Wait for shutdown completion or timeout before removing teammate state or returning from team deletion, with explicit forced-cleanup fallback on timeout.
- [ ] 3.4 Add tests for idle teammate shutdown, active teammate shutdown during team deletion, timeout-driven forced cleanup, and persisted terminal shutdown state.

## 4. Leader Ingress And Workflow Response Tooling

- [ ] 4.1 Update team message routing and session ingress mapping so leader-actionable workflows become synthesized generated inputs with private workflow metadata, while non-actionable control updates remain private or replay-only and lifecycle-critical workflow requests such as shutdown are prioritized ahead of ordinary teammate chatter.
- [ ] 4.2 Propagate workflow metadata such as `workflow_id`, workflow kind, requester identity, and allowed response actions through ingress and turn execution state.
- [ ] 4.3 Add built-in `team_respond` definitions, input validation, and handler wiring against the shared workflow service, and adapt any existing runtime or host decision entrypoints so they resolve workflows through the same mutation path.
- [ ] 4.4 Reject workflow resolution attempts that try to use raw control-message sends instead of typed workflow-response surfaces.
- [ ] 4.5 Add tests for actionable leader ingress, prioritized shutdown delivery, transcript-hidden raw envelopes, authorized `team_respond` decisions, and invalid workflow-response errors.

## 5. Host Workflow Integration

- [ ] 5.1 Extend the host bridge with optional pending-workflow query and typed workflow-response surfaces backed by the shared workflow service and the same runtime-owned workflow resolver used by model-side decisions.
- [ ] 5.2 Emit structured workflow observation events for creation, update, timeout, and terminal transitions without making host callbacks authoritative for control correctness.
- [ ] 5.3 Add tests for host-side workflow query and response, no-host fallback behavior, and identical authority validation across host-driven and model-driven responders.

## 6. Docs And Contract Coverage

- [ ] 6.1 Update runtime architecture notes to document the split between workflow authority and message transport, including the shared request/response-plus-ID protocol, centralized protocol helpers, and workflow prioritization rules.
- [ ] 6.2 Document the `team_respond` tool contract, the permission gating order, and the graceful shutdown request or acknowledge or complete lifecycle.
- [ ] 6.3 Add or update change-level regression notes and contract coverage for workflow recovery, timeout behavior, leader-ingress visibility, and teardown ordering.
