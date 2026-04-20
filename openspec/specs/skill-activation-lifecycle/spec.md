# skill-activation-lifecycle Specification

## Purpose
TBD - created by archiving change close-skill-runtime-semantics-gap. Update Purpose after archive.
## Requirements
### Requirement: Runtime discovers nested skill roots from observed workspace paths
The runtime SHALL discover additional `.claude/skills` roots by walking upward from observed workspace paths that remain under the session cwd, and SHALL merge those roots into the current session skill view.

#### Scenario: File observation discovers a nested skill root during a turn
- **WHEN** a tool reads, edits, or writes a file inside a subtree that contains a closer `.claude/skills` directory
- **THEN** the runtime SHALL discover that root and make its skills available to the same session without requiring a fresh session bootstrap

### Requirement: Closer project skill roots override broader project skill roots
The runtime SHALL prefer skills discovered from more specific workspace roots over shallower roots when the roots contribute skills with the same name and source class.

#### Scenario: Nested skill shadows a broader project skill
- **WHEN** both the project root and a deeper nested root provide a skill with the same name
- **THEN** the runtime SHALL resolve the deeper nested root as the effective skill definition for sessions operating in that subtree

### Requirement: Path-scoped skills activate from session working context
The runtime SHALL evaluate path-scoped skills against prompt paths, attachments, observed paths, and working-set context accumulated in the session.

#### Scenario: Prior file observation keeps a matching skill active in later turns
- **WHEN** a session previously observed a path that matches a path-scoped skill and a later turn no longer repeats that path explicitly
- **THEN** the runtime SHALL continue to expose the skill to that session as long as the observed path remains part of the session context

### Requirement: Activation evidence survives transcript resume
The runtime SHALL restore dynamic skill discovery roots and observed-path-backed activation evidence when a session resumes from transcript state.

#### Scenario: Resumed session restores previously discovered skill activation
- **WHEN** a session resumes from transcript state that already contains discovered nested skill roots or matching observed paths
- **THEN** the runtime SHALL reconstruct the same effective skill activation state before evaluating new user input

### Requirement: Activation diagnostics explain discovery and visibility decisions
The runtime SHALL expose diagnostics for each skill that explain discovery source, path match state, policy narrowing, and user/model visibility.

#### Scenario: Unmatched path-scoped skill exposes an activation diagnostic
- **WHEN** a discovered path-scoped skill does not match any prompt, attachment, observed, or working-set path in the current session context
- **THEN** the runtime SHALL surface a diagnostic that reports the skill as hidden and identifies the path-match outcome instead of silently omitting it

