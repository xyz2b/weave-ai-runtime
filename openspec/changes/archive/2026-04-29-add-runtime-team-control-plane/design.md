## Context

The runtime already has several pieces that look like a future teammate mode, but they currently stop at the execution substrate:

- `PersistentTeammateOrchestrator` already provides durable teammate registration, file-backed work queues, claim/retry/recovery, leader-mediated permission bridging, and teammate lifecycle projection.
- `SpawnMode.TEAMMATE` already exists in the shared agent execution model, but the built-in `agent` tool does not expose that spawn mode to models.
- `team_id` already propagates through runtime-private context into task lists, jobs, memory, and child execution metadata.
- `SessionController` and session ingress already provide a framework-grade path for runtime-generated inputs to become transcript messages, private updates, replay outputs, or admitted turns.

That means the missing piece is not “how to run a teammate turn.” The missing piece is the outer team control plane:

- durable team identity and membership
- a stable leader/team context
- structured teammate messaging and control messages
- a runtime-owned routing path from teammate messages into leader session ingress
- headless host integration surfaces for products that want to render or automate team activity

This change also has an explicit framework constraint: the runtime must remain headless. It cannot depend on a bundled UI store, pane manager, or frontend event reducer. Any UI should be built by framework consumers on top of runtime-owned state and event surfaces.

## Goals / Non-Goals

**Goals:**

- Add a runtime-owned team control plane above the existing teammate execution substrate.
- Keep team identity, membership, and leader binding durable and queryable without requiring a bundled UI layer.
- Add structured team messaging for teammate-to-leader and teammate-to-teammate communication, including control messages.
- Route leader-visible teammate messages through session ingress and host-facing runtime callbacks instead of UI-specific state mutation.
- Reuse `PersistentTeammateOrchestrator` for teammate execution rather than introducing a second model-execution stack.
- Use existing runtime-private context and ingress-private updates to carry team scope through sessions and delegated execution.

**Non-Goals:**

- Reproducing Claude Code's tmux/iTerm2 pane backends or any bundled terminal UI.
- Making the built-in `agent` tool the only way to create teammates in the first iteration.
- Replacing the existing teammate work queue, permission bridge, or shared agent execution core.
- Defining a rich frontend state model, renderer contract, or visual teammate experience.
- Solving every future multi-team or remote-cluster deployment problem in the first iteration.

## Decisions

### 1. Add a dedicated runtime team control plane above `PersistentTeammateOrchestrator`

The runtime will introduce a new runtime-owned service, referred to here as `RuntimeTeamControlPlane`, that owns:

- team creation and deletion
- durable team records
- leader session binding
- member registration and removal
- team-scoped runtime-private context helpers
- message routing coordination
- teammate runner lifecycle

`PersistentTeammateOrchestrator` remains the execution substrate for teammate work items. It is not promoted into the full team registry.

The intended state split is:

```text
RuntimeTeamControlPlane
  - TeamStore
  - TeamRegistry
  - TeamMessageBus
  - TeamMessageRouter
  - TeammateRunnerManager

PersistentTeammateOrchestrator
  - teammate registration
  - work-item queue
  - claim/retry/recovery
  - permission bridge
  - active/idle projection
```

Why:

- current teammate orchestration already solves execution durability well, but it has no concept of leader session attachment, team deletion, or structured peer messaging
- overloading it with every team concern would merge control-plane state and execution state into one service
- a separate team control plane matches the runtime's existing architecture style, where session ingress, jobs, task lists, and child observability are separate but cooperating planes

Alternatives considered:

- Expand `PersistentTeammateOrchestrator` until it owns all team semantics. Rejected because it would collapse team registry, message routing, and execution durability into one abstraction with conflicting responsibilities.
- Store team state only in session metadata. Rejected because teammates must outlive a single foreground turn and remain addressable even when the leader session is idle or detached.

v1 scope lock:

- one leader session may own at most one active team at a time
- `team_create` is idempotent for that leader binding and returns the existing active team instead of creating a second concurrent team
- a deleted team releases that leader binding so the same session may later create a new team

### 2. Keep the team message bus separate from the teammate work queue

The runtime will add a dedicated `TeamMessageBus` for structured collaboration messages. It will not reuse the existing teammate work queue mailbox as the canonical bus for all collaboration traffic.

The split is intentional:

- `TeamMessageBus` owns collaboration and control messages
- `PersistentTeammateOrchestrator` owns execution work items

The planned routing model is:

```text
team_send / runtime control event
        |
        v
  TeamMessageBus (durable message envelopes)
        |
        v
  TeamMessageRouter
    |- leader recipient   -> Session ingress / host event
    `- teammate recipient -> teammate work item via orchestrator
