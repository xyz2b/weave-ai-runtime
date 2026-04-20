## ADDED Requirements

### Requirement: Skill is a composite runtime object
The runtime SHALL treat each skill as a composite runtime object made of prompt body, typed metadata, and a runtime policy envelope rather than as prompt text alone.

#### Scenario: Skill contributes to prompt, visibility, and policy surfaces
- **WHEN** the runtime loads a valid file-backed skill definition
- **THEN** that skill SHALL participate in prompt expansion, invocation visibility, and execution policy resolution as one coherent runtime object

### Requirement: Skill prompt bodies support reference-compatible variable expansion
The runtime SHALL expand file-backed skill prompt bodies before inline injection and forked execution, supporting `$ARGUMENTS`, `${ARG1...}`, `${CLAUDE_SESSION_ID}`, and `${CLAUDE_SKILL_DIR}`.

#### Scenario: Inline skill expands arguments and runtime variables
- **WHEN** a file-backed skill is invoked inline with positional arguments inside an active session
- **THEN** the injected skill content SHALL contain the substituted argument values, the current session identifier, and the resolved skill directory path instead of the raw placeholder tokens

### Requirement: Skill shell blocks execute through the runtime shell path
The runtime SHALL execute reference-compatible shell blocks embedded in local skill bodies through the existing shell tool execution path, using the `shell` frontmatter value to select the interpreter.

#### Scenario: Skill declares a non-default shell for prompt expansion
- **WHEN** a local skill declares `shell: powershell` and contains executable shell blocks during prompt expansion
- **THEN** the runtime SHALL execute those blocks with the PowerShell-backed shell path, apply the current skill policy and permission controls, and inject the command output into the expanded prompt

### Requirement: Skill request overrides shape downstream model execution
The runtime SHALL apply skill-scoped `model` and `effort` overrides to downstream request construction for inline execution and to child invocation parameters for forked execution.

#### Scenario: Inline skill overrides the next model request
- **WHEN** an inline skill declares `model` and `effort` frontmatter
- **THEN** the next model request in that turn SHALL use the skill-provided values instead of the agent defaults until another explicit override replaces them

#### Scenario: Forked skill forwards request overrides to the child run
- **WHEN** a forked skill declares `model` and `effort` frontmatter
- **THEN** the delegated child invocation SHALL carry those requested values into the child execution context

#### Scenario: Multiple inline skills override one pending request
- **WHEN** several inline skills run before the next model request is constructed and they override overlapping request fields
- **THEN** the runtime SHALL apply last explicit write wins per field and preserve non-overridden pending fields until the request is emitted

#### Scenario: Inline request override is consumed once
- **WHEN** an inline skill has shaped the immediately following model request
- **THEN** the runtime SHALL clear that pending override state before building a later request in the same session

### Requirement: User-originated skill execution respects user visibility and activation eligibility
The runtime SHALL reject explicit user-originated skill execution when the skill is not user-invocable or is inactive for the current activation context.

#### Scenario: User attempts to invoke a non-user-invocable skill
- **WHEN** a user-originated execution path targets a skill with `user-invocable: false`
- **THEN** the runtime SHALL reject that invocation instead of executing the skill body

#### Scenario: User attempts to invoke a path-scoped skill outside its active context
- **WHEN** a user-originated execution path targets a path-scoped skill whose activation paths do not match the current session context
- **THEN** the runtime SHALL reject that invocation with an activation-eligibility error

### Requirement: Skill invocation eligibility is enforced consistently across execution surfaces
The runtime SHALL derive host-visible skills, model-visible skills, and executable skill validation from the same resolved invocation eligibility decision.

#### Scenario: Skill is host-visible but not model-invocable
- **WHEN** a skill remains user-invocable but declares `disable-model-invocation: true`
- **THEN** host-facing invocation queries SHALL continue to expose the skill while the model-visible skill pool SHALL exclude it

#### Scenario: Skill has been narrowed out of the active skill pool
- **WHEN** a skill is excluded by the current execution policy skill pool
- **THEN** the runtime SHALL omit it from model-visible execution surfaces and reject execution through model-driven skill invocation paths with a policy-based error

### Requirement: Skill shell expansion fails closed
The runtime SHALL treat shell block expansion as a fail-fast step of prompt construction for local file-backed skills.

#### Scenario: Shell expansion is denied by permission policy
- **WHEN** a skill shell block cannot run because the shell tool path is denied by the active permission policy
- **THEN** the runtime SHALL fail skill expansion and SHALL NOT inject partial shell output into the prompt

#### Scenario: Shell expansion exits with an execution failure
- **WHEN** a skill shell block returns a non-zero exit status or times out
- **THEN** the runtime SHALL fail the skill expansion and surface the failure through the normal tool and skill error channels
