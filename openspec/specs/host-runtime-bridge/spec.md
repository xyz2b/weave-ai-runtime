# host-runtime-bridge Specification

## Purpose
TBD - created by archiving change add-interactive-runtime-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Runtime exposes a host bridge contract for lifecycle and interaction
The runtime SHALL expose a host bridge contract that covers lifecycle, permission requests, elicitation, notifications, and turn-event emission.

#### Scenario: Host starts an interactive session
- **WHEN** an interactive or headless host binds to the runtime
- **THEN** the runtime SHALL provide a host bridge surface that supports startup, ready, shutdown, and the interactive control points required by that host

### Requirement: Hosts share the same session and turn stack
The runtime SHALL ensure that interactive and headless hosts submit work through the same session control and turn execution stack.

#### Scenario: CLI host and SDK host submit prompts
- **WHEN** a CLI host and an SDK host each submit prompts to the runtime
- **THEN** both hosts SHALL execute through the same `SessionController` and `TurnEngine` stack rather than separate orchestration implementations

### Requirement: Permission and elicitation requests are mediated by the host bridge
The runtime SHALL route permission prompts and elicitation requests through the host bridge rather than direct tool-local or caller-specific callbacks.

#### Scenario: Tool execution needs user confirmation
- **WHEN** a tool execution requires host-mediated confirmation or extra input
- **THEN** the runtime SHALL send that interaction through the bound host bridge and continue execution based on the returned response

### Requirement: Hosts can consume runtime turn events and notifications
The runtime SHALL allow bound hosts to consume streamed turn events and runtime notifications without taking ownership of turn orchestration.

#### Scenario: Background work emits a notification
- **WHEN** the runtime emits a background completion notice or turn-stream event
- **THEN** the bound host SHALL be able to receive that event through the host bridge while the runtime retains control of session state and execution flow

### Requirement: Host bridge exposes optional task-list query and watch surfaces
The runtime SHALL expose host-facing task-list query and observation surfaces through the runtime bridge or bound runtime API, without requiring hosts to take ownership of task orchestration.

#### Scenario: host queries task-list state for a session
- **WHEN** a bound host requests the task-list state associated with a session or resolved task-list identifier
- **THEN** the runtime SHALL return the current persisted task-list snapshot through the bridge surface
- **AND** SHALL NOT require the host to reconstruct task state from transcript messages or notifications

#### Scenario: host observes task-list changes
- **WHEN** a bound host subscribes to task-list updates for a resolved task-list identifier
- **THEN** the runtime SHALL provide a callback-based watch registration on the bound runtime surface
- **AND** SHALL emit the current full task-list snapshot when the subscription is established
- **AND** SHALL emit subsequent full snapshots after committed task-list changes for that identifier
- **AND** SHALL keep task orchestration, validation, and persistence under runtime ownership

#### Scenario: host does not consume task-list projections
- **WHEN** a bound host never queries or subscribes to task-list state
- **THEN** the runtime SHALL continue to execute task-list tools and hidden reminder sidecars normally
- **AND** SHALL NOT require host participation for task-list correctness

#### Scenario: host prefers polling over callbacks
- **WHEN** a bound host chooses not to register a task-list watch callback
- **THEN** the runtime SHALL still make the latest task-list snapshot available through query APIs
- **AND** SHALL NOT require event-stream transport support for first-version task-list projection

### Requirement: Host bridge exposes separate background-job query surfaces
The runtime SHALL expose host-facing background-job query surfaces separately from task-list surfaces so hosts can build execution monitors without conflating them with planning state.

#### Scenario: host queries background-job state
- **WHEN** a bound host requests the visible background jobs for a session, scope, or specific job identifier
- **THEN** the runtime SHALL return background-job snapshots through explicit job-oriented bridge surfaces
- **AND** SHALL NOT require the host to read task-list state to discover background execution lifecycle

#### Scenario: host consumes both task lists and jobs
- **WHEN** a bound host renders both planning state and execution state
- **THEN** the runtime SHALL let the host consume task-list and background-job data through distinct bridge contracts
- **AND** SHALL keep task-list identifiers and job identifiers distinct in those projections

