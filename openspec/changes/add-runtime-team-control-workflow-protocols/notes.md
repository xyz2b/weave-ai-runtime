## Implementation Notes

- Runtime team control now has a three-layer split instead of letting mailbox traffic carry workflow authority:
  - `RuntimeTeamWorkflowService` owns durable workflow state, deadlines, responder validation, and terminal outcomes.
  - `RuntimeTeamMessageBus` carries request / response envelopes keyed by the same `workflow_id`, but transport delivery is not the source of truth for pending or terminal state.
  - `PersistentTeammateOrchestrator` remains the execution substrate that blocks on permission workflows and drains or stops teammate work.
- Permission and shutdown reuse one shared request/response-plus-ID contract:
  - `permission` and `shutdown` both use a stable `workflow_id` across the durable record, control envelopes, ingress metadata, and host/runtime response surfaces.
  - centralized parse / serialize / summary helpers live in `src/runtime/team_workflows.py`.
- Leader- and host-side workflow responses now terminate at the same runtime-owned resolver path:
  - `team_respond` is the model-facing typed mutation surface.
  - host query / response operations call the same workflow service instead of fabricating raw control messages.
- Workflow ordering and lifecycle rules are explicit:
  - teammate permission requests stay blocked until workflow approval is recorded and any later host permission step finishes.
  - shutdown follows request -> acknowledge -> complete when graceful stop succeeds, and request -> forced_close when the deadline expires first.
  - actionable shutdown ingress is prioritized ahead of ordinary teammate chatter, while raw workflow envelopes stay transcript-hidden by default.

## Contract Tests

- `tests/test_team_workflows.py`
  - file-backed workflow persistence/index coverage by `workflow_id`, team, responder, and pending vs terminal state
  - request / response protocol round-tripping and terminal duplicate or stale response rejection
  - permission timeout behavior, leader-ingress workflow visibility, transcript-hidden raw envelopes, typed `team_respond` decisions, and raw response transport rejection
  - idle teammate shutdown completion ordering and active shutdown timeout-driven forced cleanup during team deletion
  - host-side workflow query / response, additive no-host fallback behavior, and shared validation across host-driven and model-driven responders
- `tests/test_teammate_orchestration.py`
  - workflow recovery and waiting-permission state continuity across teammate restart
- `tests/test_runtime_team_mode.py`
  - correlated control-envelope routing, leader/session visibility defaults, and unchanged mailbox/team-mode behavior outside the new workflow authority layer
