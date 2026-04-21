## MODIFIED Requirements

### Requirement: Runtime hook bus manages reference-compatible runtime phases
The runtime SHALL provide a session-scoped hook bus that manages public runtime hook phases across kernel-public and control-plane-public tiers, including registration, deregistration, matcher evaluation, handler dispatch, phase-based dispatch, and ownership-aware cleanup.

#### Scenario: Dispatching a runtime phase
- **WHEN** the runtime reaches a hookable phase such as `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, or `SessionEnd`
- **THEN** the hook bus SHALL dispatch the matching hooks for that phase using the phase-appropriate payload contract

#### Scenario: Dispatching a control-plane public phase
- **WHEN** the runtime reaches a public control-plane phase such as `PreContextAssemble`, `PreModelRequest`, or `RecoveryDecision`
- **THEN** the hook bus SHALL dispatch the matching hooks for that phase using the published payload contract for that phase

### Requirement: Hooks return structured effects that can influence runtime flow
The runtime SHALL allow hooks to return structured effects that can observe execution, add context, update tool or request input, request same-turn continuation, request session blocking, provide request overrides, emit notifications, satisfy elicitation requests, or contribute sidecar outputs, and SHALL normalize handler-specific outputs into that common effect contract before main-loop consumption.

#### Scenario: Pre-tool hook updates input
- **WHEN** a `PreToolUse` hook returns an effect containing updated tool input
- **THEN** the runtime SHALL use the updated input for the tool call instead of the original input

#### Scenario: Stop hook requests same-turn continuation
- **WHEN** a `Stop` hook returns a structured effect requesting continuation together with injected messages or a request override
- **THEN** the runtime SHALL surface that result as a structured stop outcome for recovery handling instead of finalizing the turn immediately

#### Scenario: External handler output is normalized before aggregation
- **WHEN** a non-callback handler such as `http` or `command` produces a hook result
- **THEN** the runtime SHALL convert that result into the common structured effect contract before precedence and aggregation are applied

### Requirement: Hook registration is session-scoped and ownership-aware
The runtime SHALL scope hook registrations to the owning session, owner, declared scope, and inheritance policy so that hooks added by runtime config, host integrations, skills, agents, or dynamic session APIs do not leak into unrelated sessions or invocations.

#### Scenario: Skill registers hooks during a session
- **WHEN** a skill invocation registers one or more hooks for the current session
- **THEN** those hooks SHALL only be active for that session and SHALL remain attributable to that skill registration owner

#### Scenario: Turn-scoped registration is released after the turn
- **WHEN** a registration is marked as turn-scoped and the owning turn completes or is abandoned
- **THEN** the hook bus SHALL release that registration before the next turn relies on the same session state

## ADDED Requirements

### Requirement: Hook effect aggregation is deterministic across handler classes
The runtime SHALL aggregate multiple hook effects through a deterministic order and conflict-resolution contract that is independent of which handler adapter produced each effect.

#### Scenario: Ordered context and notification aggregation is stable
- **WHEN** multiple matching hooks emit additional context fragments or notifications in one phase
- **THEN** the runtime SHALL aggregate those fragments in stable registration order so repeated runs produce the same ordered hook output

#### Scenario: Conflicting decisions follow explicit precedence
- **WHEN** multiple matching hooks request different continuation, blocking, or override outcomes in the same phase
- **THEN** the runtime SHALL resolve those conflicts through an explicit precedence contract rather than by whichever handler completed last

### Requirement: Hook registrations execute in a published precedence order
The runtime SHALL compute a stable precedence order for all active registrations targeting a public phase, using published source-kind ordering, activation/materialization ordering, and local declaration or call order, and SHALL NOT let async completion timing redefine the winner.

#### Scenario: Dynamic turn registration overrides a static baseline on replace-style fields
- **WHEN** a `runtime_config`-origin registration and a later `turn_api` registration both target the same public phase and both emit a replace-style field such as `updated_input` or `elicitation_result`
- **THEN** the runtime SHALL treat the later-published `turn_api` precedence as the public winner for that field instead of whichever handler happened to finish first

#### Scenario: Declarative registrations preserve source order within one authoring document
- **WHEN** a canonical declarative authoring surface defines multiple registrations for the same public phase in one `registrations[]` list
- **THEN** the runtime SHALL preserve that declaration order as part of the public precedence key for those registrations

#### Scenario: Session and turn APIs preserve call order
- **WHEN** multiple session-scoped or turn-scoped registrations are added programmatically for the same phase from the same source kind
- **THEN** the runtime SHALL preserve registration call order as part of the public precedence key

### Requirement: Public hook effect fields use published merge semantics
The runtime SHALL apply published merge semantics for each public effect-field class so that append-style, replace-style, gate-style, field-merge-style, and ladder-style fields resolve predictably across multiple matching hooks.

#### Scenario: Append-style fields preserve deterministic order
- **WHEN** multiple matching hooks emit `additional_context`, `notifications`, or `injected_messages`
- **THEN** the runtime SHALL append those values in published precedence order instead of reordering them by handler class or completion timing

#### Scenario: Request override records field-level winners
- **WHEN** multiple matching hooks contribute overlapping `request_override` fields
- **THEN** the runtime SHALL merge those fields in precedence order and SHALL retain field-level winner attribution so diagnostics can identify which source won each field

#### Scenario: Stop disposition uses a published ladder instead of last-writer-wins
- **WHEN** multiple matching hooks contribute different `stop_disposition` values on a public stop-capable phase
- **THEN** the runtime SHALL resolve those values through the published disposition ladder rather than by whichever registration appears last

### Requirement: Public phase effect contracts define allowed stable effect fields
The runtime SHALL publish, for each public phase, the stable set of concrete effect fields that may influence runtime behavior, and SHALL not treat effect fields outside that phase contract as portable public behavior.

#### Scenario: Pre-tool phase exposes input-shaping fields but not stop disposition
- **WHEN** the runtime validates or dispatches a public `PreToolUse` hook
- **THEN** the published phase contract SHALL allow `updated_input`, `continue_execution`, `notifications`, and `metadata`, and SHALL NOT treat `stop_disposition` as a stable `PreToolUse` effect field

#### Scenario: Observe-oriented phases do not gain override semantics by accident
- **WHEN** a hook targeting an observe/sidecar-oriented public phase such as `SessionEnd`, `SubagentStop`, `Notification`, `PreCompact`, or `PostCompact` produces fields such as `request_override` or `stop_disposition`
- **THEN** the runtime SHALL reject those fields where the registration contract is declarative, or ignore them with diagnostics where they arise dynamically, instead of treating them as portable public behavior for that phase

#### Scenario: New public effect fields require contract publication first
- **WHEN** the runtime begins consuming a new effect field on a public phase
- **THEN** that field SHALL NOT be considered part of the public integration contract until the phase's published effect-field contract is updated

### Requirement: Hook dispatch exposes structured winner and rejection diagnostics
The runtime SHALL produce structured diagnostics for each public phase dispatch that distinguish matched registrations, blocked registrations, ignored effect fields, winning registrations, and the final applied outcome.

#### Scenario: Matched registration set is observable
- **WHEN** one or more public hook registrations match a phase dispatch
- **THEN** the runtime SHALL expose diagnostics that identify the matched registration set through stable attribution fields such as registration id, owner, and source kind

#### Scenario: Ignored effect fields are distinguishable from blocked registrations
- **WHEN** a registration executes but one or more of its effect fields are ignored because they are unsupported for that phase or overridden by published precedence
- **THEN** the runtime SHALL surface that condition separately from policy-blocked or timeout-blocked registrations instead of collapsing all non-winning cases into one generic matched list

#### Scenario: Winner attribution is field-aware
- **WHEN** multiple matching registrations contribute to replace-style, field-merge-style, ladder-style, or gate-style outcomes
- **THEN** the runtime SHALL expose diagnostics that identify the winning registration or contributing registration set for the affected field or decision