### Requirement: Bound host runtime SHALL expose task mutation APIs
The runtime SHALL expose runtime-owned task mutation methods on the bound host bridge so hosts can drive the shared task plane directly without invoking agent tools or private services.

#### Scenario: host mutates task state through the bound bridge
- **WHEN** a bound host creates, updates, claims, releases, assigns, blocks, unblocks, archives, unarchives, or deletes a task through the host bridge
- **THEN** the runtime SHALL resolve the same task-list scope rules used by the tool path
- **AND** SHALL return the same canonical task snapshot shape or structured validation error categories used by the corresponding built-in task tools

### Requirement: Host exact task lookup SHALL be archival-aware
The runtime SHALL let bound hosts retrieve archived tasks by exact identifier even when archived tasks are hidden from default host task-list projections.

#### Scenario: host get task returns archived record by id
- **WHEN** a bound host invokes `get_task(...)` for an archived task identifier
- **THEN** the runtime SHALL return that archived task snapshot even if default host task-list queries hide archived tasks
- **AND** SHALL include canonical archival fields `is_archived`, `archived_at`, and `archived_by` in the returned payload

### Requirement: Host task queries SHALL support archived visibility control
The runtime SHALL let bound hosts query and watch task lists with explicit archived-visibility control, while default host task projections remain focused on active work.

#### Scenario: host task list queries hide archived tasks by default
- **WHEN** a bound host requests a task-list snapshot or registers a task-list watch without an archived-visibility override
- **THEN** the runtime SHALL emit snapshots that exclude archived task entries by default
- **AND** SHALL keep readiness summaries limited to non-archived tasks

#### Scenario: host can opt into archived task visibility
- **WHEN** a bound host requests archived visibility explicitly for task-list queries or watches
- **THEN** the runtime SHALL include archived task entries in the emitted snapshot
- **AND** SHALL preserve archival markers needed for the host to render retirement state

#### Scenario: default host task projections suppress hidden archived dependency ids
- **WHEN** a bound host receives a default task-list snapshot without archived visibility
- **THEN** the runtime SHALL suppress dependency references that target hidden archived tasks from the visible task payloads
- **AND** SHALL keep the host-facing default snapshot self-contained without references to hidden archived task ids

### Requirement: Hosts can observe structured team lifecycle and routing events through headless bridge surfaces
The runtime SHALL expose optional host-facing integration surfaces for structured team lifecycle, membership, and routed team-message events so hosts can render or automate teammate behavior without the runtime owning UI state.

#### Scenario: host observes team lifecycle updates
- **WHEN** a team is created, a teammate member is spawned, or a team is deleted
- **THEN** a bound host that enables the runtime's optional team-facing bridge surfaces SHALL be able to observe those lifecycle updates as structured runtime-owned events
- **AND** the runtime SHALL keep team state authoritative even if no host-side UI is present

#### Scenario: host observes routed team control events
- **WHEN** the runtime routes a structured team control event such as permission mediation, teammate shutdown, or teammate termination
- **THEN** a bound host that enables the runtime's optional team-facing bridge surfaces SHALL be able to receive a structured event describing that routing outcome
- **AND** SHALL NOT be required to scrape transcript text or generic notifications to infer that control-plane event

### Requirement: The minimal v1 team host bridge SHALL be a single optional structured event sink
The runtime SHALL keep the first host-facing team bridge minimal by using one optional structured event sink or equivalent compat callback rather than a mandatory family of UI-oriented callbacks.

#### Scenario: host binds one structured team-event sink
- **WHEN** a host provides the runtime's optional team-event observation sink
- **THEN** the runtime SHALL be able to deliver team lifecycle, routing, and control-plane events through that single structured channel
- **AND** SHALL NOT require separate dedicated callbacks for each specific team event type in order to expose v1 teammate mode

#### Scenario: structured team events carry stable correlation fields
- **WHEN** the runtime emits a structured team event to a bound host sink
- **THEN** that event SHALL include stable routing identity such as `event_type`, `team_id`, and `leader_session_id`
- **AND** SHOULD include additional correlation fields such as `member_id`, `message_id`, or `correlation_id` when those fields exist for the emitted event

