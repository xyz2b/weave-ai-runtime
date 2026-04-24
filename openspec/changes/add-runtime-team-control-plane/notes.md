## Implementation Notes

- Team mode now has a runtime-owned split instead of overloading the mailbox shell:
  - `RuntimeTeamControlPlane` owns durable team records, leader binding, persistent member records, lifecycle authority, and leader-session private-context updates.
  - `RuntimeTeamMessageBus` owns structured direct, broadcast, and control-message envelopes plus routing metadata.
  - `PersistentTeammateOrchestrator` remains the execution substrate for teammate work items.
- The v1 frozen built-in surface is now wired into the bundled tool pack:
  - `team_create`
  - `team_spawn`
  - `team_send`
  - `team_delete`
- Public addressing stays intra-team in v1:
  - `to="leader"` resolves to the active team leader
  - `to="*"` fans out to all other active members in the caller's active team
  - any other `to` resolves against teammate `name` only inside the caller's active team
- Leader ingress now uses runtime-generated session events instead of UI-owned mutation:
  - `WAITING` leaders drain teammate collaboration input immediately by default
  - `READY` and `RUNNING` leaders queue teammate collaboration input by default
  - control-plane envelopes resolve as transcript-hidden `replay_only` / `local_only` ingress outcomes with `private_updates`
- The host bridge stays headless and additive:
  - one optional structured `team_event` sink observes lifecycle, routing, and control-plane outcomes
  - runtime correctness does not depend on any host-side team UI implementation

## Contract Tests

- `tests/test_runtime_team_mode.py`
  - team creation reuse, unique teammate naming, leader-only lifecycle authority, durable member records, deletion cleanup, structured message routing, leader ingress defaults, control-envelope replay/private handling, built-in team tool behavior, and no-sink fallback coverage
- `tests/test_teammate_orchestration.py`
  - regression coverage for the shared teammate execution substrate that team mode still reuses
- `tests/test_builtin_tools.py`
  - regression coverage that the bundled tool pack still loads and executes alongside the new `team_*` built-ins
