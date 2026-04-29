# runtime-primary-context-authority Specification

## Purpose
TBD - created by archiving change retire-runtime-context-and-taskmanager-compat. Update Purpose after archive.
## Requirements
### Requirement: Structured prompt/private carriers SHALL be the authoritative shared context contract
The runtime SHALL treat `PromptContextEnvelope` and `RuntimePrivateContext` as the authoritative shared context carriers for prompt-visible and runtime-private state.

#### Scenario: runtime-owned path needs private execution state
- **WHEN** a runtime-owned owner-layer or execution-layer path needs shared runtime-private execution state
- **THEN** the runtime SHALL read and write that authoritative state through `RuntimePrivateContext` or ingress private updates
- **AND** SHALL NOT require raw `runtime_context` maps to remain an authoritative mutable state bag

### Requirement: Raw `runtime_context` SHALL be limited to compatibility normalization
If the runtime accepts raw `runtime_context` input at public or compatibility boundaries, it SHALL normalize that input into the structured authoritative carriers before owner-layer logic proceeds.

#### Scenario: caller supplies a raw runtime_context payload
- **WHEN** a caller invokes a compatibility or convenience API that still accepts raw `runtime_context`
- **THEN** the runtime SHALL normalize that input into `RuntimePrivateContext` or equivalent authoritative carriers before runtime-owned primary-path logic uses it
- **AND** SHALL treat the raw compatibility map as a boundary-format input rather than an authoritative shared state contract

### Requirement: Raw `runtime_context` compatibility boundaries SHALL be explicitly whitelisted
The runtime SHALL publish an explicit finite whitelist of the compatibility-only entry points that may still accept raw `runtime_context` payloads during the migration.

#### Scenario: caller inspects runtime_context compatibility metadata
- **WHEN** a caller or conformance test inspects compatibility metadata for raw `runtime_context` handling
- **THEN** the runtime SHALL identify the finite set of boundary-only entry points that may still accept raw `runtime_context`
- **AND** SHALL identify those entry points as compatibility-only normalization boundaries rather than authoritative runtime-owned state surfaces