### Requirement: Optional team-facing host surfaces SHALL remain additive
The runtime SHALL treat team-facing host surfaces as additive observation or integration hooks, and SHALL NOT require every bound host to implement them in order for team control to function.

#### Scenario: host does not implement optional team-facing surfaces
- **WHEN** a host binds to the runtime without implementing any optional team-facing observation surface
- **THEN** the runtime SHALL still allow team creation, team routing, teammate execution, and deletion to function correctly
- **AND** SHALL degrade only by omitting those optional structured side-channel events for that host

#### Scenario: runtime-owned team queries do not depend on host callbacks
- **WHEN** a framework consumer needs current team state for rendering or automation
- **THEN** the runtime SHALL keep team state authoritative in the runtime-owned control plane rather than requiring the host bridge to become the source of truth
- **AND** the optional host team sink SHALL remain observational rather than state-owning

### Requirement: Hosts SHALL be able to observe and resolve pending team control workflows through runtime-owned bridge surfaces
The runtime SHALL expose optional host-facing workflow surfaces that allow a bound host to observe pending team control workflows and submit typed workflow responses by `workflow_id` without fabricating raw control messages.

#### Scenario: host loads pending workflows after reconnect
- **WHEN** a bound host reconnects after missing prior team workflow events
- **THEN** it SHALL be able to query the runtime for the current pending team control workflows relevant to the bound team or leader session
- **AND** SHALL receive stable workflow identifiers, workflow kinds, and allowed response actions for each pending workflow

#### Scenario: host resolves a pending workflow through the runtime
- **WHEN** a bound host submits an allowed response for a pending team control workflow
- **THEN** the runtime SHALL validate that response through the same authority and state-machine checks used for model-driven workflow responses
- **AND** SHALL record the updated workflow state before emitting any follow-up observation events

### Requirement: Optional host workflow surfaces SHALL remain additive
The runtime SHALL keep workflow observation and resolution surfaces optional so model-driven team control continues to function correctly when a host does not implement them.

#### Scenario: no host workflow integration exists
- **WHEN** a bound host does not implement any optional team workflow observation or resolution surface
- **THEN** the runtime SHALL still allow leader-ingress workflow requests, teammate permission waits, and graceful shutdown workflows to proceed correctly
- **AND** SHALL degrade only by omitting those optional host-side workflow operations

### Requirement: Hosts can query and watch jobs through the shared job control plane
The runtime SHALL expose host-facing query and watch surfaces for jobs that are backed by the shared job control plane rather than by executor-specific polling contracts.

#### Scenario: host lists or reads jobs
- **WHEN** a bound host queries runtime jobs for a given session, team, or equivalent scope
- **THEN** the runtime SHALL return shared job records visible to that scope
- **AND** SHALL expose enough generic metadata for the host to distinguish lifecycle state, executor kind, and linkage

#### Scenario: host subscribes to job changes
- **WHEN** a bound host registers a job watch callback for a visible scope
- **THEN** the runtime SHALL deliver job snapshot updates or equivalent watch payloads from the shared job control plane
- **AND** SHALL NOT require the host to subscribe to executor-specific channels just to observe shared job lifecycle changes

### Requirement: Hosts can request runtime-owned job stops
The runtime SHALL allow bound hosts to request stop for visible jobs through the shared host/runtime bridge.

#### Scenario: host stops a running job
- **WHEN** a bound host requests stop for a visible running job
- **THEN** the runtime SHALL route that stop request through the shared job control plane
- **AND** SHALL return the resulting job state or a structured stop error under the same runtime-owned contract used by other job consumers

### Requirement: Optional package-specific host operations SHALL be surfaced through host facets or capability-detected extensions
The runtime SHALL surface optional package-specific host operations through package-owned host facets or equivalent capability-detected extension contracts instead of widening the mandatory host bridge for each official package feature.

