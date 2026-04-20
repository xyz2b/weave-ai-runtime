## ADDED Requirements

### Requirement: Runtime provides layered memory services
The runtime SHALL provide layered memory services that distinguish durable long-term memory, session continuity memory, agent namespace memory, and slow cross-session consolidation memory.

#### Scenario: Session starts with memory v2 enabled
- **WHEN** a session starts with memory v2 enabled
- **THEN** the runtime SHALL resolve the active long-term memory boundary, the active agent namespace, and any available session memory artifacts through separate service boundaries rather than a single undifferentiated memory store

### Requirement: Session memory is distinct from compaction
The runtime SHALL treat session continuity memory as distinct from transcript compaction.

#### Scenario: Runtime compacts a long conversation
- **WHEN** context pressure triggers transcript compaction during an active session
- **THEN** the runtime SHALL preserve compaction as a context-management concern and SHALL NOT treat compaction summary artifacts as the session memory service itself

### Requirement: Retrieval uses staged mixed policy
The runtime SHALL support staged memory retrieval that combines deterministic candidate reduction with optional semantic reranking.

#### Scenario: Runtime retrieves memories before a turn
- **WHEN** the runtime prepares a turn with memory v2 enabled
- **THEN** it SHALL support manifest or header prefiltering, deterministic shortlist generation, and optional embedding or LLM reranking before materializing memory fragments for the provider request

### Requirement: Extraction uses deterministic and background pathways
The runtime SHALL support memory extraction through both deterministic obvious-fact rules and background restricted synthesis workers.

#### Scenario: Turn completes with memory-worthy content
- **WHEN** a turn completes successfully and contains memory-worthy content
- **THEN** the runtime SHALL allow obvious durable facts to be extracted through deterministic rules and SHALL allow higher-order synthesis to be delegated to a constrained background memory worker

### Requirement: Agent namespace memory remains inside scope boundaries
The runtime SHALL ensure that agent namespace memory is resolved inside the active `user`, `project`, or `local` memory boundary rather than becoming a fourth top-level scope.

#### Scenario: Agent writes durable working memory
- **WHEN** an agent persists memory through the namespace-aware memory services
- **THEN** the runtime SHALL write that memory inside the agent namespace associated with the active scope boundary and SHALL continue to enforce parent policy ceilings for delegated agents

### Requirement: User memory configuration is declarative
The runtime SHALL expose memory v2 policy controls through a declarative configuration surface while preserving runtime-owned safety invariants.

#### Scenario: Project customizes retrieval or extraction behavior
- **WHEN** a project customizes retrieval limits, routing preferences, or extraction categories
- **THEN** the runtime SHALL apply those policies through declared configuration fields and SHALL NOT require arbitrary user-defined executable hooks in order to preserve core memory runtime invariants
