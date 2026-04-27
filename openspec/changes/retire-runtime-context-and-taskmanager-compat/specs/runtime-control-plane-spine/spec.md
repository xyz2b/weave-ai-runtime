## ADDED Requirements

### Requirement: Shared control-plane authority SHALL live on structured context carriers and shared job/task services
The runtime SHALL keep authoritative shared context state on structured prompt/private carriers and authoritative execution-control state on shared job/task services rather than on raw `runtime_context` maps or `TaskManager` compatibility surfaces.

#### Scenario: control-plane path updates shared state
- **WHEN** a runtime-owned control-plane path updates shared private context or execution-control state
- **THEN** it SHALL update that state through the structured context carriers or shared job/task services
- **AND** SHALL NOT use raw `runtime_context` or `TaskManager` as an authoritative mutable control-plane contract
