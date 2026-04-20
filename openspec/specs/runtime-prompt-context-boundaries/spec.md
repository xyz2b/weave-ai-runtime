# runtime-prompt-context-boundaries Specification

## Purpose
TBD - created by archiving change align-runtime-ingress-context-lifecycle-boundaries. Update Purpose after archive.
## Requirements
### Requirement: Runtime separates prompt-visible context from runtime-private context
The runtime SHALL maintain separate channels for prompt-visible context and runtime-private execution context during request preparation, rather than treating both as one shared metadata bag.

#### Scenario: Prompt assembly consumes only prompt-visible inputs
- **WHEN** the runtime prepares a model request
- **THEN** system prompt assembly SHALL consume only prompt-visible fragments, attachments, and explicitly admitted session context

#### Scenario: Tools retain access to private execution state
- **WHEN** a tool, agent runtime, or skill runtime executes within an active turn
- **THEN** it SHALL retain access to runtime-private execution context such as permission, policy, diagnostics, and run metadata without requiring those fields to be serialized into the prompt

### Requirement: Prompt and private context use explicit carrier types
The runtime SHALL define explicit carrier types for prompt-visible context and runtime-private context, using strong typed outer structures with controlled extension fields rather than unbounded raw dictionaries.

#### Scenario: Prompt context uses a prompt-safe carrier
- **WHEN** the runtime assembles prompt-visible context for a request
- **THEN** it SHALL do so through an explicit prompt-context carrier that contains approved prompt-facing fields and controlled extensions only

#### Scenario: Private context uses a strong outer structure
- **WHEN** runtime-private execution metadata is propagated across turn execution, tool execution, or host diagnostics
- **THEN** it SHALL do so through an explicit private-context carrier that provides named core fields and controlled extensions

### Requirement: Prompt assembly uses an allowlist for runtime-derived context
The runtime SHALL allow only explicitly approved runtime-derived fields to enter the model-visible prompt or turn context.

#### Scenario: Policy and permission state stay private
- **WHEN** request preparation includes execution policy, permission context, lifecycle diagnostics, or host/runtime metadata
- **THEN** those fields SHALL remain runtime-private and SHALL NOT be rendered into the system prompt by default

#### Scenario: Memory and compaction fragments remain prompt-visible
- **WHEN** memory retrieval, hook context, compaction summaries, or attachment descriptions are intended to guide the model
- **THEN** the runtime SHALL include those fragments through the prompt-visible channel without requiring unrelated private metadata to be exposed

### Requirement: Turn context is prompt-safe and private context remains external
The runtime SHALL treat turn-context structures that are sent to model-facing layers as prompt-safe carriers, and SHALL keep authoritative runtime-private context outside those prompt-facing structures.

#### Scenario: Turn context excludes authoritative private state
- **WHEN** the runtime constructs a model-facing turn context
- **THEN** that turn context SHALL omit authoritative runtime-private state such as policy objects or permission context instances, even if equivalent diagnostic projections are available elsewhere

#### Scenario: Model request retains separate private carrier
- **WHEN** the runtime needs private execution metadata during request emission or provider interaction
- **THEN** it SHALL retain that metadata through a separate private carrier or equivalent non-prompt field on the request path

### Requirement: Control-plane services contribute prompt and private data independently
The runtime SHALL support control-plane contributors that can independently add prompt-visible fragments and runtime-private updates during request preparation.

#### Scenario: Memory service contributes prompt and retrieval trace separately
- **WHEN** memory retrieval produces both model guidance and retrieval diagnostics
- **THEN** the runtime SHALL carry model guidance through the prompt-visible channel and retrieval diagnostics through the runtime-private channel

#### Scenario: Hook or host service adds private-only diagnostics
- **WHEN** hooks or host integration produce execution diagnostics or runtime hints that are not model-facing
- **THEN** the runtime SHALL merge those updates into runtime-private context without automatically exposing them in prompt text

### Requirement: Prompt and private context merges are deterministic
The runtime SHALL define deterministic merge precedence for session/base context, ingress updates, sidecar contributions, and request-scoped explicit overrides when assembling prompt-visible and private execution context.

#### Scenario: Prompt fragments preserve stage order
- **WHEN** prompt-visible fragments are contributed by more than one stage during request preparation
- **THEN** the runtime SHALL preserve a stable append order that reflects the configured stage precedence rather than allowing nondeterministic reordering

#### Scenario: Private key conflicts resolve by explicit precedence
- **WHEN** more than one stage writes the same runtime-private field
- **THEN** the runtime SHALL resolve that conflict by the documented merge precedence and SHALL NOT silently depend on incidental dictionary mutation order

### Requirement: Prompt-visible and private context remain observable in protocol tests
The runtime SHALL make both context channels observable enough for protocol and conformance tests to verify that private state is not leaking into prompt assembly.

#### Scenario: Request fixture omits private-only fields from prompt
- **WHEN** a protocol test captures the emitted model request
- **THEN** the prompt-visible portion of that request SHALL exclude private-only runtime fields such as permission mode traces or internal diagnostics

#### Scenario: Runtime diagnostics still expose private state
- **WHEN** a host or test inspects request metadata, turn metadata, or tool context for the same turn
- **THEN** the runtime SHALL still expose the corresponding private execution state through non-prompt channels

