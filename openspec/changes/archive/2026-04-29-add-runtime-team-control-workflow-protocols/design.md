## Context

The runtime already has the transport primitives needed for teammate coordination, but it does not yet have an authoritative workflow layer for negotiated control actions.

Today:

- `TeamMessageBus` can emit structured control messages with a correlated `correlation_id`.
- teammate permission waits already project `waiting_permission` state.
- teammate lifecycle enums already include `stopping` and `stopped`.

Those pieces are not yet composed into real control workflows:

- teammate permission requests emit a correlated control message, but the runtime still immediately calls the host permission bridge, so the leader notification is observational rather than authoritative
- leader-targeted control messages currently resolve through ingress as private or replay-only host events, so the leader cannot act on them as first-class pending requests
- teammate removal and team deletion still cancel the teammate drain task and delete state immediately instead of waiting for a graceful stop protocol
- correlation currently lives on transport envelopes, not on a workflow record that can own timeout, recovery, authority, and terminal-state rules

This change must stay within the runtime's headless architecture:

- the runtime remains the source of truth for team control state
- `TeamMessageBus` remains the delivery transport, not the workflow authority
- host integrations stay optional and additive
- autonomous task pickup, idle polling, and identity reinjection remain out of scope for this change

The Claude Code source study is useful here as a design reference, not as an implementation target. It validates three patterns we do want:

- one request/response plus unique-ID contract reused across negotiated actions
- centralized schema construction and parsing for control protocols
- reuse of existing leader or host decision surfaces instead of raw control-message authoring

It also reinforces one pattern we do not want:

- workflow authority living only in mailbox transport instead of in runtime-owned state

## Goals / Non-Goals

**Goals:**

- Add a runtime-owned workflow layer for negotiated team control actions with stable workflow identity and durable lifecycle state.
- Standardize approval and shutdown on one shared request/response plus stable-ID protocol shape with centralized typed schema helpers.
- Make teammate permission mediation truly leader-mediated by blocking host permission continuation on an explicit workflow decision.
- Add a graceful shutdown workflow for teammate stop operations, including real `stopping` and `stopped` transitions before teardown.
- Surface leader-actionable workflow requests as runtime-generated ingress inputs with typed metadata rather than replay-only notifications.
- Expose typed workflow response surfaces for both models and hosts without requiring raw control-message fabrication, and route all responders through the same runtime validation path.
- Prioritize high-importance control workflows such as shutdown requests so they are not starved behind ordinary teammate chatter.
- Define timeout and recovery behavior so pending workflows survive restart and terminate predictably.

**Non-Goals:**

- Adding the idle poller, task-board self-claiming, or any autonomous pickup behavior.
- Adding identity reinjection or context-compaction recovery behavior.
- Replacing `TeamMessageBus` or `PersistentTeammateOrchestrator` with a new execution substrate.
- Introducing mandatory UI-owned host callbacks or a bundled frontend state model.
- Generalizing the first iteration beyond approval and shutdown workflows.

## Decisions

### 1. Add a dedicated runtime-owned team control workflow service and store

The runtime will introduce a `RuntimeTeamControlWorkflowService` backed by a durable workflow store. Each workflow record is keyed by a stable `workflow_id` and stores:

- `workflow_id`
- `team_id`
- `workflow_kind` such as `permission` or `shutdown`
- requester and expected responder identity
- current status and allowed next actions
- request payload and response payload history
- linked message or ingress metadata
- created, updated, and deadline timestamps

The workflow record becomes the authoritative source of truth for pending and terminal workflow state. Message-bus envelopes continue to carry delivery details, but they no longer define whether a control action is pending, timed out, approved, rejected, or completed.

Why:

- delivery state and workflow state are different concerns
- timeout and recovery need a durable record that is independent from whether a specific control envelope has already been routed
- leader tools and host integrations need one stable object to query and mutate

Alternatives considered:

- Make `TeamMessageBus` the workflow source of truth. Rejected because message delivery state is not sufficient to encode authority, deadlines, or terminal outcomes.
- Store workflow state only inside teammate snapshots. Rejected because leader-facing approval workflows and team-level shutdown coordination outlive a single teammate snapshot.

### 2. Reuse one stable ID across workflow state and correlated transport

The runtime will standardize on one stable `workflow_id` for the entire request/response interaction. When control messages or ingress events are emitted for that workflow, they reuse the same identifier as the transport correlation key.

This produces one correlation chain across:

