## MODIFIED Requirements

### Requirement: Context assembly accepts control-plane contributions
The runtime SHALL provide a unified context-assembly boundary that can accept memory fragments, hook-provided context, compaction outputs, attachments, runtime metadata, and package-contributed context contributors before model requests are emitted.

#### Scenario: Preparing a model request
- **WHEN** the runtime prepares the context for a provider request
- **THEN** the runtime SHALL combine control-plane contributions through a dedicated context-assembly step instead of requiring each subsystem to mutate request text independently
- **AND** any package-contributed collect-style context participants SHALL run through the same runtime-owned staging contract

#### Scenario: Package-contributed context collector is absent
- **WHEN** the active runtime distribution does not include a package that would otherwise contribute a context collector for a given stage
- **THEN** the runtime SHALL continue to assemble the request through the same unified context-assembly boundary
- **AND** SHALL degrade by omitting only that optional package contribution rather than requiring a package-specific service slot to exist