```

This means a teammate-targeted plain message is first a structured team message, then routed into an execution work item for that teammate. A leader-targeted message is routed into session ingress instead of into a teammate execution slot.

Why:

- the existing work queue mailbox has claim/heartbeat/retry semantics that are correct for execution work items but awkward for broadcasts, direct control messages, and leader-side routing
- a separate bus gives the runtime one canonical collaboration protocol without forcing the leader session to pretend it is just another teammate worker
- host integrations can observe team messages and control envelopes without scraping teammate execution files

Alternatives considered:

- Reuse the existing teammate mailbox for all team traffic. Rejected because it entangles collaboration messages with execution retry and run-linkage mechanics.
- Route every teammate message directly into orchestrator work items. Rejected because it removes the opportunity for host observation and makes leader delivery asymmetrical.

### 3. Use dedicated `team_*` built-in tools in v1 instead of overloading `agent`

The first iteration will add dedicated built-ins:

- `team_create`
- `team_spawn`
- `team_send`
- `team_delete`

The built-in `agent` tool will remain focused on generic subagent delegation for now. Internally, team-spawned members still reuse `SpawnMode.TEAMMATE`, but that remains an internal execution choice rather than the public model contract of `agent`.

Why:

- `agent` currently has a clean delegation contract around sync/background child execution, and expanding it immediately would create migration and validation complexity
- a framework-grade team abstraction is clearer when the model explicitly enters team operations through team-specific tools
- team creation, deletion, and team-scoped messaging are not semantically the same as generic child delegation

Alternatives considered:

- Extend `agent` with `spawn_mode=teammate` in the first iteration. Rejected because it overloads a generic subagent tool with team lifecycle semantics before the runtime has a stable team abstraction.
- Expose only one monolithic `team` tool. Rejected because the runtime already favors narrow, typed built-ins over one “do everything” tool surface.

Future compatibility note:

- once the team control plane is stable, the runtime may add an alias path where `agent` can request team-member spawn under explicit policy, but that is intentionally deferred

v1 public contract freeze:

- built-in `team_*` tools resolve the active team from runtime-private context and leader binding; model callers do not provide `team_id`
- `team_create`, `team_spawn`, and `team_delete` are leader-only operations
- teammates may use `team_send`, but they may not create nested teams, spawn new teammates, or delete the team
- `team_send` is intra-team only; cross-team routing is rejected in v1

### 4. Team routing is headless and runtime-owned, not UI-owned

The runtime will introduce a `TeamMessageRouter` that consumes team messages and chooses one of three delivery paths:

- `session_ingress`: for leader-visible teammate messages that should become runtime-generated session input
- `host_event`: for structured lifecycle or control messages that a host may want to render or automate
- `teammate_work_item`: for teammate recipients that should process a message through the existing teammate execution path

The leader path will reuse `SessionController.submit_runtime_event(...)` and session ingress metadata rather than writing transcript text directly.

Why:

- the runtime already has a strong ingress pipeline that separates normalized messages, replay outputs, and private updates
- headless frameworks should expose events and callbacks, not embed React-like state mutation or UI inbox reducers
- direct transcript injection would bypass the runtime's established admission and private-context boundaries

Alternatives considered:

- Emit only notifications and let hosts re-inject messages themselves. Rejected because routing collaboration messages into the leader session is a runtime responsibility, not a UI concern.
- Encode teammate messages as transcript-only text without ingress metadata. Rejected because it loses routing semantics and makes filtering or automation harder.

Leader ingress default policy:

- leader-targeted collaboration messages are submitted as runtime-generated ingress inputs with explicit `admission_kind=admit_turn`
- if the leader session is `WAITING`, the runtime drains that ingress input by default so the leader can resume from teammate input without a host re-prompt
- if the leader session is `READY`, the runtime queues the admitted input by default and does not auto-drain unless an explicit runtime policy enables eager resume
- if the leader session is `RUNNING` or otherwise already executing a turn, the runtime queues the admitted input for later ordered handling and does not interrupt the active turn solely because a teammate message arrived
- control-plane envelopes that are not meant to become model-visible collaboration text resolve by default as `local_only` or `replay_only` ingress outcomes with `private_updates`, rather than as transcript-visible user text

### 5. Team context propagation will reuse `RuntimePrivateContext` and ingress private updates

The runtime will standardize a small team-scoped private-context extension set, carried through session ingress and child execution metadata:

- `team_id`
- `team_role`
- `team_member_id`
- `leader_session_id`
- optional team-scoped routing metadata such as current control-plane source or message correlation

The leader session will receive this context through a local-only or host-generated ingress update at team creation time. Teammate execution requests will continue to use execution metadata and permission-context metadata so that `team_id` and teammate identity flow into tools, memory, jobs, and task-list resolution automatically.

Why:

- the runtime already has a durable path for session-private state via ingress `private_updates`
- `team_id` is already meaningful in existing runtime services, so a new parallel context carrier would be redundant
- this approach preserves the prompt/private boundary that the runtime already treats as a core architectural invariant

Alternatives considered:

- Keep team context only in the team registry and look it up globally on every tool call. Rejected because current runtime services already consume private-context extensions locally and predictably.
- Encode team scope in prompt text. Rejected because it leaks control-plane state into model-visible context.

### 6. Teammate membership is persistent, but teammate execution stays work-item-driven

The team control plane will manage persistent teammate membership and a runtime-owned runner loop per teammate. That runner loop is responsible for:

- observing routed teammate deliveries
- ensuring the teammate remains addressable across multiple messages
- draining teammate work items through the existing orchestrator
- returning the teammate to idle after each execution

The teammate is therefore persistent as a runtime identity and runner slot, even though individual executions still happen as separate work items through the shared execution core.

Why:

- this reuses the strongest part of the current runtime instead of building a second long-lived model loop from scratch
- the existing teammate-orchestration contract already models `idle`, `active`, `waiting_permission`, and recovery across multiple work items
- it gives the framework persistent teammate behavior without requiring a UI-coupled in-process runner design

Alternatives considered:

- Rebuild teammates as fully separate long-lived session controllers. Rejected for v1 because it duplicates lifecycle machinery the orchestrator already provides.
- Treat each teammate message as a fresh one-shot teammate identity. Rejected because it breaks the persistent teammate model the runtime already introduced.

### 7. Host integration surfaces are additive and optional

This change will not require every host adapter to implement a new mandatory UI protocol. Instead, the runtime will add optional team-facing host integration surfaces, likely through compatibility callbacks or a capability-detected extension, for:

- team lifecycle events
- structured team message/control events
- teammate termination or cleanup notices

If a host does not bind those optional surfaces, the runtime still functions. Team routing remains runtime-owned; the host simply receives less structured side-channel observation.

Why:

- the framework must stay usable in headless and embedded environments
- widening the mandatory `HostRuntime` protocol would create unnecessary breakage for hosts that do not care about team collaboration
- optional event surfaces align with the runtime's additive control-plane style

Alternatives considered:

- Require a mandatory `emit_team_event(...)` method on every host. Rejected because the base host bridge should remain minimal and backward-compatible where possible.
- Reuse only generic notifications. Rejected because team lifecycle and control events need richer structure than a display-oriented notification string.

v1 host-bridge shape:

- the minimal host-facing integration surface is one optional structured team-event sink rather than a wide callback family
- a compat adapter may expose that as something like `team_event_sink(event)` while a typed host may expose it as `emit_team_event(event)`
- state querying remains a runtime/team-control-plane concern and is not pushed into host callbacks; the sink is for observation, rendering, and automation side effects
- the common event envelope should include stable fields such as `event_id`, `event_type`, `team_id`, `leader_session_id`, `occurred_at`, and optional correlation identifiers like `member_id`, `message_id`, or `correlation_id`

## Implementation Appendix

### A. `team_*` tool request/response contract is frozen in v1

To avoid re-deciding the public surface during implementation, the v1 built-in contract is:

- all `team_*` tools resolve the active team from the caller's runtime-private team context
- no v1 `team_*` tool accepts caller-supplied `team_id`
- one leader session may own only one active team at a time
- `team_create` reuses the existing active team for that leader and returns `created=false` instead of creating a second team
- teammate `name` values are required and must be unique within a team
- teammate selection for public sends is by reserved target token or teammate `name`, not by opaque runtime-only IDs

`team_create`

`input_schema`

```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"}
  },
  "additionalProperties": false
}
```

`output_schema`

```json
{
  "type": "object",
  "properties": {
    "team_id": {"type": "string"},
    "leader_session_id": {"type": "string"},
    "name": {"type": ["string", "null"]},
    "created": {"type": "boolean"}
  },
  "required": ["team_id", "leader_session_id", "name", "created"],
  "additionalProperties": true
}
```

`team_spawn`

`input_schema`

```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "agent": {"type": "string"},
    "cwd": {"type": "string"},
    "model": {"type": "string"},
    "model_route": {"type": "string"},
    "permission_mode": {
      "type": "string",
      "enum": [
        "default",
        "plan",
        "acceptEdits",
        "bypassPermissions",
        "dontAsk",
        "auto",
        "bubble"
      ]
    },
    "isolation": {"type": "string", "enum": ["none", "worktree", "remote"]},
    "max_turns": {"type": "integer", "minimum": 1}
  },
  "required": ["name", "agent"],
  "additionalProperties": false
}
```

`output_schema`

```json
{
  "type": "object",
  "properties": {
    "team_id": {"type": "string"},
    "member_id": {"type": "string"},
    "name": {"type": "string"},
    "agent": {"type": "string"},
    "status": {"type": "string"}
  },
  "required": ["team_id", "member_id", "name", "agent", "status"],
  "additionalProperties": true
}
```

`team_send`

`input_schema`

```json
{
  "type": "object",
  "properties": {
    "to": {"type": "string"},
    "message": {"type": "string"}
  },
  "required": ["to", "message"],
  "additionalProperties": false
}
```

`team_send` target resolution rules:

- `to="leader"` routes to the active team leader
- `to="*"` broadcasts to all active team members except the sender
- any other `to` value resolves against a unique teammate `name` in the caller's active team
- caller-supplied cross-team selectors are not part of the v1 surface

`output_schema`

```json
{
  "type": "object",
  "properties": {
    "team_id": {"type": "string"},
    "message_id": {"type": "string"},
    "to": {"type": "string"},
    "delivery_count": {"type": "integer", "minimum": 0},
    "queued": {"type": "boolean"}
  },
  "required": ["team_id", "message_id", "to", "delivery_count", "queued"],
  "additionalProperties": true
}
```

`team_delete`

`input_schema`

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

`output_schema`

```json
{
  "type": "object",
  "properties": {
    "team_id": {"type": "string"},
    "deleted": {"type": "boolean"}
  },
  "required": ["team_id", "deleted"],
  "additionalProperties": true
}
```

Authority rules:

- only the leader may invoke `team_create`, `team_spawn`, or `team_delete`
- leader and teammates may invoke `team_send`
- teammates cannot create nested teams or spawn more teammates in v1

### B. Leader ingress admission defaults are frozen in v1

The default delivery policy for leader-targeted team traffic is:

| Leader session status | Collaboration message default | Drain default |
|-----------------------|-------------------------------|---------------|
| `WAITING` | submit as `admit_turn` | `true` |
| `READY` | submit as `admit_turn`, queue for later execution | `false` |
| `RUNNING` | submit as `admit_turn`, queue for later execution | `false` |

Additional rules:

- queued leader collaboration messages retain their ingress private context and correlation metadata until executed
- control-plane messages such as permission mediation, shutdown, or internal routing notices default to `local_only` or `replay_only`
- those control-plane messages are transcript-hidden by default and surface structured replay or host events instead of raw transcript-visible text
- any eager auto-drain for `READY` sessions is an explicit policy override, not the v1 default

### C. Minimal headless host bridge is frozen in v1

The runtime does not define a UI protocol. The minimal host bridge for team mode is:

- one optional structured sink for team events
- runtime-owned query and mutation APIs remain outside that sink
- hosts that ignore the sink lose only structured observation, not runtime correctness

Recommended common team-event envelope:

```json
{
  "event_id": "string",
  "event_type": "string",
  "team_id": "string",
  "leader_session_id": "string",
  "occurred_at": "string",
  "member_id": "string | null",
  "message_id": "string | null",
  "correlation_id": "string | null",
  "payload": {}
}
```

## Risks / Trade-offs

- [Two durable mail systems increase complexity] → Mitigation: keep their responsibilities strict and narrow, with explicit documentation that the team bus is for collaboration/control and the teammate mailbox is for execution work items.
- [Dedicated `team_*` tools may feel redundant next to `agent`] → Mitigation: keep team operations explicit in v1 and document a future alias path only after the team abstraction stabilizes.
- [Leader routing may produce surprising turn admission if over-eager] → Mitigation: use ingress policy and session-state checks so routed messages can be queued, replay-only, or admitted depending on explicit runtime policy.
- [Optional host hooks can lead to uneven product behavior across embeddings] → Mitigation: make runtime-owned state and routing authoritative, and treat host hooks as observability extensions rather than required orchestration logic.
- [Persistent teammate runner management adds lifecycle edge cases] → Mitigation: reuse orchestrator recovery, lifecycle states, and existing teammate identity guarantees instead of inventing a new lifecycle model.

## Migration Plan

1. Add the runtime team control-plane service, durable team records, and team context helpers without changing teammate execution semantics.
2. Add `team_*` built-ins and leader/team state wiring so a lead session can create, use, and delete a team under runtime-owned contracts.
3. Add the structured team message bus and routing layer, including teammate delivery via orchestrator work items and leader delivery via session ingress.
4. Add optional host integration surfaces for structured team lifecycle and control events.
5. Update architecture docs and tests to treat teammate orchestration as the execution substrate and the new team control plane as the collaboration/control layer.

Rollback strategy:

- `team_*` tools can be removed from tool pools without disturbing the underlying teammate execution substrate
- hosts that do not bind optional team integration callbacks continue to function
- routed leader-message admission can be disabled conservatively if needed while preserving durable team records and teammate execution

## Open Questions

- None for the first iteration. The initial built-in surface is `team_create`, `team_spawn`, `team_send`, and `team_delete`, and the first host integration model is additive optional event observation rather than bundled UI behavior.