- the durable workflow record
- team control envelopes
- leader ingress metadata
- host bridge events
- teammate wait state

Why:

- the user-facing protocol is explicitly “request/response plus one unique ID”
- using separate workflow and transport IDs would add mapping complexity without improving authority or recovery

Alternatives considered:

- Separate `workflow_id` and per-envelope correlation IDs. Rejected because it would complicate response routing and timeout recovery for no clear v1 benefit.

### 3. Centralize workflow protocol schemas and helpers

Approval and shutdown transports will share one runtime-owned protocol shape: typed request and response envelopes that all carry the same workflow identity semantics while allowing workflow-kind-specific payloads.

The runtime will keep schema validation, serialization, parsing, and summary generation in one centralized workflow-protocol module. Workflow services, ingress synthesis, built-in tools, and host bridges all consume those shared helpers instead of inventing local ad hoc envelope formats.

Why:

- negotiated control actions should differ by payload and authority, not by unrelated wire-shape drift
- centralized schema helpers make future must-negotiate actions easier to add without re-solving correlation and parsing rules
- keeping summary generation with protocol helpers makes it easier to synthesize concise leader-facing requests without leaking raw transport into transcript-visible text

Alternatives considered:

- Let each workflow kind define its own message shapes independently. Rejected because it encourages protocol drift and duplicate parser logic.
- Keep schema logic inside individual tools or services. Rejected because workflow transport is a shared contract, not a local implementation detail.

### 4. Permission mediation becomes a two-stage workflow gated by leader decision

When a teammate reaches a privileged step:

1. the runtime creates a `permission` workflow record and moves the teammate into `waiting_permission`
2. the runtime emits correlated control transport and a leader-actionable ingress request
3. the teammate remains blocked on that workflow
4. only after an authorized leader or host workflow responder approves the workflow may the runtime continue to any required host permission request
5. the final outcome of the workflow reflects both the leader decision and any later host permission result

This keeps host policy intact while making the leader decision authoritative for team coordination.

Why:

- the current implementation notifies the leader but still lets the host bridge decide immediately
- “leader-mediated approval” only becomes real when leader approval is a gate, not a side-channel notification
- some approvals still require host enforcement, so the design must support a post-leader host-permission stage

Alternatives considered:

- Keep the current direct host permission call and treat leader messages as observational. Rejected because it does not satisfy negotiated team approval semantics.
- Replace host permission completely with leader approval. Rejected because the runtime still needs to respect host-level permission policy.

### 5. Shutdown uses a graceful request/acknowledge/complete workflow before cleanup

Teammate removal, explicit stop, and team deletion will all route through a `shutdown` workflow.

The shutdown protocol is:

1. the runtime creates a shutdown workflow and marks the targeted teammate `stopping`
2. the teammate stops claiming new work
3. the runtime or teammate acknowledges the request once the stop has been accepted into the runner lifecycle
4. the teammate finishes or safely closes current work
5. the shutdown workflow reaches `completed`, the teammate transitions to `stopped`, and cleanup proceeds
6. if the deadline expires first, the workflow becomes terminal with a timeout or forced-close outcome and the runtime performs forced cleanup

Member removal and team deletion wait for workflow completion or timeout before returning.

Why:

- immediate runner cancellation can leave half-finished work and inconsistent teammate state
- the existing lifecycle enum already anticipates `stopping` and `stopped`, but those states are not meaningful until stop requests become a protocol
- autonomous idle shutdown later depends on the same graceful stop machinery

Alternatives considered:

- Cancel the runner immediately and clean up state synchronously. Rejected because it can interrupt in-flight work without a defined handoff or terminal record.
- Require the teammate model to handle all shutdown semantics itself. Rejected because stop authority and cleanup timing are runtime concerns, not prompt-only conventions.

### 6. Actionable leader workflow requests enter the leader session as synthesized ingress inputs

Leader-actionable workflows will no longer appear only as replay-only control notifications. Instead, the runtime will synthesize a leader-facing ingress input that contains:

- a concise human-readable summary of the workflow request
- the `workflow_id`
- the workflow kind
- requester identity
- allowed response actions

The raw control envelope remains private runtime metadata by default. Non-actionable control updates, acknowledgements, and terminal-state notifications continue to prefer private or replay-only ingress outcomes.

Control workflows that can block lifecycle safety, especially shutdown requests, are routed ahead of ordinary teammate chatter when the runtime chooses what actionable control input to surface next. This prioritization applies to runtime control delivery and ingress synthesis, not to generic teammate messaging semantics.

