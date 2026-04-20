# tool-execution-context-boundaries Specification

## Purpose
TBD - created by archiving change formalize-tool-execution-context-lifecycles. Update Purpose after archive.
## Requirements
### Requirement: Public tool execution uses a dedicated execution context contract
The runtime SHALL expose a dedicated public `ToolExecutionContext` contract for tool execution, and SHALL NOT require tools on the public execution path to consume the internal runtime assembly context directly.

#### Scenario: public tool receives execution context instead of internal context
- **WHEN** a non-privileged tool executes through the public tool path
- **THEN** the runtime SHALL invoke that tool with a `ToolExecutionContext`-equivalent call-scoped capability view rather than the internal tool assembly context

### Requirement: Internal tool assembly context is not the public tool ABI
The runtime SHALL keep the internal tool assembly context separate from the public tool execution ABI and SHALL reserve it for runtime-owned registries, handlers, runners, compatibility wiring, and privileged control-plane access.

#### Scenario: internal context retains privileged runtime wiring
- **WHEN** the runtime prepares a tool execution inside the main orchestration path
- **THEN** it SHALL be allowed to use an internal context object that carries registries, handlers, runners, or runtime service references without exposing those objects through the public tool ABI

### Requirement: Tool trust classification is explicit and stable
The runtime SHALL classify tool execution paths explicitly into public, privileged, or legacy-compat categories, and SHALL NOT infer privileged execution from incidental runtime behavior at call time.

#### Scenario: tool execution path is selected from explicit classification
- **WHEN** the runtime resolves a tool for execution
- **THEN** it SHALL choose the public, privileged, or legacy-compat path from explicit classification metadata or equivalent runtime-owned registration data rather than from ad hoc behavior during execution

### Requirement: Runtime-owned registration is authoritative for trust routing
The runtime SHALL treat runtime-owned registration or assembly data as the authoritative source of truth for privileged or legacy-compat routing, and SHALL NOT allow tool self-description alone to escalate execution privilege.

#### Scenario: self-declared privileged metadata does not grant privileged routing
- **WHEN** a non-runtime-owned tool declares privileged-looking metadata in definition frontmatter, plugin metadata, or other self-described configuration
- **THEN** the runtime SHALL continue to route that tool on the public path unless runtime-owned registration or assembly logic explicitly classifies it otherwise

### Requirement: Public execution is the default classification for non-runtime-owned tools
The runtime SHALL treat non-runtime-owned tools as public tools by default unless an explicit privileged or legacy-compat classification is present.

#### Scenario: external tool defaults to public execution path
- **WHEN** a user-defined, external, or future third-party tool is registered without an explicit privileged or legacy-compat classification
- **THEN** the runtime SHALL execute that tool on the public tool path with the narrowed `ToolExecutionContext`

### Requirement: Public tool execution context is call-scoped and metadata-stable
The runtime SHALL derive the public tool execution context from turn-scoped capability handles and SHALL freeze call-scoped metadata including tool-use identity, replay ordering, canonical tool name when available, and execution-bound input state for that call.

#### Scenario: public execution context freezes call identity
- **WHEN** two tool calls execute within the same turn
- **THEN** each call SHALL receive a distinct public execution context whose call identity and resolved execution metadata remain stable for the lifetime of that call

### Requirement: Public tool execution context exposes explicit capability handles
The runtime SHALL expose standard tool capabilities through explicit fields on the public tool execution context, including query metadata, read-only catalogs, permission view, session-scoped state, turn-scoped state, file state, memory access, progress, notifications, capability refresh, and abort control.

#### Scenario: tool reads scoped state and control handles
- **WHEN** a tool needs to inspect current turn metadata, emit progress, update scoped runtime state, or request capability refresh
- **THEN** the runtime SHALL provide those operations through explicit handles on the public tool execution context rather than through unstructured metadata

### Requirement: Public tool execution does not expose the raw private carrier
The runtime SHALL NOT expose the full `RuntimePrivateContext` or equivalent raw private carrier through the public tool execution context. If public tools require limited private execution metadata, the runtime SHALL surface it through explicit read-only fields or a narrower read-only projection.

#### Scenario: public tool receives a narrowed private view instead of the raw carrier
- **WHEN** a public tool needs access to selected runtime-private execution metadata that is safe to expose
- **THEN** the runtime SHALL provide that data through explicit execution-context fields or a dedicated read-only private-context view rather than by passing the full private carrier object

### Requirement: Public tool execution does not depend on raw runtime service bags
The runtime SHALL NOT require public tool execution paths to access raw `runtime_services`, unrestricted registries, or privileged runners in order to use standard runtime capabilities.

#### Scenario: public tool cannot rely on raw runtime services
- **WHEN** a public tool needs notifications, memory access, capability refresh, or permission visibility
- **THEN** the runtime SHALL provide those capabilities through the public execution context and SHALL NOT require that tool to reach a raw runtime service bag

### Requirement: Scoped runtime state is explicit in the public tool ABI
The runtime SHALL distinguish session-scoped runtime state from turn-scoped runtime state in the public tool execution context rather than collapsing both into a single ambiguous application-state handle.

#### Scenario: tool observes separate session and turn state handles
- **WHEN** a tool needs to persist reusable state across turns and also coordinate ephemeral state within the current turn
- **THEN** the runtime SHALL expose separate session-scoped and turn-scoped state handles whose lifecycle boundaries are explicit in the ABI

### Requirement: Public tool execution remains compatible with legacy tools through an adapter
The runtime SHALL provide a compatibility adapter so legacy tools that still expect the current mixed tool context can continue to execute while the runtime migrates toward the public/internal context split.

#### Scenario: legacy tool continues to execute during migration
- **WHEN** a legacy tool definition still expects the current mixed tool context shape
- **THEN** the runtime SHALL allow that tool to execute through a compatibility path without re-expanding the public tool ABI to include raw internal runtime services

#### Scenario: compat path is not the default for new tools
- **WHEN** a newly added non-runtime-owned tool is introduced after the public/internal split is available
- **THEN** the runtime SHALL NOT route that tool through the legacy compatibility path by default

### Requirement: Privileged built-in tools may use an internal execution path without widening the public ABI
The runtime SHALL allow runtime-owned privileged built-in tools to execute through an internal path when they require internal control-plane access, and SHALL NOT treat that privileged path as justification to widen the public tool execution context.

#### Scenario: privileged built-in tool uses internal adapter
- **WHEN** a runtime-owned built-in tool requires privileged access to internal runners or control-plane services
- **THEN** the runtime SHALL permit that tool to execute through an internal adapter while preserving the narrower public tool execution contract for non-privileged tools

### Requirement: Compatibility and privileged paths do not redefine the public contract
The runtime SHALL treat privileged execution paths and legacy compatibility paths as exceptions to the default public path and SHALL NOT use them to redefine the default public tool execution contract.

#### Scenario: public ABI remains narrow despite exception paths
- **WHEN** the runtime supports both privileged built-in tools and legacy compatibility adapters
- **THEN** the documented and tested default public tool execution contract SHALL remain the narrower `ToolExecutionContext`-equivalent surface

