## ADDED Requirements

### Requirement: Child delegation depth is runtime-owned

The runtime SHALL enforce a delegation-depth ceiling across child execution paths instead of relying only on prompt instructions or tool-pool presentation.

#### Scenario: Root execution spawns the first child within the default ceiling

- **WHEN** a root execution delegates work while the effective child delegation depth is below the configured ceiling
- **THEN** the runtime SHALL allow that child execution to start
- **AND** SHALL thread the resulting child delegation depth into that child execution context or equivalent runtime-private state

#### Scenario: Delegated child attempts nested delegation beyond the ceiling

- **WHEN** an execution already at the configured child delegation ceiling attempts to spawn another child run
- **THEN** the runtime SHALL reject that nested child execution before launching a new child run
- **AND** SHALL NOT depend only on prompt text, visible tools, or agent self-discipline to enforce the ceiling

#### Scenario: Over-depth child spawn does not allocate a deeper child run

- **WHEN** a nested child spawn attempt is rejected because the execution is already at the configured child delegation ceiling
- **THEN** the runtime SHALL surface a structured delegation-depth policy error on the current execution path
- **AND** SHALL NOT allocate a deeper child `run_id`, start a deeper child turn, or write a deeper child run record for that rejected spawn attempt

#### Scenario: Runtime policy explicitly raises the child delegation ceiling

- **WHEN** runtime policy configures a child delegation ceiling above the conservative default
- **THEN** the runtime SHALL allow nested child execution only up to that configured ceiling
- **AND** SHALL continue to reject deeper child execution once the configured ceiling is reached

### Requirement: Parent-facing child results are summary-projected by default

The runtime SHALL expose a summary-projected child result contract for parent-facing execution surfaces by default rather than replaying full child message history.

#### Scenario: Successful child produces a summary-first parent-facing result

- **WHEN** a child run completes successfully under the default child result policy
- **THEN** the runtime SHALL expose stable child identity, terminal status, and summary in the parent-facing result
- **AND** SHALL NOT require the parent-facing result to inline the child's full internal message history by default

#### Scenario: Failed child receives a runtime-owned fallback summary

- **WHEN** a child run reaches a terminal failure or denial state without a usable terminal assistant summary
- **THEN** the runtime SHALL synthesize a runtime-owned summary for the parent-facing result
- **AND** SHALL keep that summary aligned with the child's terminal status and metadata

#### Scenario: Successful child summary is normalized from terminal assistant output

- **WHEN** a successful child run includes textual assistant output suitable for summary projection
- **THEN** the runtime SHALL derive the parent-facing summary from that terminal assistant output
- **AND** SHALL normalize and bound that summary according to runtime policy before exposing it to the parent-facing result surface
