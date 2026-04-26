## ADDED Requirements

### Requirement: `runtime-planning` is an official first-party profile/workflow package
The runtime SHALL define `runtime-planning` as an official first-party profile/workflow package that assembles planning-oriented first-party agent profiles and related workflow assets without redefining kernel control-plane ownership.

#### Scenario: `runtime-full` assembles `runtime-planning`
- **WHEN** an embedder assembles `runtime-full`
- **THEN** the runtime SHALL be allowed to include `runtime-planning` as part of the supported first-party full distribution
- **AND** SHALL register its planning definitions through the ordinary built-in discovery, replacement, and visibility rules

#### Scenario: `runtime-default` omits `runtime-planning` by default
- **WHEN** an embedder assembles `runtime-default`
- **THEN** the runtime SHALL remain conformant without `runtime-planning`
- **AND** SHALL keep shared planning primitives available through `runtime-core`

### Requirement: Planning control-plane ownership remains in `runtime-core`
The runtime SHALL keep shared planning-state and execution-observation primitives in `runtime-core` even when `runtime-planning` is installed. This includes `task_*`, `job_*`, task-list scope resolution, host task/job bridge behavior, and derived orchestration/readiness semantics.

#### Scenario: `runtime-core` starts without `runtime-planning`
- **WHEN** an embedder assembles `runtime-core` without the official planning package
- **THEN** the runtime SHALL still expose the core planning and job control-plane primitives needed by hosts, routes, and ordinary agents
- **AND** SHALL NOT require planner-profile definitions to preserve those semantics

#### Scenario: `runtime-planning` consumes core planning primitives
- **WHEN** `runtime-planning` is installed
- **THEN** it SHALL compose its profiles on top of the existing `runtime-core` planning and job primitives
- **AND** SHALL NOT replace `TaskListService`, task/job records, or host bridge ownership with package-private implementations

### Requirement: `runtime-planning` publishes canonical planning profiles
The runtime SHALL publish official first-party planning profiles through `runtime-planning`, with canonical ownership boundaries for shared-plan maintenance, coordination, and execution roles.

#### Scenario: planner profile is discovered
- **WHEN** a runtime with `runtime-planning` resolves built-in agents
- **THEN** it SHALL expose a `planner` profile centered on maintaining shared planning state through `task_*`
- **AND** SHALL NOT require workspace/devtools or team-specific tools just to activate the base planner profile

#### Scenario: coordinator profile is discovered
- **WHEN** a runtime with `runtime-planning` resolves built-in agents
- **THEN** it SHALL expose a `coordinator` profile that combines shared planning-state management with execution observation through `task_*`, `job_*`, or equivalent core orchestration surfaces
- **AND** SHALL preserve the same built-in replacement and visibility rules as other first-party agents

#### Scenario: worker profile is discovered
- **WHEN** a runtime with `runtime-planning` resolves built-in agents
- **THEN** it SHALL expose a `worker` profile that can participate in coordinated workflows without being forced to own the shared task list
- **AND** SHALL allow embedders to layer extra tools or narrower prompts on top through ordinary agent customization

### Requirement: `runtime-planning` composes optional first-party packs without taking ownership of their tools
The runtime SHALL allow `runtime-planning` profiles to compose with optional first-party packages through ordinary built-in replacement or customization paths, while keeping canonical ownership of non-planning tools in their original packages.

#### Scenario: planning profiles compose with `runtime-devtools`
- **WHEN** an embedder assembles `runtime-planning` together with `runtime-devtools`
- **THEN** the runtime SHALL allow planning profiles to be extended with workspace-oriented tools through the normal built-in customization paths
- **AND** SHALL keep canonical ownership of those tools in `runtime-devtools`

#### Scenario: planning profiles compose with `runtime-team`
- **WHEN** an embedder assembles `runtime-planning` together with `runtime-team`
- **THEN** the runtime SHALL allow planning profiles to be extended with team-oriented tools through the normal built-in customization paths
- **AND** SHALL keep canonical ownership of those tools in `runtime-team`
