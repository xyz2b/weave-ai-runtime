# runtime-package-context-contributors Specification

## Purpose
TBD - created by archiving change add-package-context-contributor-bindings. Update Purpose after archive.
## Requirements
### Requirement: Runtime packages SHALL be able to register collect-style context contributors
The runtime SHALL allow a package manifest contribution to register collect-style context contributors that participate in request-time context assembly with explicit owner metadata, stage attribution, and deterministic order.

#### Scenario: package contributes a context collector
- **WHEN** a selected runtime package returns a context-contributor binding from its manifest contribution
- **THEN** the runtime SHALL register that contributor for the named context-assembly stage together with package ownership metadata
- **AND** SHALL make that contributor available without requiring a new package-specific `RuntimeServices` top-level field

### Requirement: Context contributors SHALL respect prompt/private boundaries
The runtime SHALL require package-contributed context contributors to emit prompt-visible fragments and runtime-private updates through the canonical prompt/private carrier contract rather than mutating raw request text or unbounded metadata bags directly.

#### Scenario: contributor emits model guidance and private diagnostics
- **WHEN** a package-contributed context contributor produces both prompt-facing guidance and private execution diagnostics
- **THEN** the runtime SHALL merge the prompt-facing guidance through the prompt-visible channel
- **AND** SHALL merge the diagnostics through the runtime-private channel without exposing them by default in model-visible prompt text

### Requirement: Context-contributor execution SHALL remain runtime-owned and deterministic
The runtime SHALL own the published stage order for package-contributed context contributors and SHALL execute contributors deterministically within those stages.

#### Scenario: multiple packages contribute to the same stage
- **WHEN** more than one selected runtime package contributes a context contributor to the same published stage
- **THEN** the runtime SHALL execute those contributors in deterministic order according to the runtime-owned ordering contract
- **AND** SHALL NOT require packages to patch turn-engine control flow directly in order to participate

### Requirement: Failing or invalid context contributors SHALL degrade deterministically
The runtime SHALL treat package-contributed collect-style context contributors as best-effort participants. If a contributor raises, times out, or returns an invalid contribution shape, the runtime SHALL omit that contributor's output for the affected request and record owner- and stage-aware diagnostics.

#### Scenario: contributor raises during request preparation
- **WHEN** a package-contributed context contributor raises an exception while the runtime is preparing request-time context
- **THEN** the runtime SHALL continue request preparation without that contributor's prompt or private updates
- **AND** SHALL record a diagnostic that identifies the failing contributor owner and stage

#### Scenario: contributor returns invalid output shape
- **WHEN** a package-contributed context contributor returns an invalid output shape instead of prompt fragments or the canonical prompt/private carrier
- **THEN** the runtime SHALL reject that contributor output for the affected request
- **AND** SHALL emit diagnostics rather than silently mutating prompt-visible or private state from malformed data