#### Scenario: Official package exposes host-visible optional operations
- **WHEN** an official package contributes host-visible operations that are not required by every host
- **THEN** the runtime SHALL make those operations available through a package-owned host-facet or equivalent extension surface
- **AND** hosts that do not opt into that package SHALL still remain conformant without implementing those optional operations

### Requirement: Host facet availability SHALL be discoverable through one runtime-owned path
The runtime SHALL provide one runtime-owned discovery path that allows hosts or callers to determine which optional package-owned host facets are available in the active runtime.

#### Scenario: Caller checks for optional package-owned host operations
- **WHEN** a caller or bound host needs to determine whether an optional package-owned host facet is available
- **THEN** the runtime SHALL expose that availability through one shared discovery path
- **AND** it SHALL NOT require the caller to infer facet availability from package-specific host method presence or ad hoc object inspection

### Requirement: Missing host facets SHALL fail through a structured runtime outcome
The runtime SHALL surface absent or unavailable optional package-owned host facets through a structured runtime outcome rather than through package-specific missing-method behavior.

#### Scenario: Caller invokes an unavailable optional host facet
- **WHEN** a caller attempts to use an optional host facet that is not available in the active runtime
- **THEN** the runtime SHALL return a structured not-available or unsupported outcome through the shared host-extension path
- **AND** it SHALL NOT require package-specific exception patterns or missing-method checks as the normative behavior

### Requirement: Mandatory host bridge SHALL remain focused on shared runtime concerns
The runtime SHALL keep the mandatory host bridge focused on lifecycle, permission, elicitation, notifications, turn events, and other shared runtime concerns even when official packages add optional host-visible features.

#### Scenario: Runtime adds a new official package with optional host helpers
- **WHEN** an official package adds host-visible helpers that are specific to that package
- **THEN** the runtime SHALL keep the mandatory host bridge limited to shared runtime concerns
- **AND** it SHALL avoid promoting those package-specific helpers into the mandatory host bridge unless they become framework-wide required behavior

### Requirement: Canonical package-owned host helpers SHALL be discovered through host facets
The runtime SHALL treat host-facet discovery as the canonical path for package-owned host-visible helpers even when compatibility wrapper methods remain temporarily available on runtime-owned surfaces.

#### Scenario: caller accesses an optional package-owned host helper
- **WHEN** a caller or bound host needs an optional package-owned host-visible helper
- **THEN** the runtime SHALL make that helper available through the shared host-facet discovery path
- **AND** any retained package-specific wrapper method SHALL remain a compatibility projection over the same host-facet-owned behavior

### Requirement: Mandatory host bridge SHALL NOT grow new package-specific methods for first-party package behavior
The runtime SHALL keep the mandatory host bridge limited to shared runtime concerns and SHALL NOT add new package-specific mandatory host methods solely because one official package emits structured events or host-visible helper behavior.

#### Scenario: package requires structured host interaction beyond shared runtime concerns
- **WHEN** an official package introduces structured host interaction that is specific to that package
- **THEN** the runtime SHALL expose that interaction through a package-owned extension path or bounded compatibility surface
- **AND** it SHALL NOT widen the mandatory host bridge with a new package-specific required method unless that behavior becomes a shared runtime concern

### Requirement: Optional package-owned host operations SHALL resolve through host facets
The runtime SHALL expose optional package-owned host operations through host-facet discovery or an equivalently bounded extension path, rather than widening the mandatory `HostRuntime` bridge contract for every host.

#### Scenario: host uses an optional package-owned workflow helper
- **WHEN** a bound host needs an optional first-party package operation such as team workflow observation or response
- **THEN** the runtime SHALL resolve that operation through the canonical host facet or the corresponding runtime-owned bounded adapter
- **AND** SHALL keep the mandatory `HostRuntime` bridge valid for hosts that do not use that optional helper

### Requirement: Retained host workflow helpers SHALL remain additive compatibility wrappers
The runtime SHALL treat retained host-facing workflow helpers on `BoundHostRuntime` as additive compatibility wrappers over canonical workflow resolution and validation, not as mandatory bridge growth.

