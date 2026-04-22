## ADDED Requirements

### Requirement: Public authoring surfaces normalize into a canonical registration schema
The runtime SHALL define a canonical public registration schema for hook authoring and SHALL normalize runtime configuration documents, definition-owned hook declarations, host APIs, session APIs, and turn APIs into that schema before phase-contract validation and activation.

#### Scenario: Legacy phase-keyed definition hooks are up-converted before activation
- **WHEN** a skill, agent, or invocation definition uses a legacy phase-keyed `hooks` mapping such as `hooks.PreToolUse.matcher/effect`
- **THEN** the runtime SHALL normalize that declaration into the canonical registration schema before validating phase eligibility, effect-field eligibility, scope, and ownership

#### Scenario: Runtime config and turn API preserve the same normalized fields
- **WHEN** a runtime configuration document and a turn-scoped programmatic registration both target the same public phase
- **THEN** the runtime SHALL preserve the same normalized fields for phase, matcher, scope, owner attribution, handler manifest, and declared effect contract even if their authoring envelopes differ

#### Scenario: Declarative callback hooks use binding identifiers rather than serialized code
- **WHEN** a declarative authoring surface such as runtime config or frontmatter targets a `callback` hook handler
- **THEN** that surface SHALL reference a stable host-provided callback binding identifier rather than embedding executable code or raw callable state in the document

### Requirement: Public hook registration APIs accept typed requests and return stable handles
The runtime SHALL expose typed public registration APIs for runtime-level templates, host-bound registrations, session-scoped registrations, and turn-scoped registrations, and SHALL return stable registration handles rather than requiring callers to mutate the raw hook bus directly.

#### Scenario: Session-scoped registration returns an active handle
- **WHEN** a caller registers a public hook against an active session using the session-facing API
- **THEN** the runtime SHALL return a stable handle that includes registration identity, phase, scope, source kind, and activation state for that registration

#### Scenario: Turn-scoped registration rejects invalid turn scope
- **WHEN** a caller attempts to create a turn-scoped registration for a turn that is no longer active or otherwise not valid for activation
- **THEN** the runtime SHALL reject that registration through a stable public failure outcome rather than silently widening it to session scope

#### Scenario: Runtime or host template registration returns a template handle
- **WHEN** a caller registers a runtime-level or host-level hook template intended for future session materialization
- **THEN** the runtime SHALL return a stable handle for that template registration instead of exposing the session-owned active descendants as the only public object

### Requirement: Registration normalization preserves precedence inputs
The runtime SHALL preserve the public precedence inputs for each registration during normalization and activation, including source kind, materialization boundary, and local declaration or call order, so that multi-source hook ordering remains deterministic after activation.

#### Scenario: Canonical declarative lists preserve local order
- **WHEN** a canonical declarative authoring surface defines multiple registrations in one `hooks.registrations[]` list
- **THEN** the normalized registrations SHALL preserve that list order for precedence within the same source kind and activation boundary

#### Scenario: Template materialization preserves template order
- **WHEN** runtime-level or host-level registration templates are materialized into session-owned active registrations
- **THEN** the runtime SHALL preserve the original template order as part of the resulting active precedence order for that session

#### Scenario: Imperative APIs preserve call order after normalization
- **WHEN** a host, session, or turn API submits multiple public hook registrations for the same phase
- **THEN** the normalized registrations SHALL preserve API call order for precedence within that source kind

### Requirement: Registration handles expose idempotent lifecycle operations
The runtime SHALL model public registration handles with stable lifecycle states and idempotent release semantics so callers can reason about active, released, expired, rejected, and template materialization states without inspecting internal hook bus data structures.

#### Scenario: Releasing a live registration deactivates future matches
- **WHEN** a caller releases an active session-scoped or turn-scoped registration handle
- **THEN** the runtime SHALL ensure that registration no longer participates in future matching phase dispatches

#### Scenario: Releasing an expired handle is idempotent
- **WHEN** a caller releases a registration handle whose scope has already expired naturally
- **THEN** the runtime SHALL treat that release as idempotent and SHALL surface a stable non-active lifecycle result instead of an unstable internal error

#### Scenario: Template release has published descendant behavior
- **WHEN** a caller releases a runtime-level or host-level template handle
- **THEN** the runtime SHALL apply the published template-release behavior for future materializations and any existing active descendants instead of leaving that behavior implementation-defined

