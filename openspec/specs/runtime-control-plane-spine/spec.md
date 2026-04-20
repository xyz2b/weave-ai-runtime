# runtime-control-plane-spine Specification

## Purpose
TBD - created by archiving change introduce-runtime-control-plane-spine. Update Purpose after archive.
## Requirements
### Requirement: Kernel assembles an explicit control-plane service graph
The runtime SHALL assemble an explicit control-plane service graph before any session or turn execution begins, rather than wiring control logic solely through ad hoc callbacks.

#### Scenario: Building a runnable runtime
- **WHEN** the host or application assembles the runtime from configuration
- **THEN** the runtime SHALL construct shared control-plane service instances before creating any `SessionController` or turn-execution surface

### Requirement: Execution plane consumes control-plane services through a stable runtime contract
The runtime SHALL provide `SessionController`, `TurnEngine`, `ToolRuntime`, `AgentRuntime`, and `SkillRuntime` with a stable runtime-level contract for consuming control-plane services.

#### Scenario: Turn execution needs runtime control services
- **WHEN** a turn, tool call, agent delegation, or skill execution requires access to permissions, hooks, elicitation, memory, compaction, tasks, or transcript services
- **THEN** the execution path SHALL access those capabilities through the shared runtime control-plane contract rather than per-call callback injection

### Requirement: Control-plane and execution-plane responsibilities remain separated
The runtime SHALL keep control-plane concerns and execution-plane concerns in distinct layers, so that lifecycle, permissions, hooks, memory, and compaction do not become hidden responsibilities of the turn engine alone.

#### Scenario: Adding a new control-plane subsystem
- **WHEN** the runtime introduces a new cross-cutting subsystem such as hooks, permissions, elicitation, memory, or compaction
- **THEN** that subsystem SHALL be attached to the control-plane layer and consumed by execution components through the runtime contract instead of being embedded directly into a single execution class

### Requirement: Context assembly accepts control-plane contributions
The runtime SHALL provide a unified context-assembly boundary that can accept memory fragments, hook-provided context, compaction outputs, attachments, and runtime metadata before model requests are emitted.

#### Scenario: Preparing a model request
- **WHEN** the runtime prepares the context for a provider request
- **THEN** the runtime SHALL combine control-plane contributions through a dedicated context-assembly step instead of requiring each subsystem to mutate request text independently

