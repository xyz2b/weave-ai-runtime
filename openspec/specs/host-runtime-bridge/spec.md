# host-runtime-bridge Specification

## Purpose
TBD - created by archiving change add-interactive-runtime-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Runtime exposes a host bridge contract for lifecycle and interaction
The runtime SHALL expose a host bridge contract that covers lifecycle, permission requests, elicitation, notifications, and turn-event emission.

#### Scenario: Host starts an interactive session
- **WHEN** an interactive or headless host binds to the runtime
- **THEN** the runtime SHALL provide a host bridge surface that supports startup, ready, shutdown, and the interactive control points required by that host

### Requirement: Hosts share the same session and turn stack
The runtime SHALL ensure that interactive and headless hosts submit work through the same session control and turn execution stack.

#### Scenario: CLI host and SDK host submit prompts
- **WHEN** a CLI host and an SDK host each submit prompts to the runtime
- **THEN** both hosts SHALL execute through the same `SessionController` and `TurnEngine` stack rather than separate orchestration implementations

### Requirement: Permission and elicitation requests are mediated by the host bridge
The runtime SHALL route permission prompts and elicitation requests through the host bridge rather than direct tool-local or caller-specific callbacks.

#### Scenario: Tool execution needs user confirmation
- **WHEN** a tool execution requires host-mediated confirmation or extra input
- **THEN** the runtime SHALL send that interaction through the bound host bridge and continue execution based on the returned response

### Requirement: Hosts can consume runtime turn events and notifications
The runtime SHALL allow bound hosts to consume streamed turn events and runtime notifications without taking ownership of turn orchestration.

#### Scenario: Background work emits a notification
- **WHEN** the runtime emits a background completion notice or turn-stream event
- **THEN** the bound host SHALL be able to receive that event through the host bridge while the runtime retains control of session state and execution flow