Why:

- the leader needs an actionable request, not just an observed control event
- the runtime already has structured ingress for generated inputs and private metadata
- raw control envelopes are transport artifacts and should not leak into transcript-visible history by default
- shutdown and approval coordination should not be delayed indefinitely behind lower-priority conversational traffic

Alternatives considered:

- Append raw control envelopes to transcript text. Rejected because it leaks protocol transport into model-visible history and weakens routing semantics.
- Keep all control traffic replay-only. Rejected because the leader would still lack a first-class workflow request to act on.
- Treat workflow traffic and ordinary teammate chatter as identical FIFO ingress. Rejected because lifecycle-critical control requests can be starved behind low-value chatter.

### 7. Add typed response surfaces instead of fabricating control messages

The built-in runtime pack will add a typed workflow-response tool, named `team_respond`, that resolves a pending workflow by `workflow_id` and response action. Hosts get equivalent runtime-owned query and mutation surfaces for workflow observation and resolution.

Authority is derived from runtime team role and workflow state:

- leaders may resolve approval workflows
- targeted teammates may acknowledge or complete shutdown workflows
- hosts may resolve workflows only through the same runtime validation path

Existing leader or host decision surfaces should adapt into this same resolver path rather than maintaining a parallel approval queue or bespoke control-response mechanism. The runtime may expose multiple front doors, but they must terminate at one shared workflow mutation service.

The runtime will reject attempts to resolve workflows by sending raw ad hoc control messages through `team_send`.

Why:

- raw message composition is the wrong API for protocol state mutation
- typed response surfaces allow authority checks, state-machine validation, and structured results
- one shared runtime mutation path keeps model-driven and host-driven decisions consistent
- reusing existing decision surfaces reduces product-specific duplication while preserving one authoritative control path

Alternatives considered:

- Reuse `team_send` for approval and shutdown responses. Rejected because it bypasses typed validation and keeps transport as the protocol API.
- Add a host-only response API and no model-side tool. Rejected because approval workflows are intended to be leader-actionable inside the runtime itself.

### 8. Host workflow participation remains optional and additive

Hosts may observe pending workflows and submit typed responses, but the runtime continues to own workflow state, workflow timers, and final teammate lifecycle transitions.

This means:

- model-driven leader workflows work even without host support
- hosts can reconnect and query current pending workflows from runtime-owned state
- no host callback becomes the required source of truth for whether a workflow is pending or resolved

Why:

- the framework must remain headless and reusable across products
- host availability cannot be required for correctness of workflow coordination

Alternatives considered:

- Make hosts the mandatory approval and shutdown authority. Rejected because it would move runtime control semantics into product-specific integration code.

## Risks / Trade-offs

- [Workflow state duplicates some transport metadata] -> Keep the workflow record limited to decision-critical state and link back to emitted envelopes by `workflow_id` and message IDs.
- [Leader approval can still be followed by host denial] -> Model the permission workflow with a distinct post-leader host-permission stage and preserve the final outcome source in workflow state.
- [Graceful shutdown can delay member removal or team deletion] -> Require per-workflow deadlines and a force-cleanup timeout policy.
- [Actionable workflow ingress can add model-visible noise] -> Admit only workflows that require leader action and keep non-actionable control traffic private or replay-only by default.
- [Concurrent responders could race to resolve the same workflow] -> Use workflow-store compare-and-swap or equivalent terminal-state guards so only the first valid response wins.

## Migration Plan

1. Add the workflow store and service under a new runtime-owned namespace so existing team and teammate records remain unchanged.
2. Switch teammate permission mediation to create and wait on workflow records before any host permission call continues.
3. Switch teammate removal and team deletion to create shutdown workflows and wait for terminal outcomes before cleanup.
4. Add `team_respond` plus host-facing workflow query and response surfaces against the same workflow service.
5. Add regression coverage for restart recovery, timeout handling, and unchanged non-workflow message delivery.

No existing persisted team or teammate data requires migration. Existing teams can start with an empty workflow store. If rollout must be reversed, the runtime can ignore pending workflow records and fall back to the prior direct permission and teardown paths while leaving the new workflow files inert.

## Open Questions

- No design blockers remain for this change. Implementation may choose the exact runtime service and file-layout names as long as the workflow authority, ingress, and graceful-shutdown semantics defined above are preserved.
