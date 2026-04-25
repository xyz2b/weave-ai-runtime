## MODIFIED Requirements

### Requirement: Hook platform accepts registrations from multiple authoring surfaces
The runtime SHALL guarantee a stable public hook registration contract for runtime configuration, host-bound integrations, skill-owned declarations, and session-facing registration APIs. The runtime SHALL publish those stable public registration surfaces separately from advanced surfaces. Turn-scoped programmatic APIs MAY remain available as advanced surfaces, and agent definition-owned hook declarations SHALL NOT be treated as portable ordinary-v1 public configuration.

#### Scenario: runtime and skill hooks coexist under the stable public contract
- **WHEN** a runtime-level hook registration and a skill-owned hook registration target the same session
- **THEN** the runtime SHALL preserve both registrations under the same public ownership-aware registration model
- **AND** SHALL treat both authoring surfaces as part of the stable public hook contract

#### Scenario: session API adds a temporary stable hook
- **WHEN** a caller programmatically registers a session-scoped public hook through the session-facing API
- **THEN** the runtime SHALL activate that hook through the same stable registration model used by runtime config and host registrations
- **AND** SHALL return the same stable registration-handle semantics

#### Scenario: host-bound registrations remain part of the stable surface
- **WHEN** a host binds a hook registration through the published host integration surface
- **THEN** the runtime SHALL treat that registration as part of the stable public hook registration contract
- **AND** SHALL normalize its lifecycle ownership and effect handling through the same public model used by runtime config and skill-owned registrations

#### Scenario: turn-scoped programmatic APIs remain advanced
- **WHEN** a runtime specialist uses a turn-scoped programmatic hook registration API during execution
- **THEN** the runtime MAY expose that API as an advanced surface without promoting it to the ordinary-v1 public registration contract
- **AND** SHALL keep embedders conformant without requiring them to depend on that API for portable hook integration

#### Scenario: agent definition hooks are not an ordinary-v1 portability promise
- **WHEN** an agent definition declares hooks in frontmatter or equivalent definition-owned metadata
- **THEN** the runtime SHALL NOT require embedders to depend on that declaration form as a portable ordinary-v1 hook registration surface
- **AND** MAY treat that form as compatibility-only, advanced, or implementation-defined until a future contract revision promotes it explicitly

### Requirement: Handler manifests declare invocation and normalization behavior
The runtime SHALL publish `callback` as the only required stable public v1 hook handler kind. External handler kinds such as `http`, `command`, `agent`, and `prompt` MAY exist as advanced or package-specific extensions, but the runtime SHALL remain conformant without treating them as part of the ordinary-v1 public promise.

#### Scenario: callback hook remains the guaranteed public handler kind
- **WHEN** a framework integrator registers an in-process `callback` hook on a stable public phase
- **THEN** the runtime SHALL invoke that callback with the phase-appropriate typed payload
- **AND** SHALL normalize the result through the common public hook effect contract

#### Scenario: stable handler catalog is published separately from advanced kinds
- **WHEN** an embedder inspects the hook handler contract for an ordinary-v1 integration
- **THEN** the runtime SHALL publish `callback` as the only required stable public handler kind
- **AND** SHALL classify `http`, `command`, `agent`, and `prompt` as advanced or package-specific rather than ordinary-v1 portability requirements

#### Scenario: runtime remains conformant without external handler support
- **WHEN** a runtime build or supported distribution chooses not to expose `http`, `command`, `agent`, or `prompt` hook handlers as ordinary public surfaces
- **THEN** that runtime SHALL still conform to the public hook configuration platform contract
- **AND** SHALL continue to provide the stable callback-first hook authoring path

#### Scenario: external handlers remain policy-gated when present
- **WHEN** a runtime distribution does expose `http`, `command`, `agent`, or `prompt` hook handlers
- **THEN** the runtime SHALL gate those handlers through explicit policy or package-level enablement
- **AND** SHALL NOT require ordinary hook consumers to depend on them for portable integration behavior
