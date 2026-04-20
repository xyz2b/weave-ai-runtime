## ADDED Requirements

### Requirement: Runtime provides a Claude-style memory manager
The runtime SHALL provide a Claude-style memory manager that owns memory path resolution, entrypoint loading, relevant memory retrieval, post-turn extraction, and agent memory scope behavior.

#### Scenario: Session starts with default memory enabled
- **WHEN** a session starts with the default memory manager enabled
- **THEN** the runtime SHALL resolve the applicable memory scope and load the memory entrypoint content for that session context

### Requirement: Memory entrypoint loading follows Claude-style file semantics
The runtime SHALL use Claude-style file-based memory entrypoint semantics centered on `MEMORY.md` rather than a generic key-value lookup.

#### Scenario: Project-scoped memory is available
- **WHEN** a session resolves to a project-scoped memory boundary with a `MEMORY.md` entrypoint
- **THEN** the runtime SHALL load that file through the memory manager and expose it to context assembly as a structured memory contribution

### Requirement: Relevant memories are retrieved before turn execution
The runtime SHALL retrieve relevant memories before a turn executes and provide them to context assembly as memory fragments.

#### Scenario: User submits a prompt
- **WHEN** the user submits a prompt in a session with available stored memories
- **THEN** the runtime SHALL evaluate the available memory documents and pass the relevant memory fragments into the turn-preparation pipeline before the provider request is emitted

### Requirement: Post-turn extraction runs on the main thread
The runtime SHALL support post-turn memory extraction for main-thread turns when the default memory manager is enabled.

#### Scenario: Main-thread turn completes
- **WHEN** a main-thread turn completes without an explicit user-managed memory update path taking ownership
- **THEN** the runtime SHALL run the configured post-turn memory extraction flow and persist any resulting memory updates through the memory manager

### Requirement: Agent memory scopes are explicit
The runtime SHALL support explicit agent memory scopes for `user`, `project`, and `local` memory behavior.

#### Scenario: Agent declares project-scoped memory
- **WHEN** an agent definition declares project-scoped memory behavior
- **THEN** the runtime SHALL load and persist memory updates within the project-scoped boundary rather than a user-wide or unrelated local boundary
