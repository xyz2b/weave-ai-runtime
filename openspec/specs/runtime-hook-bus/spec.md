# runtime-hook-bus Specification

## Purpose
TBD - created by archiving change add-interactive-runtime-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Runtime hook bus manages Claude-compatible runtime phases
The runtime SHALL provide a session-scoped hook bus that manages Claude-compatible runtime hook phases, including registration, deregistration, matcher evaluation, and phase-based dispatch.

#### Scenario: Dispatching a runtime phase
- **WHEN** the runtime reaches a hookable phase such as `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, or `SessionEnd`
- **THEN** the hook bus SHALL dispatch the matching hooks for that phase using the phase-appropriate payload contract

### Requirement: Hooks return structured effects that can influence runtime flow
The runtime SHALL allow hooks to return structured effects that can add context, update tool input, block continuation, emit notifications, or satisfy elicitation requests.

#### Scenario: Pre-tool hook updates input
- **WHEN** a `PreToolUse` hook returns an effect containing updated tool input
- **THEN** the runtime SHALL use the updated input for the tool call instead of the original input

#### Scenario: Stop hook blocks completion
- **WHEN** a `Stop` hook returns an effect indicating continuation should not proceed
- **THEN** the runtime SHALL not finalize the turn as completed until the hook outcome is resolved according to the runtime flow contract

### Requirement: Hook registration is session-scoped and ownership-aware
The runtime SHALL scope hook registrations to the owning session and owning registrar so that hooks added by skills, host integrations, or runtime configuration do not leak into unrelated sessions or invocations.

#### Scenario: Skill registers hooks during a session
- **WHEN** a skill invocation registers one or more hooks for the current session
- **THEN** those hooks SHALL only be active for that session and SHALL remain attributable to that skill registration owner

