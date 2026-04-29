## ADDED Requirements

### Requirement: Production-oriented runtime profiles persist child-run history by default
The runtime SHALL provide a bundled durable child-run history path for production-oriented persistence profiles rather than leaving child-run durability entirely to ad hoc embedder injection.

#### Scenario: production profile recovers child-run history
- **WHEN** a production-oriented runtime profile persists child runs and the runtime is later restarted or reassembled against the same durable state
- **THEN** the runtime SHALL reload the persisted child-run records through its standard child-run observability surfaces
- **AND** those records SHALL preserve stable `run_id`, parent linkage, status, and terminal metadata

#### Scenario: lightweight profile publishes non-durable child-run behavior
- **WHEN** a lightweight runtime profile keeps child-run history in-memory only
- **THEN** the runtime SHALL publish that child-run durability is non-default or non-durable in assembly metadata
- **AND** the runtime SHALL NOT imply full child-run history recovery guarantees for that profile
