## ADDED Requirements

### Requirement: Default memory manager paths SHALL use `.weavert/memory`
The runtime SHALL expose `.weavert/memory` as the canonical user-visible default filesystem layout for the reference-style memory manager, including the `MEMORY.md` entrypoint and persisted memory artifacts.

#### Scenario: Session resolves the default memory boundary
- **WHEN** a session starts with the default file-based memory manager enabled
- **THEN** the runtime SHALL resolve the canonical memory entrypoint under `<scope>/.weavert/memory/MEMORY.md`
- **AND** it SHALL place canonical persisted memory artifacts under `<scope>/.weavert/memory/**`