#### Scenario: compatibility helper delegates to canonical workflow path
- **WHEN** a caller invokes `BoundHostRuntime.list_team_workflows()` or `BoundHostRuntime.respond_team_workflow()`
- **THEN** the runtime SHALL scope and validate that request through the same canonical workflow service or host-facet-backed path used by the runtime-owned implementation
- **AND** SHALL NOT require the bound host to implement additional package-specific mandatory protocol methods

#### Scenario: optional workflow helper is unavailable
- **WHEN** the active runtime distribution does not provide the relevant package-owned workflow capability or host facet
- **THEN** observation helpers such as `list_team_workflows()` SHALL degrade to an empty result, while mutating helpers such as `respond_team_workflow()` SHALL fail with an explicit not-available error or equivalent bounded availability failure
- **AND** SHALL NOT widen the mandatory host bridge to compensate for that missing package behavior

### Requirement: Optional package-owned host interactions SHALL use host facets and generic extension events
The runtime SHALL expose optional package-owned host interactions through canonical host facets for host-to-runtime operations and through the generic extension-event host contract for runtime-to-host structured package events.

#### Scenario: host performs an optional team workflow operation
- **WHEN** a host needs to list or respond to package-owned team workflow operations
- **THEN** the runtime SHALL expose that operation through the canonical team workflow host facet
- **AND** SHALL NOT require a package-specific workflow helper method on the mandatory host bridge or bound-host owner surface

#### Scenario: runtime emits a package-owned team event
- **WHEN** the runtime emits a structured package-owned team event for host consumption
- **THEN** it SHALL emit that event through the generic extension-event host contract
- **AND** SHALL NOT require a package-specific team event method on the mandatory host bridge

### Requirement: Removed team bridge surfaces SHALL publish canonical replacements and absence semantics
The runtime SHALL publish canonical replacement paths and bounded absence semantics for each removed team-specific host-facing or bound-host bridge surface.

#### Scenario: caller inspects team bridge migration metadata
- **WHEN** a caller or conformance test inspects migration metadata for removed team bridge surfaces
- **THEN** the runtime SHALL identify each removed surface's canonical replacement path
- **AND** SHALL describe the bounded behavior when `runtime-team` is absent rather than restoring a wrapper on the mandatory host bridge

### Requirement: Host-visible extension namespaces SHALL use WeaveRT identifiers
The runtime SHALL expose WeaveRT-branded canonical identifiers for host-visible extension-event namespaces and related public bridge metadata. When the host bridge surfaces capability-specific extension namespaces, the canonical namespace SHALL use the `weavert.*` form instead of `runtime.*`.

#### Scenario: Host receives a capability-specific extension event
- **WHEN** the runtime emits an extension event for a first-party capability such as team coordination
- **THEN** the host-visible canonical namespace SHALL use `weavert.*`
- **AND** the runtime SHALL NOT advertise `runtime.*` as the canonical public namespace for that event family

### Requirement: Hosts can query and watch runtime-owned task orchestration views
The runtime SHALL expose host-facing query and watch surfaces for task orchestration views without requiring hosts to compute dependency readiness or claimability from raw task snapshots themselves.

#### Scenario: host queries derived task orchestration view
- **WHEN** a bound host queries task state for a session or resolved task list
- **THEN** the runtime SHALL be able to return a task orchestration view that includes derived readiness information such as available or blocked tasks
- **AND** SHALL expose list-level readiness summaries without requiring the host to reimplement blocker resolution

#### Scenario: host orchestration snapshot includes minimum readiness fields
- **WHEN** the runtime returns a host-facing task orchestration snapshot
- **THEN** that snapshot SHALL include list-level readiness summaries such as `available_task_ids` and `blocked_task_ids` or equivalent fields
- **AND** SHALL include per-task readiness state plus unresolved blocker identifiers for blocked tasks

#### Scenario: host watches task orchestration updates
- **WHEN** a bound host registers to observe task orchestration updates
- **THEN** the runtime SHALL provide full current orchestration snapshots or equivalent stable watch payloads on relevant task-list mutations
- **AND** SHALL keep orchestration persistence and validation under runtime ownership rather than shifting scheduler responsibility to the host

