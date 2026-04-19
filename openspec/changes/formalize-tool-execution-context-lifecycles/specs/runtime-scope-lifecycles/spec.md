## ADDED Requirements

### Requirement: Session scope has an explicit lifecycle owner
The runtime SHALL model session-scoped execution resources through an explicit `SessionScope`-equivalent structure owned by the session controller or equivalent session lifecycle owner.

#### Scenario: session scope is created and owned by session control
- **WHEN** a new session is started or resumed into an active execution path
- **THEN** the runtime SHALL create a session-scoped structure owned by session control rather than lazily inferring session lifetime from tool execution state

### Requirement: Session-scoped resources persist across turns and dispose on session close
The runtime SHALL keep session-scoped resources alive across multiple admitted turns within the same session and SHALL dispose them when session close semantics complete.

#### Scenario: session-scoped state survives multiple turns
- **WHEN** a session submits more than one admitted turn before closing
- **THEN** the runtime SHALL preserve session-scoped state and other session-owned resources across those turns

#### Scenario: session close disposes session-owned resources
- **WHEN** a session is closed after success, interruption, or failure
- **THEN** the runtime SHALL dispose session-owned resources exactly once as part of session close semantics

### Requirement: Session scope owns reusable session-only state inventory
The runtime SHALL assign reusable session-only execution resources, including session-scoped runtime state and any session-internal cache or equivalent reusable session optimization, to session scope unless another stricter owner is explicitly declared.

#### Scenario: reusable session state belongs to session scope
- **WHEN** a runtime resource is intended to survive more than one admitted turn in the same session
- **THEN** the runtime SHALL model that resource as session-owned state or session-owned internal infrastructure rather than as turn-scoped or call-scoped state

### Requirement: Turn scope has an explicit lifecycle owner
The runtime SHALL model turn-scoped execution resources through an explicit `TurnScope`-equivalent structure owned by the turn engine or equivalent turn orchestration owner.

#### Scenario: admitted turn creates turn scope
- **WHEN** ingress admits a new turn for execution
- **THEN** the runtime SHALL create a turn-scoped structure owned by turn orchestration before model request preparation and tool execution begin

### Requirement: Turn-scoped resources dispose at terminal turn completion
The runtime SHALL treat turn-scoped resources as authoritative only for the current admitted turn and SHALL dispose or replace them when that turn reaches terminal completion.

#### Scenario: turn-scoped state does not leak into next turn
- **WHEN** a turn reaches terminal completion and a later turn begins in the same session
- **THEN** the runtime SHALL create a new turn-scoped structure for the later turn rather than reusing the previous turn's authoritative turn-scoped resources

### Requirement: Turn scope owns authoritative turn-local state inventory
The runtime SHALL assign authoritative turn-local execution resources, including turn-scoped runtime state, tool and skill pool snapshots, file observation state, progress, notifications, capability refresh, and abort control, to turn scope unless another stricter owner is explicitly declared.

#### Scenario: turn-local orchestration handles belong to turn scope
- **WHEN** a runtime handle is authoritative only for the currently admitted turn
- **THEN** the runtime SHALL model that handle as turn-owned state or turn-owned control infrastructure rather than as session-owned or call-owned state

### Requirement: Call-scoped execution context is derived from turn scope
The runtime SHALL derive call-scoped tool execution context from the active turn scope and SHALL allow multiple calls in the same turn to share underlying turn-scoped handles while preserving distinct call-scoped metadata.

#### Scenario: multiple calls share turn handles but not call identity
- **WHEN** two tool calls execute within the same turn
- **THEN** the runtime SHALL allow them to share the same underlying turn-scoped capability handles while still giving each call its own call-scoped identity and resolved metadata

### Requirement: Call-scoped execution context disposes after terminal call completion
The runtime SHALL treat call-scoped execution context as valid only for the lifetime of a single tool call and SHALL dispose that call-scoped context after replay commit or equivalent terminal non-executable completion for that call.

#### Scenario: call-scoped context does not survive beyond one call
- **WHEN** a tool call reaches replay commit or an equivalent terminal non-executable completion
- **THEN** the runtime SHALL treat that call's call-scoped execution context as complete rather than reusing it for a later tool call

### Requirement: State handles expose explicit scope semantics
The runtime SHALL model session-scoped state and turn-scoped state as distinct public handles, and SHALL NOT rely on a single ambiguous state container to encode both lifetimes by convention alone.

#### Scenario: runtime distinguishes session and turn state structurally
- **WHEN** code interacts with scoped runtime state from session orchestration, turn orchestration, or tool execution
- **THEN** the runtime SHALL make the intended state lifetime structurally explicit through separate session-state and turn-state handle shapes on the public ABI

### Requirement: File observation state is turn-scoped
The runtime SHALL treat file observation and conflict-tracking state as turn-scoped execution state unless a stricter owner is explicitly declared.

#### Scenario: file observation resets for a new turn
- **WHEN** a new admitted turn begins after the previous turn completed
- **THEN** the runtime SHALL provide a fresh authoritative turn-scoped file-state view for that new turn

### Requirement: Session-internal caches are not exposed as public tool capability by default
The runtime SHALL keep session-internal caches or similar runtime-owned reusable session resources out of the default public tool execution context unless they are explicitly modeled as public capability handles.

#### Scenario: session read cache remains internal
- **WHEN** the runtime maintains a reusable session-scoped read cache or similar internal optimization
- **THEN** the runtime SHALL treat that cache as session-owned internal state rather than exposing it by default as part of the public tool execution context

#### Scenario: absence of a concrete session read cache is still conforming
- **WHEN** the runtime has not yet implemented a concrete reusable session-scoped read cache
- **THEN** it SHALL still conform to this capability as long as any future reusable session-only read optimization is assigned to session scope rather than turn scope or the public tool ABI

### Requirement: Scope owners create runtime state explicitly rather than relying on implicit default construction inside tool execution
The runtime SHALL assign creation of session-scoped and turn-scoped state handles to their respective scope owners and SHALL NOT rely on implicit default construction inside tool execution paths as the authoritative lifecycle mechanism.

#### Scenario: tool execution consumes owner-provided state handles
- **WHEN** a tool executes within an admitted turn
- **THEN** the runtime SHALL provide that tool execution path with state handles that were created by the owning session or turn scope rather than treating tool-context-local default construction as the authoritative source of lifecycle ownership
