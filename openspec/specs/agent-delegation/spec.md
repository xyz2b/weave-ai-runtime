# agent-delegation Specification

## Purpose
TBD - created by archiving change close-agent-tool-behavior-gap. Update Purpose after archive.
## Requirements
### Requirement: Main-thread context exposes visible agent catalog
The runtime SHALL expose the visible agent catalog to the main-thread model context, including a stable `available_agents` list and a prompt-visible summary of each available agent's role.

#### Scenario: turn context includes available agent names
- **WHEN** the runtime composes a main-thread `TurnContext` for a model request
- **THEN** it SHALL include the currently visible agent names in `available_agents`
- **AND** it SHALL NOT require the model to infer agent availability only from tool-local capability state

#### Scenario: system prompt includes a concise Agents section
- **WHEN** the runtime composes the main-thread system prompt
- **THEN** it SHALL include an `Agents:` section or equivalent prompt fragment containing each visible agent's name and description
- **AND** it SHALL keep that section aligned with the active visible agent catalog for the turn

### Requirement: Main router follows an explicit routing hierarchy
The built-in `main-router` agent SHALL be instructed to choose between direct response, tool invocation, skill invocation, and subagent delegation using an explicit routing hierarchy rather than an implicit generic prompt.

#### Scenario: main-router may answer directly without delegation
- **WHEN** the current user task can be completed without additional tools, skills, or child agents
- **THEN** `main-router` SHALL be allowed to answer directly
- **AND** the routing prompt SHALL NOT force delegation for every turn

#### Scenario: main-router may delegate to a specialized child agent
- **WHEN** the current task requires a separate execution thread, specialized role, or background execution
- **THEN** `main-router` SHALL be instructed that subagent delegation is an available routing choice
- **AND** the routing prompt SHALL distinguish that choice from direct tool or skill invocation

### Requirement: Agent tool accepts an explicit delegation contract
The built-in `agent` tool SHALL accept a structured delegation contract that can shape child execution, including explicit spawn mode and execution overrides.

#### Scenario: agent tool accepts explicit child execution overrides
- **WHEN** the model invokes the `agent` tool with fields such as `spawn_mode`, `cwd`, `model`, or `model_route`
- **THEN** the runtime SHALL validate those fields as part of the tool input contract
- **AND** it SHALL pass the validated values into the child agent invocation path as structured execution input rather than unstructured metadata

#### Scenario: explicit spawn mode wins over legacy background flag
- **WHEN** the `agent` tool input includes both an explicit `spawn_mode` and a conflicting legacy `background` value
- **THEN** the runtime SHALL use the explicit `spawn_mode` as the dispatch source of truth
- **AND** it SHALL NOT allow the legacy boolean flag to silently override that decision

### Requirement: Agent tool returns structured child run identity
The `agent` tool SHALL return structured child run identity and terminal execution information so callers can observe delegated work deterministically, and its `terminal_metadata` surface SHALL stay aligned with the child run record instead of collapsing to a minimal summary.

#### Scenario: synchronous child returns run identity
- **WHEN** the `agent` tool launches a synchronous child execution
- **THEN** the tool result SHALL include at least `run_id`, `turn_id`, `agent`, `status`, and `terminal_metadata`
- **AND** `terminal_metadata` SHALL preserve the child's stable terminal fields together with additive runtime metadata emitted for that child run
- **AND** it SHALL expose any effective model or route hints that shaped that execution

#### Scenario: background child returns task and run identity
- **WHEN** the `agent` tool launches a background child execution
- **THEN** the tool result SHALL include both `task_id` and `run_id`
- **AND** it SHALL identify the child as background execution rather than reporting only a generic success payload

### Requirement: Agent tool projects child results for parent context

The built-in `agent` tool SHALL return a summary-first projection of child execution by default so parent callers can observe child outcomes without ingesting full child history.

#### Scenario: Synchronous child returns a summary-first tool result

- **WHEN** the `agent` tool launches a synchronous child execution under the default child result policy
- **THEN** the tool result SHALL include child identity, terminal status, run identity, and summary
- **AND** SHALL NOT require nested child `messages` history in the default payload

#### Scenario: Compatibility mode allows detailed child payloads

- **WHEN** runtime policy explicitly enables detailed parent-facing child projections
- **THEN** the `agent` tool SHALL include detailed child message history in addition to summary
- **AND** SHALL keep summary and stable child identity fields present in that payload

