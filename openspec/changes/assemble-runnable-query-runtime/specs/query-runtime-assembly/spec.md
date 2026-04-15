## ADDED Requirements

### Requirement: Runtime assembly constructs a runnable query stack
The runtime SHALL provide an assembly layer that constructs a runnable query stack from kernel configuration, including turn execution, agent orchestration, skill execution, session control, and transcript persistence.

#### Scenario: Host obtains a runnable session from assembled runtime
- **WHEN** a host binds to the runtime using runtime configuration and bundled definitions
- **THEN** the runtime SHALL provide a runnable session surface backed by an assembled turn engine, agent runtime, skill executor, and transcript store

### Requirement: Model-generated agent and skill tool calls execute through assembled runtimes
The runtime SHALL wire built-in `agent` and `skill` tool execution through the assembled `AgentRuntime` and `SkillExecutor`, rather than requiring ad hoc caller-provided runners.

#### Scenario: Model-generated agent tool delegates successfully
- **WHEN** the model emits a built-in `agent` tool call during a turn
- **THEN** the runtime SHALL invoke the assembled subagent execution path instead of failing due to a missing agent runner

### Requirement: Session execution is host-independent
The runtime SHALL expose a session execution surface that interactive and headless hosts can share without reimplementing turn orchestration.

#### Scenario: Interactive and headless hosts share the same turn stack
- **WHEN** an interactive host and a headless host submit turns through the runtime
- **THEN** both hosts SHALL execute through the same assembled session and turn orchestration stack

### Requirement: Tool execution context includes turn-scoped runtime state
The runtime SHALL provide tools with turn-scoped execution context that includes current messages, request interruption handles, and runtime callbacks needed for permission, notification, or mid-turn capability refresh behavior.

#### Scenario: Tool reads turn-scoped context during execution
- **WHEN** a tool executes during an active turn
- **THEN** the tool context SHALL expose the current turn history and runtime callbacks needed for that tool execution path
