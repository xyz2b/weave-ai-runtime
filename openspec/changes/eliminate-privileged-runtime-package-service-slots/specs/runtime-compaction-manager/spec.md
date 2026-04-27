## ADDED Requirements

### Requirement: Compaction manager SHALL attach to owner layers through a canonical package-service protocol binding
The runtime SHALL attach the unified compaction manager to owner-layer and execution-layer runtime paths through the canonical compaction service-family protocol binding rather than through `RuntimeServices.compaction` as a privileged source-of-truth slot.

#### Scenario: turn preparation invokes compaction
- **WHEN** the runtime prepares a turn and needs compaction behavior
- **THEN** the runtime SHALL resolve that behavior through the canonical compaction service-family protocol binding
- **AND** SHALL treat any retained `RuntimeServices.compaction` field as a compatibility projection rather than the normative binding surface
