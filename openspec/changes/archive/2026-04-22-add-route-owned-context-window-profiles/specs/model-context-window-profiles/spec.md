## ADDED Requirements

### Requirement: Model integrations may register context window profiles
The runtime SHALL allow model integrations or provider-backed model adapters to register optional model context window profiles and minimal recovery classification hints independently of agent definitions.

#### Scenario: Integration provides an exact model context window profile
- **WHEN** a model integration registers a context window profile for a concrete provider and model combination used by a resolved route
- **THEN** the runtime SHALL load that profile as structured context window metadata for the request
- **AND** the profile SHALL be able to include values such as `max_input_tokens`, `reserved_output_tokens`, token-estimation hints, minimal recovery classification hints focused on `context_limit` and optionally `output_limit`, and bounded observability metadata such as `source` or `confidence`

#### Scenario: Integration omits a context window profile
- **WHEN** the resolved route or final model has no matching profile in the integration-owned catalog
- **THEN** the runtime SHALL treat the context window as unknown rather than failing route resolution or agent execution

#### Scenario: Integration omits recovery classification hints
- **WHEN** a model integration provides a context window profile but does not provide explicit recovery classification hints beyond raw provider metadata
- **THEN** the runtime SHALL continue to use provider-neutral fallback classification for recovery decisions
- **AND** SHALL NOT require the integration author to define a complete provider-specific error taxonomy before the route can be used

#### Scenario: Recovery classification hints remain minimal
- **WHEN** a model integration provides explicit recovery classification hints
- **THEN** the runtime SHALL require that those hints cover `context_limit`
- **AND** MAY allow optional `output_limit` hints
- **AND** SHALL NOT require a complete provider error taxonomy for unrelated failure classes before the route can participate in context-window-aware execution

### Requirement: Routes own context window policy resolution
The runtime SHALL resolve context window ownership through named routes and route-level context window policy rather than through agent-level context-window fields or a required runtime-global model table.

#### Scenario: Route narrows integration defaults
- **WHEN** a named route declares stricter reserved output headroom, tighter trigger policy, or an equivalent narrowing override on top of an integration-provided context window profile
- **THEN** the runtime SHALL apply the route-level policy to requests resolved through that route
- **AND** SHALL NOT require the underlying integration profile to be rewritten for that route-specific adjustment

#### Scenario: Agent selects a route without context window fields
- **WHEN** an agent or delegated component selects a named route and does not declare any context-window fields of its own
- **THEN** the runtime SHALL still resolve context window policy from the route and integration metadata
- **AND** SHALL NOT require `AgentDefinition` to expose context-window-specific configuration fields in order to participate in context-window-aware request shaping

### Requirement: Context window profile matching precedence is deterministic
The runtime SHALL resolve context window profiles using deterministic precedence and SHALL reject ambiguous same-specificity matches instead of relying on declaration order.

#### Scenario: Exact match beats pattern and provider-default
- **WHEN** exact-model, pattern-based, and provider-default profiles could all match the final model
- **THEN** the runtime SHALL prefer the exact-model profile over the pattern profile
- **AND** SHALL prefer the pattern profile over the provider-default profile

#### Scenario: Route policy applies after baseline profile selection
- **WHEN** a route-level context window policy narrows or overrides a selected integration profile
- **THEN** the runtime SHALL first resolve the integration baseline profile
- **AND** SHALL then apply route narrowing or override to produce the resolved context window snapshot

#### Scenario: Ambiguous same-specificity matches are rejected
- **WHEN** two profiles with the same matching specificity both apply to the same provider and final model
- **THEN** the runtime SHALL treat that condition as a configuration error during registration or assembly
- **AND** SHALL NOT silently choose one by declaration order

### Requirement: Resolved context window snapshots provide bounded hints and fallback mode
The runtime SHALL derive a bounded resolved context window snapshot for request shaping surfaces when possible and SHALL degrade to reactive-only fallback when the current route or model context window is unknown.

#### Scenario: Known context window snapshot contributes request-shaping hints
- **WHEN** the runtime resolves a known context window snapshot for the current route and final model
- **THEN** it SHALL expose bounded hints such as `max_input_tokens`, `reserved_output_tokens`, equivalent remaining-input metadata, and bounded observability fields such as `source`, `confidence`, or `fallback_mode` to context-preparation or request-shaping hook surfaces

#### Scenario: Unknown context window snapshot degrades to reactive-only handling
- **WHEN** the runtime cannot resolve a known context window snapshot for the current route or final model
- **THEN** it SHALL expose null or unknown context window hints rather than fabricated numeric limits
- **AND** SHALL allow execution to continue with reactive context-limit handling instead of treating the missing context window data as a configuration error

### Requirement: Context window observability uses a bounded canonical field set
The runtime SHALL expose a bounded, canonical host-visible context-window metadata set rather than leaking provider-specific or ad hoc field names.

#### Scenario: Host-visible metadata exposes structured context window fields
- **WHEN** a request or prepared context carries resolved context window information
- **THEN** the runtime SHALL expose a structured `context_window` view containing at least `max_input_tokens`, `reserved_output_tokens`, `remaining_input_tokens`, `fallback_mode`, `source`, and `confidence`
- **AND** SHALL expose `context_window_policy_tag` as a canonical host-visible metadata field when a policy tag exists

### Requirement: Context-control request-shaping surfaces use context-window vocabulary
The runtime SHALL expose canonical context-control request-shaping contracts and metadata using context-window vocabulary rather than budget vocabulary when those surfaces describe context-window pressure, tool-result downgrade, or context preparation behavior.

#### Scenario: Canonical context-control types and metadata use context-window naming
- **WHEN** the runtime exposes public types, config fields, structured diagnostics, or effect kinds for context-control request shaping
- **THEN** it SHALL use canonical context-window-oriented names such as `ContextWindowHook`, `ContextWindowRequest`, `ProviderContextWindowHints`, `ContextWindowPlan`, `ContextWindowDecision`, or equivalent context-window vocabulary
- **AND** SHALL NOT present budget-oriented names as the primary contract for surfaces that are semantically about context-window pressure rather than billing or quota management

#### Scenario: Legacy budget-named aliases remain available during migration
- **WHEN** an existing integration or extension still references a legacy budget-named context-control surface during the migration window
- **THEN** the runtime MAY accept that legacy alias as a compatibility bridge
- **AND** SHALL keep the context-window-oriented name as the canonical contract for new integrations, documentation, and examples

#### Scenario: New names win when both new and legacy config keys are present
- **WHEN** a runtime or host configuration surface provides both a canonical `ContextWindow*` key and its legacy `ContextBudget*` alias for the same semantic field
- **THEN** the runtime SHALL prefer the canonical context-window-oriented key
- **AND** SHALL surface a structured deprecation diagnostic for the legacy key rather than silently treating both as equivalent
