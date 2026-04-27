## ADDED Requirements

### Requirement: Memory manager SHALL attach to owner layers through a canonical package-service protocol binding
The runtime SHALL attach the reference memory manager to owner-layer and execution-layer runtime paths through the canonical memory service-family protocol binding rather than through `RuntimeServices.memory` as a privileged source-of-truth slot.

#### Scenario: runtime assembles default memory support
- **WHEN** the runtime assembles the default memory manager and later executes session or turn paths that require memory behavior
- **THEN** those runtime-owned paths SHALL resolve memory behavior through the canonical memory service-family protocol binding
- **AND** SHALL treat any retained `RuntimeServices.memory` field as a compatibility projection rather than the normative binding surface
