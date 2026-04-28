## MODIFIED Requirements

### Requirement: Runtime discovers nested skill roots from observed workspace paths
The runtime SHALL discover additional `.weavert/skills` roots by walking upward from observed workspace paths that remain under the session cwd, and SHALL merge those roots into the current session skill view.

#### Scenario: File observation discovers a nested skill root during a turn
- **WHEN** a tool reads, edits, or writes a file inside a subtree that contains a closer `.weavert/skills` directory
- **THEN** the runtime SHALL discover that root and make its skills available to the same session without requiring a fresh session bootstrap
