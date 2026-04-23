## ADDED Requirements

### Requirement: Forked skill execution honors child delegation ceilings

The runtime SHALL apply the same child delegation-depth ceiling to forked skill execution that it applies to direct child agent execution.

#### Scenario: Forked skill creates a child within the effective ceiling

- **WHEN** an execution invokes a forked skill while its effective child delegation depth remains below the configured ceiling
- **THEN** the runtime SHALL allow the forked child execution to start
- **AND** SHALL apply the same child delegation-depth accounting used by direct child agent execution

#### Scenario: Forked skill cannot bypass a nested delegation ban

- **WHEN** an execution already at the configured child delegation ceiling invokes a skill that would fork a child
- **THEN** the runtime SHALL reject that forked child execution
- **AND** SHALL NOT treat skill fork as a separate delegation namespace that bypasses child delegation policy

#### Scenario: Over-depth skill fork does not allocate a deeper child run

- **WHEN** a forked skill invocation is rejected because the execution is already at the configured child delegation ceiling
- **THEN** the runtime SHALL surface a structured delegation-depth policy error on the current execution path
- **AND** SHALL NOT allocate a deeper child `run_id`, start a deeper child turn, or write a deeper child run record for that rejected fork attempt
