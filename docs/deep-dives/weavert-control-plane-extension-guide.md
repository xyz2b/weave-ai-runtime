# WeaveRT Control-Plane and Hook Integration

> Documentation note: This file remains a deep-dive reference for control-plane extension. Start with `docs/guides/extend-the-control-plane.md`, `docs/guides/bind-a-host.md`, and `docs/guides/register-hooks.md`; use `docs/concepts/hosts-permissions-memory.md` for the conceptual boundary layer.

This reference keeps the control-plane boundary ledger: host ownership, permissions and elicitation, HookBus versus context contributors, refresh semantics, and compatibility posture.

Primary docs path:

- Host binding -> `docs/guides/bind-a-host.md`
- Control-plane overview -> `docs/guides/extend-the-control-plane.md`
- Hook authoring -> `docs/guides/register-hooks.md`
- Concept boundary -> `docs/concepts/hosts-permissions-memory.md`

Use this page when you need the finer ownership rules rather than a runnable tutorial.

## 1. Separate two hook-shaped surfaces

One of the most important runtime distinctions is:

### 1.1 Event hooks

These are `HookBus` phases.
They are:

- event-driven
- phase-based
- payload-oriented
- consumed through hook effects

Typical examples:

- `PreToolUse`
- `PostToolUse`
- `PreModelRequest`
- `Stop`
- `Elicitation`

### 1.2 Context contributors

These are package-owned pre-request sidecars.
The canonical path is:

- `PackageContribution.context_contributors`
- `RuntimeServices.context_contributor_execution_plan()`

They are:

- not an event bus
- executed during request assembly
- able to contribute prompt, private, or diagnostics data

Compatibility adapter surfaces such as `RuntimeServices.hooks.collect()` or `RuntimeServices.memory.collect()` may still exist, but they are not the preferred modern abstraction.

Rule of thumb:

- use hooks when reacting to runtime phases
- use contributors when shaping request context before the model call

## 2. Host is the formal control-plane boundary

If your system is a real interactive host, the formal runtime-side contract is `HostRuntime`.

The host owns:

- lifecycle presentation
- approvals and elicitation UX
- notifications and turn-event rendering
- app-local shell or UI behavior

The runtime still owns:

- session and turn control flow
- permission evaluation triggers
- elicitation triggers
- tool, skill, and agent orchestration

Recommended binding path:

- assemble a runtime
- bind a host
- interact through grouped bound surfaces such as `bound.prompts`, `bound.sessions`, `bound.hooks`, `bound.inspection`, and `bound.work`

Lifecycle ordering should remain:

1. host startup
2. host ready
3. session use inside the bound scope
4. session cleanup
5. host shutdown

Session cleanup should not implicitly shut down the host itself.

## 3. Permission and elicitation boundaries

Permissions and elicitation belong to the control plane, not to prompt prose.

### 3.1 Permission

Permission is the right seam when:

- a tool or workflow must be explicitly mediated
- host or deployment policy must stay visible
- side effects should remain auditable

Keep these separate:

- runtime decides that mediation is needed
- host may decide how the interaction is rendered
- the decision record should stay explicit and inspectable

### 3.2 Elicitation

Elicitation is the right seam when the runtime needs structured human input rather than just approval.

It belongs on the control plane because:

- the runtime should not fake structured human input with prompt-only conventions
- the host may present the question in different ways
- the response should remain part of formal runtime control flow

## 4. HookBus contract

For the full low-level hook model, use `weavert-hook-configuration-platform.md`.
At this control-plane level, the key points are:

### 4.1 Public phases are explicit

Stable public phases should be preferred.
Advanced phases exist, but they are not the default portability promise.

### 4.2 Registration source affects ownership

The same hook model may come from:

- runtime config
- bound host
- session API
- turn API
- skill hooks

The difference is not "different hook types."
The difference is ownership, lifecycle, and activation scope.

### 4.3 Stop and recovery are formal control flow

`Stop` is not just an event sink.
It can halt continuation and preserve recoverable state.
`RecoveryDecision` is the formal continuation path.

This makes it the correct seam for:

- approval gates
- continue-after-failure flows
- controlled resume behavior

### 4.4 External handlers are not the default safe surface

Callback hooks are the stable public default.
External handler kinds may exist, but they require explicit policy allowance and should not be treated as the baseline integration path.

## 5. Skill hooks versus agent hooks

Current boundary:

- skill hooks are the mature definition-level hook path
- agent-owned hooks are not the ordinary recommended v1 surface
- default assembly rejects agent-owned hooks
- compatibility modes may still tolerate historical shapes, but that is not the forward path

If you need reusable hook behavior packaged with workflow logic, prefer skill hooks.

## 6. Context-contributor channel boundaries

Context contributors should preserve three channels:

- prompt-visible context
- runtime-private context
- diagnostics

Do not collapse all three into one undifferentiated payload.

This separation matters because:

- prompt-safe context is model-visible
- private context is runtime-only
- diagnostics should help explain what happened without becoming prompt input

Compaction also remains a dedicated control-plane subsystem rather than a generic contributor blob.

## 7. Job, work, and refresh boundaries

### 7.1 Job plane

Background work should converge on the shared job plane rather than ad hoc task-specific helpers.

Treat these as canonical:

- `RuntimeServices.job_service`
- bound-host work surfaces
- job-oriented built-ins such as `job_get`, `job_list`, and `job_stop`

`TaskManager` may still exist as a compatibility facade, but it should not become the new authoritative dependency.

### 7.2 Tool refresh

Use `tool_refresh_callback` when the visible capability pool truly depends on changing session or environment conditions.

Do not use refresh as a substitute for:

- ordinary static discovery
- package composition
- clearer capability boundaries

## 8. Package-owned control-plane contracts

When a package participates in the control plane, prefer protocol surfaces over ad hoc fields.

Typical canonical paths include:

- context contributors
- invocation providers
- capability lookup
- host-facet lookup
- generic host extension events

This keeps package-owned runtime behavior discoverable without expanding mandatory host or runtime interfaces for each package family.

## 9. Stability guidance

### 9.1 Safer to depend on

- `HostRuntime` / `BoundHostRuntime`
- stable public hook phases
- skill hooks
- context contributors
- permission and elicitation services
- job service and bound work surfaces

### 9.2 Depend on more carefully

- advanced hook phases
- external hook handlers
- compatibility adapter collection surfaces
- compatibility-only facades such as `TaskManager`

### 9.3 Avoid treating as primary public contract

- agent-owned hooks
- internal-only phases
- package-specific ad hoc fields on core runtime objects

## 10. Recommended layering for integrators

Use this order:

1. host boundary for lifecycle and UX
2. permission and elicitation for mediation
3. hooks for lifecycle reaction
4. context contributors for pre-request shaping
5. refresh only when capability visibility must change dynamically

That order keeps orchestration runtime-owned while still exposing meaningful control-plane seams.

## 11. Related documents

- `docs/guides/extend-the-control-plane.md`
- `docs/guides/bind-a-host.md`
- `docs/guides/register-hooks.md`
- `docs/reference/hook-registration.md`
- `docs/deep-dives/weavert-hook-configuration-platform.md`
- `docs/deep-dives/weavert-integration-guide.md`
- `docs/deep-dives/current-system-architecture.md`
