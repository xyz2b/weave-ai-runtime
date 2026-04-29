# skill-policy-semantics Specification

## Purpose
TBD - created by archiving change add-skill-policy-and-isolation-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Skill invocation narrows capabilities instead of escalating them
The runtime SHALL apply non-escalation semantics to skill invocation so that a skill can only narrow the capabilities exposed by the parent agent or session.

#### Scenario: Skill declares allowed tools
- **WHEN** a skill is invoked with an `allowed-tools` restriction
- **THEN** the runtime SHALL intersect that restriction with the parent execution context rather than allowing the skill to expand the available tool pool

### Requirement: Inline and forked skills share one policy envelope
The runtime SHALL resolve skill policy once and apply it consistently across inline skill execution and forked skill execution.

#### Scenario: Forked skill inherits parent policy
- **WHEN** a forked skill delegates work into a dedicated agent context
- **THEN** the runtime SHALL apply the same resolved capability limits and permission ceiling that would have constrained the skill in inline mode

### Requirement: Skill-owned hooks have explicit ownership and cleanup
The runtime SHALL track hooks registered by a skill invocation as skill-owned registrations and clean them up when that invocation ends.

#### Scenario: Skill registers hooks for the current invocation
- **WHEN** a skill invocation registers hooks through its frontmatter or execution path
- **THEN** the runtime SHALL associate those hooks with that invocation and remove them when the invocation completes

### Requirement: Delegated execution preserves policy ceilings
The runtime SHALL preserve parent policy ceilings for delegated agent execution, including tool availability, skill availability, permission context, and memory scope.

#### Scenario: Subagent inherits narrowed execution context
- **WHEN** the runtime delegates execution from a parent agent or skill into a subagent
- **THEN** the subagent SHALL inherit the parent's effective policy ceiling and SHALL not regain capabilities that were already narrowed away

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