### Requirement: Hook platform accepts registrations from multiple authoring surfaces
The runtime SHALL provide a hook configuration platform that can register hooks from runtime configuration, host integrations, definition-owned declarations, and session-scoped programmatic APIs, and SHALL normalize those registrations into a common ownership-aware runtime registration model.

#### Scenario: Runtime and definition hooks coexist
- **WHEN** a host runtime registers a `PreModelRequest` hook for a session and a skill invocation registers a `PreToolUse` hook for that same session
- **THEN** the runtime SHALL preserve both registrations with distinct source and owner metadata instead of flattening them into one anonymous handler set

#### Scenario: Session API adds a temporary hook
- **WHEN** a caller programmatically registers a turn-scoped hook during an active session
- **THEN** the runtime SHALL activate that hook only for the targeted scope and SHALL release it automatically when that scope ends

#### Scenario: Runtime and host templates materialize into session-owned activations
- **WHEN** a runtime-level or host-level hook declaration is intended to apply to matching sessions
- **THEN** the runtime SHALL materialize a derived session-owned active registration for each matching session rather than treating the hook bus itself as a global mutable registration store

### Requirement: Handler manifests declare invocation and normalization behavior
The runtime SHALL model each public hook handler kind through a typed handler manifest that declares how the handler is invoked, what timeout and failure semantics apply, what trust/policy class it requires, and how its output is normalized into the common hook effect contract.

#### Scenario: HTTP manifest declares transport boundary and response contract
- **WHEN** a caller configures an `http` hook handler through a public authoring surface
- **THEN** the handler manifest SHALL declare the endpoint target, timeout behavior, and hook-result normalization contract required for that handler to participate in public hook execution

#### Scenario: Command manifest declares local execution boundary
- **WHEN** a caller configures a `command` hook handler through a public authoring surface
- **THEN** the handler manifest SHALL declare the command invocation boundary, timeout behavior, and normalization contract instead of relying on ad hoc transport-specific fields at the registration site

#### Scenario: Imperative callback registration is normalized into the same manifest model
- **WHEN** a host, session, or turn API registers an in-process callback directly
- **THEN** the runtime SHALL normalize that callback into the same handler-manifest model used by declarative surfaces before dispatch and diagnostics attribution

### Requirement: Hook handler kinds are typed and policy-aware
The runtime SHALL expose a typed hook handler model that supports at least `callback`, `http`, `command`, `agent`, and `prompt` handlers, and SHALL define for each handler kind its payload contract, timeout semantics, failure behavior, and policy/trust requirements before that handler kind can be used as a public authoring surface.

#### Scenario: Callback handler receives typed payload
- **WHEN** a framework integrator registers an in-process `callback` hook on a public phase
- **THEN** the runtime SHALL invoke that callback with the phase-appropriate typed payload rather than only a provider-specific or transport-specific raw blob

#### Scenario: External handler is gated by policy
- **WHEN** project or host policy forbids external execution for a hook source or handler class
- **THEN** the runtime SHALL block `http`, `command`, `agent`, or `prompt` handlers of that class from executing and SHALL surface that denial through hook diagnostics

### Requirement: Hook registration is validated against the public phase contract
The runtime SHALL validate every public hook registration against the published phase contract for its target phase, including tier, payload contract, allowed effect classes, allowed stable effect fields, and external-handler eligibility, before that registration becomes active.

#### Scenario: Unsupported blocking registration is rejected
- **WHEN** a caller configures a blocking or override-capable hook on a public phase whose contract only allows `observe` and `sidecar`
- **THEN** the runtime SHALL reject or deactivate that registration instead of silently treating the phase as block-capable

#### Scenario: Internal-only phase cannot be targeted through public config
- **WHEN** a public authoring surface attempts to register a hook against a phase that is not present in the current public phase catalog
- **THEN** the runtime SHALL reject that registration as targeting an `internal-only` phase

#### Scenario: Payload assumptions cannot exceed the published schema
- **WHEN** a public authoring surface, adapter, or generated hook definition claims to require payload fields beyond the published minimum schema for its target phase
- **THEN** the runtime SHALL require those fields to be part of the published phase contract before treating that registration as portable public configuration

#### Scenario: Effect field assumptions cannot exceed the published phase matrix
- **WHEN** a public authoring surface, adapter manifest, or generated hook definition declares that a hook on `PostToolUseFailure`, `SessionEnd`, or another public phase may emit concrete effect fields that are not listed in that phase's published effect-field contract
- **THEN** the runtime SHALL reject or deactivate that registration instead of silently widening the phase's public behavior surface

### Requirement: Hook registrations declare scope, owner, and inheritance policy
The runtime SHALL model every hook registration with explicit owner identity, scope, cleanup boundary, and inheritance policy so that runtime-level, host-level, definition-owned, session-scoped, and turn-scoped hooks can coexist without leaking into unrelated executions.

#### Scenario: Turn-scoped hook does not leak forward
- **WHEN** a turn-scoped hook is registered for one turn and the session advances to a later turn
- **THEN** the runtime SHALL remove or ignore that registration for the later turn unless the registration explicitly declared a broader scope

#### Scenario: Child execution inherits only allowed hooks
- **WHEN** a parent session delegates work to a child execution while some parent-owned hooks are marked as inheritable and others are not
- **THEN** the runtime SHALL propagate only the inheritable registrations to the child and SHALL retain the original owner attribution for those inherited hooks

#### Scenario: Definition-owned declarations receive default activation scope
- **WHEN** an agent, skill, or invocation definition declares hooks without an explicit public scope override
- **THEN** the runtime SHALL assign those hooks a documented default activation scope for that definition kind instead of leaving their lifetime implicit

### Requirement: Hook platform exposes diagnostics for effective behavior
The runtime SHALL surface host-visible diagnostics for hook registration and execution, including matched handlers, blocked handlers, owning sources, normalized effects, and the final applied hook outcomes that influenced runtime flow.

#### Scenario: Host can inspect blocked external handler
- **WHEN** a configured external hook is skipped because of policy, trust, timeout, or adapter failure
- **THEN** the runtime SHALL emit diagnostics that identify the hook source, handler kind, phase, and blocking reason

#### Scenario: Effective winner is observable after aggregation
- **WHEN** multiple hooks match the same phase and produce overlapping decisions or overrides
- **THEN** the runtime SHALL expose diagnostics that make the effective applied outcome and its contributing hook owners observable to the host

### Requirement: Host-visible diagnostics use a stable schema
The runtime SHALL publish a stable host-visible diagnostics schema for hook inventory and hook dispatch traces, and SHALL use that schema consistently across tool denial, elicitation satisfaction, stop/recovery blocking, and other hook-influenced runtime outcomes.

#### Scenario: Registration inventory exposes stable attribution fields
- **WHEN** a host inspects the active public hook registrations for a session or turn
- **THEN** the runtime SHALL expose a stable inventory view that includes at least registration id, source kind, source reference, owner, phase, scope, handler kind, and precedence summary

#### Scenario: Dispatch trace distinguishes matched, blocked, ignored, and applied
- **WHEN** a host inspects diagnostics for one public phase dispatch
- **THEN** the runtime SHALL expose distinct diagnostics sections for matched registrations, blocked registrations, ignored effect fields, winner attribution, and applied outcome summary rather than only a flat list of matched hook owners

#### Scenario: Runtime outcome metadata can correlate to hook dispatch diagnostics
- **WHEN** a hook influences a tool denial, elicitation result, stop/recovery block, or request override outcome
- **THEN** the runtime SHALL expose enough stable correlation data for the host to connect the surfaced runtime outcome back to the relevant hook dispatch diagnostics entry

#### Scenario: Sensitive implementation detail is redacted from public diagnostics
- **WHEN** hook execution involves secret material, raw callback objects, host handles, private context carriers, or transport-native exception internals
- **THEN** the host-visible diagnostics schema SHALL expose only redacted reasons or opaque references instead of leaking those implementation details directly

### Requirement: Public inspection APIs expose hook inventory and dispatch traces
The runtime SHALL expose public inspection APIs that return inventory snapshots of active registrations and queryable hook dispatch traces through stable query objects and stable summary views.

#### Scenario: Inventory query returns a stable snapshot
- **WHEN** a caller queries active public hooks for a session or turn
- **THEN** the runtime SHALL return a stable snapshot view filtered by the requested phase, owner, source kind, or scope rather than exposing a live mutable registration collection

#### Scenario: Dispatch trace query supports bounded retrieval
- **WHEN** a caller queries public hook dispatch traces for a session, turn, or phase
- **THEN** the runtime SHALL support bounded retrieval through stable query controls such as limit and cursor rather than requiring callers to consume an unbounded internal trace log

#### Scenario: Host facade preserves runtime hook API semantics
- **WHEN** a host-facing facade or managed-session wrapper exposes hook registration or inspection APIs
- **THEN** that facade SHALL preserve the same typed request, handle, and query semantics as the underlying runtime surface instead of inventing a divergent hook API contract
